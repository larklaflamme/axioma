"""PlasticityTracker — observes plasticity buffers; reports adaptation_delta."""
from __future__ import annotations

import pytest

from axioma.config import AxiomaConfig
from axioma.measurement import PlasticityTracker
from axioma.observability import AxiomaContext
from axioma.schemas import ORGAN_ORDER
from axioma.substrate import SubstrateApp


@pytest.fixture()
def app_ctx():
    cfg = AxiomaConfig()
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    ctx.register("substrate", app)
    return cfg, ctx, app


def test_construct() -> None:
    ctx = AxiomaContext()
    t = PlasticityTracker(ctx)
    assert t.name == "plasticity_tracker"
    assert t.natural_period_beats == 100


def test_no_substrate_returns_invalid() -> None:
    ctx = AxiomaContext()
    t = PlasticityTracker(ctx)
    t.compute()
    assert not t.current_value().valid


def test_no_plasticity_summaries_returns_invalid(app_ctx) -> None:
    """If plasticity buffers haven't fired yet (no last_summary), report invalid."""
    _, ctx, _ = app_ctx
    t = PlasticityTracker(ctx)
    t.compute()
    assert not t.current_value().valid


def test_reports_adaptation_delta_after_plasticity_updates(app_ctx) -> None:
    _, ctx, app = app_ctx
    t = PlasticityTracker(ctx)
    # Beat substrate past 100 beats so plasticity buffers update at least once
    for beat in range(110):
        app.tick(beat_no=beat, timestamp=0.0)
    t.compute()
    reading = t.current_value()
    assert reading.valid
    assert set(reading.adaptation_delta.keys()) == set(ORGAN_ORDER)
    # All organs should have a numeric delta
    for organ in ORGAN_ORDER:
        assert isinstance(reading.adaptation_delta[organ], float)
        assert reading.adaptation_delta[organ] >= 0


def test_adaptation_delta_grows_with_more_history(app_ctx) -> None:
    _, ctx, app = app_ctx
    t = PlasticityTracker(ctx)
    # Need at least 4 plasticity updates for the per-half comparison to fire
    for beat in range(500):
        app.tick(beat_no=beat, timestamp=0.0)
        if beat > 0 and beat % 100 == 0:
            t.compute()
    reading = t.current_value()
    assert reading.valid
    # adaptation_delta should be > 0 for some organs (substrate is evolving)
    nonzero = sum(1 for v in reading.adaptation_delta.values() if v > 0)
    assert nonzero >= 3


def test_save_load_roundtrip(app_ctx) -> None:
    _, ctx, app = app_ctx
    t = PlasticityTracker(ctx)
    for beat in range(200):
        app.tick(beat_no=beat, timestamp=0.0)
        if beat > 0 and beat % 100 == 0:
            t.compute()
    snap = t.save_state()
    t2 = PlasticityTracker(ctx)
    t2.load_state(snap)
    r1 = t.current_value()
    r2 = t2.current_value()
    assert r1.beat_no == r2.beat_no
    assert r1.adaptation_delta == r2.adaptation_delta


def test_history_for_returns_max_drift_trace(app_ctx) -> None:
    _, ctx, app = app_ctx
    t = PlasticityTracker(ctx)
    for beat in range(300):
        app.tick(beat_no=beat, timestamp=0.0)
        if beat > 0 and beat % 100 == 0:
            t.compute()
    hist = t.history_for("eidolon")
    assert len(hist) >= 2
    for b, max_drift, var_ratio in hist:
        assert isinstance(b, int)
        assert max_drift >= 0
        assert var_ratio > 0  # var_ratio > 0 always (current_var / rolling_var + eps)
