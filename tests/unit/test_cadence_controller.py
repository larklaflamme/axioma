"""CadenceController — adaptive 5/30/60-beat schedule."""
from __future__ import annotations

from axioma.compose import CadenceController
from axioma.observability import AxiomaContext
from axioma.schemas import ComposeCadence, PerturbationContext


def test_construct_defaults() -> None:
    ctx = AxiomaContext()
    c = CadenceController(ctx)
    assert c.baseline_period_beats == 30
    assert c.perturbation_period_beats == 5
    assert c.recovery_period_beats == 60


def test_should_compose_at_baseline() -> None:
    ctx = AxiomaContext()
    c = CadenceController(ctx)
    # Baseline: every 30 beats
    assert c.should_compose(30)
    assert not c.should_compose(31)
    assert not c.should_compose(45)
    assert c.should_compose(60)


def test_should_compose_perturbation_window() -> None:
    """After a perturbation, switch to 5-beat cadence for window_beats."""
    ctx = AxiomaContext()
    c = CadenceController(ctx, perturbation_window_beats=50)
    # Open a perturbation window starting at beat 100
    ctx.emit_sync("perturbation_injected", PerturbationContext(
        event_id="e1", kind="contradiction", target="eidolon",
        magnitude=0.3, started_at_beat=100, duration_beats=1,
    ))
    assert c.current_cadence(105) == ComposeCadence.PERTURBATION
    # 5-beat compose during window
    assert c.should_compose(105)
    assert not c.should_compose(106)
    assert c.should_compose(110)
    assert c.should_compose(145)
    # Window ends at beat 150 → back to baseline
    assert c.current_cadence(160) == ComposeCadence.BASELINE


def test_should_compose_recovery() -> None:
    """During active recovery, use 60-beat cadence."""
    ctx = AxiomaContext()
    c = CadenceController(ctx)
    ctx.emit_sync("recovery_state_change", {"beat_no": 200, "state": "active"})
    assert c.current_cadence(250) == ComposeCadence.RECOVERY
    assert not c.should_compose(230)
    assert c.should_compose(240)
    assert c.should_compose(300)


def test_recovery_overrides_perturbation() -> None:
    """If both perturbation window and recovery active, recovery dominates."""
    ctx = AxiomaContext()
    c = CadenceController(ctx)
    # Open perturbation window
    ctx.emit_sync("perturbation_injected", PerturbationContext(
        event_id="e1", kind="contradiction", target="eidolon",
        magnitude=0.3, started_at_beat=100, duration_beats=1,
    ))
    # Then enter recovery
    ctx.emit_sync("recovery_state_change", {"beat_no": 110, "state": "active"})
    assert c.current_cadence(120) == ComposeCadence.RECOVERY


def test_recovery_exits_to_baseline() -> None:
    ctx = AxiomaContext()
    c = CadenceController(ctx)
    ctx.emit_sync("recovery_state_change", {"beat_no": 200, "state": "active"})
    assert c.current_cadence(250) == ComposeCadence.RECOVERY
    ctx.emit_sync("recovery_state_change", {"beat_no": 300, "state": "baseline"})
    assert c.current_cadence(310) == ComposeCadence.BASELINE


def test_should_compose_no_double_fire() -> None:
    """should_compose returns True only once per beat (idempotent at same beat_no)."""
    ctx = AxiomaContext()
    c = CadenceController(ctx)
    assert c.should_compose(30)
    assert not c.should_compose(30)  # same beat → False


def test_should_compose_beat_zero() -> None:
    """Beat 0 never triggers compose (warmup convention)."""
    ctx = AxiomaContext()
    c = CadenceController(ctx)
    assert not c.should_compose(0)


def test_save_load_roundtrip() -> None:
    ctx = AxiomaContext()
    c = CadenceController(ctx)
    ctx.emit_sync("perturbation_injected", PerturbationContext(
        event_id="e1", kind="contradiction", target="eidolon",
        magnitude=0.3, started_at_beat=100, duration_beats=1,
    ))
    c.should_compose(110)
    snap = c.save_state()
    ctx2 = AxiomaContext()
    c2 = CadenceController(ctx2)
    c2.load_state(snap)
    assert c2._perturbation_window_until_beat == c._perturbation_window_until_beat
    assert c2._last_compose_beat == c._last_compose_beat
