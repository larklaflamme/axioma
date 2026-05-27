"""CadenceController — adaptive compose cadence per D2.

Per ARCH_DESIGN_v1.0.md §4.6 + IMPLEMENTATION_PLAN_v1.0.md §7.3.

  BASELINE       → compose every 30 beats (default)
  PERTURBATION   → compose every 5 beats for 50 beats after any
                   perturbation_injected event (captures post-event AOS-G
                   dynamics that the 30-beat cadence misses)
  RECOVERY       → compose every 60 beats during active recovery
                   (compose runs less often to give substrate breathing room)

Subscribes to:
  - `perturbation_injected` event (sets perturbation_window_active for 50 beats)
  - `recovery_state_change` event (toggles recovery_active)

`should_compose(beat_no)` is the single decision: it picks the right cadence
based on current state. The heartbeat consults it before invoking compose.
"""
from __future__ import annotations

from typing import Any

from ..observability import get_logger
from ..observability.context import AxiomaContext
from ..persistence.snapshot import Stateful  # noqa: F401
from ..schemas import ComposeCadence

log = get_logger(__name__)


class CadenceController:
    """State machine: BASELINE ↔ PERTURBATION ↔ RECOVERY.

    Recovery dominates: if both perturbation and recovery are active, use
    recovery cadence (compose less often to give substrate space).
    """

    name = "cadence_controller"
    schema_version = 1

    def __init__(
        self,
        ctx: AxiomaContext,
        *,
        baseline_period_beats: int = 30,
        perturbation_period_beats: int = 5,
        recovery_period_beats: int = 60,
        perturbation_window_beats: int = 50,
    ) -> None:
        self.ctx = ctx
        self.baseline_period_beats = baseline_period_beats
        self.perturbation_period_beats = perturbation_period_beats
        self.recovery_period_beats = recovery_period_beats
        self.perturbation_window_beats = perturbation_window_beats
        # State
        self._perturbation_window_until_beat: int | None = None
        self._recovery_active: bool = False
        self._last_compose_beat: int | None = None
        # Subscribe to events
        self.ctx.subscribe("perturbation_injected", self._on_perturbation)
        self.ctx.subscribe("recovery_state_change", self._on_recovery_state)

    # ── Event handlers ───────────────────────────────────────────────────

    def _on_perturbation(self, payload: Any) -> None:
        """Open a perturbation window for self.perturbation_window_beats."""
        started_at = (
            int(payload.started_at_beat)
            if hasattr(payload, "started_at_beat")
            else int(payload.get("started_at_beat", 0))
            if isinstance(payload, dict)
            else 0
        )
        self._perturbation_window_until_beat = started_at + self.perturbation_window_beats
        log.debug(
            "cadence_perturbation_window_opened",
            until=self._perturbation_window_until_beat,
        )

    def _on_recovery_state(self, payload: Any) -> None:
        state = (
            payload.get("state")
            if isinstance(payload, dict)
            else getattr(payload, "state", "baseline")
        )
        self._recovery_active = state == "active"

    # ── Decision ─────────────────────────────────────────────────────────

    def current_cadence(self, beat_no: int) -> ComposeCadence:
        """Which cadence regime are we in right now?"""
        if self._recovery_active:
            return ComposeCadence.RECOVERY
        if (
            self._perturbation_window_until_beat is not None
            and beat_no < self._perturbation_window_until_beat
        ):
            return ComposeCadence.PERTURBATION
        return ComposeCadence.BASELINE

    def current_period_beats(self, beat_no: int) -> int:
        cadence = self.current_cadence(beat_no)
        if cadence == ComposeCadence.RECOVERY:
            return self.recovery_period_beats
        if cadence == ComposeCadence.PERTURBATION:
            return self.perturbation_period_beats
        return self.baseline_period_beats

    def should_compose(self, beat_no: int) -> bool:
        """Should compose run this beat?

        True iff beat_no % current_period_beats == 0 AND it's a new beat
        relative to the last compose (avoids double-firing if called twice).
        """
        if beat_no <= 0:
            return False
        period = self.current_period_beats(beat_no)
        if beat_no % period != 0:
            return False
        if self._last_compose_beat == beat_no:
            return False
        self._last_compose_beat = beat_no
        return True

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "perturbation_window_until_beat": self._perturbation_window_until_beat,
            "recovery_active": self._recovery_active,
            "last_compose_beat": self._last_compose_beat,
            "baseline_period_beats": self.baseline_period_beats,
            "perturbation_period_beats": self.perturbation_period_beats,
            "recovery_period_beats": self.recovery_period_beats,
        }

    def load_state(self, snap: dict[str, Any]) -> None:
        self._perturbation_window_until_beat = snap.get("perturbation_window_until_beat")
        self._recovery_active = bool(snap.get("recovery_active", False))
        self._last_compose_beat = snap.get("last_compose_beat")


__all__ = ["CadenceController"]
