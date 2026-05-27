"""CoherenceScheduler — throttle policy + E13 effectiveness."""
from __future__ import annotations

import pytest

from axioma.config import AxiomaConfig
from axioma.observability import AxiomaContext
from axioma.scheduler import (
    DEFAULT_ENGINE_PRIORITY,
    THROTTLE_THRESHOLDS,
    CoherenceScheduler,
    IneffectiveThrottleEvent,
    Priority,
)
from axioma.substrate import SubstrateApp


@pytest.fixture()
def app_ctx():
    cfg = AxiomaConfig()
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    ctx.register("substrate", app)
    return cfg, ctx, app


# ── Priority table (E2: meta-cog at High) ───────────────────────────────


def test_meta_cog_is_high_priority() -> None:
    """E2: meta_cognition is HIGH (only throttled at budget < 0.15)."""
    assert DEFAULT_ENGINE_PRIORITY["meta_cognition"] == Priority.HIGH


def test_substrate_compose_recovery_are_critical() -> None:
    """CRITICAL engines are never throttled."""
    for name in ("substrate", "compose", "recovery_protocol"):
        assert DEFAULT_ENGINE_PRIORITY[name] == Priority.CRITICAL


def test_critical_threshold_is_zero() -> None:
    assert THROTTLE_THRESHOLDS[Priority.CRITICAL] == 0.0
    assert THROTTLE_THRESHOLDS[Priority.HIGH] == 0.15
    assert THROTTLE_THRESHOLDS[Priority.MEDIUM] == 0.30
    assert THROTTLE_THRESHOLDS[Priority.LOW] == 0.50


# ── Basic throttle decisions ────────────────────────────────────────────


def test_throttle_critical_never(app_ctx) -> None:
    _, ctx, _ = app_ctx
    sched = CoherenceScheduler(ctx)
    sched._current_budget = 0.05  # severe stress
    t = sched.throttle_for("substrate")
    assert not t.is_throttled
    assert t.effective_period_beats == t.natural_period_beats


def test_throttle_low_under_50_percent(app_ctx) -> None:
    _, ctx, _ = app_ctx
    sched = CoherenceScheduler(ctx)
    sched.register_natural_period("plasticity_tracker", 100)
    sched._current_budget = 0.4  # below 0.50 → throttle LOW
    t = sched.throttle_for("plasticity_tracker")
    assert t.is_throttled
    assert t.effective_period_beats == 400  # × 4


def test_throttle_medium_under_30_percent(app_ctx) -> None:
    _, ctx, _ = app_ctx
    sched = CoherenceScheduler(ctx)
    sched.register_natural_period("theta_long", 10)
    sched._current_budget = 0.25
    t = sched.throttle_for("theta_long")
    assert t.is_throttled
    assert t.effective_period_beats == 20  # × 2


def test_throttle_high_only_under_15_percent(app_ctx) -> None:
    _, ctx, _ = app_ctx
    sched = CoherenceScheduler(ctx)
    sched.register_natural_period("meta_cognition", 100)
    sched._current_budget = 0.20
    # At 0.20, HIGH (threshold 0.15) is NOT throttled
    t = sched.throttle_for("meta_cognition")
    assert not t.is_throttled
    # At 0.10, HIGH IS throttled
    sched._current_budget = 0.10
    t = sched.throttle_for("meta_cognition")
    assert t.is_throttled


def test_high_budget_no_throttle(app_ctx) -> None:
    _, ctx, _ = app_ctx
    sched = CoherenceScheduler(ctx)
    sched.register_natural_period("delta_phi", 5)
    sched._current_budget = 0.9
    t = sched.throttle_for("delta_phi")
    assert not t.is_throttled
    assert t.effective_period_beats == 5


def test_unknown_engine_defaults_to_medium(app_ctx) -> None:
    _, ctx, _ = app_ctx
    sched = CoherenceScheduler(ctx)
    t = sched.throttle_for("some_new_engine")
    assert t.priority == Priority.MEDIUM


def test_register_natural_period(app_ctx) -> None:
    _, ctx, _ = app_ctx
    sched = CoherenceScheduler(ctx)
    sched.register_natural_period("delta_phi", 5)
    assert sched.engine_natural_period["delta_phi"] == 5


# ── tick() refreshes budget ─────────────────────────────────────────────


def test_tick_reads_coherence_budget(app_ctx) -> None:
    _, ctx, app = app_ctx
    sched = CoherenceScheduler(ctx)
    app.tick(beat_no=0, timestamp=0.0)
    sched.tick(beat_no=1)
    # Budget should reflect PNEUMA's actual coherence_budget
    assert 0.0 <= sched.current_budget() <= 1.0


# ── E13: effectiveness window + escalation ──────────────────────────────


def test_effectiveness_window_closes_at_50_beats(app_ctx) -> None:
    _, ctx, app = app_ctx
    sched = CoherenceScheduler(ctx, effectiveness_window_beats=50)
    # Pre-register an engine and pretend it's throttled
    sched.register_natural_period("theta_long", 10)
    # Manually populate throttle state as if engine called throttle_for()
    sched._current_throttle_state["theta_long"] = sched.throttle_for("theta_long")
    for beat in range(60):
        app.tick(beat_no=beat, timestamp=0.0)
        sched.tick(beat_no=beat)
    # At least one window should have closed (at beat 50)
    assert len(sched.recent_windows()) >= 1


def test_effectiveness_escalates_after_3_ineffective_windows(app_ctx) -> None:
    """E13: 3 consecutive ineffective windows → ineffective_throttle event.

    Synthetic regime: PNEUMA's coherence_budget stays pinned low (we monkey-
    patch render to return a fixed-low budget); throttle stays high;
    effectiveness near zero across consecutive windows.
    """
    _, ctx, app = app_ctx
    # Pin PNEUMA's coherence_budget to a stressed value
    from axioma.schemas import PneumaState
    app.pneuma.render = lambda *a, **kw: PneumaState(
        integration_level=0.5, global_coherence=0.5, fragmentation=0.5,
        awareness_level=0.5, attention_focus=0.5, buffer_depth=0,
        coherence_budget=0.10,  # below MEDIUM threshold 0.30
    )
    sched = CoherenceScheduler(
        ctx, effectiveness_window_beats=5,  # tiny window for test
        escalation_consecutive_windows=3,
        effectiveness_min_threshold=0.1,
    )
    sched.register_natural_period("theta_long", 1)
    received = []
    ctx.subscribe("ineffective_throttle", lambda p: received.append(p))
    for beat in range(20):
        # Mark engine as throttled
        sched._current_throttle_state["theta_long"] = sched.throttle_for("theta_long")
        sched.tick(beat_no=beat)
    # Should have triggered at least one escalation event
    assert len(received) >= 1
    assert isinstance(received[0], IneffectiveThrottleEvent)


def test_no_escalation_when_not_throttling(app_ctx) -> None:
    """When all engines are running freely (no throttle), no escalation."""
    _, ctx, _ = app_ctx
    sched = CoherenceScheduler(ctx, effectiveness_window_beats=5)
    sched.register_natural_period("theta_short", 1)
    received = []
    ctx.subscribe("ineffective_throttle", lambda p: received.append(p))
    sched._current_budget = 0.9  # plenty of budget
    for beat in range(50):
        sched._current_throttle_state["theta_short"] = sched.throttle_for("theta_short")
        sched.tick(beat_no=beat)
    assert len(received) == 0


# ── Save/load roundtrip ────────────────────────────────────────────────


def test_save_load_roundtrip(app_ctx) -> None:
    _, ctx, app = app_ctx
    sched = CoherenceScheduler(ctx)
    sched.register_natural_period("theta_long", 10)
    for beat in range(60):
        app.tick(beat_no=beat, timestamp=0.0)
        sched.tick(beat_no=beat)
    snap = sched.save_state()
    sched2 = CoherenceScheduler(ctx)
    sched2.load_state(snap)
    assert sched2.current_budget() == sched.current_budget()
    assert len(sched2.recent_windows()) == len(sched.recent_windows())
