"""FragmentationMonitor — 4-stage detector + recovery_request emission.

Per ARCH_DESIGN_v1.0.md §6.6 + IMPLEMENTATION_PLAN_v1.0.md §6.1 step 7.

4 stages with rolling thresholds (per ARCH §6.6 + F9 empirical validation):

  Stage 0 — coherent: nothing tripped
  Stage 1 — MNEME retrieval lag: retrieval_rate < 0.7× rolling_mean for 30+ beats
  Stage 2 — ANIMA valence volatility: var(valence over last 50 beats) > 2× rolling_var
  Stage 3 — NOUS confidence spread: confidence_spread > 1.5× rolling_mean for 30+ beats
  Stage 4 — PNEUMA fragmentation: fragmentation > 0.7

The monitor reports the MAX stage currently met. Stage transitions are
emitted on the AxiomaContext bus as `fragmentation_stage_change` events.
When stage ≥ min_recovery_stage (default 2) is first reached for an
episode, a `recovery_request` event is emitted with stage + signals.

F9: thresholds are initial estimates; Phase E empirical validation tunes
them to hit escalation_probability ∈ [0.20, 0.40] per stage.

Read-only on substrate. Recovery is requested via event bus, NOT direct
substrate mutation (per ARCH §6.6 — recovery is substrate-owned).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..observability import FRAGMENTATION_STAGE, get_logger
from ..observability.context import AxiomaContext
from ..persistence.snapshot import Stateful  # noqa: F401
from .engine_base import MeasurementEngine

log = get_logger(__name__)


@dataclass
class FragmentationReading:
    beat_no: int = 0
    current_stage: int = 0
    signals: dict[str, float] = field(default_factory=dict)
    stage1_streak_beats: int = 0
    stage3_streak_beats: int = 0
    valid: bool = False


@dataclass
class RecoveryRequestPayload:
    """Emitted on `recovery_request` event when stage ≥ min_recovery_stage."""

    request_id: str
    beat_no: int
    stage: int
    signals: dict[str, float]
    source: str = "fragmentation_monitor"


@dataclass
class FragmentationStageChange:
    """Emitted on `fragmentation_stage_change` events."""

    beat_no: int
    previous_stage: int
    new_stage: int


# Default thresholds per ARCH §6.6 (F9 empirically tuned in Phase E)
DEFAULT_THRESHOLDS: dict[str, float] = {
    "stage1_retrieval_ratio": 0.7,
    "stage1_streak_beats": 30,
    "stage2_valence_var_window": 50,
    "stage2_valence_var_ratio": 2.0,
    "stage3_confidence_spread_ratio": 1.5,
    "stage3_streak_beats": 30,
    "stage4_pneuma_fragmentation": 0.7,
    # Rolling baseline windows (EMA cadence)
    "rolling_alpha": 0.05,
}


class FragmentationMonitor(MeasurementEngine):
    """4-stage detector. Default cadence: every 10 beats."""

    name = "fragmentation_monitor"
    natural_period_beats = 10
    schema_version = 1

    def __init__(
        self,
        ctx: AxiomaContext,
        *,
        thresholds: dict[str, float] | None = None,
        min_recovery_stage: int = 2,
        history_capacity: int = 200,
        valence_window_beats: int = 50,
    ) -> None:
        super().__init__(ctx)
        self.thresholds = dict(DEFAULT_THRESHOLDS)
        if thresholds:
            self.thresholds.update(thresholds)
        self.min_recovery_stage = min_recovery_stage
        self.history_capacity = history_capacity
        self.valence_window_beats = valence_window_beats

        # Rolling baselines (EMA)
        self._rolling_retrieval_mean: float | None = None
        self._rolling_confidence_spread_mean: float | None = None
        self._rolling_valence_var: float | None = None
        # Per-stage streak counters
        self._stage1_streak = 0
        self._stage3_streak = 0
        # State
        self._current = FragmentationReading()
        self._previous_stage = 0
        # Episode tracker — set of request_ids emitted for the current
        # continuous stage≥min run; reset when stage drops below min
        self._episode_active = False
        self._episode_last_request_beat: int | None = None
        # History for HTTP endpoint
        self.history: deque[FragmentationReading] = deque(maxlen=history_capacity)

    def compute(self) -> None:
        if not (self.ctx.has("substrate") and self.ctx.has("state_buffer")):
            return
        substrate = self.ctx.substrate
        buf = self.ctx.get("state_buffer")
        if len(buf) < 30:  # need at least baseline beats
            return

        latest_internal = substrate.last_internal()
        if latest_internal is None:
            return
        beat_no = latest_internal.beat_no

        # ── Stage 1: MNEME retrieval_rate ──
        retrieval_rate = float(latest_internal.mneme.retrieval_rate)
        alpha = self.thresholds["rolling_alpha"]
        if self._rolling_retrieval_mean is None:
            self._rolling_retrieval_mean = retrieval_rate
        else:
            self._rolling_retrieval_mean = (
                (1 - alpha) * self._rolling_retrieval_mean + alpha * retrieval_rate
            )
        stage1_trip = retrieval_rate < (
            self.thresholds["stage1_retrieval_ratio"] * self._rolling_retrieval_mean
        )
        if stage1_trip:
            self._stage1_streak += self.natural_period_beats
        else:
            self._stage1_streak = 0
        stage1_active = self._stage1_streak >= int(self.thresholds["stage1_streak_beats"])

        # ── Stage 2: ANIMA valence variance ──
        win = buf.window(int(self.thresholds["stage2_valence_var_window"]))
        anima_window = win.get("anima")
        if anima_window is not None and anima_window.shape[0] > 5:
            valence_var = float(anima_window[:, 0].var())  # valence is col 0
        else:
            valence_var = 0.0
        if self._rolling_valence_var is None:
            self._rolling_valence_var = valence_var + 1e-6
        else:
            self._rolling_valence_var = (
                (1 - alpha) * self._rolling_valence_var + alpha * valence_var
            )
        stage2_active = valence_var > (
            self.thresholds["stage2_valence_var_ratio"] * self._rolling_valence_var
        )

        # ── Stage 3: NOUS confidence_spread ──
        confidence_spread = float(latest_internal.nous.confidence_spread)
        if self._rolling_confidence_spread_mean is None:
            self._rolling_confidence_spread_mean = confidence_spread
        else:
            self._rolling_confidence_spread_mean = (
                (1 - alpha) * self._rolling_confidence_spread_mean
                + alpha * confidence_spread
            )
        stage3_trip = confidence_spread > (
            self.thresholds["stage3_confidence_spread_ratio"]
            * self._rolling_confidence_spread_mean
        )
        if stage3_trip:
            self._stage3_streak += self.natural_period_beats
        else:
            self._stage3_streak = 0
        stage3_active = self._stage3_streak >= int(self.thresholds["stage3_streak_beats"])

        # ── Stage 4: PNEUMA fragmentation ──
        fragmentation_value = float(latest_internal.pneuma.fragmentation)
        stage4_active = fragmentation_value > self.thresholds["stage4_pneuma_fragmentation"]

        # Pick max stage. Higher stages override lower.
        stage = 0
        if stage1_active:
            stage = 1
        if stage2_active:
            stage = max(stage, 2)
        if stage3_active:
            stage = max(stage, 3)
        if stage4_active:
            stage = max(stage, 4)

        signals = {
            "mneme_retrieval_rate": retrieval_rate,
            "mneme_retrieval_rolling_mean": float(self._rolling_retrieval_mean),
            "anima_valence_var": valence_var,
            "anima_valence_var_rolling": float(self._rolling_valence_var),
            "nous_confidence_spread": confidence_spread,
            "nous_confidence_spread_rolling": float(self._rolling_confidence_spread_mean),
            "pneuma_fragmentation": fragmentation_value,
            "stage1_streak_beats": float(self._stage1_streak),
            "stage3_streak_beats": float(self._stage3_streak),
        }

        reading = FragmentationReading(
            beat_no=beat_no,
            current_stage=stage,
            signals=signals,
            stage1_streak_beats=self._stage1_streak,
            stage3_streak_beats=self._stage3_streak,
            valid=True,
        )
        self._current = reading
        self.history.append(reading)
        FRAGMENTATION_STAGE.set(stage)

        # Stage transition event
        if stage != self._previous_stage:
            self.ctx.emit_sync(
                "fragmentation_stage_change",
                FragmentationStageChange(
                    beat_no=beat_no,
                    previous_stage=self._previous_stage,
                    new_stage=stage,
                ),
            )
            log.info("fragmentation_stage_change", previous=self._previous_stage,
                     new=stage, signals=signals)
        self._previous_stage = stage

        # Recovery episode tracking
        if stage < self.min_recovery_stage:
            # Episode broken — reset
            if self._episode_active:
                log.debug("fragmentation_episode_cleared", beat_no=beat_no)
            self._episode_active = False
            self._episode_last_request_beat = None
        else:
            # Emit recovery request on every monitor tick while in episode
            # (downstream RejectionEscalator throttles via its own cooldown)
            import uuid as _uuid
            req = RecoveryRequestPayload(
                request_id=str(_uuid.uuid4()),
                beat_no=beat_no,
                stage=stage,
                signals=signals,
                source="fragmentation_monitor",
            )
            # Phase E: on the FIRST request of a new episode, ask the
            # recovery protocol to finalize durability of prior events.
            # Re-entering fragmentation is the trigger for "previous recovery
            # did not hold." The watchdog at 3000 beats catches the opposite
            # case (no fragmentation → durability=1.0).
            episode_was_active = self._episode_active
            self._episode_active = True
            self._episode_last_request_beat = beat_no
            if not episode_was_active and self.ctx.has("recovery_protocol"):
                try:
                    proto = self.ctx.get("recovery_protocol")
                    if hasattr(proto, "finalize_durability_on_next_fragmentation"):
                        proto.finalize_durability_on_next_fragmentation(beat_no)
                except Exception:
                    log.debug("durability_finalize_failed", beat_no=beat_no)
            self.ctx.emit_sync("recovery_request", req)
            log.debug("recovery_request_emitted", beat_no=beat_no, stage=stage,
                      request_id=req.request_id)

    def current_value(self) -> FragmentationReading:
        return self._current

    def recent_history(self, n: int | None = None) -> list[FragmentationReading]:
        h = list(self.history)
        return h[-n:] if n is not None else h

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "thresholds": dict(self.thresholds),
            "min_recovery_stage": self.min_recovery_stage,
            "rolling_retrieval_mean": self._rolling_retrieval_mean,
            "rolling_confidence_spread_mean": self._rolling_confidence_spread_mean,
            "rolling_valence_var": self._rolling_valence_var,
            "stage1_streak": self._stage1_streak,
            "stage3_streak": self._stage3_streak,
            "previous_stage": self._previous_stage,
            "episode_active": self._episode_active,
            "episode_last_request_beat": self._episode_last_request_beat,
            "current": {
                "beat_no": self._current.beat_no,
                "current_stage": self._current.current_stage,
                "signals": self._current.signals,
                "stage1_streak_beats": self._current.stage1_streak_beats,
                "stage3_streak_beats": self._current.stage3_streak_beats,
                "valid": self._current.valid,
            },
        }

    def load_state(self, snapshot: dict[str, Any]) -> None:
        self.thresholds = dict(snapshot.get("thresholds", DEFAULT_THRESHOLDS))
        self.min_recovery_stage = int(snapshot.get("min_recovery_stage", 2))
        self._rolling_retrieval_mean = snapshot.get("rolling_retrieval_mean")
        self._rolling_confidence_spread_mean = snapshot.get("rolling_confidence_spread_mean")
        self._rolling_valence_var = snapshot.get("rolling_valence_var")
        self._stage1_streak = int(snapshot.get("stage1_streak", 0))
        self._stage3_streak = int(snapshot.get("stage3_streak", 0))
        self._previous_stage = int(snapshot.get("previous_stage", 0))
        self._episode_active = bool(snapshot.get("episode_active", False))
        self._episode_last_request_beat = snapshot.get("episode_last_request_beat")
        cur = snapshot.get("current", {})
        self._current = FragmentationReading(
            beat_no=int(cur.get("beat_no", 0)),
            current_stage=int(cur.get("current_stage", 0)),
            signals=dict(cur.get("signals", {})),
            stage1_streak_beats=int(cur.get("stage1_streak_beats", 0)),
            stage3_streak_beats=int(cur.get("stage3_streak_beats", 0)),
            valid=bool(cur.get("valid", False)),
        )


__all__ = [
    "DEFAULT_THRESHOLDS",
    "FragmentationMonitor",
    "FragmentationReading",
    "FragmentationStageChange",
    "RecoveryRequestPayload",
]
