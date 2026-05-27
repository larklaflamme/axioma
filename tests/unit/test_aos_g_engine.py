"""AOS-G + ψ engine — gap, structural_health (E1), gap_variance_health (E3),
compose_probe_health (E4)."""
from __future__ import annotations

import numpy as np
import pytest

from axioma.config import AxiomaConfig
from axioma.measurement import (
    AOSGEngine,
    IdentityCompose,
    InternalStateRingBuffer,
)
from axioma.measurement.aos_g_engine import (
    ComposeProbeHealth,
    GapVarianceHealth,
    StructuralHealthMonitor,
)
from axioma.observability import AxiomaContext
from axioma.schemas import ORGAN_ORDER, InternalState
from axioma.substrate import SubstrateApp


@pytest.fixture()
def wired_ctx():
    cfg = AxiomaConfig()
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    ctx.register("substrate", app)
    buf = InternalStateRingBuffer(capacity=200)
    ctx.register("state_buffer", buf)
    return cfg, ctx, app, buf


# ── IdentityCompose stub ────────────────────────────────────────────────


def test_identity_compose_returns_input_arrays() -> None:
    compose = IdentityCompose()
    internal = InternalState.initial(beat_no=0)
    out = compose.compose(internal)
    for o in ORGAN_ORDER:
        assert o in out
        np.testing.assert_array_equal(out[o], internal.get_organ(o).to_array())


# ── StructuralHealthMonitor (E1) ────────────────────────────────────────


def test_structural_health_initial_is_healthy() -> None:
    sh = StructuralHealthMonitor()
    assert sh.score() == 1.0


def test_structural_health_no_forbidden_modules_passes() -> None:
    """When forbidden modules don't exist (Phase B.3 — no interface yet),
    structural_health should pass."""
    sh = StructuralHealthMonitor(forbidden_modules=("nonexistent.module.xyz",))
    sh.check()
    assert sh.score() == 1.0


def test_structural_health_debounce_single_failure() -> None:
    """E1: single transient failure floored at 0.6."""
    sh = StructuralHealthMonitor(
        forbidden_modules=("axioma.schemas.internal_state",),  # always exists
        forbidden_name="InternalState",  # always exported
    )
    sh.check()  # 1 failure
    # consecutive_failures = 1, debounce_floor = 0.6
    score = sh.score()
    assert score >= 0.6  # debounce floor


def test_structural_health_two_consecutive_failures_below_floor() -> None:
    """E1: 2+ consecutive failures relax the debounce."""
    sh = StructuralHealthMonitor(
        forbidden_modules=("axioma.schemas.internal_state",),
        forbidden_name="InternalState",
    )
    sh.check()
    sh.check()  # consecutive = 2
    # Now score is raw pass_fraction (0/2 = 0)
    score = sh.score()
    assert score == 0.0


def test_structural_health_save_load_roundtrip() -> None:
    sh = StructuralHealthMonitor()
    sh.check()
    snap = sh.save_state()
    sh2 = StructuralHealthMonitor()
    sh2.load_state(snap)
    assert sh2.consecutive_failures == sh.consecutive_failures


# ── GapVarianceHealth (E3) ──────────────────────────────────────────────


def test_gap_variance_health_no_data_is_healthy() -> None:
    gvh = GapVarianceHealth()
    assert gvh.score() == 1.0


def test_gap_variance_health_zero_variance_reports_low() -> None:
    """Per ARCH §5.4: variance collapsed = compose degenerated = low score."""
    gvh = GapVarianceHealth()
    for _ in range(20):
        gvh.record_gap(0.5)  # constant gap → zero variance
    assert gvh.score() < 0.1


def test_gap_variance_health_grows_with_variance() -> None:
    """As variance approaches target, score → ~0.63 (1 - 1/e)."""
    gvh = GapVarianceHealth(target_var_baseline=0.1)
    rng = np.random.default_rng(0)
    for _ in range(50):
        gvh.record_gap(float(rng.normal(0.5, 0.3)))  # var ~ 0.09
    score = gvh.score()
    assert 0.3 < score < 1.0


def test_gap_variance_health_recovery_state_changes_blend() -> None:
    gvh = GapVarianceHealth()
    assert gvh.blend_factor == 0.0
    gvh.on_recovery_state("active")
    assert gvh.blend_factor == 1.0
    gvh.on_recovery_state("baseline")
    assert gvh.blend_factor == 0.0
    # Restoring decrements
    gvh.on_recovery_state("active")
    for _ in range(5):
        gvh.on_recovery_state("restoring")
    assert gvh.blend_factor < 1.0


# ── ComposeProbeHealth (E4) ─────────────────────────────────────────────


def test_compose_probe_skips_at_stage_4() -> None:
    """E4: probe is skipped during Stage 4 recovery."""
    probe = ComposeProbeHealth(probe_period=10)
    probe.on_stage_change(4)
    probe.on_recovery_state("active")
    probe.health = 0.5  # known prior value
    compose = IdentityCompose()
    internal = InternalState.initial(beat_no=10)
    probe.maybe_probe(beat_no=10, compose=compose, probe_internal=internal)
    # Stage 4 + active → skip; health unchanged
    assert probe.health == 0.5


def test_compose_probe_uses_baseline_when_not_recovering() -> None:
    probe = ComposeProbeHealth(probe_period=10)
    compose = IdentityCompose()
    internal = InternalState.initial(beat_no=10)
    # Calibrate with the compose output itself
    probe.calibrate(compose.compose(internal))
    probe.maybe_probe(beat_no=10, compose=compose, probe_internal=internal)
    # Identity compose + same internal + matching baseline → all organs match
    assert probe.score() == 1.0


def test_compose_probe_uses_recovery_when_in_recovery() -> None:
    probe = ComposeProbeHealth(probe_period=10)
    compose = IdentityCompose()
    internal = InternalState.initial(beat_no=10)
    expected_baseline = compose.compose(internal)
    # Recovery expected is DIFFERENT from baseline
    expected_recovery = {
        k: np.full_like(v, 999.0) for k, v in expected_baseline.items()
    }
    probe.calibrate(expected_baseline)
    probe.calibrate_recovery(expected_recovery)
    probe.on_recovery_state("active")
    probe.maybe_probe(beat_no=10, compose=compose, probe_internal=internal)
    # Compose returns ≈ internal, but expected_recovery is 999 — mismatch
    assert probe.score() < 1.0


def test_compose_probe_no_calibration_assumes_healthy() -> None:
    probe = ComposeProbeHealth(probe_period=10)
    compose = IdentityCompose()
    internal = InternalState.initial(beat_no=10)
    probe.maybe_probe(beat_no=10, compose=compose, probe_internal=internal)
    assert probe.score() == 1.0


# ── AOSGEngine ──────────────────────────────────────────────────────────


def test_aos_g_construct() -> None:
    ctx = AxiomaContext()
    e = AOSGEngine(ctx)
    assert e.name == "aos_g"
    assert e.natural_period_beats == 30


def test_aos_g_identity_compose_yields_zero_gap(wired_ctx) -> None:
    """With IdentityCompose, gap is always 0; per-organ_gap all 0."""
    _, ctx, app, buf = wired_ctx
    e = AOSGEngine(ctx, compose=IdentityCompose())
    for beat in range(60):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        e.run_if_due(beat, 1.0)
    cv = e.current_value()
    assert cv.valid
    assert cv.aos_g_gap == 0.0
    for organ, gap in cv.per_organ_gap.items():
        assert gap == 0.0


def test_aos_g_psi_reflects_min_of_subsignals(wired_ctx) -> None:
    """ψ = min(gv, sh, cp). With IdentityCompose, gap_variance_health → 0
    (compose degenerated), so ψ → 0."""
    _, ctx, app, buf = wired_ctx
    e = AOSGEngine(ctx, compose=IdentityCompose())
    for beat in range(120):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        e.run_if_due(beat, 1.0)
    cv = e.current_value()
    assert cv.valid
    assert cv.structural_health == 1.0  # interface module doesn't exist yet
    assert cv.compose_probe_health == 1.0  # no calibration set; assumed healthy
    # gap_variance_health collapses for stub compose
    assert cv.psi == cv.gap_variance_health


def test_aos_g_alert_fires_on_low_psi(wired_ctx) -> None:
    """When ψ < 0.3, aos_g_alert is True."""
    _, ctx, app, buf = wired_ctx
    e = AOSGEngine(ctx, compose=IdentityCompose())
    for beat in range(60):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        e.run_if_due(beat, 1.0)
    cv = e.current_value()
    if cv.psi < 0.3:
        assert cv.aos_g_alert


def test_aos_g_save_load_roundtrip(wired_ctx) -> None:
    _, ctx, app, buf = wired_ctx
    e = AOSGEngine(ctx, compose=IdentityCompose())
    for beat in range(60):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        e.run_if_due(beat, 1.0)
    snap = e.save_state()
    e2 = AOSGEngine(ctx, compose=IdentityCompose())
    e2.load_state(snap)
    cv1 = e.current_value()
    cv2 = e2.current_value()
    assert cv1.aos_g_gap == cv2.aos_g_gap
    assert cv1.psi == cv2.psi


def test_aos_g_responds_to_recovery_state_change(wired_ctx) -> None:
    """When recovery_state_change event fires, gap_variance_health blend updates."""
    _, ctx, _app, _buf = wired_ctx
    e = AOSGEngine(ctx, compose=IdentityCompose())
    initial_blend = e.gap_variance.blend_factor
    # Simulate a recovery_state_change event
    import asyncio
    asyncio.run(ctx.emit("recovery_state_change", {"beat_no": 100, "state": "active"}))
    assert e.gap_variance.blend_factor != initial_blend
    assert e.gap_variance.blend_factor == 1.0
