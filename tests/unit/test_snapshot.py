"""SnapshotManager — atomic snapshots + load with schema-mismatch tolerance."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from axioma.persistence import SNAPSHOT_MANIFEST, SnapshotManager, Stateful


class FakeOrgan:
    name = "fake_organ"
    schema_version = 1

    def __init__(self) -> None:
        self.counter = 0
        self.history: list[str] = []

    def save_state(self) -> dict[str, Any]:
        return {"counter": self.counter, "history": list(self.history)}

    def load_state(self, snap: dict[str, Any]) -> None:
        self.counter = snap["counter"]
        self.history = list(snap["history"])


class AnotherFake:
    name = "another"
    schema_version = 2

    def __init__(self) -> None:
        self.payload: dict[str, Any] = {}

    def save_state(self) -> dict[str, Any]:
        return self.payload

    def load_state(self, snap: dict[str, Any]) -> None:
        self.payload = dict(snap)


def test_register_validates_stateful_protocol(tmp_snapshot_root: Path) -> None:
    mgr = SnapshotManager(tmp_snapshot_root)
    with pytest.raises(TypeError):
        mgr.register(object())  # type: ignore[arg-type]


def test_register_duplicate_raises(tmp_snapshot_root: Path) -> None:
    mgr = SnapshotManager(tmp_snapshot_root)
    a = FakeOrgan()
    b = FakeOrgan()
    mgr.register(a)
    with pytest.raises(KeyError):
        mgr.register(b)


def test_isinstance_stateful() -> None:
    organ = FakeOrgan()
    assert isinstance(organ, Stateful)


async def test_take_snapshot_and_roundtrip(tmp_snapshot_root: Path) -> None:
    mgr = SnapshotManager(tmp_snapshot_root)
    organ = FakeOrgan()
    organ.counter = 99
    organ.history = ["x", "y"]
    mgr.register(organ)

    target = await mgr.take_snapshot(beat_no=1000)
    assert target.exists()
    assert (target / SNAPSHOT_MANIFEST).exists()
    assert (target / "fake_organ.json").exists()
    assert (tmp_snapshot_root / "current").is_symlink()

    organ.counter = 0
    organ.history = []
    beat = await mgr.load_latest()
    assert beat == 1000
    assert organ.counter == 99
    assert organ.history == ["x", "y"]


async def test_load_cold_start_returns_none(tmp_snapshot_root: Path) -> None:
    mgr = SnapshotManager(tmp_snapshot_root)
    mgr.register(FakeOrgan())
    beat = await mgr.load_latest()
    assert beat is None


async def test_multiple_components(tmp_snapshot_root: Path) -> None:
    mgr = SnapshotManager(tmp_snapshot_root)
    a = FakeOrgan()
    a.counter = 5
    b = AnotherFake()
    b.payload = {"q": 1, "r": "two"}
    mgr.register(a)
    mgr.register(b)
    await mgr.take_snapshot(beat_no=42)

    a.counter = 0
    b.payload = {}
    await mgr.load_latest()
    assert a.counter == 5
    assert b.payload == {"q": 1, "r": "two"}


async def test_schema_mismatch_cold_starts_component(tmp_snapshot_root: Path) -> None:
    """If schema_version changes between save and load, the component cold-starts
    and the rest of the load proceeds. Per IMPLEMENTATION_PLAN_v1.0.md §4.6."""
    mgr = SnapshotManager(tmp_snapshot_root)
    a = FakeOrgan()
    a.counter = 7
    mgr.register(a)
    await mgr.take_snapshot(beat_no=1)

    # Simulate version bump
    a.schema_version = 2
    a.counter = 0
    beat = await mgr.load_latest()
    assert beat == 1
    # Should NOT have loaded (schema mismatch); counter stays 0
    assert a.counter == 0


async def test_orphan_component_in_snapshot_is_skipped(tmp_snapshot_root: Path) -> None:
    """A snapshot containing a component not registered now is logged and skipped."""
    mgr1 = SnapshotManager(tmp_snapshot_root)
    mgr1.register(FakeOrgan())
    mgr1.register(AnotherFake())
    await mgr1.take_snapshot(beat_no=10)

    # New manager with only one of the components
    mgr2 = SnapshotManager(tmp_snapshot_root)
    a = FakeOrgan()
    mgr2.register(a)
    beat = await mgr2.load_latest()
    assert beat == 10
    # orphan "another" silently skipped; no exception


async def test_rolling_prune(tmp_snapshot_root: Path) -> None:
    mgr = SnapshotManager(tmp_snapshot_root, rolling_keep=3)
    mgr.register(FakeOrgan())
    # Take 5 snapshots; only 3 should survive
    for i in range(5):
        await mgr.take_snapshot(beat_no=i + 1)
    rolling = sorted(
        p for p in tmp_snapshot_root.iterdir()
        if p.is_dir() and not p.name.startswith("daily_") and "_beat_" in p.name
    )
    assert len(rolling) == 3
    # The 3 surviving are the 3 most recent
    assert all(int(p.name.split("_beat_")[-1]) >= 3 for p in rolling)


async def test_daily_snapshot_separate_series(tmp_snapshot_root: Path) -> None:
    mgr = SnapshotManager(tmp_snapshot_root)
    mgr.register(FakeOrgan())
    await mgr.take_snapshot(beat_no=1)
    await mgr.take_snapshot(beat_no=2, daily=True)
    dirs = sorted(p.name for p in tmp_snapshot_root.iterdir() if p.is_dir())
    daily = [d for d in dirs if d.startswith("daily_")]
    rolling = [d for d in dirs if not d.startswith("daily_") and "_beat_" in d]
    assert len(daily) == 1
    assert len(rolling) == 1


async def test_current_symlink_points_at_latest(tmp_snapshot_root: Path) -> None:
    mgr = SnapshotManager(tmp_snapshot_root)
    mgr.register(FakeOrgan())
    await mgr.take_snapshot(beat_no=1)
    await mgr.take_snapshot(beat_no=2)
    current = tmp_snapshot_root / "current"
    resolved = current.resolve()
    assert "beat_2" in resolved.name


async def test_save_failure_cleans_up_tmp(tmp_snapshot_root: Path, monkeypatch) -> None:
    """If save_state raises, the temp dir is cleaned and `current` is unchanged."""
    mgr = SnapshotManager(tmp_snapshot_root)

    class Bad:
        name = "bad"
        schema_version = 1

        def save_state(self) -> dict[str, Any]:
            raise RuntimeError("intentional")

        def load_state(self, snap: dict[str, Any]) -> None:
            pass

    mgr.register(Bad())
    with pytest.raises(RuntimeError):
        await mgr.take_snapshot(beat_no=99)
    # No tmp dir leaked
    tmps = [p for p in tmp_snapshot_root.iterdir() if p.name.endswith(".tmp")]
    assert tmps == []
    # No current symlink created
    assert not (tmp_snapshot_root / "current").exists()


def test_registered_names(tmp_snapshot_root: Path) -> None:
    mgr = SnapshotManager(tmp_snapshot_root)
    mgr.register(FakeOrgan())
    mgr.register(AnotherFake())
    assert sorted(mgr.registered()) == ["another", "fake_organ"]


# ── v1.5.5 (Checkpoint FF) — load-result detail + register-time validation ──


def test_v1_5_5_register_rejects_component_missing_save_state(
    tmp_snapshot_root: Path,
) -> None:
    """register() now validates save_state is present + callable at boot,
    not at first snapshot."""
    class IncompleteA:
        name = "incomplete"
        schema_version = 1
        # missing save_state
        def load_state(self, snap: dict[str, Any]) -> None:
            pass

    mgr = SnapshotManager(tmp_snapshot_root)
    with pytest.raises(TypeError, match="save_state"):
        mgr.register(IncompleteA())  # type: ignore[arg-type]


def test_v1_5_5_register_rejects_component_missing_load_state(
    tmp_snapshot_root: Path,
) -> None:
    class IncompleteB:
        name = "incomplete"
        schema_version = 1
        def save_state(self) -> dict[str, Any]:
            return {}
        # missing load_state

    mgr = SnapshotManager(tmp_snapshot_root)
    with pytest.raises(TypeError, match="load_state"):
        mgr.register(IncompleteB())  # type: ignore[arg-type]


def test_v1_5_5_register_rejects_non_callable_save_state(
    tmp_snapshot_root: Path,
) -> None:
    """save_state as an attribute (not method) is also caught."""
    class AttrSaveState:
        name = "attr_save"
        schema_version = 1
        save_state = "not callable"  # type: ignore[assignment]
        def load_state(self, snap: dict[str, Any]) -> None:
            pass

    mgr = SnapshotManager(tmp_snapshot_root)
    with pytest.raises(TypeError, match="not callable"):
        mgr.register(AttrSaveState())  # type: ignore[arg-type]


async def test_v1_5_5_last_load_result_cold_start(tmp_snapshot_root: Path) -> None:
    """last_load_result is `no_snapshot` before any snapshot exists."""
    mgr = SnapshotManager(tmp_snapshot_root)
    mgr.register(FakeOrgan())
    beat = await mgr.load_latest()
    assert beat is None
    assert mgr.last_load_result.status == "no_snapshot"
    assert mgr.last_load_result.is_loaded is False
    assert mgr.last_load_result.reason == "no_current_symlink"


async def test_v1_5_5_last_load_result_full_load(tmp_snapshot_root: Path) -> None:
    """After loading, last_load_result.is_loaded + loaded_components populated."""
    mgr = SnapshotManager(tmp_snapshot_root)
    a = FakeOrgan()
    a.counter = 11
    b = AnotherFake()
    b.payload = {"k": "v"}
    mgr.register(a)
    mgr.register(b)
    await mgr.take_snapshot(beat_no=50)

    a.counter = 0
    b.payload = {}
    beat = await mgr.load_latest()
    assert beat == 50
    assert mgr.last_load_result.is_loaded
    assert sorted(mgr.last_load_result.loaded_components) == ["another", "fake_organ"]
    assert mgr.last_load_result.skipped_components == []
    assert mgr.last_load_result.is_partial is False


async def test_v1_5_5_last_load_result_partial_load_on_schema_mismatch(
    tmp_snapshot_root: Path,
) -> None:
    """last_load_result.is_partial=True when at least one component skipped
    on schema mismatch; skipped_reasons explains why."""
    mgr1 = SnapshotManager(tmp_snapshot_root)
    a1 = FakeOrgan()
    b1 = AnotherFake()
    mgr1.register(a1)
    mgr1.register(b1)
    await mgr1.take_snapshot(beat_no=20)

    mgr2 = SnapshotManager(tmp_snapshot_root)
    a2 = FakeOrgan()
    a2.schema_version = 99  # mismatch
    b2 = AnotherFake()
    mgr2.register(a2)
    mgr2.register(b2)
    await mgr2.load_latest()
    assert mgr2.last_load_result.is_loaded
    assert mgr2.last_load_result.is_partial
    assert mgr2.last_load_result.loaded_components == ["another"]
    assert mgr2.last_load_result.skipped_components == ["fake_organ"]
    assert "schema mismatch" in mgr2.last_load_result.skipped_reasons["fake_organ"]


async def test_v1_5_5_corrupt_manifest_returns_manifest_corrupt_status(
    tmp_snapshot_root: Path,
) -> None:
    """A manifest that decodes as a non-dict (e.g., a JSON list) now surfaces
    as `manifest_corrupt` rather than silently returning None."""
    import json

    mgr = SnapshotManager(tmp_snapshot_root)
    mgr.register(FakeOrgan())
    await mgr.take_snapshot(beat_no=1)
    current = (tmp_snapshot_root / "current").resolve()
    # Overwrite manifest with a JSON list (valid JSON, wrong shape)
    (current / "manifest.json").write_text(json.dumps(["not", "a", "dict"]))
    beat = await mgr.load_latest()
    assert beat is None
    assert mgr.last_load_result.status == "manifest_corrupt"
    assert "expected dict" in (mgr.last_load_result.reason or "")


async def test_v1_5_5_corrupt_manifest_unreadable_json_returns_manifest_corrupt(
    tmp_snapshot_root: Path,
) -> None:
    """A manifest that doesn't even parse as JSON → manifest_corrupt with
    decode-failed reason."""
    mgr = SnapshotManager(tmp_snapshot_root)
    mgr.register(FakeOrgan())
    await mgr.take_snapshot(beat_no=1)
    current = (tmp_snapshot_root / "current").resolve()
    (current / "manifest.json").write_text("not even valid json {{{")
    beat = await mgr.load_latest()
    assert beat is None
    assert mgr.last_load_result.status == "manifest_corrupt"
    assert "decode failed" in (mgr.last_load_result.reason or "")


async def test_v1_5_5_load_result_exposes_orphan_skip_reason(
    tmp_snapshot_root: Path,
) -> None:
    """Orphan components (in snapshot but not registered now) are now visible
    in skipped_components + skipped_reasons."""
    mgr1 = SnapshotManager(tmp_snapshot_root)
    mgr1.register(FakeOrgan())
    mgr1.register(AnotherFake())
    await mgr1.take_snapshot(beat_no=7)

    mgr2 = SnapshotManager(tmp_snapshot_root)
    mgr2.register(FakeOrgan())  # AnotherFake not registered → orphan
    await mgr2.load_latest()
    assert "another" in mgr2.last_load_result.skipped_components
    assert "orphan" in mgr2.last_load_result.skipped_reasons["another"]
