"""snapshot_inspect CLI tests (v1.8.0, Checkpoint NN).

Covers the three command modes (default --list, --current, --target) plus
the --component drill-down option and the error paths (missing root,
missing manifest, corrupted manifest, missing component file).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from axioma.persistence import SnapshotManager
from axioma.tools.snapshot_inspect import (
    cmd_current,
    cmd_inspect,
    cmd_list,
)


class FakeOrgan:
    name = "fake_organ"
    schema_version = 1

    def __init__(self, counter: int = 0) -> None:
        self.counter = counter

    def save_state(self) -> dict[str, Any]:
        return {"counter": self.counter, "history": ["a", "b"]}

    def load_state(self, snap: dict[str, Any]) -> None:
        self.counter = snap.get("counter", 0)


class OtherStateful:
    name = "other"
    schema_version = 2

    def save_state(self) -> dict[str, Any]:
        return {"q": 1, "r": "two"}

    def load_state(self, snap: dict[str, Any]) -> None:
        pass


async def _populate(tmp_snapshot_root: Path) -> SnapshotManager:
    mgr = SnapshotManager(tmp_snapshot_root)
    mgr.register(FakeOrgan(counter=42))
    mgr.register(OtherStateful())
    await mgr.take_snapshot(beat_no=500)
    await mgr.take_snapshot(beat_no=1000)
    await mgr.take_snapshot(beat_no=1500, daily=True)
    return mgr


# ── cmd_list ────────────────────────────────────────────────────────────


def test_v1_8_0_cmd_list_empty_root_returns_0(tmp_path: Path, capsys) -> None:
    """Empty root with no snapshots — must not crash; reports 'No snapshots'."""
    rc = cmd_list(tmp_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert "No snapshots" in out


async def test_v1_8_0_cmd_list_shows_rolling_and_daily(
    tmp_snapshot_root: Path, capsys,
) -> None:
    """Populated root shows rolling + daily snapshots with timestamps."""
    await _populate(tmp_snapshot_root)
    rc = cmd_list(tmp_snapshot_root)
    assert rc == 0
    out = capsys.readouterr().out
    # All three snapshots should appear
    assert "beat_500" in out
    assert "beat_1000" in out
    assert "beat_1500" in out
    # Daily marker
    assert "daily" in out
    # `current` symlink target marker
    assert "current →" in out


async def test_v1_8_0_cmd_list_marks_current_with_arrow(
    tmp_snapshot_root: Path, capsys,
) -> None:
    """The snapshot pointed to by `current` is flagged in the CUR column."""
    await _populate(tmp_snapshot_root)
    rc = cmd_list(tmp_snapshot_root)
    assert rc == 0
    out = capsys.readouterr().out
    # The arrow should appear at least once (the daily one was the last taken)
    assert "→" in out


# ── cmd_inspect ─────────────────────────────────────────────────────────


async def test_v1_8_0_cmd_inspect_prints_manifest(
    tmp_snapshot_root: Path, capsys,
) -> None:
    """Inspecting a single snapshot dir prints beat_no, components, sizes."""
    await _populate(tmp_snapshot_root)
    # Find one of the snapshot dirs
    snap_dir = next(p for p in tmp_snapshot_root.iterdir()
                    if p.is_dir() and "beat_500" in p.name)
    rc = cmd_inspect(snap_dir, component_name=None)
    assert rc == 0
    out = capsys.readouterr().out
    assert "beat_no:        500" in out
    assert "fake_organ" in out
    assert "v1" in out
    assert "other" in out
    assert "v2" in out


def test_v1_8_0_cmd_inspect_missing_dir_returns_2(tmp_path: Path, capsys) -> None:
    rc = cmd_inspect(tmp_path / "nonexistent", component_name=None)
    assert rc == 2
    err = capsys.readouterr().err
    assert "not found" in err


async def test_v1_8_0_cmd_inspect_missing_manifest_returns_2(
    tmp_path: Path, capsys,
) -> None:
    """A dir that exists but has no manifest.json reports 'no manifest'."""
    snap_dir = tmp_path / "broken"
    snap_dir.mkdir()
    rc = cmd_inspect(snap_dir, component_name=None)
    assert rc == 2
    err = capsys.readouterr().err
    assert "no manifest" in err


async def test_v1_8_0_cmd_inspect_corrupted_manifest_returns_2(
    tmp_path: Path, capsys,
) -> None:
    """A non-dict JSON manifest reports the decode error."""
    snap_dir = tmp_path / "broken"
    snap_dir.mkdir()
    (snap_dir / "manifest.json").write_text(json.dumps(["not", "a", "dict"]))
    rc = cmd_inspect(snap_dir, component_name=None)
    assert rc == 2
    err = capsys.readouterr().err
    assert "manifest decode failed" in err or "expected dict" in err


async def test_v1_8_0_cmd_inspect_with_component_dumps_state(
    tmp_snapshot_root: Path, capsys,
) -> None:
    """--component dumps the named component's saved state as pretty JSON."""
    await _populate(tmp_snapshot_root)
    snap_dir = next(p for p in tmp_snapshot_root.iterdir()
                    if p.is_dir() and "beat_500" in p.name)
    rc = cmd_inspect(snap_dir, component_name="fake_organ")
    assert rc == 0
    out = capsys.readouterr().out
    assert '"counter": 42' in out
    assert '"history"' in out
    assert "=== component 'fake_organ' state ===" in out


async def test_v1_8_0_cmd_inspect_with_missing_component_returns_2(
    tmp_snapshot_root: Path, capsys,
) -> None:
    """--component on a name not in the snapshot reports clearly."""
    await _populate(tmp_snapshot_root)
    snap_dir = next(p for p in tmp_snapshot_root.iterdir()
                    if p.is_dir() and "beat_500" in p.name)
    rc = cmd_inspect(snap_dir, component_name="nonexistent")
    assert rc == 2
    err = capsys.readouterr().err
    assert "not found" in err


# ── cmd_current ────────────────────────────────────────────────────────


async def test_v1_8_0_cmd_current_follows_symlink(
    tmp_snapshot_root: Path, capsys,
) -> None:
    """--current resolves the symlink and prints the target snapshot's manifest."""
    await _populate(tmp_snapshot_root)
    rc = cmd_current(tmp_snapshot_root, component_name=None)
    assert rc == 0
    out = capsys.readouterr().out
    # Most-recent snapshot was the daily beat_1500
    assert "beat_no:        1500" in out


def test_v1_8_0_cmd_current_no_symlink_returns_2(tmp_path: Path, capsys) -> None:
    """Cold-start root (no snapshots) — `current` symlink doesn't exist."""
    rc = cmd_current(tmp_path, component_name=None)
    assert rc == 2
    err = capsys.readouterr().err
    assert "cold start" in err or "no `current`" in err


# ── CLI integration via main() ─────────────────────────────────────────


async def test_v1_8_0_main_default_action_is_list(
    tmp_snapshot_root: Path, monkeypatch, capsys,
) -> None:
    """No action flag → defaults to --list."""
    from axioma.tools.snapshot_inspect import main as snap_main

    await _populate(tmp_snapshot_root)
    monkeypatch.setattr(
        "sys.argv",
        ["snapshot_inspect", str(tmp_snapshot_root)],
    )
    rc = snap_main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "beat_500" in out
    assert "beat_1500" in out


def test_v1_8_0_main_component_without_target_errors(
    tmp_path: Path, monkeypatch,
) -> None:
    """--component without --current/--target should fail at argparse level."""
    from axioma.tools.snapshot_inspect import main as snap_main

    monkeypatch.setattr(
        "sys.argv",
        ["snapshot_inspect", str(tmp_path), "--component", "fake_organ"],
    )
    with pytest.raises(SystemExit):
        snap_main()


async def test_v1_8_0_main_target_with_component_works(
    tmp_snapshot_root: Path, monkeypatch, capsys,
) -> None:
    """--target NAME --component NAME end-to-end via main()."""
    from axioma.tools.snapshot_inspect import main as snap_main

    await _populate(tmp_snapshot_root)
    # Find a snapshot dir name to pass as --target
    target_name = next(
        p.name for p in tmp_snapshot_root.iterdir()
        if p.is_dir() and "beat_500" in p.name
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "snapshot_inspect",
            str(tmp_snapshot_root),
            "--target",
            target_name,
            "--component",
            "fake_organ",
        ],
    )
    rc = snap_main()
    assert rc == 0
    out = capsys.readouterr().out
    assert '"counter": 42' in out
