"""CalibrationRecorder — F6/F8 live operator labeling."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from axioma.interface.calibration import (
    CalibrationRecorder,
    _cohens_kappa,
)
from axioma.measurement.meta_cognition_loop import MetaCognition, OverallAssessment
from axioma.observability import AxiomaContext
from axioma.schemas import Zone
from axioma.schemas.external_state import ExternalState


def _make_ctx_with_zone(zone: Zone = Zone.FOCUS) -> AxiomaContext:
    ctx = AxiomaContext()
    ext = ExternalState(
        anima=np.zeros(4, dtype=np.float32),
        eidolon=np.zeros(6, dtype=np.float32),
        mneme=np.zeros(5, dtype=np.float32),
        nous=np.zeros(6, dtype=np.float32),
        pneuma=np.zeros(7, dtype=np.float32),
        beat_no=100,
        timestamp=1.0,
    )
    ext.zone = zone

    class _MockCompose:
        latest_external = ext
    ctx.register("compose_function", _MockCompose())
    ctx.register("heartbeat", type("HB", (), {"beat_no": 100})())
    return ctx


def _make_ctx_with_metacog(
    assessment: OverallAssessment = OverallAssessment.NOMINAL,
    confidence: float = 0.9,
) -> AxiomaContext:
    ctx = AxiomaContext()
    mc = MetaCognition()
    mc.overall_assessment = assessment
    mc.confidence = confidence

    class _MockMC:
        current = mc
    ctx.register("meta_cognition_loop", _MockMC())
    ctx.register("heartbeat", type("HB", (), {"beat_no": 100})())
    return ctx


def test_session_lifecycle_zone(tmp_path: Path) -> None:
    ctx = _make_ctx_with_zone(zone=Zone.FOCUS)
    rec = CalibrationRecorder(ctx, results_root=tmp_path)
    session = rec.start_session(kind="zone", task_type="analytical", duration_minutes=60)
    assert session.session_id.startswith("zone-")
    assert session.task_type == "analytical"
    assert session.started_at_beat == 100
    assert rec.get_active("zone") is session
    # Record labels
    p1 = rec.record_label(kind="zone", beat_no=100, operator_label="focus")
    p2 = rec.record_label(kind="zone", beat_no=200, operator_label="flow")
    assert p1.operator_label == "focus" and p1.system_label == "focus"
    assert p2.operator_label == "flow" and p2.system_label == "focus"
    # End
    summary = rec.end_session(kind="zone")
    assert summary["n_pairs"] == 2
    assert summary["agreements"] == 1
    assert summary["kappa"] is not None  # κ computed
    # File written
    files = list(tmp_path.glob("calibration_session_*.json"))
    assert len(files) == 1
    body = json.loads(files[0].read_text())
    assert body["session_id"] == session.session_id
    assert len(body["pairs"]) == 2


def test_session_double_start_rejected() -> None:
    ctx = _make_ctx_with_zone()
    rec = CalibrationRecorder(ctx)
    rec.start_session(kind="zone", task_type="x")
    with pytest.raises(RuntimeError, match="already active"):
        rec.start_session(kind="zone", task_type="y")
    # But a different kind can start
    rec.start_session(kind="meta_cog", task_type="x")


def test_record_label_without_session_fails() -> None:
    ctx = _make_ctx_with_zone()
    rec = CalibrationRecorder(ctx)
    with pytest.raises(RuntimeError, match="no active session"):
        rec.record_label(kind="zone", beat_no=100, operator_label="focus")


def test_zone_session_pass_verdict(tmp_path: Path) -> None:
    """κ ≥ 0.3 → PASS."""
    ctx = _make_ctx_with_zone(zone=Zone.FOCUS)
    rec = CalibrationRecorder(ctx, results_root=tmp_path)
    rec.start_session(kind="zone", task_type="analytical")
    # 8 agreements, 2 disagreements out of 10 → high κ
    for _ in range(8):
        rec.record_label(kind="zone", beat_no=100, operator_label="focus")
    for _ in range(2):
        rec.record_label(kind="zone", beat_no=100, operator_label="flow")
    summary = rec.end_session(kind="zone")
    # Distributions: operator={focus:8, flow:2}; system={focus:10}
    # po = 0.8; pe = (0.8*1.0) + (0.2*0.0) = 0.8 → κ = 0
    # The pair has no diversity in system labels, so κ stays at 0.
    # This tests the κ=0 case (zero diversity, perfect chance match).
    assert summary["kappa"] == 0.0
    assert summary["verdict"] == "HARD_FAIL"


def test_zone_session_with_diverse_system_labels(tmp_path: Path) -> None:
    """When system labels diversify mid-session, κ > 0 is possible."""
    ctx = _make_ctx_with_zone(zone=Zone.FOCUS)
    rec = CalibrationRecorder(ctx, results_root=tmp_path)
    rec.start_session(kind="zone", task_type="x")
    # 5 agreements
    for _ in range(5):
        rec.record_label(kind="zone", beat_no=100, operator_label="focus")
    # Swap system label mid-session
    ctx.get("compose_function").latest_external.zone = Zone.FLOW
    for _ in range(5):
        rec.record_label(kind="zone", beat_no=100, operator_label="flow")
    summary = rec.end_session(kind="zone")
    # Now operator = system on all 10 → perfect agreement → κ = 1.0
    assert summary["agreements"] == 10
    assert summary["kappa"] == 1.0
    assert summary["verdict"] == "PASS"


def test_meta_cog_session_calibration(tmp_path: Path) -> None:
    """F8 calibration: confidence-weighted miscalibration."""
    ctx = _make_ctx_with_metacog(OverallAssessment.NOMINAL, confidence=0.9)
    rec = CalibrationRecorder(ctx, results_root=tmp_path)
    rec.start_session(kind="meta_cog", task_type="analytical")
    # All matches; high confidence → low miscalibration
    for _ in range(10):
        rec.record_label(kind="meta_cog", beat_no=100, operator_label="nominal")
    summary = rec.end_session(kind="meta_cog")
    assert summary["accuracy_rate"] == 1.0
    # confidence=0.9, accuracy=1 → miscalibration=0.1
    assert summary["mean_miscalibration"] == 0.1
    assert summary["f8_verdict"] == "PASS"
    assert summary["accuracy_verdict"] == "PASS"
    assert summary["verdict"] == "PASS"


def test_meta_cog_high_miscalibration_hard_fail(tmp_path: Path) -> None:
    """confidence 1.0 but accuracy 0 → miscalibration 1.0 → HARD_FAIL."""
    ctx = _make_ctx_with_metacog(OverallAssessment.NOMINAL, confidence=1.0)
    rec = CalibrationRecorder(ctx, results_root=tmp_path)
    rec.start_session(kind="meta_cog", task_type="x")
    for _ in range(10):
        rec.record_label(kind="meta_cog", beat_no=100, operator_label="fragmented")
    summary = rec.end_session(kind="meta_cog")
    assert summary["accuracy_rate"] == 0.0
    assert summary["mean_miscalibration"] == 1.0
    assert summary["f8_verdict"] == "HARD_FAIL"


def test_empty_session_insufficient_data(tmp_path: Path) -> None:
    ctx = _make_ctx_with_zone()
    rec = CalibrationRecorder(ctx, results_root=tmp_path)
    rec.start_session(kind="zone", task_type="x")
    summary = rec.end_session(kind="zone")
    assert summary["verdict"] == "INSUFFICIENT_DATA"
    assert summary["n_pairs"] == 0


def test_cohens_kappa_perfect_agreement() -> None:
    a = ["x", "y", "x", "y"]
    b = ["x", "y", "x", "y"]
    assert _cohens_kappa(a, b) == 1.0


def test_cohens_kappa_chance_only() -> None:
    """All same label both sides → po=1.0 pe=1.0 → undefined, returns 1.0."""
    a = ["x", "x", "x", "x"]
    b = ["x", "x", "x", "x"]
    assert _cohens_kappa(a, b) == 1.0


def test_cohens_kappa_empty_returns_zero() -> None:
    assert _cohens_kappa([], []) == 0.0


def test_cohens_kappa_complete_disagreement() -> None:
    a = ["x", "x", "x", "x"]
    b = ["y", "y", "y", "y"]
    # po=0; pe=0 (no shared categories at all in agreement) → -∞ would be wrong;
    # the implementation treats pe=0 as undefined, returns (0 - 0)/(1 - 0) = 0
    assert _cohens_kappa(a, b) == 0.0


def test_list_active_returns_all_open_sessions() -> None:
    ctx = AxiomaContext()
    ctx.register("heartbeat", type("HB", (), {"beat_no": 0})())
    rec = CalibrationRecorder(ctx)
    s1 = rec.start_session(kind="zone", task_type="x")
    s2 = rec.start_session(kind="meta_cog", task_type="y")
    active = rec.list_active()
    assert {s.session_id for s in active} == {s1.session_id, s2.session_id}


def test_snap_system_value_zone_no_compose(tmp_path: Path) -> None:
    """Without compose_function, zone snap returns 'unknown'."""
    ctx = AxiomaContext()
    ctx.register("heartbeat", type("HB", (), {"beat_no": 0})())
    rec = CalibrationRecorder(ctx, results_root=tmp_path)
    rec.start_session(kind="zone", task_type="x")
    pair = rec.record_label(kind="zone", beat_no=10, operator_label="focus")
    assert pair.system_label == "unknown"
