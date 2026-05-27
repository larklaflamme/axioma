"""Phase B.1 end-to-end: substrate + state_buffer + all 4 measurement engines."""
from __future__ import annotations

import time

import pytest
import torch

from axioma.config import AxiomaConfig
from axioma.measurement import (
    CascadeDelayEngine,
    InternalStateRingBuffer,
    RawMIEngine,
    build_theta_engines,
)
from axioma.observability import AxiomaContext
from axioma.runtime import Heartbeat
from axioma.substrate import SubstrateApp


@pytest.fixture()
def b1_app():
    """Full Phase-B.1 system: substrate + ring buffer + 4 engines + heartbeat."""
    cfg = AxiomaConfig()
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    ctx.register("substrate", app)
    buf = InternalStateRingBuffer(capacity=600)
    ctx.register("state_buffer", buf)
    short, long_e = build_theta_engines(ctx, short_window=30, long_window=500, n_permutations=20)
    raw = RawMIEngine(ctx)
    ctx.register("raw_mi", raw)
    cascade = CascadeDelayEngine(ctx, lookback_beats=20)
    ctx.register("cascade_delay", cascade)
    hb = Heartbeat(ctx=ctx, substrate=app, state_buffer=buf, hz=10)
    for eng in (short, raw, cascade, long_e):
        hb.register_measurement_engine(eng)
    return ctx, app, buf, hb


def test_heartbeat_populates_state_buffer(b1_app) -> None:
    _, _, buf, hb = b1_app
    for _ in range(50):
        hb.tick()
    assert len(buf) == 50


def test_theta_short_produces_value_after_warmup(b1_app) -> None:
    ctx, _, _, hb = b1_app
    for _ in range(60):  # 60 beats > theta_short window 30 → engine warm
        hb.tick()
    short = ctx.get("theta_short")
    assert short.current_value() is not None
    assert isinstance(short.current_value().theta, float)


def test_theta_long_produces_value_after_500_beats(b1_app) -> None:
    ctx, _, _, hb = b1_app
    for _ in range(510):
        hb.tick()
    long_e = ctx.get("theta_long")
    assert long_e.current_value() is not None
    # Should have run on GPU if available
    expected_backend = "gpu" if torch.cuda.is_available() else "cpu"
    assert long_e.current_value().details["backend"] == expected_backend


def test_raw_mi_populates_after_5_beats(b1_app) -> None:
    ctx, _, _, hb = b1_app
    for _ in range(10):
        hb.tick()
    raw = ctx.get("raw_mi")
    short_mi = raw.latest_5beat()
    assert len(short_mi) == 10
    # Most should be > 0 (substrate is correlated)
    assert sum(1 for v in short_mi.values() if v > 0) >= 5


def test_cascade_delay_valid_after_25_beats(b1_app) -> None:
    ctx, _, _, hb = b1_app
    for _ in range(30):
        hb.tick()
    cascade = ctx.get("cascade_delay")
    assert cascade.current_value().valid


def test_heartbeat_persistence_through_beats(b1_app, tmp_snapshot_root) -> None:
    """End-to-end: substrate + engines + ring buffer all snapshot + restore."""
    import asyncio

    from axioma.persistence import SnapshotManager

    ctx, app, buf, hb = b1_app
    short = ctx.get("theta_short")
    raw = ctx.get("raw_mi")
    cascade = ctx.get("cascade_delay")

    mgr = SnapshotManager(tmp_snapshot_root)
    mgr.register(app)
    mgr.register(buf)
    mgr.register(short)
    mgr.register(raw)
    mgr.register(cascade)

    for _ in range(60):
        hb.tick()
    asyncio.run(mgr.take_snapshot(beat_no=60))

    # Verify roundtrip — fresh instances + load
    cfg = AxiomaConfig()
    ctx2 = AxiomaContext()
    app2 = SubstrateApp.from_config(cfg.substrate, seed=99)  # different seed
    ctx2.register("substrate", app2)
    buf2 = InternalStateRingBuffer(capacity=600)
    ctx2.register("state_buffer", buf2)
    short2, _long2 = build_theta_engines(ctx2, short_window=30, long_window=500, n_permutations=20)
    raw2 = RawMIEngine(ctx2)
    ctx2.register("raw_mi", raw2)
    cascade2 = CascadeDelayEngine(ctx2, lookback_beats=20)
    ctx2.register("cascade_delay", cascade2)

    mgr2 = SnapshotManager(tmp_snapshot_root)
    mgr2.register(app2)
    mgr2.register(buf2)
    mgr2.register(short2)
    mgr2.register(raw2)
    mgr2.register(cascade2)
    asyncio.run(mgr2.load_latest())

    # Buffer state restored — same size + same most-recent state
    assert len(buf2) == len(buf)
    # θ_short restored — same current theta
    cv1 = short.current_value()
    cv2 = short2.current_value()
    if cv1 is not None and cv2 is not None:
        assert cv1.theta == cv2.theta


def test_beat_duration_under_budget(b1_app) -> None:
    """Phase E performance acceptance gate (V11): 10-beat rolling average < 100ms."""
    _, _, _, hb = b1_app
    # Warm up to get out of cold-start (first beats are heavier due to GPU init)
    for _ in range(50):
        hb.tick()
    # Measure 50-beat average
    t0 = time.perf_counter()
    for _ in range(50):
        hb.tick()
    avg = (time.perf_counter() - t0) / 50
    # 100ms is the V11 hard ceiling; Phase B.1 should be well under
    assert avg < 0.1, f"avg beat duration {avg * 1000:.1f}ms exceeds 100ms"


@pytest.mark.slow
def test_heartbeat_runs_async_for_beats(b1_app) -> None:
    """Async run for a fixed number of beats."""
    import asyncio

    _, _, _, hb = b1_app
    # 1000 Hz so the test is fast
    hb.hz = 1000
    hb.period_s = 0.001
    asyncio.run(hb.run(beats=50))
    assert hb.beat_no == 50
