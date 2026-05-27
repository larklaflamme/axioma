"""Stateful protocol + SnapshotManager — atomic, per-component snapshots.

Per IMPLEMENTATION_PLAN_v1.0.md §4.

Every stateful component implements save_state() / load_state(). The
SnapshotManager takes periodic snapshots (default every 600 beats = 60 s
at 10 Hz) and persists each component to its own file in a timestamped
directory. Atomic write via tempdir + rename + symlink swap.

Schema mismatches on load are NON-FATAL: per-component cold start is
preferable to refusing to boot. Operator sees the WARN log and decides.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import msgspec

from ..observability.logging import get_logger
from ..observability.metrics import (
    PERSISTENCE_WRITE_LATENCY,
    PERSISTENCE_WRITES,
)

log = get_logger(__name__)

SNAPSHOT_MANIFEST = "manifest.json"
CURRENT_SYMLINK = "current"
DAILY_PREFIX = "daily_"


@dataclass
class LoadResult:
    """v1.5.5 (Checkpoint FF): rich result from `load_latest()`.

    Lets callers distinguish:
      - `no_snapshot`: no `current` symlink (clean cold start)
      - `no_manifest`: snapshot dir exists but manifest is missing
      - `manifest_corrupt`: manifest exists but is unreadable or non-dict
      - `loaded`: at least one component loaded (`loaded_components`)
                  with optional `skipped_components` for partial loads

    `load_latest()` still returns `int | None` for backwards compat
    (None for any non-loaded outcome; beat_no for loaded). Inspect
    `SnapshotManager.last_load_result` for the richer detail.
    """

    status: str  # "no_snapshot" | "no_manifest" | "manifest_corrupt" | "loaded"
    beat_no: int | None = None
    loaded_components: list[str] = field(default_factory=list)
    skipped_components: list[str] = field(default_factory=list)
    skipped_reasons: dict[str, str] = field(default_factory=dict)
    reason: str | None = None  # for non-loaded statuses; freeform

    @property
    def is_loaded(self) -> bool:
        return self.status == "loaded"

    @property
    def is_partial(self) -> bool:
        """At least one component loaded but at least one was skipped."""
        return self.is_loaded and bool(self.skipped_components)


@runtime_checkable
class Stateful(Protocol):
    """All components that hold in-memory state implement this protocol."""

    name: str  # stable; used as filename in the snapshot dir
    schema_version: int

    def save_state(self) -> dict[str, Any]:
        """Return a JSON-serializable dict of in-memory state."""

    def load_state(self, snapshot: dict[str, Any]) -> None:
        """Restore from snapshot. MUST be idempotent (load twice = load once)."""


# msgspec encoder/decoder — fast JSON
_encoder = msgspec.json.Encoder()
_decoder = msgspec.json.Decoder()


class SnapshotManager:
    """Coordinates snapshot/load for a set of Stateful components.

    Snapshot procedure (atomic):
      1. Write each component's state to <tmp>/<name>.json
      2. Write manifest.json
      3. fsync the directory
      4. os.replace(tmp, target)  # atomic on POSIX
      5. Update <current> symlink atomically
      6. Prune old snapshots (keep last N rolling + daily series)
    """

    def __init__(
        self,
        root: Path,
        rolling_keep: int = 24,
        daily_keep_days: int = 30,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.rolling_keep = rolling_keep
        self.daily_keep_days = daily_keep_days
        self._components: list[Stateful] = []
        # Re-entrancy guard so two concurrent snapshots can't trample each other
        self._lock = asyncio.Lock()
        # v1.5.5 (Checkpoint FF): rich result from the last load_latest() call.
        # `load_latest()` still returns `int | None`; this attribute exposes
        # the loaded/skipped breakdown for callers that want it.
        self.last_load_result: LoadResult = LoadResult(status="no_snapshot")

    def register(self, component: Stateful) -> None:
        # v1.5.5 (Checkpoint FF): also validate that save_state + load_state
        # are callable. Previously only `name` and `schema_version` attrs were
        # checked, so a Stateful-protocol violation (missing methods) only
        # surfaced at first snapshot — a boot-time error masquerading as a
        # runtime error. Now register() catches this immediately.
        missing = [
            attr for attr in ("name", "schema_version", "save_state", "load_state")
            if not hasattr(component, attr)
        ]
        if missing:
            raise TypeError(
                f"component {component!r} does not implement Stateful "
                f"(missing: {', '.join(missing)})"
            )
        for method_name in ("save_state", "load_state"):
            if not callable(getattr(component, method_name)):
                raise TypeError(
                    f"component {component!r}.{method_name} is not callable"
                )
        # Reject duplicate names
        if any(c.name == component.name for c in self._components):
            raise KeyError(f"component already registered: {component.name}")
        self._components.append(component)
        log.debug("snapshot_register", component=component.name)

    def registered(self) -> list[str]:
        return [c.name for c in self._components]

    async def take_snapshot(self, beat_no: int, *, daily: bool = False) -> Path:
        """Take a snapshot of all registered components. Returns target dir."""
        async with self._lock:
            return await self._take_snapshot_impl(beat_no, daily=daily)

    async def _take_snapshot_impl(self, beat_no: int, *, daily: bool) -> Path:
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        name = f"{DAILY_PREFIX}{ts}_beat_{beat_no}" if daily else f"{ts}_beat_{beat_no}"
        target = self.root / name
        tmp = self.root / (name + ".tmp")
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)

        manifest: dict[str, Any] = {
            "schema_version": 1,
            "beat_no": beat_no,
            "timestamp": ts,
            "is_daily": daily,
            "components": [],
        }

        try:
            for c in self._components:
                with PERSISTENCE_WRITE_LATENCY.labels(target=c.name).time():
                    data = c.save_state()
                    payload = _encoder.encode(data)
                    (tmp / f"{c.name}.json").write_bytes(payload)
                manifest["components"].append(
                    {
                        "name": c.name,
                        "schema_version": c.schema_version,
                        "bytes": len(payload),
                    }
                )
                PERSISTENCE_WRITES.labels(target=c.name).inc()
            (tmp / SNAPSHOT_MANIFEST).write_bytes(_encoder.encode(manifest))

            # fsync the directory to make the rename durable on POSIX
            try:
                dir_fd = os.open(tmp, os.O_DIRECTORY)
                os.fsync(dir_fd)
                os.close(dir_fd)
            except OSError:
                # Best-effort; some filesystems (tmpfs) don't support directory fsync
                pass

            os.replace(tmp, target)
            self._swap_current_symlink(target)
        except Exception:
            log.exception("snapshot_failed", beat_no=beat_no, name=name)
            shutil.rmtree(tmp, ignore_errors=True)
            raise

        self._prune_rolling()
        if daily:
            self._prune_daily()

        log.info(
            "snapshot_written",
            beat_no=beat_no,
            target=str(target.name),
            components=len(self._components),
            daily=daily,
        )
        return target

    def _swap_current_symlink(self, target: Path) -> None:
        current = self.root / CURRENT_SYMLINK
        tmp_link = self.root / (CURRENT_SYMLINK + ".tmp")
        if tmp_link.exists() or tmp_link.is_symlink():
            tmp_link.unlink()
        tmp_link.symlink_to(target.name)  # relative — survives moves of the root
        os.replace(tmp_link, current)

    def _prune_rolling(self) -> None:
        rolling = sorted(
            (
                p
                for p in self.root.iterdir()
                if p.is_dir() and not p.name.startswith(DAILY_PREFIX) and "_beat_" in p.name
            ),
            key=lambda p: p.name,
        )
        excess = len(rolling) - self.rolling_keep
        if excess <= 0:
            return
        for p in rolling[:excess]:
            try:
                shutil.rmtree(p)
                log.debug("snapshot_pruned_rolling", removed=p.name)
            except OSError:
                log.exception("snapshot_prune_failed", target=p.name)

    def _prune_daily(self) -> None:
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(days=self.daily_keep_days)
        for p in self.root.iterdir():
            if not (p.is_dir() and p.name.startswith(DAILY_PREFIX)):
                continue
            # daily_YYYYMMDD_HHMMSS_beat_N
            try:
                ts_str = p.name[len(DAILY_PREFIX) : len(DAILY_PREFIX) + 15]
                ts = datetime.strptime(ts_str, "%Y%m%d_%H%M%S").replace(tzinfo=UTC)
            except (ValueError, IndexError):
                continue
            if ts < cutoff:
                try:
                    shutil.rmtree(p)
                    log.debug("snapshot_pruned_daily", removed=p.name)
                except OSError:
                    log.exception("snapshot_prune_failed", target=p.name)

    # ── Load ─────────────────────────────────────────────────────────────

    async def load_latest(self) -> int | None:
        """Load the most recent snapshot via the `current` symlink.

        Returns the beat_no of the loaded snapshot, or None if no
        snapshot was loaded (cold start, missing manifest, or corrupt
        manifest). For richer detail inspect `self.last_load_result`
        (v1.5.5+).

        Per-component cold-start on schema mismatch — never raises.
        """
        current = self.root / CURRENT_SYMLINK
        if not current.exists():
            log.info("snapshot_cold_start", reason="no_current_symlink")
            self.last_load_result = LoadResult(
                status="no_snapshot", reason="no_current_symlink",
            )
            return None
        return await self._load_dir(current.resolve())

    async def _load_dir(self, target: Path) -> int | None:
        manifest_path = target / SNAPSHOT_MANIFEST
        if not manifest_path.exists():
            log.warning("snapshot_no_manifest", target=str(target))
            self.last_load_result = LoadResult(
                status="no_manifest", reason=f"missing at {target}",
            )
            return None
        try:
            manifest = _decoder.decode(manifest_path.read_bytes())
        except Exception as exc:
            log.exception("snapshot_manifest_decode_failed", target=str(target))
            self.last_load_result = LoadResult(
                status="manifest_corrupt",
                reason=f"decode failed: {type(exc).__name__}: {exc}",
            )
            return None

        # v1.5.5 (Checkpoint FF): explicit type check. A manifest that decoded
        # successfully but isn't a dict (e.g., someone wrote `[]` to the file)
        # would previously raise AttributeError inside the components loop and
        # get swallowed by an exception handler, silently returning None as if
        # no snapshot existed. Now the operator sees `status=manifest_corrupt`
        # with a clear reason.
        if not isinstance(manifest, dict):
            log.warning(
                "snapshot_manifest_not_dict",
                target=str(target),
                got_type=type(manifest).__name__,
            )
            self.last_load_result = LoadResult(
                status="manifest_corrupt",
                reason=f"manifest is {type(manifest).__name__}, expected dict",
            )
            return None

        by_name = {c.name: c for c in self._components}
        loaded_components: list[str] = []
        skipped_components: list[str] = []
        skipped_reasons: dict[str, str] = {}
        for entry in manifest.get("components", []):
            name = entry["name"]
            c = by_name.get(name)
            if c is None:
                log.warning("snapshot_component_orphan", name=name)
                skipped_components.append(name)
                skipped_reasons[name] = "orphan (no registered component)"
                continue
            if c.schema_version != entry["schema_version"]:
                log.warning(
                    "snapshot_schema_mismatch",
                    name=name,
                    expected=c.schema_version,
                    found=entry["schema_version"],
                )
                skipped_components.append(name)
                skipped_reasons[name] = (
                    f"schema mismatch: expected v{c.schema_version}, "
                    f"found v{entry['schema_version']}"
                )
                continue
            try:
                data = _decoder.decode((target / f"{name}.json").read_bytes())
                c.load_state(data)
                loaded_components.append(name)
            except Exception as exc:
                log.exception("snapshot_load_failed", name=name)
                skipped_components.append(name)
                skipped_reasons[name] = f"{type(exc).__name__}: {exc}"

        beat_no = int(manifest.get("beat_no", 0))
        log.info(
            "snapshot_loaded",
            target=str(target.name),
            beat_no=beat_no,
            loaded=len(loaded_components),
            skipped=len(skipped_components),
        )
        self.last_load_result = LoadResult(
            status="loaded",
            beat_no=beat_no,
            loaded_components=loaded_components,
            skipped_components=skipped_components,
            skipped_reasons=skipped_reasons,
        )
        return beat_no
