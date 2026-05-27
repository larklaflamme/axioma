"""ThetaShortEngine / ThetaLongEngine / RawMIEngine / CascadeDelayEngine."""
from __future__ import annotations

import pytest

from axioma.config import AxiomaConfig
from axioma.measurement import (
    CascadeDelayEngine,
    InternalStateRingBuffer,
    RawMIEngine,
    ThetaLongEngine,
    ThetaShortEngine,
    build_theta_engines,
)
from axioma.measurement.theta_engine import ThetaResult
from axioma.observability import AxiomaContext
from axioma.substrate import SubstrateApp


@pytest.fixture()
def wired_substrate():
    """Pre-warmed substrate + context with state_buffer + engines wired."""
    cfg = AxiomaConfig()
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    ctx.register("substrate", app)
    buf = InternalStateRingBuffer(capacity=600)
    ctx.register("state_buffer", buf)
    return ctx, app, buf


# ── ThetaShortEngine ────────────────────────────────────────────────────────


def test_theta_short_should_run_every_beat(wired_substrate) -> None:
    ctx, _, _ = wired_substrate
    e = ThetaShortEngine(ctx)
    for beat in range(5):
        assert e.should_run(beat, 1.0)


def test_theta_short_no_state_buffer_logs_and_returns() -> None:
    ctx = AxiomaContext()
    e = ThetaShortEngine(ctx)
    # Should NOT raise; just logs warning + returns
    e.compute()
    assert e.current_value() is None


def test_theta_short_not_warm_returns_none(wired_substrate) -> None:
    ctx, app, buf = wired_substrate
    e = ThetaShortEngine(ctx, window_size=30)
    # Push 20 beats (less than 30-beat window)
    for beat in range(20):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
    e.compute()
    assert e.current_value() is None


def test_theta_short_produces_value_when_warm(wired_substrate) -> None:
    ctx, app, buf = wired_substrate
    e = ThetaShortEngine(ctx, window_size=30, n_permutations=20)
    for beat in range(50):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
    e.compute()
    result = e.current_value()
    assert isinstance(result, ThetaResult)
    assert isinstance(result.theta, float)
    assert 0.0 <= result.p_value <= 1.0
    assert result.method in ("zscore", "rint")


def test_theta_short_window_validation() -> None:
    ctx = AxiomaContext()
    with pytest.raises(ValueError, match="window_size"):
        ThetaShortEngine(ctx, window_size=2)


def test_theta_short_save_load_roundtrip(wired_substrate) -> None:
    ctx, app, buf = wired_substrate
    e = ThetaShortEngine(ctx, window_size=30, n_permutations=20)
    for beat in range(50):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
    e.compute()
    snap = e.save_state()

    e2 = ThetaShortEngine(ctx, window_size=30, n_permutations=20)
    e2.load_state(snap)
    cv1 = e.current_value()
    cv2 = e2.current_value()
    assert cv1 is not None and cv2 is not None
    assert cv1.theta == cv2.theta


def test_theta_short_bias_diagnostic_insufficient_data(wired_substrate) -> None:
    ctx, _app, _buf = wired_substrate
    short = ThetaShortEngine(ctx, window_size=30, n_permutations=20)
    # No theta_long registered → insufficient_data
    bd = short.bias_diagnostic()
    assert bd.insufficient_data


# ── ThetaLongEngine ─────────────────────────────────────────────────────────


def test_theta_long_should_run_every_10_beats(wired_substrate) -> None:
    ctx, _, _ = wired_substrate
    e = ThetaLongEngine(ctx)
    assert e.should_run(0, 1.0)
    assert not e.should_run(1, 1.0)
    assert not e.should_run(9, 1.0)
    assert e.should_run(10, 1.0)
    assert e.should_run(100, 1.0)


# ── build_theta_engines convenience ────────────────────────────────────────


def test_build_theta_engines_registers_both(wired_substrate) -> None:
    ctx, _, _ = wired_substrate
    short, long_e = build_theta_engines(ctx, short_window=30, long_window=500)
    assert ctx.get("theta_short") is short
    assert ctx.get("theta_long") is long_e
    assert short.name == "theta_short"
    assert long_e.name == "theta_long"


# ── RawMIEngine ─────────────────────────────────────────────────────────────


def test_raw_mi_engine_construct(wired_substrate) -> None:
    ctx, _, _ = wired_substrate
    e = RawMIEngine(ctx)
    assert e.short_window == 5
    assert e.long_window == 20
    assert e.name == "raw_mi"


def test_raw_mi_window_validation() -> None:
    ctx = AxiomaContext()
    with pytest.raises(ValueError, match="short_window"):
        RawMIEngine(ctx, short_window=2)
    with pytest.raises(ValueError, match="long_window"):
        RawMIEngine(ctx, short_window=10, long_window=5)


def test_raw_mi_produces_per_pair_values(wired_substrate) -> None:
    ctx, app, buf = wired_substrate
    e = RawMIEngine(ctx)
    for beat in range(20):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
    e.compute()
    short_mi = e.latest_5beat()
    long_mi = e.latest_20beat()
    # 10 pairs across 5 organs
    assert len(short_mi) == 10
    assert len(long_mi) == 10
    # All MI values are non-negative
    for v in short_mi.values():
        assert v >= 0.0


def test_raw_mi_history_populates(wired_substrate) -> None:
    ctx, app, buf = wired_substrate
    e = RawMIEngine(ctx)
    for beat in range(10):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        e.compute()
    # anima-eidolon trace should have entries for beats 4..9 (warmed at beat 4)
    hist = e.history_5beat("anima-eidolon")
    assert len(hist) >= 5


def test_raw_mi_save_load_roundtrip(wired_substrate) -> None:
    ctx, app, buf = wired_substrate
    e = RawMIEngine(ctx)
    for beat in range(15):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        e.compute()
    snap = e.save_state()
    e2 = RawMIEngine(ctx)
    e2.load_state(snap)
    assert e2.latest_5beat() == e.latest_5beat()
    assert len(e2.history_5beat("anima-eidolon")) == len(e.history_5beat("anima-eidolon"))


# ── CascadeDelayEngine ──────────────────────────────────────────────────────


def test_cascade_delay_construct() -> None:
    ctx = AxiomaContext()
    e = CascadeDelayEngine(ctx, lookback_beats=20)
    assert e.name == "cascade_delay"
    assert e.lookback_beats == 20


def test_cascade_delay_lookback_validation() -> None:
    ctx = AxiomaContext()
    with pytest.raises(ValueError, match="lookback_beats"):
        CascadeDelayEngine(ctx, lookback_beats=2)


def test_cascade_delay_no_raw_mi_returns_invalid() -> None:
    """Without raw_mi engine registered, cascade_delay can't compute."""
    ctx = AxiomaContext()
    e = CascadeDelayEngine(ctx)
    e.compute()
    cv = e.current_value()
    assert not cv.valid


def test_cascade_delay_produces_valid_reading_when_wired(wired_substrate) -> None:
    ctx, app, buf = wired_substrate
    raw = RawMIEngine(ctx)
    ctx.register("raw_mi", raw)
    cascade = CascadeDelayEngine(ctx, lookback_beats=20)
    # Beat the substrate long enough for raw_mi to populate
    for beat in range(50):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        raw.compute()
        cascade.compute()
    cv = cascade.current_value()
    assert cv.valid
    # The value can be positive or negative (it's a time difference)
    assert isinstance(cv.cascade_delay_beats, float)
    # Per-downstream dict has entries for MNEME, NOUS, PNEUMA
    assert set(cv.per_downstream.keys()) >= {"mneme", "nous", "pneuma"}


def test_cascade_delay_feeds_pneuma_load_signal(wired_substrate) -> None:
    """When cascade_delay computes, it should set PNEUMA's cascade_delay_beats."""
    ctx, app, buf = wired_substrate
    raw = RawMIEngine(ctx)
    ctx.register("raw_mi", raw)
    cascade = CascadeDelayEngine(ctx, lookback_beats=20)
    _initial_pneuma_cascade = app.pneuma._cascade_delay_beats
    for beat in range(50):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        raw.compute()
        cascade.compute()
    # Should have been updated by cascade_delay engine
    cv = cascade.current_value()
    if cv.valid:
        assert app.pneuma._cascade_delay_beats == cv.cascade_delay_beats


def test_cascade_delay_save_load_roundtrip(wired_substrate) -> None:
    ctx, app, buf = wired_substrate
    raw = RawMIEngine(ctx)
    ctx.register("raw_mi", raw)
    cascade = CascadeDelayEngine(ctx)
    for beat in range(40):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        raw.compute()
        cascade.compute()
    snap = cascade.save_state()
    cascade2 = CascadeDelayEngine(ctx)
    cascade2.load_state(snap)
    assert cascade2.current_value().cascade_delay_beats == cascade.current_value().cascade_delay_beats
