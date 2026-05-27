"""FragmentationMonitor — 4-stage detector + recovery_request emission."""
from __future__ import annotations

import pytest

from axioma.config import AxiomaConfig
from axioma.measurement import (
    FragmentationMonitor,
    FragmentationStageChange,
    InternalStateRingBuffer,
    RecoveryRequestPayload,
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
    return cfg, ctx, app, buf


def test_construct() -> None:
    ctx = AxiomaContext()
    m = FragmentationMonitor(ctx)
    assert m.name == "fragmentation_monitor"
    assert m.min_recovery_stage == 2


def test_no_substrate_or_buffer_returns_quiet() -> None:
    ctx = AxiomaContext()
    m = FragmentationMonitor(ctx)
    m.compute()
    assert not m.current_value().valid


def test_baseline_stage_zero(app_ctx) -> None:
    """With a freshly-running substrate, stage should stay at 0 in baseline."""
    _, ctx, app, buf = app_ctx
    m = FragmentationMonitor(ctx)
    for beat in range(200):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        m.run_if_due(beat, 1.0)
    cv = m.current_value()
    assert cv.valid
    # No perturbations + freshly-warm substrate → stage should be 0 or 1
    assert cv.current_stage <= 1


def test_stage4_pneuma_fragmentation_trigger(app_ctx) -> None:
    """Stage 4 fires when PNEUMA fragmentation > 0.7."""
    _, ctx, app, buf = app_ctx
    m = FragmentationMonitor(ctx)
    # Warm up
    for beat in range(30):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
    # Manually force PNEUMA's latent to render high fragmentation
    # fragmentation = to_unit(latent[2]) — needs latent[2] very positive
    app.pneuma.latent[2] = 100.0  # forces sigmoid → 1.0
    for beat in range(30, 50):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        m.run_if_due(beat, 1.0)
    cv = m.current_value()
    assert cv.valid
    assert cv.current_stage == 4


def test_stage_transition_emits_event(app_ctx) -> None:
    """A stage change should fire fragmentation_stage_change event."""
    _, ctx, app, buf = app_ctx
    m = FragmentationMonitor(ctx)
    received = []
    ctx.subscribe(
        "fragmentation_stage_change",
        lambda payload: received.append(payload),
    )
    # Warm up
    for beat in range(30):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
    # Force PNEUMA into fragmentation
    app.pneuma.latent[2] = 100.0
    for beat in range(30, 60):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        m.run_if_due(beat, 1.0)
    # At least one stage change event (0 → 4)
    assert len(received) >= 1
    assert all(isinstance(e, FragmentationStageChange) for e in received)
    # The first one should go from 0 to some higher stage
    first = received[0]
    assert first.new_stage > first.previous_stage


def test_recovery_request_emitted_in_episode(app_ctx) -> None:
    """When stage ≥ min_recovery_stage (default 2), recovery_request fires."""
    _, ctx, app, buf = app_ctx
    m = FragmentationMonitor(ctx)
    received_requests = []
    ctx.subscribe(
        "recovery_request",
        lambda payload: received_requests.append(payload),
    )
    # Warm up
    for beat in range(30):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
    # Force PNEUMA into fragmentation (stage 4)
    app.pneuma.latent[2] = 100.0
    for beat in range(30, 60):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        m.run_if_due(beat, 1.0)
    assert len(received_requests) >= 1
    assert all(isinstance(r, RecoveryRequestPayload) for r in received_requests)
    assert all(r.stage >= 2 for r in received_requests)


def test_save_load_roundtrip(app_ctx) -> None:
    _, ctx, app, buf = app_ctx
    m = FragmentationMonitor(ctx)
    for beat in range(60):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        m.run_if_due(beat, 1.0)
    snap = m.save_state()

    m2 = FragmentationMonitor(ctx)
    m2.load_state(snap)
    assert m2._previous_stage == m._previous_stage
    assert m2._rolling_retrieval_mean == m._rolling_retrieval_mean
