"""Measurement-engine base class with the should_run() pattern.

Per IMPLEMENTATION_PLAN_v1.0.md §3.5.

Every measurement engine implements:
  - should_run(beat_no, coherence_budget) -> bool
  - compute() -> None  (read-only on substrate)
  - current_value() -> any (latest result)

The heartbeat calls should_run() before invoking compute(). The coherence
scheduler answers the throttle question; the engine doesn't need to know
its own throttle multiplier directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from ..observability.logging import get_logger
from ..observability.metrics import measure_engine

if TYPE_CHECKING:
    from ..observability.context import AxiomaContext

log = get_logger(__name__)


class MeasurementEngine(ABC):
    """Base class for all measurement-layer engines.

    Subclasses define:
      - name: stable identifier (used by coherence scheduler + metrics)
      - natural_period_beats: intrinsic cadence (1 = every beat)
      - schema_version: int (for persistence)
      - compute(): the actual work
      - save_state() / load_state(): persistence

    The heartbeat calls:
        if engine.should_run(beat_no, coherence_budget):
            with measure_engine(engine.name):
                engine.compute()
    """

    name: str = ""  # subclass must override
    natural_period_beats: int = 1
    schema_version: int = 1

    def __init__(self, ctx: AxiomaContext) -> None:
        self.ctx = ctx
        self._scheduler_registered = False

    def _ensure_scheduler_registered(self) -> None:
        """Self-register natural_period_beats with the CoherenceScheduler.

        Lazy: runs on first should_run() call. Defensive: if the registered
        object doesn't have a register_natural_period method (e.g., a test
        fake), silently skip — the throttle_for() call still works.
        """
        if self._scheduler_registered:
            return
        if not self.ctx.has("coherence_scheduler"):
            return
        scheduler = self.ctx.get("coherence_scheduler")
        if hasattr(scheduler, "register_natural_period"):
            scheduler.register_natural_period(self.name, self.natural_period_beats)
        self._scheduler_registered = True

    def should_run(self, beat_no: int, coherence_budget: float) -> bool:
        """Decide whether to run this beat.

        Default: respect natural cadence + ask CoherenceScheduler for throttle.
        Override only if the engine has special timing requirements
        (e.g. perturbation-triggered runs that ignore natural cadence).
        """
        if beat_no % self.natural_period_beats != 0:
            return False
        if not self.ctx.has("coherence_scheduler"):
            # No scheduler registered yet (early Phase A) — run on natural cadence
            return True
        self._ensure_scheduler_registered()
        throttle = self.ctx.coherence_scheduler.throttle_for(self.name)
        return beat_no % throttle.effective_period_beats == 0

    @abstractmethod
    def compute(self) -> None:
        """Run the engine. Must NOT mutate substrate state."""

    def current_value(self) -> Any:
        """Return the most-recent computed value. None if never run."""
        return None

    # ── Stateful protocol (also implemented by persistence.snapshot.Stateful) ──

    def save_state(self) -> dict[str, Any]:
        """Return serializable snapshot of in-memory state.

        Default: empty (engine is purely derived from substrate state).
        Override if the engine carries rolling buffers, baselines, etc.
        """
        return {}

    def load_state(self, snapshot: dict[str, Any]) -> None:
        """Restore from snapshot. Default no-op."""
        return None

    def run_if_due(self, beat_no: int, coherence_budget: float) -> bool:
        """Convenience: should_run + measure_engine + compute. Returns ran."""
        if not self.should_run(beat_no, coherence_budget):
            return False
        with measure_engine(self.name):
            self.compute()
        return True
