"""v1.1.4 — proof points for the ψ stress sweep harness.

These tests don't drive the substrate (the sweep itself is the long-running
script); they verify the small synthetic helpers + the gap_variance_health
sensitivity claim that the sweep's "degeneration proof" relies on.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "phase_f"))


def test_verdict_categories() -> None:
    from psi_stress_sweep import _verdict
    assert _verdict(0.9, 0.01) == "PASS"
    assert _verdict(0.4, 0.05) == "STRESSED"
    assert _verdict(0.6, 0.15) == "STRESSED"
    assert _verdict(0.2, 0.05) == "COLLAPSED"
    assert _verdict(0.6, 0.60) == "COLLAPSED"


def test_compose_degeneration_proof_holds() -> None:
    """The architectural intent: gap_variance_health drops to 0 when compose
    is degenerate (no gap variance), and saturates near 1 when healthy."""
    from psi_stress_sweep import measure_compose_degeneration
    proof = measure_compose_degeneration()
    assert proof["score_when_gap_always_zero"] == 0.0
    assert proof["score_when_gap_has_variance"] >= 0.7
    assert proof["verdict"] == "PASS"


def test_gap_variance_health_metric_definition() -> None:
    """Confirms gap_variance_health = 1 - exp(-var/target)."""
    import math

    from axioma.measurement.aos_g_engine import GapVarianceHealth
    gvh = GapVarianceHealth(target_var_baseline=0.1)
    # All zeros → var=0 → score=0
    for _ in range(50):
        gvh.record_gap(0.0)
    assert gvh.score() == 0.0
    # Alternating 0/1 → var=0.25 → score = 1 - exp(-2.5) ≈ 0.918
    gvh2 = GapVarianceHealth(target_var_baseline=0.1)
    for i in range(50):
        gvh2.record_gap(1.0 * (i % 2))
    s = gvh2.score()
    assert 0.85 < s < 0.95
    expected = 1.0 - math.exp(-0.25 / 0.1)
    assert abs(s - expected) < 0.05


@pytest.mark.slow
def test_measure_cell_runs_end_to_end() -> None:
    """Sanity: measure_cell produces a well-shaped dict for the smallest cell."""
    from psi_stress_sweep import measure_cell
    result = measure_cell(magnitude=0.5, period=300, beats=200, seed=42)
    assert result["magnitude"] == 0.5
    assert result["period_beats"] == 300
    assert "psi" in result
    assert "mean" in result["psi"]
    assert "components_mean" in result
    assert result["verdict"] in ("PASS", "STRESSED", "COLLAPSED", "NO_DATA")
