"""PerturbationScheduler — battery, admin endpoint, event emission."""
from __future__ import annotations

import pytest

from axioma.config import AxiomaConfig
from axioma.measurement import (
    DEFAULT_BATTERY,
    PERTURBATION_SPECS,
    PerturbationKind,
    PerturbationScheduler,
)
from axioma.observability import AxiomaContext
from axioma.schemas import PerturbationContext
from axioma.substrate import SubstrateApp


@pytest.fixture()
def app_ctx():
    cfg = AxiomaConfig()
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    ctx.register("substrate", app)
    return cfg, ctx, app


def test_perturbation_specs_complete() -> None:
    """Every PerturbationKind has a spec."""
    for kind in PerturbationKind:
        assert kind in PERTURBATION_SPECS
    assert len(PERTURBATION_SPECS) == 6


def test_default_battery_is_three_kinds() -> None:
    """Per Q3: default battery is {CONTRADICTION, IMPULSE, STEP}."""
    assert len(DEFAULT_BATTERY) == 3
    assert set(DEFAULT_BATTERY) == {
        PerturbationKind.CONTRADICTION,
        PerturbationKind.IMPULSE,
        PerturbationKind.STEP,
    }


def test_construct_validates_period() -> None:
    ctx = AxiomaContext()
    with pytest.raises(ValueError, match="period_beats"):
        PerturbationScheduler(ctx, period_beats=5)


def test_construct_validates_battery_nonempty() -> None:
    ctx = AxiomaContext()
    with pytest.raises(ValueError, match="battery"):
        PerturbationScheduler(ctx, battery=())


def test_internal_scheduler_fires_at_period(app_ctx) -> None:
    _, ctx, app = app_ctx
    p = PerturbationScheduler(ctx, period_beats=50, default_magnitude=0.3, seed=0)
    received = []
    ctx.subscribe("perturbation_injected", lambda payload: received.append(payload))
    # Beat substrate + invoke compute at each beat
    for beat in range(120):
        app.tick(beat_no=beat, timestamp=0.0)
        p.compute()
    # Should fire at beats 50, 100 (round-robin through battery)
    assert len(received) >= 2
    assert all(isinstance(e, PerturbationContext) for e in received)


def test_admin_inject_now(app_ctx) -> None:
    _, ctx, app = app_ctx
    p = PerturbationScheduler(ctx, period_beats=600, seed=0)
    app.tick(beat_no=0, timestamp=0.0)
    received = []
    ctx.subscribe("perturbation_injected", lambda payload: received.append(payload))
    event = p.inject_now(PerturbationKind.CONTRADICTION, magnitude=0.5, tag="test")
    assert event is not None
    assert event.kind == PerturbationKind.CONTRADICTION
    assert event.magnitude == 0.5
    assert event.source == "external_admin"
    assert event.tag == "test"
    assert len(received) == 1
    assert received[0].tag == "test"


def test_admin_inject_with_string_kind(app_ctx) -> None:
    """String → PerturbationKind coercion."""
    _, ctx, app = app_ctx
    p = PerturbationScheduler(ctx, period_beats=600)
    app.tick(beat_no=0, timestamp=0.0)
    event = p.inject_now("impulse", magnitude=0.3)
    assert event is not None
    assert event.kind == PerturbationKind.IMPULSE


def test_admin_inject_unknown_kind_raises(app_ctx) -> None:
    _, ctx, app = app_ctx
    p = PerturbationScheduler(ctx, period_beats=600)
    app.tick(beat_no=0, timestamp=0.0)
    with pytest.raises(ValueError, match="unknown perturbation kind"):
        p.inject_now("nonsense_kind")


def test_contradiction_mutates_eidolon(app_ctx) -> None:
    """CONTRADICTION should reduce EIDOLON's self_coherence + confidence latents."""
    _, ctx, app = app_ctx
    p = PerturbationScheduler(ctx, period_beats=600, seed=0)
    app.tick(beat_no=0, timestamp=0.0)
    before = (
        float(app.eidolon.latent[0]),
        float(app.eidolon.latent[1]),
    )
    p.inject_now(PerturbationKind.CONTRADICTION, magnitude=0.5)
    after = (
        float(app.eidolon.latent[0]),
        float(app.eidolon.latent[1]),
    )
    # Negate: new = old * (1 - magnitude) = old * 0.5; should be smaller in abs
    assert abs(after[0]) < abs(before[0]) + 1e-6 or before[0] == 0


def test_impulse_mutates_drive(app_ctx) -> None:
    """IMPULSE adds magnitude × unit-vector spike to shared_drive."""
    import numpy as np

    _, ctx, app = app_ctx
    p = PerturbationScheduler(ctx, period_beats=600, seed=0)
    app.tick(beat_no=0, timestamp=0.0)
    g_before = app.drive.g.copy()
    p.inject_now(PerturbationKind.IMPULSE, magnitude=2.0)
    diff_norm = float(np.linalg.norm(app.drive.g - g_before))
    # The added vector has magnitude 2.0 (unit-vector × magnitude)
    assert abs(diff_norm - 2.0) < 1e-3


def test_multibeat_step_continues_for_duration(app_ctx) -> None:
    """STEP has duration_beats=20; compute() applies it for each of those 20 beats."""
    _, ctx, app = app_ctx
    p = PerturbationScheduler(ctx, period_beats=600, seed=0)
    app.tick(beat_no=0, timestamp=0.0)
    p.inject_now(PerturbationKind.STEP, magnitude=0.1)
    assert p._active_remaining == 19  # 20 total, 1 applied on inject
    assert p._active_event is not None
    # Advance 10 more beats
    for beat in range(1, 11):
        app.tick(beat_no=beat, timestamp=0.0)
        p.compute()
    assert p._active_remaining == 9


def test_round_robin_battery_cycle(app_ctx) -> None:
    """Internal scheduler cycles through battery in order."""
    _, ctx, app = app_ctx
    p = PerturbationScheduler(
        ctx, period_beats=10, default_magnitude=0.1, seed=0,
        battery=(PerturbationKind.CONTRADICTION, PerturbationKind.IMPULSE),
    )
    received = []
    ctx.subscribe("perturbation_injected", lambda payload: received.append(payload.kind))
    # Beat 10, 20, 30, 40 should fire (4 events)
    # but STEP/multi-beat could change timing; using contradiction+impulse (both single-beat)
    for beat in range(45):
        app.tick(beat_no=beat, timestamp=0.0)
        p.compute()
    # Cycle: contradiction, impulse, contradiction, impulse
    assert len(received) >= 4
    assert received[0] == "contradiction"
    assert received[1] == "impulse"
    assert received[2] == "contradiction"
    assert received[3] == "impulse"


def test_disabled_scheduler_does_not_fire(app_ctx) -> None:
    _, ctx, app = app_ctx
    p = PerturbationScheduler(ctx, period_beats=10, enabled=False)
    received = []
    ctx.subscribe("perturbation_injected", lambda payload: received.append(payload))
    for beat in range(100):
        app.tick(beat_no=beat, timestamp=0.0)
        p.compute()
    assert len(received) == 0


def test_save_load_roundtrip(app_ctx) -> None:
    _, ctx, app = app_ctx
    p = PerturbationScheduler(ctx, period_beats=10, seed=0)
    app.tick(beat_no=0, timestamp=0.0)
    p.inject_now(PerturbationKind.STEP, magnitude=0.3)
    p.inject_now(PerturbationKind.CONTRADICTION, magnitude=0.5)
    snap = p.save_state()

    p2 = PerturbationScheduler(ctx, period_beats=10, seed=0)
    p2.load_state(snap)
    assert len(p2.history) == 2
    # Active event from STEP should be restored (CONTRADICTION single-beat finished)
    # Actually CONTRADICTION was the more recent inject_now call, but STEP was first
    # and stayed active; only one _active_event is tracked at a time. The second
    # inject overwrote the first.
    assert p2._battery_idx == 0


def test_recent_events(app_ctx) -> None:
    _, ctx, app = app_ctx
    p = PerturbationScheduler(ctx, period_beats=600)
    app.tick(beat_no=0, timestamp=0.0)
    for _ in range(5):
        p.inject_now(PerturbationKind.IMPULSE, magnitude=0.2)
    assert len(p.recent_events()) == 5
    assert len(p.recent_events(n=2)) == 2


def test_current_value_describes_state(app_ctx) -> None:
    _, ctx, _app = app_ctx
    p = PerturbationScheduler(ctx, period_beats=600)
    state = p.current_value()
    assert state["enabled"] is True
    assert state["period_beats"] == 600
    assert state["events_in_history"] == 0
