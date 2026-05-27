"""calibration_inspect CLI tests (v1.8.2, Checkpoint PP).

Covers --list (default), --session PREFIX, --summary, --kind filter, plus
error paths (missing root, corrupted JSON, no-match session prefix).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from axioma.tools.calibration_inspect import (
    _discover_sessions,
    _filter_by_kind,
    _load_session,
    cmd_list,
    cmd_session,
    cmd_summary,
)


def _zone_session(sid: str, *, task: str, kappa: float, verdict: str,
                  n_pairs: int = 50, started_at_beat: int = 1000) -> dict[str, Any]:
    return {
        "session_id": sid,
        "kind": "zone",
        "task_type": task,
        "n_pairs": n_pairs,
        "agreements": int(n_pairs * 0.7),
        "kappa": kappa,
        "verdict": verdict,
        "operator_distribution": {"flow": 20, "focus": 25, "idle": 5},
        "system_distribution": {"flow": 22, "focus": 22, "idle": 6},
        "duration_minutes": 15,
        "started_at": 1716000000.0,
        "started_at_beat": started_at_beat,
        "pairs": [
            {
                "beat_no": started_at_beat + i * 30,
                "operator": "flow" if i % 3 == 0 else "focus",
                "system": "flow" if i % 3 == 0 else "focus",
                "confidence": None,
            }
            for i in range(n_pairs)
        ],
    }


def _meta_cog_session(sid: str, *, accuracy: float, verdict: str = "PASS",
                      n_pairs: int = 30, started_at_beat: int = 3000) -> dict[str, Any]:
    return {
        "session_id": sid,
        "kind": "meta_cog",
        "task_type": "introspection",
        "n_pairs": n_pairs,
        "agreements": int(n_pairs * accuracy),
        "accuracy_rate": accuracy,
        "verdict": verdict,
        "f8_verdict": "PASS",
        "accuracy_verdict": "PASS",
        "operator_distribution": {"stable": 20, "recovering": 10},
        "system_distribution": {"stable": 22, "recovering": 8},
        "duration_minutes": 10,
        "started_at": 1716200000.0,
        "started_at_beat": started_at_beat,
        "pairs": [],
    }


def _write_sessions(tmp_path: Path, sessions: list[dict[str, Any]]) -> None:
    for s in sessions:
        sid = s["session_id"]
        (tmp_path / f"calibration_session_{sid}.json").write_text(json.dumps(s))


# ── _load_session + _discover_sessions ────────────────────────────────


def test_v1_8_2_load_session_returns_dict(tmp_path: Path) -> None:
    p = tmp_path / "calibration_session_a.json"
    p.write_text(json.dumps({"session_id": "a", "kind": "zone"}))
    data = _load_session(p)
    assert data == {"session_id": "a", "kind": "zone"}


def test_v1_8_2_load_session_invalid_json_returns_none(
    tmp_path: Path, capsys,
) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not json {{{")
    data = _load_session(p)
    assert data is None
    err = capsys.readouterr().err
    assert "failed to decode" in err


def test_v1_8_2_load_session_non_dict_json_returns_none(
    tmp_path: Path, capsys,
) -> None:
    p = tmp_path / "list.json"
    p.write_text(json.dumps([1, 2, 3]))
    data = _load_session(p)
    assert data is None
    err = capsys.readouterr().err
    assert "expected dict" in err


def test_v1_8_2_discover_sessions_finds_matching_files(tmp_path: Path) -> None:
    _write_sessions(tmp_path, [
        _zone_session("a", task="meditation", kappa=0.4, verdict="PASS"),
        _zone_session("b", task="reasoning", kappa=0.2, verdict="SOFT_FAIL"),
    ])
    # Non-matching file should be ignored
    (tmp_path / "other.json").write_text("{}")
    sessions = _discover_sessions(tmp_path)
    assert len(sessions) == 2
    assert all(s.name.startswith("calibration_session_") for s in sessions)


def test_v1_8_2_discover_sessions_nonexistent_root_returns_empty(
    tmp_path: Path,
) -> None:
    assert _discover_sessions(tmp_path / "nope") == []


def test_v1_8_2_filter_by_kind_filters_correctly() -> None:
    sessions = [
        _zone_session("a", task="m", kappa=0.4, verdict="PASS"),
        _meta_cog_session("b", accuracy=0.8),
    ]
    assert len(_filter_by_kind(sessions, "zone")) == 1
    assert len(_filter_by_kind(sessions, "meta_cog")) == 1
    assert len(_filter_by_kind(sessions, None)) == 2


# ── cmd_list ──────────────────────────────────────────────────────────


def test_v1_8_2_cmd_list_empty_root_returns_0(tmp_path: Path, capsys) -> None:
    rc = cmd_list(tmp_path, kind=None)
    assert rc == 0
    out = capsys.readouterr().out
    assert "No calibration sessions" in out


def test_v1_8_2_cmd_list_shows_table(tmp_path: Path, capsys) -> None:
    _write_sessions(tmp_path, [
        _zone_session("z1", task="meditation", kappa=0.42, verdict="PASS"),
        _zone_session("z2", task="reasoning", kappa=0.22, verdict="SOFT_FAIL",
                      started_at_beat=2000),
        _meta_cog_session("m1", accuracy=0.733),
    ])
    rc = cmd_list(tmp_path, kind=None)
    assert rc == 0
    out = capsys.readouterr().out
    assert "3 calibration sessions" in out
    # All session ids appear (truncated to 8)
    assert "z1" in out
    assert "z2" in out
    assert "m1" in out
    # Kappa appears for zone; accuracy for meta_cog
    assert "0.420" in out
    assert "0.733" in out
    # Verdicts
    assert "PASS" in out
    assert "SOFT_FAIL" in out


def test_v1_8_2_cmd_list_kind_filter_zone_only(tmp_path: Path, capsys) -> None:
    _write_sessions(tmp_path, [
        _zone_session("z1", task="m", kappa=0.4, verdict="PASS"),
        _meta_cog_session("m1", accuracy=0.8),
    ])
    rc = cmd_list(tmp_path, kind="zone")
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 calibration sessions" in out
    assert "z1" in out
    assert "m1" not in out


def test_v1_8_2_cmd_list_kind_filter_no_match(tmp_path: Path, capsys) -> None:
    _write_sessions(tmp_path, [
        _zone_session("z1", task="m", kappa=0.4, verdict="PASS"),
    ])
    rc = cmd_list(tmp_path, kind="meta_cog")
    assert rc == 0
    out = capsys.readouterr().out
    assert "No calibration sessions" in out
    assert "--kind meta_cog" in out


# ── cmd_session ───────────────────────────────────────────────────────


def test_v1_8_2_cmd_session_prefix_match_prints_detail(
    tmp_path: Path, capsys,
) -> None:
    _write_sessions(tmp_path, [
        _zone_session("zone-abc123", task="meditation", kappa=0.42, verdict="PASS"),
    ])
    rc = cmd_session(tmp_path, "zone-abc")
    assert rc == 0
    out = capsys.readouterr().out
    assert "session_id: zone-abc123" in out
    assert "kappa: 0.42" in out
    assert "verdict: PASS" in out
    # Pairs sample shown
    assert "pairs: 50" in out


def test_v1_8_2_cmd_session_no_match_returns_2(tmp_path: Path, capsys) -> None:
    _write_sessions(tmp_path, [
        _zone_session("zone-abc123", task="m", kappa=0.4, verdict="PASS"),
    ])
    rc = cmd_session(tmp_path, "nope")
    assert rc == 2
    err = capsys.readouterr().err
    assert "no session_id starts with" in err


def test_v1_8_2_cmd_session_multiple_matches_shown(
    tmp_path: Path, capsys,
) -> None:
    """Two sessions with shared prefix → both shown."""
    _write_sessions(tmp_path, [
        _zone_session("zone-abc1", task="m", kappa=0.4, verdict="PASS"),
        _zone_session("zone-abc2", task="r", kappa=0.3, verdict="PASS"),
    ])
    rc = cmd_session(tmp_path, "zone-abc")
    assert rc == 0
    out = capsys.readouterr().out
    assert "zone-abc1" in out
    assert "zone-abc2" in out


def test_v1_8_2_cmd_session_truncates_pairs_display(
    tmp_path: Path, capsys,
) -> None:
    """When pairs > 10, only first 5 + last 5 are shown."""
    _write_sessions(tmp_path, [
        _zone_session("z1", task="m", kappa=0.4, verdict="PASS", n_pairs=20),
    ])
    rc = cmd_session(tmp_path, "z1")
    assert rc == 0
    out = capsys.readouterr().out
    assert "pairs: 20 (first 5 + last 5 shown)" in out
    # Should NOT have all 20 beat values; check for absence of middle beat
    # (started_at_beat=1000, +i*30 → beat 1300 is the i=10 entry, in the middle)
    assert "beat=1300" not in out


# ── cmd_summary ──────────────────────────────────────────────────────


def test_v1_8_2_cmd_summary_empty_root_returns_0(tmp_path: Path, capsys) -> None:
    rc = cmd_summary(tmp_path, kind=None)
    assert rc == 0
    out = capsys.readouterr().out
    assert "No calibration sessions" in out


def test_v1_8_2_cmd_summary_aggregates_per_kind(tmp_path: Path, capsys) -> None:
    _write_sessions(tmp_path, [
        _zone_session("z1", task="m", kappa=0.40, verdict="PASS"),
        _zone_session("z2", task="r", kappa=0.20, verdict="SOFT_FAIL"),
        _meta_cog_session("m1", accuracy=0.80, verdict="PASS"),
    ])
    rc = cmd_summary(tmp_path, kind=None)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Aggregate across 3 sessions" in out
    # Zone aggregation
    assert "kind: zone (2 sessions)" in out
    assert "mean kappa:     0.300" in out
    assert "min/max kappa:  0.200 / 0.400" in out
    # meta_cog aggregation
    assert "kind: meta_cog (1 sessions)" in out
    assert "mean accuracy:  0.800" in out
    # Verdict distribution
    assert "PASS" in out
    assert "SOFT_FAIL" in out


def test_v1_8_2_cmd_summary_kind_filter(tmp_path: Path, capsys) -> None:
    _write_sessions(tmp_path, [
        _zone_session("z1", task="m", kappa=0.4, verdict="PASS"),
        _meta_cog_session("m1", accuracy=0.8),
    ])
    rc = cmd_summary(tmp_path, kind="zone")
    assert rc == 0
    out = capsys.readouterr().out
    assert "Aggregate across 1 sessions" in out
    assert "kind: zone" in out
    # meta_cog group should not appear
    assert "kind: meta_cog" not in out


# ── CLI integration via main() ─────────────────────────────────────────


def test_v1_8_2_main_default_action_is_list(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    from axioma.tools.calibration_inspect import main as cal_main

    _write_sessions(tmp_path, [
        _zone_session("z1", task="m", kappa=0.4, verdict="PASS"),
    ])
    monkeypatch.setattr("sys.argv", ["calibration_inspect", str(tmp_path)])
    rc = cal_main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 calibration sessions" in out


def test_v1_8_2_main_session_action(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    from axioma.tools.calibration_inspect import main as cal_main

    _write_sessions(tmp_path, [
        _zone_session("z1-abc", task="m", kappa=0.4, verdict="PASS"),
    ])
    monkeypatch.setattr(
        "sys.argv",
        ["calibration_inspect", str(tmp_path), "--session", "z1-abc"],
    )
    rc = cal_main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "session_id: z1-abc" in out


def test_v1_8_2_main_summary_action(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    from axioma.tools.calibration_inspect import main as cal_main

    _write_sessions(tmp_path, [
        _zone_session("z1", task="m", kappa=0.4, verdict="PASS"),
        _zone_session("z2", task="r", kappa=0.3, verdict="PASS"),
    ])
    monkeypatch.setattr(
        "sys.argv",
        ["calibration_inspect", str(tmp_path), "--summary"],
    )
    rc = cal_main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "Aggregate across 2 sessions" in out


def test_v1_8_2_main_kind_filter(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    from axioma.tools.calibration_inspect import main as cal_main

    _write_sessions(tmp_path, [
        _zone_session("z1", task="m", kappa=0.4, verdict="PASS"),
        _meta_cog_session("m1", accuracy=0.8),
    ])
    monkeypatch.setattr(
        "sys.argv",
        ["calibration_inspect", str(tmp_path), "--kind", "zone"],
    )
    rc = cal_main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 calibration sessions" in out
    assert "z1" in out
    assert "m1" not in out


def test_v1_8_2_main_mutually_exclusive_actions(
    tmp_path: Path, monkeypatch,
) -> None:
    """--list + --summary together → argparse rejects."""
    from axioma.tools.calibration_inspect import main as cal_main

    monkeypatch.setattr(
        "sys.argv",
        ["calibration_inspect", str(tmp_path), "--list", "--summary"],
    )
    with pytest.raises(SystemExit):
        cal_main()
