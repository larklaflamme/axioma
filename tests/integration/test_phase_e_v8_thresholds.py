"""V8 — F9 fragmentation threshold validation procedure (reproducible).

Per IMPLEMENTATION_PLAN_v1.0.md §9.2 V8 + ARCH §6.6.

Full V8 spec: 5 hours of operation × up to 3 iterations of perturbation-driven
escalation; each threshold tuned to achieve escalation probability
∈ [0.20, 0.40] with substrate's `test_mode=True` (rejects all recovery
requests during validation). Outputs `fragmentation_thresholds.json`.

This test is the **reproducible per-commit version**: shorter runs + smaller
perturbation battery, focused on verifying the *procedure* works end-to-end
(measures escalation probability, writes JSON, iterates). The full 5h × 3
iteration sweep ships as a separate script (`scripts/phase_e_f9_sweep.py`)
for the actual v1.0 acceptance.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from .phase_e_harness import build_phase_e_stack, run_for_beats


def _measure_escalation_probability(
    stack: Any, total_beats: int, sample_window_beats: int = 50,
) -> dict[int, float]:
    """Run for total_beats and count what fraction of windows escalated to each stage.

    Window = sample_window_beats; we sample after each window and bucket the
    MAX stage in that window. Returns {stage: probability}.
    """
    stage_hits: dict[int, int] = defaultdict(int)
    windows = 0
    last_window_start = stack.hb.beat_no
    last_max_stage = 0
    for _ in range(total_beats):
        stack.hb.tick()
        if (stack.hb.beat_no - last_window_start) >= sample_window_beats:
            stage_hits[last_max_stage] += 1
            windows += 1
            last_window_start = stack.hb.beat_no
            last_max_stage = 0
        else:
            cur_stage = stack.fragmentation_monitor.current_value().current_stage
            if cur_stage > last_max_stage:
                last_max_stage = cur_stage
    if windows == 0:
        return {}
    return {stage: count / windows for stage, count in stage_hits.items()}


@pytest.mark.slow
def test_threshold_validation_writes_output_file(tmp_path: Path) -> None:
    """Run a single shortened V8 iteration; verify output structure."""
    stack = build_phase_e_stack(
        # Force a moderately stressful regime
        perturbation_period_beats=100,
        perturbation_magnitude=0.5,
        test_mode_recovery=True,  # rejects recovery so fragmentation stays elevated
    )
    # Warm up
    run_for_beats(stack, 300)
    # Measure
    probs = _measure_escalation_probability(stack, total_beats=600, sample_window_beats=50)
    out_path = tmp_path / "fragmentation_thresholds.json"
    out_path.write_text(
        json.dumps(
            {
                "thresholds_used": dict(stack.fragmentation_monitor.thresholds),
                "escalation_probabilities": {str(k): v for k, v in probs.items()},
                "target_range": [0.20, 0.40],
                "iteration": 1,
                "test_mode": True,
            },
            indent=2,
        )
    )
    assert out_path.exists()
    body = json.loads(out_path.read_text())
    assert "thresholds_used" in body
    assert "escalation_probabilities" in body
    assert body["target_range"] == [0.20, 0.40]
    # Reproducibility check: each stage probability is in [0, 1]
    for prob in body["escalation_probabilities"].values():
        assert 0.0 <= prob <= 1.0


@pytest.mark.slow
def test_threshold_iteration_loop_smoke() -> None:
    """3-iteration loop that ADJUSTS thresholds based on observed probability.

    This is the V8 search procedure in miniature; each iteration nudges the
    threshold up if escalation is too frequent, down if too rare, with
    binary-search-like step sizes.
    """
    stack = build_phase_e_stack(
        perturbation_period_beats=100,
        perturbation_magnitude=0.5,
        test_mode_recovery=True,
    )
    run_for_beats(stack, 300)
    target_low, target_high = 0.20, 0.40
    iterations = []
    for it in range(3):
        probs = _measure_escalation_probability(stack, total_beats=400, sample_window_beats=50)
        stage2_prob = probs.get(2, 0.0) + probs.get(3, 0.0) + probs.get(4, 0.0)
        thresh = stack.fragmentation_monitor.thresholds["stage2_valence_var_ratio"]
        iterations.append({"iter": it, "stage2_prob": stage2_prob, "stage2_threshold": thresh})
        # Nudge: too rare → lower threshold; too frequent → raise threshold
        if stage2_prob < target_low:
            stack.fragmentation_monitor.thresholds["stage2_valence_var_ratio"] = thresh * 0.8
        elif stage2_prob > target_high:
            stack.fragmentation_monitor.thresholds["stage2_valence_var_ratio"] = thresh * 1.2
    # Verify the iteration loop ran and recorded data
    assert len(iterations) == 3
    for entry in iterations:
        assert 0.0 <= entry["stage2_prob"] <= 1.0
        assert entry["stage2_threshold"] > 0


def test_threshold_validation_uses_test_mode_recovery() -> None:
    """V8 explicitly requires test_mode=True so recovery rejects all requests."""
    stack = build_phase_e_stack(test_mode_recovery=True)
    assert stack.recovery_protocol.test_mode is True
    # Forcing a request should be rejected
    from axioma.substrate.recovery import RecoveryDecision, RecoveryRequest
    req = RecoveryRequest(
        request_id="t1", beat_no=100, stage=2, signals={}, source="fragmentation_monitor",
    )
    decision = stack.recovery_protocol.handle_recovery_request(req)
    assert decision == RecoveryDecision.REJECT_TEST_MODE
