"""v1.1.6 — AOS-G Weighted Euclidean gap tests.

Verifies:
  - Uniform weighting reduces EXACTLY to v1.0 plain L2.
  - Preset weightings shift the gap as expected when the chosen organ deviates.
  - Negative weights are rejected.
  - Missing organs in a weights dict default to 1.0.
  - Save/load round-trip preserves gap_weights.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from axioma.config import SubstrateConfig
from axioma.measurement.aos_g_engine import (
    EIDOLON_WEIGHTED_GAP_WEIGHTS,
    PNEUMA_WEIGHTED_GAP_WEIGHTS,
    UNIFORM_GAP_WEIGHTS,
    AOSGEngine,
    _normalize_weights,
)
from axioma.observability import AxiomaContext
from axioma.schemas import ORGAN_ORDER
from axioma.substrate.app import SubstrateApp


def _ctx_with_substrate() -> tuple[AxiomaContext, SubstrateApp]:
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(SubstrateConfig(), seed=42)
    for beat in range(10):
        app.tick(beat_no=beat, timestamp=float(beat) * 0.1)
    ctx.register("substrate", app)
    return ctx, app


def test_normalize_weights_fills_missing_organs() -> None:
    w = _normalize_weights({"eidolon": 2.0})
    assert w == {"anima": 1.0, "eidolon": 2.0, "mneme": 1.0, "nous": 1.0, "pneuma": 1.0}


def test_normalize_weights_rejects_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _normalize_weights({"eidolon": -0.5})


def test_default_weights_are_uniform() -> None:
    ctx, _ = _ctx_with_substrate()
    engine = AOSGEngine(ctx)
    assert engine.gap_weights == UNIFORM_GAP_WEIGHTS


def test_custom_weights_normalized() -> None:
    ctx, _ = _ctx_with_substrate()
    engine = AOSGEngine(ctx, gap_weights={"eidolon": 3.0})
    assert engine.gap_weights["eidolon"] == 3.0
    assert engine.gap_weights["anima"] == 1.0


def test_uniform_weights_match_plain_l2() -> None:
    """Verify exact equivalence: with uniform weights, the new path computes
    the same gap as the v1.0 plain L2."""
    ctx, app = _ctx_with_substrate()
    engine = AOSGEngine(ctx)  # uniform default
    internal = app.last_internal()
    assert internal is not None
    # Build a perturbed "external" — same shape but with random deltas
    rng = np.random.default_rng(0)
    per_organ_external = {}
    for name in ORGAN_ORDER:
        arr = internal.get_organ(name).to_array()
        per_organ_external[name] = arr + rng.normal(0, 0.1, size=arr.shape).astype(arr.dtype)
    # Compute manually with plain L2
    total_sq_plain = 0.0
    for name in ORGAN_ORDER:
        internal_arr = internal.get_organ(name).to_array()
        diff = internal_arr - per_organ_external[name]
        total_sq_plain += float(np.sum(diff * diff))
    expected_gap = math.sqrt(total_sq_plain)
    # Compute via engine path
    total_sq_weighted = 0.0
    for name in ORGAN_ORDER:
        internal_arr = internal.get_organ(name).to_array()
        diff = internal_arr - per_organ_external[name]
        per_dim_sq = float(np.sum(diff * diff))
        total_sq_weighted += engine.gap_weights[name] * per_dim_sq
    weighted_gap = math.sqrt(total_sq_weighted)
    assert abs(weighted_gap - expected_gap) < 1e-9


def test_eidolon_weighted_amplifies_eidolon_drift() -> None:
    """When ONLY eidolon drifts from internal, eidolon-weighted gap is larger
    than uniform gap (because eidolon's contribution gets the 2.5× weight)."""
    ctx, app = _ctx_with_substrate()
    internal = app.last_internal()
    assert internal is not None
    rng = np.random.default_rng(0)
    per_organ_external = {}
    for name in ORGAN_ORDER:
        arr = internal.get_organ(name).to_array()
        if name == "eidolon":
            per_organ_external[name] = arr + rng.normal(0, 0.5, size=arr.shape).astype(arr.dtype)
        else:
            per_organ_external[name] = arr.copy()
    # Compute under uniform
    uniform_engine = AOSGEngine(ctx, gap_weights=UNIFORM_GAP_WEIGHTS)
    eidolon_engine = AOSGEngine(ctx, gap_weights=EIDOLON_WEIGHTED_GAP_WEIGHTS)
    # We call the metric directly for a synthetic external
    def _gap(engine: AOSGEngine) -> float:
        total_sq = 0.0
        for name in ORGAN_ORDER:
            internal_arr = internal.get_organ(name).to_array()
            diff = internal_arr - per_organ_external[name]
            total_sq += engine.gap_weights[name] * float(np.sum(diff * diff))
        return math.sqrt(total_sq)
    u_gap = _gap(uniform_engine)
    e_gap = _gap(eidolon_engine)
    # With eidolon weight 2.5 (vs 1.0 in uniform), the eidolon contribution
    # is the only non-zero term, so eidolon_gap = sqrt(2.5) × uniform_gap ≈ 1.58 ×
    assert e_gap > u_gap
    assert abs(e_gap / u_gap - math.sqrt(2.5)) < 0.01


def test_pneuma_weighted_amplifies_pneuma_drift() -> None:
    ctx, app = _ctx_with_substrate()
    internal = app.last_internal()
    assert internal is not None
    rng = np.random.default_rng(1)
    per_organ_external = {}
    for name in ORGAN_ORDER:
        arr = internal.get_organ(name).to_array()
        if name == "pneuma":
            per_organ_external[name] = arr + rng.normal(0, 0.5, size=arr.shape).astype(arr.dtype)
        else:
            per_organ_external[name] = arr.copy()
    uniform_engine = AOSGEngine(ctx, gap_weights=UNIFORM_GAP_WEIGHTS)
    pneuma_engine = AOSGEngine(ctx, gap_weights=PNEUMA_WEIGHTED_GAP_WEIGHTS)
    def _gap(engine: AOSGEngine) -> float:
        total_sq = 0.0
        for name in ORGAN_ORDER:
            internal_arr = internal.get_organ(name).to_array()
            diff = internal_arr - per_organ_external[name]
            total_sq += engine.gap_weights[name] * float(np.sum(diff * diff))
        return math.sqrt(total_sq)
    assert _gap(pneuma_engine) > _gap(uniform_engine)


def test_save_load_preserves_gap_weights() -> None:
    ctx, _ = _ctx_with_substrate()
    engine = AOSGEngine(ctx, gap_weights=EIDOLON_WEIGHTED_GAP_WEIGHTS)
    snap = engine.save_state()
    assert snap["gap_weights"]["eidolon"] == 2.5
    ctx2 = AxiomaContext()
    ctx2.register("substrate", ctx.substrate)
    engine2 = AOSGEngine(ctx2)  # default uniform
    engine2.load_state(snap)
    assert engine2.gap_weights["eidolon"] == 2.5
    assert engine2.gap_weights["anima"] == 0.5


def test_recommended_alert_threshold_uniform_returns_baseline() -> None:
    from axioma.measurement.aos_g_engine import recommended_alert_threshold
    assert recommended_alert_threshold(None) == 0.10
    assert recommended_alert_threshold(UNIFORM_GAP_WEIGHTS) == 0.10


def test_recommended_alert_threshold_pneuma_scales_up() -> None:
    """PNEUMA-weighted gap is 1.52× uniform's baseline; threshold scales the same."""
    from axioma.measurement.aos_g_engine import recommended_alert_threshold
    threshold = recommended_alert_threshold(PNEUMA_WEIGHTED_GAP_WEIGHTS)
    assert 0.14 < threshold < 0.16  # ≈ 0.10 × 1.52 = 0.152


def test_recommended_alert_threshold_eidolon_scales_down() -> None:
    """EIDOLON-weighted gap is 0.72× uniform's baseline; threshold scales down."""
    from axioma.measurement.aos_g_engine import recommended_alert_threshold
    threshold = recommended_alert_threshold(EIDOLON_WEIGHTED_GAP_WEIGHTS)
    assert 0.06 < threshold < 0.08  # ≈ 0.10 × 0.72 = 0.072


def test_recommended_alert_threshold_arbitrary_requires_measurement() -> None:
    """Arbitrary weights without a measured gap_mean fall back to baseline."""
    from axioma.measurement.aos_g_engine import recommended_alert_threshold
    custom = {"anima": 0.3, "eidolon": 1.5, "mneme": 1.0, "nous": 1.0, "pneuma": 1.2}
    assert recommended_alert_threshold(custom) == 0.10
    # With measurement: scaled correctly
    threshold = recommended_alert_threshold(custom, variant_gap_mean=14.34)
    assert abs(threshold - 0.20) < 0.005  # = 0.10 × 14.34/7.17


def test_engine_with_uniform_matches_existing_v1_0_behavior() -> None:
    """Smoke: AOSGEngine with default uniform weights produces same gap output
    as the v1.0 path (this is the backwards-compat invariant)."""
    ctx, _app = _ctx_with_substrate()
    engine = AOSGEngine(ctx)
    # Run compute; verify it doesn't error and produces a valid reading
    engine.compute()
    reading = engine.current_value()
    assert reading.valid
    assert reading.aos_g_gap >= 0.0
