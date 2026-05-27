"""Snapshot inspection CLI (v1.8.0, Checkpoint NN).

Read-only inspection of AXIOMA snapshot directories. Does NOT boot the
substrate; operates on the on-disk manifest + component JSON files
written by `axioma.persistence.snapshot.SnapshotManager`.

Use cases:
  - "What snapshots do I have, and when were they taken?" → --list
  - "What's in my latest snapshot?" → --current
  - "What's in a specific snapshot dir?" → --target NAME
  - "What's the contents of a specific component's state?" → --component NAME

Usage:
    python -m axioma.tools.snapshot_inspect [DIR] [OPTIONS]

    DIR: snapshot root (default: data/state/snapshots — common project default).
         Can also be the path to a single snapshot directory if --target is omitted.

Examples:
    # List all snapshots, sorted by name (which is timestamp-prefixed)
    python -m axioma.tools.snapshot_inspect data/state/snapshots

    # Inspect the current (latest) snapshot's manifest
    python -m axioma.tools.snapshot_inspect data/state/snapshots --current

    # Inspect a specific snapshot's manifest
    python -m axioma.tools.snapshot_inspect data/state/snapshots --target 20260527_120000_beat_5000

    # Show the recovery_protocol's saved state from the current snapshot
    python -m axioma.tools.snapshot_inspect data/state/snapshots --current --component recovery_protocol
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import msgspec

from ..persistence.snapshot import CURRENT_SYMLINK, DAILY_PREFIX, SNAPSHOT_MANIFEST

_decoder = msgspec.json.Decoder()


def _list_snapshots(root: Path) -> tuple[list[Path], list[Path]]:
    """Return (rolling, daily) snapshot dirs, sorted by name."""
    if not root.exists():
        return [], []
    all_dirs = [p for p in root.iterdir() if p.is_dir() and "_beat_" in p.name]
    rolling = sorted(p for p in all_dirs if not p.name.startswith(DAILY_PREFIX))
    daily = sorted(p for p in all_dirs if p.name.startswith(DAILY_PREFIX))
    return rolling, daily


def _read_manifest(target: Path) -> dict[str, Any] | None:
    manifest_path = target / SNAPSHOT_MANIFEST
    if not manifest_path.exists():
        return None
    try:
        result = _decoder.decode(manifest_path.read_bytes())
    except Exception as exc:
        return {"_decode_error": f"{type(exc).__name__}: {exc}"}
    if not isinstance(result, dict):
        return {"_decode_error": f"manifest is {type(result).__name__}, expected dict"}
    return result


def _parse_timestamp(name: str) -> str | None:
    """Pull `YYYYMMDD_HHMMSS` from snapshot dir name (with or without daily_ prefix)
    and format as ISO."""
    if name.startswith(DAILY_PREFIX):
        name = name[len(DAILY_PREFIX):]
    parts = name.split("_beat_")
    if len(parts) < 2:
        return None
    ts_str = parts[0]
    try:
        ts = datetime.strptime(ts_str, "%Y%m%d_%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None
    return ts.isoformat()


def cmd_list(root: Path) -> int:
    """List all snapshots in the root, sorted by name (timestamp-prefixed).

    Prints one row per snapshot: name, ISO timestamp, beat_no, component count.
    """
    rolling, daily = _list_snapshots(root)
    current = root / CURRENT_SYMLINK
    current_target = None
    if current.exists() and current.is_symlink():
        current_target = current.resolve().name

    if not rolling and not daily:
        print(f"No snapshots in {root}")
        return 0

    print(f"{'CUR':>3}  {'TYPE':<7}  {'NAME':<40}  {'TIMESTAMP':<26}  {'BEAT':>10}  {'COMPS':>5}")
    print("-" * 100)
    for kind, dirs in (("daily", daily), ("rolling", rolling)):
        for p in dirs:
            mf = _read_manifest(p)
            ts = _parse_timestamp(p.name) or "?"
            cur_marker = "→" if p.name == current_target else " "
            if mf is None or "_decode_error" in mf:
                err = (mf or {}).get("_decode_error", "missing manifest")
                print(f"{cur_marker:>3}  {kind:<7}  {p.name:<40}  {ts:<26}  {'?':>10}  ?     ({err})")
            else:
                beat = mf.get("beat_no", "?")
                ncomp = len(mf.get("components", []))
                print(f"{cur_marker:>3}  {kind:<7}  {p.name:<40}  {ts:<26}  {beat!s:>10}  {ncomp:>5}")
    if current_target:
        print(f"\ncurrent → {current_target}")
    else:
        print("\n(no `current` symlink set)")
    return 0


def cmd_inspect(target_dir: Path, component_name: str | None) -> int:
    """Inspect a single snapshot directory's manifest, optionally dumping a component."""
    if not target_dir.exists():
        print(f"snapshot dir not found: {target_dir}", file=sys.stderr)
        return 2
    mf = _read_manifest(target_dir)
    if mf is None:
        print(f"no manifest at {target_dir / SNAPSHOT_MANIFEST}", file=sys.stderr)
        return 2
    if "_decode_error" in mf:
        print(f"manifest decode failed: {mf['_decode_error']}", file=sys.stderr)
        return 2

    print(f"snapshot: {target_dir.name}")
    print(f"  path:           {target_dir}")
    print(f"  beat_no:        {mf.get('beat_no')}")
    print(f"  timestamp:      {mf.get('timestamp')}")
    print(f"  is_daily:       {mf.get('is_daily', False)}")
    print(f"  schema_version: {mf.get('schema_version')}")
    components = mf.get("components", [])
    print(f"  components:     {len(components)}")
    if components:
        max_name_len = max(len(c.get("name", "?")) for c in components)
        for c in components:
            name = c.get("name", "?")
            ver = c.get("schema_version", "?")
            nbytes = c.get("bytes", "?")
            print(f"    - {name:<{max_name_len}}  v{ver}  {nbytes} bytes")

    if component_name is not None:
        comp_file = target_dir / f"{component_name}.json"
        if not comp_file.exists():
            print(
                f"\ncomponent {component_name!r} not found at {comp_file}",
                file=sys.stderr,
            )
            return 2
        try:
            data = _decoder.decode(comp_file.read_bytes())
        except Exception as exc:
            print(f"\nfailed to decode {comp_file}: {exc}", file=sys.stderr)
            return 2
        print(f"\n=== component {component_name!r} state ===")
        # Pretty-print via json (sorted keys, indent=2) — operator-friendly
        print(json.dumps(data, indent=2, sort_keys=True, default=str))
    return 0


def cmd_current(root: Path, component_name: str | None) -> int:
    """Inspect the `current` symlink target."""
    current = root / CURRENT_SYMLINK
    if not current.exists():
        print(f"no `current` symlink in {root} (cold start, no snapshots taken yet)",
              file=sys.stderr)
        return 2
    return cmd_inspect(current.resolve(), component_name)


def main() -> int:
    p = argparse.ArgumentParser(
        prog="python -m axioma.tools.snapshot_inspect",
        description="Inspect AXIOMA snapshot directories (read-only).",
    )
    p.add_argument(
        "root",
        type=Path,
        nargs="?",
        default=Path("data/state/snapshots"),
        help="snapshot root directory (default: data/state/snapshots)",
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--list",
        action="store_true",
        help="list all snapshots in root (default if no other action given)",
    )
    group.add_argument(
        "--current",
        action="store_true",
        help="inspect the `current` symlink target",
    )
    group.add_argument(
        "--target",
        type=str,
        default=None,
        metavar="NAME",
        help="inspect a specific snapshot directory by name",
    )
    p.add_argument(
        "--component",
        type=str,
        default=None,
        metavar="NAME",
        help="when used with --current / --target, also decode + print a "
             "component's saved state",
    )
    args = p.parse_args()

    # --component requires --current or --target
    if args.component is not None and not (args.current or args.target):
        p.error("--component requires --current or --target")

    if args.current:
        return cmd_current(args.root, args.component)
    if args.target:
        return cmd_inspect(args.root / args.target, args.component)
    # default: --list
    return cmd_list(args.root)


if __name__ == "__main__":
    raise SystemExit(main())
