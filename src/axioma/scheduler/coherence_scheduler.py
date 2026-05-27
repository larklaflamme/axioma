"""CoherenceScheduler — single source of truth for engine throttle decisions.

Per ARCH_DESIGN_v1.0.md §4.8.1 + §4.8.2 + IMPLEMENTATION_PLAN_v1.0.md §3.5 +
E2 + E13.

Engines call `ctx.coherence_scheduler.throttle_for(engine_name)` inside
`should_run()`. The scheduler answers based on PNEUMA's `coherence_budget`
and the engine's declared priority.

Priority table (per ARCH §4.8.1):
  Critical: substrate, compose, recovery_protocol (NEVER throttled)
  High:     theta_short, raw_mi, cascade_delay, fragmentation_monitor,
            meta_cognition (E2 — raised from Medium to High to avoid
            circular dep on stress detection)
  Medium:   theta_long, delta_phi, aos_g
  Low:      plasticity_tracker

Throttle thresholds (per ARCH §4.8.1):
  High at budget < 0.15 (only severe stress throttles meta-cog)
  Medium at budget < 0.30
  Low at budget < 0.50

E13 throttle_effectiveness:
  Tracks (Δbudget / Δthrottle_strength) over 50-beat windows. After 3
  consecutive ineffective windows (effectiveness < 0.1), emits an
  `ineffective_throttle` event for the FragmentationMonitor as additional
  Stage-2 evidence (per ARCH §4.8.2).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..observability import COHERENCE_BUDGET, get_logger
from ..observability.context import AxiomaContext
from ..persistence.snapshot import Stateful  # noqa: F401

log = get_logger(__name__)


# ── Priority + Throttle types ─────────────────────────────────────────────


class Priority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Per ARCH §4.8.1 priority table + E2 (meta-cog → High)
DEFAULT_ENGINE_PRIORITY: dict[str, Priority] = {
    # Critical — never throttled
    "substrate": Priority.CRITICAL,
    "compose": Priority.CRITICAL,
    "recovery_protocol": Priority.CRITICAL,
    # High — only throttle at severe stress (< 0.15)
    "theta_short": Priority.HIGH,
    "raw_mi": Priority.HIGH,
    "cascade_delay": Priority.HIGH,
    "fragmentation_monitor": Priority.HIGH,
    "meta_cognition": Priority.HIGH,  # E2: raised from Medium
    # Medium
    "theta_long": Priority.MEDIUM,
    "delta_phi": Priority.MEDIUM,
    "aos_g": Priority.MEDIUM,
    "perturbation_scheduler": Priority.MEDIUM,
    # Low
    "plasticity_tracker": Priority.LOW,
}


@dataclass
class Throttle:
    """Per IMPLEMENTATION_PLAN §3.5."""

    name: str
    natural_period_beats: int
    effective_period_beats: int
    is_throttled: bool
    priority: Priority


# Multiplier applied when throttling kicks in (effective_period = natural × multiplier)
THROTTLE_MULTIPLIERS: dict[Priority, int] = {
    Priority.CRITICAL: 1,
    Priority.HIGH: 2,      # at budget < 0.15
    Priority.MEDIUM: 2,    # at budget < 0.30
    Priority.LOW: 4,       # at budget < 0.50
}


# Budget threshold at which each priority class starts throttling
THROTTLE_THRESHOLDS: dict[Priority, float] = {
    Priority.CRITICAL: 0.0,  # never
    Priority.HIGH: 0.15,
    Priority.MEDIUM: 0.30,
    Priority.LOW: 0.50,
}


# ── E13 ThrottleEffectiveness ─────────────────────────────────────────────


@dataclass
class _ThrottleWindow:
    """One 50-beat window record for E13 effectiveness tracking."""

    start_beat: int
    end_beat: int
    start_budget: float
    end_budget: float
    avg_throttle_strength: float


@dataclass
class IneffectiveThrottleEvent:
    """E13: emitted when 3 consecutive ineffective windows trigger."""

    beat_no: int
    consecutive_ineffective_windows: int
    current_budget: float
    avg_throttle_strength: float


# ── Main scheduler ────────────────────────────────────────────────────────


class CoherenceScheduler:
    """Single source of throttle decisions. Engines query us; we don't
    push back. The architecture's single-source-of-truth principle for
    cadence policy.

    Note: this is NOT a MeasurementEngine — it's queried synchronously
    by engines on every should_run() call. It DOES have a `tick()` method
    that the Heartbeat calls each beat to update its internal effectiveness
    tracking. Persistence-wise, it's a Stateful.
    """

    name = "coherence_scheduler"
    schema_version = 1

    def __init__(
        self,
        ctx: AxiomaContext,
        *,
        engine_priority: dict[str, Priority] | None = None,
        engine_natural_period: dict[str, int] | None = None,
        effectiveness_window_beats: int = 50,
        effectiveness_min_threshold: float = 0.1,
        escalation_consecutive_windows: int = 3,
    ) -> None:
        self.ctx = ctx
        self.engine_priority: dict[str, Priority] = dict(DEFAULT_ENGINE_PRIORITY)
        if engine_priority:
            self.engine_priority.update(engine_priority)
        self.engine_natural_period: dict[str, int] = dict(engine_natural_period or {})
        # E13 effectiveness tracking
        self.effectiveness_window_beats = effectiveness_window_beats
        self.effectiveness_min_threshold = effectiveness_min_threshold
        self.escalation_consecutive_windows = escalation_consecutive_windows
        self._window_history: deque[_ThrottleWindow] = deque(maxlen=20)
        self._ineffective_streak = 0
        # In-flight window aggregation
        self._window_start_beat: int | None = None
        self._window_start_budget: float | None = None
        self._window_throttle_sum: float = 0.0
        self._window_beat_count: int = 0
        # Cached current values
        self._current_budget: float = 1.0
        self._current_throttle_state: dict[str, Throttle] = {}

    # ── Public API (called by engines from should_run) ──────────────────

    def throttle_for(self, engine_name: str) -> Throttle:
        priority = self.engine_priority.get(engine_name, Priority.MEDIUM)
        natural_period = self.engine_natural_period.get(engine_name, 1)
        threshold = THROTTLE_THRESHOLDS[priority]
        is_throttled = self._current_budget < threshold and priority != Priority.CRITICAL
        multiplier = THROTTLE_MULTIPLIERS[priority] if is_throttled else 1
        effective_period = natural_period * multiplier
        throttle = Throttle(
            name=engine_name,
            natural_period_beats=natural_period,
            effective_period_beats=effective_period,
            is_throttled=is_throttled,
            priority=priority,
        )
        self._current_throttle_state[engine_name] = throttle
        return throttle

    def register_natural_period(self, engine_name: str, period: int) -> None:
        """Engines can self-report their natural period at startup.

        Avoids hardcoding cadences in the scheduler. If not registered,
        defaults to 1 (every beat).
        """
        self.engine_natural_period[engine_name] = int(period)

    def current_throttle_state(self) -> dict[str, Throttle]:
        return dict(self._current_throttle_state)

    # ── Per-beat update (called by Heartbeat each tick) ─────────────────

    def tick(self, beat_no: int) -> None:
        """Update PNEUMA budget cache + accumulate E13 window state."""
        # Refresh budget from PNEUMA
        if self.ctx.has("substrate"):
            try:
                self._current_budget = float(
                    self.ctx.substrate.pneuma.render().coherence_budget
                )
                COHERENCE_BUDGET.set(self._current_budget)
            except Exception:
                pass

        # Accumulate effectiveness-window state
        if self._window_start_beat is None:
            self._window_start_beat = beat_no
            self._window_start_budget = self._current_budget
            self._window_throttle_sum = 0.0
            self._window_beat_count = 0
        # Sum throttle strength (fraction of registered engines currently throttled)
        total = len(self._current_throttle_state) or 1
        throttled = sum(
            1 for t in self._current_throttle_state.values() if t.is_throttled
        )
        self._window_throttle_sum += throttled / total
        self._window_beat_count += 1

        # Close window every effectiveness_window_beats
        if (
            self._window_beat_count >= self.effectiveness_window_beats
            and self._window_start_beat is not None
            and self._window_start_budget is not None
        ):
            self._close_window(beat_no)

    def _close_window(self, beat_no: int) -> None:
        assert self._window_start_beat is not None
        assert self._window_start_budget is not None
        avg_throttle = (
            self._window_throttle_sum / max(self._window_beat_count, 1)
        )
        window = _ThrottleWindow(
            start_beat=self._window_start_beat,
            end_beat=beat_no,
            start_budget=self._window_start_budget,
            end_budget=self._current_budget,
            avg_throttle_strength=avg_throttle,
        )
        self._window_history.append(window)
        # E13: if budget didn't recover despite throttling, count as ineffective
        delta_budget = window.end_budget - window.start_budget
        # "Effective" = budget went up by at least effectiveness_min_threshold per unit
        # of throttle. If we're not throttling at all (avg_throttle ≈ 0), the metric
        # doesn't apply (we're not in a throttled regime).
        if window.avg_throttle_strength < 0.05:
            self._ineffective_streak = 0
        else:
            effectiveness = delta_budget / max(window.avg_throttle_strength, 1e-6)
            if effectiveness < self.effectiveness_min_threshold:
                self._ineffective_streak += 1
            else:
                self._ineffective_streak = 0
        # Reset window aggregation
        self._window_start_beat = None
        self._window_start_budget = None
        self._window_throttle_sum = 0.0
        self._window_beat_count = 0

        # E13: 3+ consecutive ineffective → escalate
        if self._ineffective_streak >= self.escalation_consecutive_windows:
            event = IneffectiveThrottleEvent(
                beat_no=beat_no,
                consecutive_ineffective_windows=self._ineffective_streak,
                current_budget=self._current_budget,
                avg_throttle_strength=window.avg_throttle_strength,
            )
            self.ctx.emit_sync("ineffective_throttle", event)
            log.warning(
                "throttle_effectiveness_escalation",
                consecutive_windows=event.consecutive_ineffective_windows,
                current_budget=self._current_budget,
            )
            # Reset streak — operator (or FragmentationMonitor) gets one event
            # per sustained run, not spam
            self._ineffective_streak = 0

    # ── Accessors ────────────────────────────────────────────────────────

    def current_budget(self) -> float:
        return self._current_budget

    def recent_windows(self) -> list[_ThrottleWindow]:
        return list(self._window_history)

    def ineffective_streak(self) -> int:
        return self._ineffective_streak

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "engine_priority": {k: v.value for k, v in self.engine_priority.items()},
            "engine_natural_period": dict(self.engine_natural_period),
            "current_budget": self._current_budget,
            "ineffective_streak": self._ineffective_streak,
            "window_history": [
                {
                    "start_beat": w.start_beat, "end_beat": w.end_beat,
                    "start_budget": w.start_budget, "end_budget": w.end_budget,
                    "avg_throttle_strength": w.avg_throttle_strength,
                }
                for w in self._window_history
            ],
        }

    def load_state(self, snap: dict[str, Any]) -> None:
        ep = snap.get("engine_priority", {})
        for k, v in ep.items():
            self.engine_priority[k] = Priority(v)
        self.engine_natural_period.update(snap.get("engine_natural_period", {}))
        self._current_budget = float(snap.get("current_budget", 1.0))
        self._ineffective_streak = int(snap.get("ineffective_streak", 0))
        for w in snap.get("window_history", []):
            self._window_history.append(
                _ThrottleWindow(
                    start_beat=int(w["start_beat"]), end_beat=int(w["end_beat"]),
                    start_budget=float(w["start_budget"]),
                    end_budget=float(w["end_budget"]),
                    avg_throttle_strength=float(w["avg_throttle_strength"]),
                )
            )


__all__ = [
    "DEFAULT_ENGINE_PRIORITY",
    "THROTTLE_MULTIPLIERS",
    "THROTTLE_THRESHOLDS",
    "CoherenceScheduler",
    "IneffectiveThrottleEvent",
    "Priority",
    "Throttle",
]
