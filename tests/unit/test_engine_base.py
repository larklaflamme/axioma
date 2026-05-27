"""MeasurementEngine base class + should_run pattern."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from axioma.measurement.engine_base import MeasurementEngine
from axioma.observability import AxiomaContext


class CountingEngine(MeasurementEngine):
    name = "counting"
    natural_period_beats = 1
    schema_version = 1

    def __init__(self, ctx: AxiomaContext) -> None:
        super().__init__(ctx)
        self.runs = 0

    def compute(self) -> None:
        self.runs += 1


class EveryFiveEngine(MeasurementEngine):
    name = "every_five"
    natural_period_beats = 5
    schema_version = 1

    def __init__(self, ctx: AxiomaContext) -> None:
        super().__init__(ctx)
        self.runs = 0

    def compute(self) -> None:
        self.runs += 1


@dataclass
class FakeThrottle:
    effective_period_beats: int


class FakeCoherenceScheduler:
    def __init__(self, effective_period: int = 1) -> None:
        self._effective = effective_period

    def throttle_for(self, _engine_name: str) -> FakeThrottle:
        return FakeThrottle(self._effective)


def test_should_run_every_beat_when_no_scheduler() -> None:
    """Without a CoherenceScheduler registered, engines run on natural cadence."""
    ctx = AxiomaContext()
    eng = CountingEngine(ctx)
    for beat in range(5):
        assert eng.should_run(beat, 1.0)


def test_should_run_respects_natural_period() -> None:
    ctx = AxiomaContext()
    eng = EveryFiveEngine(ctx)
    assert eng.should_run(0, 1.0)
    assert not eng.should_run(1, 1.0)
    assert not eng.should_run(4, 1.0)
    assert eng.should_run(5, 1.0)
    assert eng.should_run(10, 1.0)


def test_should_run_uses_scheduler_when_present() -> None:
    """When scheduler returns effective_period=2, engine runs every 2 beats."""
    ctx = AxiomaContext()
    ctx.register("coherence_scheduler", FakeCoherenceScheduler(effective_period=2))
    eng = CountingEngine(ctx)
    assert eng.should_run(0, 1.0)
    assert not eng.should_run(1, 1.0)
    assert eng.should_run(2, 1.0)
    assert not eng.should_run(3, 1.0)


def test_run_if_due_returns_true_and_runs() -> None:
    ctx = AxiomaContext()
    eng = CountingEngine(ctx)
    assert eng.run_if_due(0, 1.0)
    assert eng.runs == 1
    assert eng.run_if_due(1, 1.0)
    assert eng.runs == 2


def test_run_if_due_returns_false_and_does_not_run() -> None:
    ctx = AxiomaContext()
    eng = EveryFiveEngine(ctx)
    # natural period 5: beat 1 is not due
    assert not eng.run_if_due(1, 1.0)
    assert eng.runs == 0


def test_default_save_load_state_is_noop() -> None:
    ctx = AxiomaContext()
    eng = CountingEngine(ctx)
    assert eng.save_state() == {}
    eng.load_state({"unused": "data"})  # does not raise
    assert eng.current_value() is None


def test_abstract_compute_required() -> None:
    class IncompleteEngine(MeasurementEngine):
        name = "incomplete"

    ctx = AxiomaContext()
    with pytest.raises(TypeError):
        IncompleteEngine(ctx)  # type: ignore[abstract]
