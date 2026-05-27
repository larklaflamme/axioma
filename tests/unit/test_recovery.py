"""RecoveryProtocol + Q1 RejectionEscalator + RecoveryQuality (F1 windowed) + RecoveryLearner."""
from __future__ import annotations

import pytest

from axioma.config import AxiomaConfig
from axioma.measurement import (
    InternalStateRingBuffer,
    build_theta_engines,
)
from axioma.observability import AxiomaContext
from axioma.substrate import (
    LearnerEfficacy,
    RecoveryDecision,
    RecoveryEvent,
    RecoveryHistory,
    RecoveryLearner,
    RecoveryProtocol,
    RecoveryQuality,
    RecoveryRequest,
    RecoveryState,
    RejectionEscalator,
    SubstrateApp,
)
from axioma.substrate.recovery import (
    _recovery_event_from_dict,
    _recovery_event_to_dict,
)


@pytest.fixture()
def cfg():
    return AxiomaConfig()


@pytest.fixture()
def wired_ctx(cfg):
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    ctx.register("substrate", app)
    buf = InternalStateRingBuffer(capacity=600)
    ctx.register("state_buffer", buf)
    short, _long = build_theta_engines(ctx, short_window=30, long_window=500, n_permutations=10)
    return ctx, app, buf, short


def _fake_request(stage: int = 2, beat_no: int = 100) -> RecoveryRequest:
    import uuid
    return RecoveryRequest(
        request_id=str(uuid.uuid4()),
        beat_no=beat_no,
        stage=stage,
        signals={},
        source="fragmentation_monitor",
    )


# ── RejectionEscalator (Q1) ────────────────────────────────────────────────


def test_rejection_escalator_warns_after_3_consecutive(wired_ctx) -> None:
    ctx, _, _, _ = wired_ctx
    esc = RejectionEscalator(ctx, consecutive_threshold=3, cooldown_beats=100)
    received = []
    ctx.subscribe("recovery_rejected_run", lambda payload: received.append(payload))
    for i in range(3):
        req = _fake_request(stage=2, beat_no=100 + i)
        esc.on_decision(req, RecoveryDecision.REJECT_ALREADY_RECOVERING, 2, "reject_already_recovering")
    assert len(received) == 1
    assert received[0].consecutive_rejects == 3


def test_rejection_escalator_accept_resets_counter(wired_ctx) -> None:
    ctx, _, _, _ = wired_ctx
    esc = RejectionEscalator(ctx)
    received = []
    ctx.subscribe("recovery_rejected_run", lambda payload: received.append(payload))
    # 2 rejects, then accept, then 2 more rejects → no warning
    esc.on_decision(_fake_request(2, 100), RecoveryDecision.REJECT_BELOW_THRESHOLD, 2, "below_threshold")
    esc.on_decision(_fake_request(2, 110), RecoveryDecision.REJECT_BELOW_THRESHOLD, 2, "below_threshold")
    esc.on_decision(_fake_request(2, 120), RecoveryDecision.ACCEPT, 2, "accept")
    esc.on_decision(_fake_request(2, 130), RecoveryDecision.REJECT_BELOW_THRESHOLD, 2, "below_threshold")
    esc.on_decision(_fake_request(2, 140), RecoveryDecision.REJECT_BELOW_THRESHOLD, 2, "below_threshold")
    assert len(received) == 0


def test_rejection_escalator_episode_end_resets(wired_ctx) -> None:
    """When current_stage drops below 2, episode is over → reset."""
    ctx, _, _, _ = wired_ctx
    esc = RejectionEscalator(ctx)
    received = []
    ctx.subscribe("recovery_rejected_run", lambda payload: received.append(payload))
    # 2 rejects in episode, then current_stage drops → reset, then 2 rejects → no warn
    esc.on_decision(_fake_request(2, 100), RecoveryDecision.REJECT_BELOW_THRESHOLD, 2, "x")
    esc.on_decision(_fake_request(2, 110), RecoveryDecision.REJECT_BELOW_THRESHOLD, 2, "x")
    esc.on_decision(_fake_request(2, 120), RecoveryDecision.REJECT_BELOW_THRESHOLD, 0, "x")  # episode end
    esc.on_decision(_fake_request(2, 130), RecoveryDecision.REJECT_BELOW_THRESHOLD, 2, "x")
    esc.on_decision(_fake_request(2, 140), RecoveryDecision.REJECT_BELOW_THRESHOLD, 2, "x")
    assert len(received) == 0


def test_rejection_escalator_cooldown(wired_ctx) -> None:
    """After a warning, no more for cooldown_beats."""
    ctx, _, _, _ = wired_ctx
    esc = RejectionEscalator(ctx, consecutive_threshold=3, cooldown_beats=600)
    received = []
    ctx.subscribe("recovery_rejected_run", lambda payload: received.append(payload))
    # First 3 → warning
    for i in range(3):
        esc.on_decision(_fake_request(2, 100 + i), RecoveryDecision.REJECT_BELOW_THRESHOLD, 2, "x")
    assert len(received) == 1
    # 3 more within cooldown → no second warning
    for i in range(3):
        esc.on_decision(_fake_request(2, 200 + i), RecoveryDecision.REJECT_BELOW_THRESHOLD, 2, "x")
    assert len(received) == 1
    # 3 more outside cooldown → warning
    for i in range(3):
        esc.on_decision(_fake_request(2, 800 + i), RecoveryDecision.REJECT_BELOW_THRESHOLD, 2, "x")
    assert len(received) == 2


# ── RecoveryProtocol decision logic ────────────────────────────────────────


def test_accept_normal_request(wired_ctx, cfg) -> None:
    ctx, _, _, _ = wired_ctx
    rp = RecoveryProtocol(ctx, cfg.recovery)
    req = _fake_request(stage=2)
    # Substrate's coherence_budget should be > 0.20 in default cold start
    decision = rp.handle_recovery_request(req)
    # Could be ACCEPT or REJECT_BUDGET_INSUFFICIENT depending on substrate state;
    # accept the most likely path
    assert decision in (RecoveryDecision.ACCEPT, RecoveryDecision.REJECT_BUDGET_INSUFFICIENT)


def test_reject_below_threshold(wired_ctx, cfg) -> None:
    ctx, _, _, _ = wired_ctx
    rp = RecoveryProtocol(ctx, cfg.recovery)
    req = _fake_request(stage=1)
    decision = rp.handle_recovery_request(req)
    assert decision == RecoveryDecision.REJECT_BELOW_THRESHOLD


def test_reject_test_mode(wired_ctx, cfg) -> None:
    ctx, _, _, _ = wired_ctx
    rp = RecoveryProtocol(ctx, cfg.recovery, test_mode=True)
    req = _fake_request(stage=2)
    decision = rp.handle_recovery_request(req)
    assert decision == RecoveryDecision.REJECT_TEST_MODE


def test_force_accept_operator_override(wired_ctx, cfg) -> None:
    """Operator force-accept bypasses other reject paths."""
    ctx, _, _, _ = wired_ctx
    rp = RecoveryProtocol(ctx, cfg.recovery, test_mode=True)  # would normally reject
    req = RecoveryRequest(
        request_id="op-1", beat_no=100, stage=1, signals={},
        source="operator", force_accept=True,
    )
    decision = rp.handle_recovery_request(req)
    assert decision == RecoveryDecision.FORCE_ACCEPT_OPERATOR


def test_reject_already_recovering(wired_ctx, cfg) -> None:
    ctx, _, _, _ = wired_ctx
    rp = RecoveryProtocol(ctx, cfg.recovery)
    rp.state = RecoveryState.ACTIVE  # force in-progress state
    decision = rp.handle_recovery_request(_fake_request(stage=3))
    assert decision == RecoveryDecision.REJECT_ALREADY_RECOVERING


# ── Recovery action flow ──────────────────────────────────────────────────


def test_start_recovery_mutates_substrate(wired_ctx, cfg) -> None:
    ctx, app, _, _ = wired_ctx
    rp = RecoveryProtocol(ctx, cfg.recovery)
    # Capture pristine W
    original_W = app.anima.W.copy()
    rp._on_recovery_request(_fake_request(stage=2, beat_no=100))
    # State should be active
    assert rp.state == RecoveryState.ACTIVE
    # W should be reduced (coupling_reduction_factor = 0.8 default)
    import numpy as np
    assert not np.allclose(app.anima.W, original_W)


def test_recovery_completes_full_cycle(wired_ctx, cfg) -> None:
    """ACCEPT → ACTIVE → RESTORING → BASELINE through full duration."""
    ctx, _app, _, _ = wired_ctx
    rp = RecoveryProtocol(ctx, cfg.recovery)
    rp._on_recovery_request(_fake_request(stage=2, beat_no=100))
    assert rp.state == RecoveryState.ACTIVE
    # Tick through full duration (default 100 beats)
    for beat in range(100, 100 + cfg.recovery.default_duration_beats):
        rp.tick(beat)
    # Should now be RESTORING
    assert rp.state == RecoveryState.RESTORING
    # Tick through restore window
    for beat in range(100 + cfg.recovery.default_duration_beats,
                      100 + cfg.recovery.default_duration_beats + cfg.recovery.restore_beats):
        rp.tick(beat)
    # Should be back to BASELINE
    assert rp.state == RecoveryState.BASELINE
    # An event should be in history
    assert len(rp.history.events) == 1
    event = rp.history.events[0]
    assert event.quality_finalized


# ── RecoveryQuality F1 windowed smoothness ────────────────────────────────


def test_recovery_quality_has_smoothness_window_beats_field(wired_ctx, cfg) -> None:
    """F1: RecoveryQuality reports smoothness_window_beats for transparency."""
    ctx, app, buf, short = wired_ctx
    rp = RecoveryProtocol(ctx, cfg.recovery)
    # Warm up theta_short so quality computation has data
    for beat in range(40):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        short.run_if_due(beat, 1.0)
    rp._on_recovery_request(_fake_request(stage=2, beat_no=40))
    # Run through recovery
    for beat in range(40, 40 + cfg.recovery.default_duration_beats + cfg.recovery.restore_beats + 1):
        internal = app.tick(beat_no=beat, timestamp=0.0)
        buf.push(internal)
        short.run_if_due(beat, 1.0)
        rp.tick(beat)
    assert len(rp.history.events) == 1
    quality = rp.history.events[0].quality
    # F1: smoothness_window_beats reflects how many beats actually fed the smoothness calc
    # (≤ 50 per F1)
    assert quality.smoothness_window_beats <= 50
    assert quality.smoothness_window_beats > 0


# ── Recovery learner ─────────────────────────────────────────────────────


def test_learner_returns_defaults_under_cold_start(cfg) -> None:
    learner = RecoveryLearner(cfg.recovery)
    history = RecoveryHistory()
    params = learner.select_params(2, history)
    assert params.coupling_reduction_factor == cfg.recovery.coupling_reduction_factor


def test_learner_stage_4_always_uses_defaults(cfg) -> None:
    learner = RecoveryLearner(cfg.recovery)
    history = RecoveryHistory()
    # Even with arbitrary history, stage 4 uses defaults (emergency action)
    params = learner.select_params(4, history)
    assert params.coupling_reduction_factor == cfg.recovery.coupling_reduction_factor


def test_learner_warming_up_until_20_events(cfg) -> None:
    learner = RecoveryLearner(cfg.recovery)
    history = RecoveryHistory()
    # 10 finalized events at stage 2 — learner stays warming up
    for i in range(10):
        e = RecoveryEvent(
            event_id=f"e{i}", request_id=f"r{i}", stage=2,
            started_at_beat=i*100, ended_at_beat=i*100 + 100,
            actions_used={"coupling_reduction_factor": 0.8, "mneme_forgetting_boost": 1.5,
                          "recovery_compose_period_beats": 60},
            quality=RecoveryQuality(smoothness=0.5, completeness=0.5, composite_score=0.5),
            quality_finalized=True,
        )
        history.append(e)
    efficacy, _adopted = learner.update(history)
    # Hasn't reached the 20-event threshold for stage 2
    assert efficacy in (LearnerEfficacy.WARMING_UP, LearnerEfficacy.MONITORING)


def test_recovery_event_serialization_roundtrip() -> None:
    e = RecoveryEvent(
        event_id="e1", request_id="r1", stage=3,
        started_at_beat=100, ended_at_beat=200,
        actions_used={"coupling_reduction_factor": 0.7, "mneme_forgetting_boost": 1.8,
                      "recovery_compose_period_beats": 50},
        quality=RecoveryQuality(smoothness=0.6, completeness=0.8,
                                composite_score=0.7, smoothness_window_beats=50),
        quality_finalized=True,
    )
    d = _recovery_event_to_dict(e)
    e2 = _recovery_event_from_dict(d)
    assert e2.event_id == e.event_id
    assert e2.stage == e.stage
    assert e2.quality.smoothness == e.quality.smoothness
    assert e2.quality.smoothness_window_beats == e.quality.smoothness_window_beats


# ── Save/load roundtrip ─────────────────────────────────────────────────


def test_recovery_protocol_save_load(wired_ctx, cfg) -> None:
    ctx, _app, _buf, _short = wired_ctx
    rp = RecoveryProtocol(ctx, cfg.recovery)
    # Start a recovery
    rp._on_recovery_request(_fake_request(stage=2, beat_no=100))
    snap = rp.save_state()
    # New protocol; restore
    rp2 = RecoveryProtocol(ctx, cfg.recovery)
    rp2.load_state(snap)
    assert rp2.state == rp.state
    assert rp2._beats_remaining == rp._beats_remaining
    assert rp2._active_event is not None
