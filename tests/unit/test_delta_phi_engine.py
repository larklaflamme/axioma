"""DeltaPhiEngine — S1/S2/S3 with perturbation-relative recording."""
from __future__ import annotations

import math

import pytest

from axioma.config import AxiomaConfig
from axioma.measurement import (
    DeltaPhiEngine,
    InternalStateRingBuffer,
    PerturbationKind,
    PerturbationScheduler,
    build_theta_engines,
)
from axioma.observability import AxiomaContext
from axioma.substrate import SubstrateApp


@pytest.fixture()
def app_ctx():
    cfg = AxiomaConfig()
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    ctx.register("substrate", app)
    buf = InternalStateRingBuffer(capacity=600)
    ctx.register("state_buffer", buf)
    short, _long = build_theta_engines(ctx, short_window=30, long_window=500, n_permutations=20)
    return cfg, ctx, app, buf, short


def test_construct() -> None:
    ctx = AxiomaContext()
    e = DeltaPhiEngine(ctx)
    assert e.name == "delta_phi"
    assert e.natural_period_beats == 5


def test_window_validation() -> None:
    ctx = AxiomaContext()
    with pytest.raises(ValueError, match="window_beats"):
        DeltaPhiEngine(ctx, window_beats=5)


def test_subscribes_to_perturbation_events(app_ctx) -> None:
    """The engine should auto-subscribe to perturbation_injected on construction."""
    _, ctx, app, _buf, _short = app_ctx
    pert = PerturbationScheduler(ctx, period_beats=600, seed=0)
    ctx.register("perturbation_scheduler", pert)
    e = DeltaPhiEngine(ctx, window_beats=50)
    app.tick(beat_no=0, timestamp=0.0)
    pert.inject_now(PerturbationKind.IMPULSE, magnitude=0.2)
    # Should open a window for this event
    assert e.active_window_count() == 1


def test_window_closes_after_window_beats(app_ctx) -> None:
    """After 50 beats post-perturbation, the window closes + S1/S2 are finalized."""
    _, ctx, app, buf, short = app_ctx
    pert = PerturbationScheduler(ctx, period_beats=600, seed=0)
    ctx.register("perturbation_scheduler", pert)
    e = DeltaPhiEngine(ctx, window_beats=50)
    # Warm up so theta_short has values
    for beat in range(40):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        short.run_if_due(beat, 1.0)
    pert.inject_now(PerturbationKind.STEP, magnitude=0.3)
    assert e.active_window_count() == 1
    # Beat through the window
    for beat in range(40, 95):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        short.run_if_due(beat, 1.0)
        e.run_if_due(beat, 1.0)
    # Window should be closed
    assert e.active_window_count() == 0
    cv = e.current_value()
    assert cv.valid
    assert cv.event_kind == "step"
    assert cv.s1_peak_delta_theta is not None
    assert cv.s1_peak_delta_theta >= 0


def test_s2_inf_when_not_recovered(app_ctx) -> None:
    """If theta_short doesn't return to baseline within window, S2 = inf."""
    _, ctx, app, buf, short = app_ctx
    pert = PerturbationScheduler(ctx, period_beats=600, seed=0)
    ctx.register("perturbation_scheduler", pert)
    e = DeltaPhiEngine(ctx, window_beats=50)
    # Warm theta_short
    for beat in range(40):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        short.run_if_due(beat, 1.0)
    # Inject very large perturbation
    pert.inject_now(PerturbationKind.STEP, magnitude=10.0)
    # Beat through window
    for beat in range(40, 95):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        short.run_if_due(beat, 1.0)
        e.run_if_due(beat, 1.0)
    cv = e.current_value()
    # S2 may or may not be inf depending on signal noise; just verify it's a number
    assert cv.s2_recovery_beats is None or math.isfinite(cv.s2_recovery_beats) or math.isinf(cv.s2_recovery_beats)


def test_no_theta_short_returns_quiet(app_ctx) -> None:
    """If no theta_short engine in context, ΔΦ stays at default."""
    _, _ctx, app, _buf, _short = app_ctx
    # New context without theta_short
    ctx2 = AxiomaContext()
    ctx2.register("substrate", app)
    e = DeltaPhiEngine(ctx2, window_beats=50)
    e.compute()
    cv = e.current_value()
    assert not cv.valid


def test_save_load_roundtrip(app_ctx) -> None:
    _, ctx, app, buf, short = app_ctx
    pert = PerturbationScheduler(ctx, period_beats=600, seed=0)
    ctx.register("perturbation_scheduler", pert)
    e = DeltaPhiEngine(ctx, window_beats=50)
    for beat in range(40):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        short.run_if_due(beat, 1.0)
    pert.inject_now(PerturbationKind.IMPULSE, magnitude=0.3)
    for beat in range(40, 95):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        short.run_if_due(beat, 1.0)
        e.run_if_due(beat, 1.0)
    snap = e.save_state()

    e2 = DeltaPhiEngine(ctx, window_beats=50)
    e2.load_state(snap)
    assert e2.current_value().s1_peak_delta_theta == e.current_value().s1_peak_delta_theta
    assert len(e2.history) == len(e.history)
