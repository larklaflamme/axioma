"""recovery_inspect CLI tests (v1.8.1, Checkpoint OO).

Covers three command modes (--list default, --event PREFIX, --learner) plus
filters (--stage, --synthetic, --real, --limit) and error paths
(missing snapshot dir, missing recovery_protocol.json, corrupted JSON).
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from axioma.tools.recovery_inspect import (
    _filter_events,
    cmd_event,
    cmd_learner,
    cmd_list,
)


def _make_event(
    *, stage: int, start: int, composite: float,
    synthetic: bool = False, finalized: bool = True,
) -> dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()),
        "request_id": str(uuid.uuid4()),
        "stage": stage,
        "started_at_beat": start,
        "ended_at_beat": start + 50,
        "actions_used": {
            "coupling_reduction_factor": 0.8,
            "mneme_forgetting_boost": 1.5,
            "recovery_compose_period_beats": 60,
        },
        "quality": {
            "smoothness": 0.7,
            "completeness": 0.8,
            "durability": 0.5,
            "composite_score": composite,
            "smoothness_window_beats": 50,
        },
        "quality_finalized": finalized,
        "is_synthetic": synthetic,
    }


def _sample_recovery_data() -> dict[str, Any]:
    events = [
        _make_event(stage=2, start=0, composite=0.70),
        _make_event(stage=3, start=100, composite=0.75),
        _make_event(stage=2, start=200, composite=0.80),
        _make_event(stage=3, start=300, composite=0.85),
        _make_event(stage=2, start=400, composite=0.90, synthetic=True),
    ]
    return {
        "state": "baseline",
        "history": events,
        "learner": {
            "adoptions_count": 3,
            "reversions_count": 1,
            "baseline_score_per_stage": {"2": 0.7, "3": 0.8},
            "efficacy_per_stage": {"2": "monitoring", "3": "effective"},
            "clean_baseline_remaining": {"2": 0, "3": 0},
            "current_params": {
                "2": {
                    "coupling_reduction_factor": 0.8,
                    "mneme_forgetting_boost": 1.5,
                    "recovery_compose_period_beats": 60,
                },
                "3": {
                    "coupling_reduction_factor": 0.75,
                    "mneme_forgetting_boost": 1.8,
                    "recovery_compose_period_beats": 80,
                },
            },
        },
    }


# ── _filter_events ─────────────────────────────────────────────────────


def test_v1_8_1_filter_no_filters_returns_most_recent_first() -> None:
    data = _sample_recovery_data()
    out = _filter_events(
        data["history"],
        stage=None, synthetic_only=False, real_only=False, limit=20,
    )
    assert len(out) == 5
    # Most-recent-first (highest started_at_beat first)
    assert out[0]["started_at_beat"] == 400
    assert out[-1]["started_at_beat"] == 0


def test_v1_8_1_filter_stage_filters_correctly() -> None:
    data = _sample_recovery_data()
    out = _filter_events(
        data["history"],
        stage=2, synthetic_only=False, real_only=False, limit=20,
    )
    assert len(out) == 3
    assert all(e["stage"] == 2 for e in out)


def test_v1_8_1_filter_synthetic_only_picks_synth_events() -> None:
    data = _sample_recovery_data()
    out = _filter_events(
        data["history"],
        stage=None, synthetic_only=True, real_only=False, limit=20,
    )
    assert len(out) == 1
    assert out[0]["is_synthetic"] is True


def test_v1_8_1_filter_real_only_excludes_synth() -> None:
    data = _sample_recovery_data()
    out = _filter_events(
        data["history"],
        stage=None, synthetic_only=False, real_only=True, limit=20,
    )
    assert len(out) == 4
    assert all(not e["is_synthetic"] for e in out)


def test_v1_8_1_filter_limit_caps_output() -> None:
    data = _sample_recovery_data()
    out = _filter_events(
        data["history"],
        stage=None, synthetic_only=False, real_only=False, limit=2,
    )
    assert len(out) == 2


# ── cmd_list ────────────────────────────────────────────────────────────


def test_v1_8_1_cmd_list_prints_table(capsys) -> None:
    data = _sample_recovery_data()
    rc = cmd_list(
        data, stage=None, synthetic_only=False, real_only=False, limit=20,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "recovery history: 5 total events" in out
    assert "EVENT_ID" in out
    assert "COMPOSITE" in out
    # All 5 events listed
    assert "0.900" in out
    assert "0.700" in out


def test_v1_8_1_cmd_list_shows_filter_metadata_in_header(capsys) -> None:
    data = _sample_recovery_data()
    rc = cmd_list(
        data, stage=3, synthetic_only=False, real_only=True, limit=10,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "filter: stage=3" in out
    assert "filter: --real" in out


def test_v1_8_1_cmd_list_empty_filter_prints_no_match(capsys) -> None:
    data = _sample_recovery_data()
    rc = cmd_list(
        data, stage=99, synthetic_only=False, real_only=False, limit=20,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "no events match" in out


def test_v1_8_1_cmd_list_corrupt_history_returns_2(capsys) -> None:
    """If recovery_protocol.history is not a list, return 2 and report clearly."""
    data: dict[str, Any] = {"history": "not a list"}
    rc = cmd_list(
        data, stage=None, synthetic_only=False, real_only=False, limit=20,
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "expected list" in err


# ── cmd_event ──────────────────────────────────────────────────────────


def test_v1_8_1_cmd_event_matches_by_prefix(capsys) -> None:
    data = _sample_recovery_data()
    first_id = data["history"][0]["event_id"]
    rc = cmd_event(data, first_id[:8])
    assert rc == 0
    out = capsys.readouterr().out
    assert "matched 1 event" in out
    # JSON dump should contain the full event_id + composite_score
    assert first_id in out
    assert '"composite_score": 0.7' in out


def test_v1_8_1_cmd_event_no_match_returns_2(capsys) -> None:
    data = _sample_recovery_data()
    rc = cmd_event(data, "zzzz")
    assert rc == 2
    err = capsys.readouterr().err
    assert "no event_id starts with" in err


def test_v1_8_1_cmd_event_corrupt_history_returns_2(capsys) -> None:
    data: dict[str, Any] = {"history": 42}
    rc = cmd_event(data, "any")
    assert rc == 2


# ── cmd_learner ────────────────────────────────────────────────────────


def test_v1_8_1_cmd_learner_prints_state(capsys) -> None:
    data = _sample_recovery_data()
    rc = cmd_learner(data)
    assert rc == 0
    out = capsys.readouterr().out
    assert "adoptions_count:    3" in out
    assert "reversions_count:   1" in out
    assert "baseline_score" in out
    assert "efficacy_per_stage" in out
    # Per-stage params printed
    assert "stage 2" in out
    assert "coupling_reduction_factor: 0.8" in out
    assert "stage 3" in out
    assert "mneme_forgetting_boost: 1.8" in out


def test_v1_8_1_cmd_learner_missing_keys_handled_gracefully(capsys) -> None:
    """A recovery_protocol with no learner state (early-life snapshot) still works."""
    data: dict[str, Any] = {"history": [], "learner": {}}
    rc = cmd_learner(data)
    assert rc == 0
    out = capsys.readouterr().out
    assert "adoptions_count:    0" in out
    assert "reversions_count:   0" in out


# ── CLI integration via main() ─────────────────────────────────────────


def _write_recovery_snapshot(snapshot_dir: Path) -> None:
    """Write a recovery_protocol.json into the dir."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "recovery_protocol.json").write_text(
        json.dumps(_sample_recovery_data())
    )


def test_v1_8_1_main_root_as_snapshot_dir_lists_events(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """When ROOT itself contains recovery_protocol.json, treat ROOT as the
    snapshot dir (no --current needed)."""
    from axioma.tools.recovery_inspect import main as rec_main

    _write_recovery_snapshot(tmp_path)
    monkeypatch.setattr("sys.argv", ["recovery_inspect", str(tmp_path)])
    rc = rec_main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "5 total events" in out


def test_v1_8_1_main_missing_recovery_json_returns_2(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """Snapshot dir without recovery_protocol.json reports clearly."""
    from axioma.tools.recovery_inspect import main as rec_main

    monkeypatch.setattr("sys.argv", ["recovery_inspect", str(tmp_path)])
    rc = rec_main()
    assert rc == 2


def test_v1_8_1_main_target_resolves_via_root(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """--target NAME resolves ROOT/NAME and reads its recovery_protocol.json."""
    from axioma.tools.recovery_inspect import main as rec_main

    snap_dir = tmp_path / "20260527_test_beat_500"
    _write_recovery_snapshot(snap_dir)
    monkeypatch.setattr(
        "sys.argv",
        ["recovery_inspect", str(tmp_path),
         "--target", "20260527_test_beat_500"],
    )
    rc = rec_main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "5 total events" in out


def test_v1_8_1_main_current_follows_symlink(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """--current follows ROOT/current → real snapshot dir."""
    import os

    from axioma.tools.recovery_inspect import main as rec_main

    snap_dir = tmp_path / "real_dir_beat_500"
    _write_recovery_snapshot(snap_dir)
    os.symlink(snap_dir.name, tmp_path / "current")
    monkeypatch.setattr(
        "sys.argv", ["recovery_inspect", str(tmp_path), "--current"],
    )
    rc = rec_main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "5 total events" in out


def test_v1_8_1_main_learner_action(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    from axioma.tools.recovery_inspect import main as rec_main

    _write_recovery_snapshot(tmp_path)
    monkeypatch.setattr(
        "sys.argv", ["recovery_inspect", str(tmp_path), "--learner"],
    )
    rc = rec_main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "adoptions_count:    3" in out


def test_v1_8_1_main_event_action(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """--event PREFIX matches by event_id prefix."""
    from axioma.tools.recovery_inspect import main as rec_main

    snap_data = _sample_recovery_data()
    tmp_path_snap = tmp_path
    tmp_path_snap.mkdir(parents=True, exist_ok=True)
    (tmp_path_snap / "recovery_protocol.json").write_text(json.dumps(snap_data))
    first_id_prefix = snap_data["history"][0]["event_id"][:8]
    monkeypatch.setattr(
        "sys.argv",
        ["recovery_inspect", str(tmp_path), "--event", first_id_prefix],
    )
    rc = rec_main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "matched 1 event" in out


def test_v1_8_1_main_mutually_exclusive_actions(
    tmp_path: Path, monkeypatch,
) -> None:
    """--list + --learner together → argparse rejects."""
    from axioma.tools.recovery_inspect import main as rec_main

    _write_recovery_snapshot(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["recovery_inspect", str(tmp_path), "--list", "--learner"],
    )
    with pytest.raises(SystemExit):
        rec_main()
