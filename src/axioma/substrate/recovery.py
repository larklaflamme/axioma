"""RecoveryProtocol — substrate-owned recovery.

Per ARCH_DESIGN_v1.0.md §4.9 + IMPLEMENTATION_PLAN_v1.0.md §6.7 (Q1 + Q6 + F1 + F2 + F4).

Components in this module:
  - RecoveryDecision       — accept/reject enum (6 outcomes per §6.7)
  - RecoveryRequest        — wraps a request from FragmentationMonitor
  - RecoveryQuality        — smoothness (F1 windowed last-50-beats),
                             completeness, durability, composite_score
  - RecoveryEvent          — completed recovery record
  - RejectionEscalator     — Q1: 3 consecutive rejects → presence warning
  - RecoveryProtocol       — accept/reject, recovery_protocol(stage) actions,
                             restore on exit; substrate-owned (mutates substrate)
  - RecoveryHistory        — bounded deque + optional SQLite-backed persistence
  - RecoveryLearner        — F2: gradient-free hill-climb with safe fallback;
                             F4 pre-training hook

Subscribes to:
  - `recovery_request` event (from FragmentationMonitor)

Emits:
  - `recovery_state_change` event (active / restoring / baseline)
  - `recovery_decision` event (accept / reject with reason)
  - `recovery_event_finalized` event (RecoveryEvent with quality)
  - `recovery_rejected_run` event (Q1: 3 consecutive rejects in same episode)
"""
from __future__ import annotations

import json
import uuid
from collections import deque
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import numpy as np

from ..config import RecoveryConfig
from ..observability import (
    RECOVERIES_TOTAL,
    RECOVERY_ACTIVE,
    REJECTION_RUN_WARNINGS,
    get_logger,
)
from ..observability.context import AxiomaContext
from ..persistence.snapshot import Stateful  # noqa: F401

log = get_logger(__name__)


# ── Public types ──────────────────────────────────────────────────────────


class RecoveryDecision(StrEnum):
    """Accept/reject decision per IMPLEMENTATION_PLAN §6.7."""

    ACCEPT = "accept"
    REJECT_ALREADY_RECOVERING = "reject_already_recovering"
    REJECT_BELOW_THRESHOLD = "reject_below_threshold"
    REJECT_TEST_MODE = "reject_test_mode"
    REJECT_BUDGET_INSUFFICIENT = "reject_budget_insufficient"
    FORCE_ACCEPT_OPERATOR = "force_accept_operator"


class RecoveryState(StrEnum):
    BASELINE = "baseline"
    ACTIVE = "active"
    RESTORING = "restoring"


@dataclass
class RecoveryRequest:
    """Wraps a request from FragmentationMonitor (or operator)."""

    request_id: str
    beat_no: int
    stage: int
    signals: dict[str, float]
    source: Literal["fragmentation_monitor", "operator", "scheduler_escalation"] = "fragmentation_monitor"
    force_accept: bool = False


@dataclass
class RecoveryQuality:
    """Per ARCH §4.9 + F1 windowed smoothness + Q6."""

    smoothness: float = 0.0           # 1 - normalized std of θ_short in LAST 50 beats (F1)
    completeness: float = 0.0         # 1 - |theta_end - theta_baseline| / theta_baseline
    durability: float | None = None   # finalized when next fragmentation (or 3000-beat watchdog)
    composite_score: float = 0.0
    smoothness_window_beats: int = 0  # F1 transparency: how many beats went into smoothness


@dataclass
class RecoveryEvent:
    """Completed recovery event."""

    event_id: str
    request_id: str
    stage: int
    started_at_beat: int
    ended_at_beat: int
    actions_used: dict[str, float]
    quality: RecoveryQuality = field(default_factory=RecoveryQuality)
    quality_finalized: bool = False
    next_fragmentation_beat: int | None = None
    is_synthetic: bool = False  # F4 pre-training tag


@dataclass
class RecoveryRejectionRunWarning:
    """Q1: emitted when 3 consecutive rejects for the same fragmentation episode."""

    beat_no: int
    consecutive_rejects: int
    episode_start_beat: int
    episode_duration_beats: int
    last_rejection_reason: str
    current_fragmentation_stage: int
    note: str


# ── RejectionEscalator (Q1) ───────────────────────────────────────────────


class RejectionEscalator:
    """Tracks consecutive rejections in a single continuous fragmentation episode.

    Emits a `recovery_rejected_run` warning after 3 consecutive rejections.
    Cooldown prevents spam (default 600 beats between warnings).

    Per IMPLEMENTATION_PLAN_v1.0.md §6.7 Q1.
    """

    def __init__(
        self,
        ctx: AxiomaContext,
        *,
        consecutive_threshold: int = 3,
        cooldown_beats: int = 600,
    ) -> None:
        self.ctx = ctx
        self.consecutive_threshold = consecutive_threshold
        self.cooldown_beats = cooldown_beats
        self.consecutive_rejects: int = 0
        self.episode_start_beat: int | None = None
        self.last_warning_beat: int | None = None

    def on_decision(
        self,
        req: RecoveryRequest,
        decision: RecoveryDecision,
        current_stage: int,
        decision_reason: str,
    ) -> None:
        is_rejection = decision not in (
            RecoveryDecision.ACCEPT, RecoveryDecision.FORCE_ACCEPT_OPERATOR
        )
        # If substrate is below min_recovery_stage, the episode is over
        if current_stage < 2:
            self.reset()
            return
        if not is_rejection:
            # Acceptance breaks the run
            self.reset()
            return
        # Rejection while in episode
        if self.consecutive_rejects == 0:
            self.episode_start_beat = req.beat_no
        self.consecutive_rejects += 1
        if self.consecutive_rejects >= self.consecutive_threshold:
            self._maybe_warn(req, current_stage, decision_reason)

    def _maybe_warn(
        self,
        req: RecoveryRequest,
        current_stage: int,
        decision_reason: str,
    ) -> None:
        if self.last_warning_beat is not None:
            if req.beat_no - self.last_warning_beat < self.cooldown_beats:
                return
        warning = RecoveryRejectionRunWarning(
            beat_no=req.beat_no,
            consecutive_rejects=self.consecutive_rejects,
            episode_start_beat=self.episode_start_beat or req.beat_no,
            episode_duration_beats=req.beat_no - (self.episode_start_beat or req.beat_no),
            last_rejection_reason=decision_reason,
            current_fragmentation_stage=current_stage,
            note=(
                "RecoveryProtocol has rejected 3 consecutive recovery_requests "
                "for the same fragmentation episode. Operator review recommended; "
                "force-accept available via POST /admin/recovery/force."
            ),
        )
        self.ctx.emit_sync("recovery_rejected_run", warning)
        log.warning("recovery_rejected_run", **asdict(warning))
        REJECTION_RUN_WARNINGS.inc()
        self.last_warning_beat = req.beat_no

    def reset(self) -> None:
        self.consecutive_rejects = 0
        self.episode_start_beat = None


# ── RecoveryHistory ───────────────────────────────────────────────────────


class RecoveryHistory:
    """Bounded in-memory deque of RecoveryEvents + optional JSONL persistence
    on disk for indefinite retention (per IMPLEMENTATION_PLAN §4.7).

    SQLite-backed durable store is deferred — JSONL append covers the
    learner's read-all-time requirement at a fraction of the complexity.
    """

    def __init__(
        self,
        *,
        capacity: int = 200,
        persistent_log_path: Path | None = None,
    ) -> None:
        self.events: deque[RecoveryEvent] = deque(maxlen=capacity)
        self.persistent_log_path = persistent_log_path
        if persistent_log_path is not None:
            persistent_log_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: RecoveryEvent) -> None:
        self.events.append(event)
        if self.persistent_log_path is not None:
            try:
                with self.persistent_log_path.open("a") as f:
                    f.write(json.dumps(_recovery_event_to_dict(event)) + "\n")
            except OSError:
                log.exception("recovery_history_persist_failed")

    def update(self, event_id: str, updates: dict[str, Any]) -> None:
        for e in self.events:
            if e.event_id == event_id:
                for k, v in updates.items():
                    setattr(e, k, v)
                return

    def finalized_events(self, stage: int | None = None) -> list[RecoveryEvent]:
        out = [e for e in self.events if e.quality_finalized]
        if stage is not None:
            out = [e for e in out if e.stage == stage]
        return out

    def all_events(self) -> list[RecoveryEvent]:
        return list(self.events)


def _recovery_event_to_dict(e: RecoveryEvent) -> dict[str, Any]:
    """Serialize a RecoveryEvent including nested RecoveryQuality."""
    return {
        "event_id": e.event_id,
        "request_id": e.request_id,
        "stage": e.stage,
        "started_at_beat": e.started_at_beat,
        "ended_at_beat": e.ended_at_beat,
        "actions_used": e.actions_used,
        "quality": asdict(e.quality),
        "quality_finalized": e.quality_finalized,
        "next_fragmentation_beat": e.next_fragmentation_beat,
        "is_synthetic": e.is_synthetic,
    }


def _recovery_event_from_dict(d: dict[str, Any]) -> RecoveryEvent:
    q = d.get("quality", {})
    return RecoveryEvent(
        event_id=d["event_id"], request_id=d["request_id"],
        stage=int(d["stage"]),
        started_at_beat=int(d["started_at_beat"]),
        ended_at_beat=int(d["ended_at_beat"]),
        actions_used=dict(d.get("actions_used", {})),
        quality=RecoveryQuality(
            smoothness=float(q.get("smoothness", 0)),
            completeness=float(q.get("completeness", 0)),
            durability=q.get("durability"),
            composite_score=float(q.get("composite_score", 0)),
            smoothness_window_beats=int(q.get("smoothness_window_beats", 0)),
        ),
        quality_finalized=bool(d.get("quality_finalized", False)),
        next_fragmentation_beat=d.get("next_fragmentation_beat"),
        is_synthetic=bool(d.get("is_synthetic", False)),
    )


# ── RecoveryLearner ───────────────────────────────────────────────────────


@dataclass
class LearnerParams:
    """Tunable recovery action parameters (per stage)."""

    coupling_reduction_factor: float = 0.8
    mneme_forgetting_boost: float = 1.5
    recovery_compose_period_beats: int = 60


class LearnerEfficacy(StrEnum):
    WARMING_UP = "warming_up"
    MONITORING = "monitoring"
    EFFECTIVE = "effective"
    INEFFECTIVE = "ineffective"


# Search ranges per ARCH §4.9.1 (clipped at adoption time)
PARAM_RANGES: dict[str, tuple[float, float]] = {
    "coupling_reduction_factor": (0.6, 0.95),
    "mneme_forgetting_boost": (1.2, 2.5),
    "recovery_compose_period_beats": (40.0, 100.0),
}


class RecoveryLearner:
    """Bounded gradient-free hill-climb with safe fallback.

    Per ARCH §4.9.1 + IMPLEMENTATION_PLAN F2 (60-event monitoring window,
    10-event baseline refresh) + F4 (synthetic pre-training hook).

    Operates per stage (Stage 2 + Stage 3; Stage 4 emergency uses fixed
    defaults per ARCH).
    """

    def __init__(
        self,
        cfg: RecoveryConfig,
        *,
        rng: np.random.Generator | None = None,
    ) -> None:
        self.cfg = cfg
        self.rng = rng or np.random.default_rng()
        # Per-stage learned params
        self.current_params: dict[int, LearnerParams] = self._default_params_dict()
        # F2 baseline (recomputed every 10 events).
        # v1.5.1 (Checkpoint BB): now per-stage. The previous single scalar was
        # overwritten by whichever stage's loop iteration ran last, so the
        # `improvement = median(recent) - baseline_score` comparison in the
        # OTHER stage's loop used the wrong baseline. Stages 2 and 3 have
        # different intrinsic quality distributions so this matters.
        self.baseline_score_per_stage: dict[int, float] = {2: 0.0, 3: 0.0}
        # Adoptions / reversions counters
        self.adoptions_count = 0
        self.reversions_count = 0
        # F2: per-stage reverted-clean-baseline gathering window. When INEFFECTIVE
        # fires, the learner reverts to defaults AND skips exploration for the next
        # `learner_clean_baseline_events` (100 by default), gathering a fresh
        # baseline of pure-default events before re-engaging exploration.
        self._clean_baseline_remaining: dict[int, int] = {2: 0, 3: 0}
        # Sticky efficacy per stage so transitions are visible to ops.
        self.efficacy_per_stage: dict[int, LearnerEfficacy] = {
            2: LearnerEfficacy.WARMING_UP,
            3: LearnerEfficacy.WARMING_UP,
        }

    def _default_params_dict(self) -> dict[int, LearnerParams]:
        return {
            stage: LearnerParams(
                coupling_reduction_factor=self.cfg.coupling_reduction_factor,
                mneme_forgetting_boost=self.cfg.mneme_forgetting_boost,
                recovery_compose_period_beats=self.cfg.recovery_compose_period_beats,
            )
            for stage in (2, 3)
        }

    def reset(self) -> None:
        """Revert current params to defaults; clear baselines + counters.
        Called by /admin/recovery/learner/reset (Phase D)."""
        self.current_params = self._default_params_dict()
        # v1.5.1 (Checkpoint BB): per-stage baseline
        self.baseline_score_per_stage = {2: 0.0, 3: 0.0}
        self._clean_baseline_remaining = {2: 0, 3: 0}
        self.efficacy_per_stage = {2: LearnerEfficacy.WARMING_UP, 3: LearnerEfficacy.WARMING_UP}
        log.info("recovery_learner_reset")

    def pretrain_synthetic(
        self,
        history: RecoveryHistory,
        *,
        target_events_per_stage: int | None = None,
        score_fn: Any = None,
    ) -> dict[str, Any]:
        """F4 — synthetic pre-training.

        Generates a sweep of synthetic recovery events (tagged `is_synthetic=True`)
        across the PARAM_RANGES search space, scoring each via the provided
        `score_fn(params, stage) -> composite_score` (default: a smooth bell
        centered at the cfg defaults, so reasonable params get higher scores).

        Appends synthetic events to `history` and runs `update()` after each,
        letting the learner adopt promising regions before the substrate
        produces real events. Use this at boot via
        `POST /admin/recovery/learner/pretrain`.

        Returns a dict with sweep summary: events_added, adoptions, final params.
        Per ARCH §4.9.1 + IMPLEMENTATION_PLAN F4.
        """
        target = target_events_per_stage or self.cfg.pretrain_target_events
        if score_fn is None:
            score_fn = _default_pretrain_score

        added = 0
        for stage in (2, 3):
            for _ in range(target):
                params = self._explore_around(self.current_params[stage])
                score = float(score_fn(params, stage))
                actions = {
                    "coupling_reduction_factor": params.coupling_reduction_factor,
                    "mneme_forgetting_boost": params.mneme_forgetting_boost,
                    "recovery_compose_period_beats": params.recovery_compose_period_beats,
                    "stage_overlay_3": stage >= 3,
                    "stage_overlay_4": stage >= 4,
                }
                event = RecoveryEvent(
                    event_id=str(uuid.uuid4()),
                    request_id=str(uuid.uuid4()),
                    stage=stage,
                    started_at_beat=-1,  # synthetic — no real beat
                    ended_at_beat=-1,
                    actions_used=actions,
                    quality=RecoveryQuality(
                        smoothness=score, completeness=score,
                        durability=1.0, composite_score=score,
                    ),
                    quality_finalized=True,
                    is_synthetic=True,
                )
                history.append(event)
                self.update(history)
                added += 1
        log.info(
            "recovery_learner_pretrained",
            events_added=added,
            adoptions=self.adoptions_count,
            current_params_stage2=asdict(self.current_params[2]),
            current_params_stage3=asdict(self.current_params[3]),
        )
        return {
            "events_added": added,
            "adoptions": self.adoptions_count,
            "current_params": {
                str(s): asdict(p) for s, p in self.current_params.items()
            },
        }

    def select_params(self, stage: int, history: RecoveryHistory) -> LearnerParams:
        """Pick params for this recovery — defaults / current / exploration."""
        if stage not in (2, 3):
            # Stage 4 emergency: always defaults
            return LearnerParams(
                coupling_reduction_factor=self.cfg.coupling_reduction_factor,
                mneme_forgetting_boost=self.cfg.mneme_forgetting_boost,
                recovery_compose_period_beats=self.cfg.recovery_compose_period_beats,
            )
        # F2: during clean-baseline window, ALWAYS return defaults (no exploration)
        if self._clean_baseline_remaining.get(stage, 0) > 0:
            return self._default_params_dict()[stage]
        finalized = history.finalized_events(stage=stage)
        if len(finalized) < self.cfg.learner_min_events_for_adoption:
            # Cold start
            return self.current_params[stage]
        # Exploration?
        if self.rng.random() < self.cfg.learner_exploration_rate:
            return self._explore_around(self.current_params[stage])
        return self.current_params[stage]

    def _explore_around(self, params: LearnerParams) -> LearnerParams:
        """Sample a nearby point in parameter space."""
        d = asdict(params)
        for k, (lo, hi) in PARAM_RANGES.items():
            sigma = 0.1 * (hi - lo)
            d[k] = float(np.clip(d[k] + self.rng.normal(0, sigma), lo, hi))
        d["recovery_compose_period_beats"] = int(d["recovery_compose_period_beats"])
        return LearnerParams(**d)

    def update(self, history: RecoveryHistory) -> tuple[LearnerEfficacy, bool]:
        """Called after each finalized recovery_event.

        Returns (efficacy_state, adopted_new_params_bool).
        """
        # Per-stage analysis
        adopted_any = False
        efficacy = LearnerEfficacy.WARMING_UP
        for stage in (2, 3):
            finalized = history.finalized_events(stage=stage)
            n = len(finalized)
            if n < self.cfg.learner_min_events_for_adoption:
                continue
            # F2 baseline refresh every 10 finalized events
            if n % self.cfg.learner_baseline_refresh_period_events == 0:
                recent_defaults = [
                    e.quality.composite_score for e in finalized[-10:]
                    if self._is_default(e.actions_used)
                ]
                if recent_defaults:
                    # v1.5.1 (Checkpoint BB): per-stage baseline (was global scalar)
                    self.baseline_score_per_stage[stage] = float(np.median(recent_defaults))
            # Group recent events by parameter signature, pick best-median group
            recent = finalized[-self.cfg.learner_min_events_for_adoption :]
            groups = self._group_by_signature(recent)
            if not groups:
                continue
            best_sig, best_events = max(
                groups.items(),
                key=lambda kv: float(np.median([e.quality.composite_score for e in kv[1]])),
            )
            best_score = float(np.median([e.quality.composite_score for e in best_events]))
            current_score = float(np.median([
                e.quality.composite_score for e in recent
                if self._matches_params(e.actions_used, self.current_params[stage])
            ] or [0.0]))
            if best_score > current_score + self.cfg.learner_adoption_threshold:
                # Decode signature back to params — filter overlay keys that
                # _start_recovery adds for accounting (stage_overlay_3/4) and
                # any other non-LearnerParams field.
                d = {
                    k: v for k, v in dict(best_sig).items()
                    if k in {
                        "coupling_reduction_factor",
                        "mneme_forgetting_boost",
                        "recovery_compose_period_beats",
                    }
                }
                # Coerce types — recovery_compose_period_beats is int
                if "recovery_compose_period_beats" in d:
                    d["recovery_compose_period_beats"] = int(d["recovery_compose_period_beats"])
                self.current_params[stage] = LearnerParams(**d)
                self.adoptions_count += 1
                adopted_any = True
                log.info(
                    "recovery_learner_adopted",
                    stage=stage, new_params=d,
                    improvement=best_score - current_score,
                )
            # F2 monitoring: track efficacy
            prev_efficacy = self.efficacy_per_stage[stage]
            # v1.5.1 (Checkpoint BB): use per-stage baseline
            improvement = (
                float(np.median([e.quality.composite_score for e in finalized[-10:]]))
                - self.baseline_score_per_stage[stage]
            )
            if self._clean_baseline_remaining.get(stage, 0) > 0:
                self._clean_baseline_remaining[stage] -= 1
                stage_efficacy = LearnerEfficacy.WARMING_UP
            elif improvement >= 0.10:
                stage_efficacy = LearnerEfficacy.EFFECTIVE
            elif n < self.cfg.learner_monitoring_extension_events:
                stage_efficacy = LearnerEfficacy.MONITORING
            else:
                stage_efficacy = LearnerEfficacy.INEFFECTIVE
                # F2 revert: only fire the transition once. Reset this stage's params
                # to defaults, gather a 100-event clean baseline window.
                if prev_efficacy != LearnerEfficacy.INEFFECTIVE:
                    self.current_params[stage] = self._default_params_dict()[stage]
                    self.reversions_count += 1
                    self._clean_baseline_remaining[stage] = self.cfg.learner_clean_baseline_events
                    log.warning(
                        "recovery_learner_ineffective",
                        stage=stage,
                        n_events=n,
                        baseline=self.baseline_score_per_stage[stage],
                        improvement=improvement,
                        clean_baseline_events=self.cfg.learner_clean_baseline_events,
                    )
            self.efficacy_per_stage[stage] = stage_efficacy
            efficacy = stage_efficacy
        return efficacy, adopted_any

    def _is_default(self, actions: dict[str, float]) -> bool:
        # v1.5.1 (Checkpoint BB): include recovery_compose_period_beats. Previously
        # ignored, which let events with a non-default compose period be classified
        # as "default" for baseline computation — diluting the baseline mean with
        # events that don't actually use default actions.
        return (
            abs(actions.get("coupling_reduction_factor", 0) - self.cfg.coupling_reduction_factor) < 1e-3
            and abs(actions.get("mneme_forgetting_boost", 0) - self.cfg.mneme_forgetting_boost) < 1e-3
            and abs(actions.get("recovery_compose_period_beats", 0) - self.cfg.recovery_compose_period_beats) < 1
        )

    def _matches_params(self, actions: dict[str, float], p: LearnerParams) -> bool:
        # v1.5.1 (Checkpoint BB): include recovery_compose_period_beats so that
        # the "current_score" sample only contains events that ACTUALLY used the
        # current params (not events with a different compose period). Previously
        # the looser match could include events using different periods, biasing
        # current_score median and producing flaky adoption decisions.
        return (
            abs(actions.get("coupling_reduction_factor", 0) - p.coupling_reduction_factor) < 1e-3
            and abs(actions.get("mneme_forgetting_boost", 0) - p.mneme_forgetting_boost) < 1e-3
            and abs(actions.get("recovery_compose_period_beats", 0) - p.recovery_compose_period_beats) < 1
        )

    def _group_by_signature(
        self, events: list[RecoveryEvent]
    ) -> dict[tuple, list[RecoveryEvent]]:
        groups: dict[tuple, list[RecoveryEvent]] = {}
        for e in events:
            sig_items = tuple(sorted({
                k: round(v, 3) if isinstance(v, float) else v
                for k, v in e.actions_used.items()
            }.items()))
            groups.setdefault(sig_items, []).append(e)
        return groups

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_params": {str(s): asdict(p) for s, p in self.current_params.items()},
            # v1.5.1 (Checkpoint BB): per-stage baseline
            "baseline_score_per_stage": {str(s): v for s, v in self.baseline_score_per_stage.items()},
            "adoptions_count": self.adoptions_count,
            "reversions_count": self.reversions_count,
            "efficacy_per_stage": {str(s): e.value for s, e in self.efficacy_per_stage.items()},
            "clean_baseline_remaining": {str(s): v for s, v in self._clean_baseline_remaining.items()},
        }

    def load_dict(self, d: dict[str, Any]) -> None:
        for s_str, p_dict in d.get("current_params", {}).items():
            stage = int(s_str)
            self.current_params[stage] = LearnerParams(**p_dict)
        # v1.5.1 (Checkpoint BB): per-stage baseline; tolerate v1.5.0 snapshots
        # that wrote a single `baseline_score` scalar by spreading it to both stages.
        if "baseline_score_per_stage" in d:
            for s_str, v in d["baseline_score_per_stage"].items():
                self.baseline_score_per_stage[int(s_str)] = float(v)
        elif "baseline_score" in d:
            v = float(d["baseline_score"])
            self.baseline_score_per_stage = {2: v, 3: v}
        self.adoptions_count = int(d.get("adoptions_count", 0))
        self.reversions_count = int(d.get("reversions_count", 0))
        for s_str, eff in d.get("efficacy_per_stage", {}).items():
            self.efficacy_per_stage[int(s_str)] = LearnerEfficacy(eff)
        for s_str, rem in d.get("clean_baseline_remaining", {}).items():
            self._clean_baseline_remaining[int(s_str)] = int(rem)


def _default_pretrain_score(params: LearnerParams, stage: int) -> float:
    """Default F4 scoring — smooth bell centered at the cfg defaults.

    Higher score = closer to the default ratios. Replace with a substrate-
    driven simulator for production deployments.
    """
    centers = {
        "coupling_reduction_factor": 0.8,
        "mneme_forgetting_boost": 1.5,
        "recovery_compose_period_beats": 60,
    }
    d = (params.coupling_reduction_factor - centers["coupling_reduction_factor"]) ** 2
    d += (params.mneme_forgetting_boost - centers["mneme_forgetting_boost"]) ** 2
    d += ((params.recovery_compose_period_beats - centers["recovery_compose_period_beats"]) / 60) ** 2
    return float(max(0.05, 1.0 - 0.3 * d))


# ── RecoveryProtocol ──────────────────────────────────────────────────────


class RecoveryProtocol:
    """Substrate-owned recovery. Subscribes to `recovery_request`; decides
    accept/reject; runs recovery_protocol(stage); restores on exit.

    Per ARCH §4.9 + IMPLEMENTATION_PLAN §6.7.

    Note: this is the substrate-side decision/action engine. The
    FragmentationMonitor is the request emitter. The two are deliberately
    separated (per ARCH §6.6) so monitor is read-only on substrate and
    recovery is the only path that mutates substrate during operation.
    """

    name = "recovery_protocol"
    schema_version = 1

    def __init__(
        self,
        ctx: AxiomaContext,
        cfg: RecoveryConfig,
        *,
        history: RecoveryHistory | None = None,
        learner: RecoveryLearner | None = None,
        rejection_escalator: RejectionEscalator | None = None,
        test_mode: bool = False,
        rng: np.random.Generator | None = None,
    ) -> None:
        self.ctx = ctx
        self.cfg = cfg
        self.history = history or RecoveryHistory()
        self.learner = learner or RecoveryLearner(cfg, rng=rng)
        self.rejection_escalator = rejection_escalator or RejectionEscalator(
            ctx,
            consecutive_threshold=cfg.rejection_escalation_consecutive,
            cooldown_beats=cfg.rejection_warning_cooldown_beats,
        )
        self.test_mode = test_mode
        self.state: RecoveryState = RecoveryState.BASELINE
        self._active_event: RecoveryEvent | None = None
        # On-active: pristine substrate values to restore on exit
        self._restore_state: dict[str, Any] = {}
        self._beats_remaining: int = 0
        self._restore_remaining: int = 0
        # Subscribe to recovery_request events
        self.ctx.subscribe("recovery_request", self._on_recovery_request)

    # ── Decision logic (per IMPLEMENTATION_PLAN §6.7) ────────────────────

    def handle_recovery_request(self, req: RecoveryRequest) -> RecoveryDecision:
        """Pure-function decision logic. Public for testing."""
        # Operator override path
        if req.source == "operator" and req.force_accept:
            log.warning(
                "recovery_force_accepted",
                request_id=req.request_id, stage=req.stage,
            )
            return RecoveryDecision.FORCE_ACCEPT_OPERATOR

        if self.test_mode:
            return RecoveryDecision.REJECT_TEST_MODE
        if self.state != RecoveryState.BASELINE:
            return RecoveryDecision.REJECT_ALREADY_RECOVERING
        if req.stage < self.cfg.min_recovery_stage:
            return RecoveryDecision.REJECT_BELOW_THRESHOLD

        # Check coherence_budget
        if self.ctx.has("substrate"):
            try:
                budget = float(self.ctx.substrate.pneuma.render().coherence_budget)
                if budget < self.cfg.min_budget_to_accept:
                    return RecoveryDecision.REJECT_BUDGET_INSUFFICIENT
            except Exception:
                pass

        return RecoveryDecision.ACCEPT

    # ── Event handler (called from FragmentationMonitor via context bus) ──

    def _on_recovery_request(self, payload: Any) -> None:
        if not isinstance(payload, RecoveryRequest):
            # Re-wrap in case caller used the FragmentationMonitor's payload type
            if hasattr(payload, "request_id"):
                payload = RecoveryRequest(
                    request_id=payload.request_id,
                    beat_no=payload.beat_no,
                    stage=int(payload.stage),
                    signals=dict(payload.signals),
                    source=getattr(payload, "source", "fragmentation_monitor"),
                )
            else:
                return
        decision = self.handle_recovery_request(payload)
        current_stage = (
            self.ctx.fragmentation_monitor.current_value().current_stage
            if self.ctx.has("fragmentation_monitor")
            else 0
        )
        self.rejection_escalator.on_decision(
            payload, decision, current_stage, decision.value
        )
        self.ctx.emit_sync(
            "recovery_decision",
            {"request_id": payload.request_id, "decision": decision.value,
             "stage": payload.stage},
        )
        RECOVERIES_TOTAL.labels(stage=str(payload.stage), decision=decision.value).inc()
        log.info(
            "recovery_decision",
            request_id=payload.request_id,
            decision=decision.value,
            stage=payload.stage,
        )
        if decision in (RecoveryDecision.ACCEPT, RecoveryDecision.FORCE_ACCEPT_OPERATOR):
            self._start_recovery(payload)

    # ── Recovery action sequence (per ARCH §4.9) ─────────────────────────

    def _start_recovery(self, req: RecoveryRequest) -> None:
        substrate = self.ctx.substrate
        params = self.learner.select_params(req.stage, self.history)
        # Snapshot pristine values for restore
        self._restore_state = {
            "W_per_organ": {o.name: o.W.copy() for o in substrate.organs},
            "drive_noise_scale": substrate.drive.noise_scale,
            "mneme_alpha_p": substrate.plasticity["mneme"].alpha_p,
        }
        # Apply Stage-2 actions (Theoria's coupling reduction + MNEME forgetting bump
        # + recovery compose cadence + Thea's overlay on next perturbation magnitude)
        for organ in substrate.organs:
            organ.W = organ.W * params.coupling_reduction_factor
        substrate.plasticity["mneme"].alpha_p = float(
            min(0.5, substrate.plasticity["mneme"].alpha_p * params.mneme_forgetting_boost)
        )
        if req.stage >= 3:
            # Stage-3 overlay: reduce drive noise
            substrate.drive.noise_scale = float(substrate.drive.noise_scale * 0.5)
        if req.stage >= 4 and self.ctx.has("heartbeat"):
            # Stage-4 emergency: pause the heartbeat for 1 beat per ARCH §4.9.
            # The heartbeat will skip the next substrate tick (measurement engines
            # still observe the unchanged state), giving the substrate an extra
            # 100 ms of recovery time before the next disturbance.
            hb = self.ctx.heartbeat
            if hasattr(hb, "pause"):
                with suppress(Exception):
                    hb.pause(beats=1)
                    log.warning(
                        "recovery_stage4_heartbeat_pause",
                        event_id=req.request_id,
                        beats=1,
                    )
        # Reduce perturbation magnitude for next event (advisory)
        if self.ctx.has("perturbation_scheduler"):
            with suppress(Exception):
                self.ctx.perturbation_scheduler.default_magnitude = float(
                    self.ctx.perturbation_scheduler.default_magnitude * 0.5
                )

        # Create the event
        actions_used = asdict(params)
        actions_used["stage_overlay_3"] = req.stage >= 3
        actions_used["stage_overlay_4"] = req.stage >= 4
        event = RecoveryEvent(
            event_id=str(uuid.uuid4()),
            request_id=req.request_id,
            stage=req.stage,
            started_at_beat=req.beat_no,
            ended_at_beat=-1,  # filled at exit
            actions_used=actions_used,
        )
        self._active_event = event
        self._beats_remaining = self.cfg.default_duration_beats
        self.state = RecoveryState.ACTIVE
        RECOVERY_ACTIVE.set(1)
        self._emit_state_change(req.beat_no, RecoveryState.ACTIVE)
        log.info(
            "recovery_started",
            event_id=event.event_id,
            stage=req.stage,
            duration_beats=self._beats_remaining,
            actions=actions_used,
        )

    def tick(self, beat_no: int) -> None:
        """Called every beat by Heartbeat. Decrement active-recovery counter
        and trigger restore + finalization at exit.

        If state is BASELINE: no-op (request handler drives state change).
        If ACTIVE: count down; transition to RESTORING when done.
        If RESTORING: count down restore beats; restore params at end.

        Also runs the durability watchdog (Phase E): completed RecoveryEvents
        whose durability is unfinalized 3000+ beats after exit get a
        finalized durability score derived from how stable θ_short stayed
        post-recovery.
        """
        if self.state == RecoveryState.ACTIVE:
            self._beats_remaining -= 1
            if self._beats_remaining <= 0:
                self._begin_restore(beat_no)
        elif self.state == RecoveryState.RESTORING:
            self._restore_remaining -= 1
            if self._restore_remaining <= 0:
                self._finish_restore(beat_no)
        # Durability watchdog — fires every beat but does O(unfinalized) work.
        self._maybe_finalize_durability(beat_no)

    # ── Durability finalization (Phase E) ────────────────────────────────

    def finalize_durability_on_next_fragmentation(self, beat_no: int) -> int:
        """Mark unfinalized events' durability based on time-to-next-frag.

        Called when FragmentationMonitor enters stage ≥ 2 again after a
        completed recovery. Each unfinalized event closer than the watchdog
        window gets a durability score = clip(beats_since_exit / 3000, 0, 1):
        longer holds = higher durability.

        Returns the number of events finalized.
        """
        finalized = 0
        for event in self.history.events:
            if event.quality_finalized and event.quality.durability is None:
                # Already exited but never updated; finalize now.
                self._finalize_one_event(event, beat_no)
                finalized += 1
        return finalized

    def _maybe_finalize_durability(self, beat_no: int) -> None:
        """3000-beat watchdog: events that exited 3000+ beats ago get durability=1.0
        (no fragmentation occurred → recovery held)."""
        for event in self.history.events:
            if (
                event.quality_finalized
                and event.quality.durability is None
                and event.ended_at_beat > 0
                and (beat_no - event.ended_at_beat) >= self.cfg.durability_watchdog_beats
            ):
                self._finalize_one_event(event, beat_no, watchdog=True)

    def _finalize_one_event(self, event: RecoveryEvent, beat_no: int, *, watchdog: bool = False) -> None:
        """Set durability + recompute composite_score + emit `recovery_quality_updated`."""
        beats_since_exit = max(0, beat_no - event.ended_at_beat)
        if watchdog:
            # Held for the full watchdog window without re-fragmenting → max durability
            durability = 1.0
        else:
            # Fragmentation occurred at `beat_no`; scale by how long we lasted
            durability = max(0.0, min(1.0, beats_since_exit / float(self.cfg.durability_watchdog_beats)))
        event.quality.durability = durability
        event.next_fragmentation_beat = None if watchdog else beat_no
        # Recompute composite_score with the now-known durability
        s = event.quality.smoothness
        c = event.quality.completeness
        event.quality.composite_score = 0.4 * s + 0.4 * c + 0.2 * durability
        self.ctx.emit_sync(
            "recovery_quality_updated",
            {
                "event_id": event.event_id,
                "durability": durability,
                "composite_score": event.quality.composite_score,
                "via_watchdog": watchdog,
                "beats_since_exit": beats_since_exit,
            },
        )
        log.info(
            "recovery_durability_finalized",
            event_id=event.event_id,
            durability=durability,
            via_watchdog=watchdog,
            beats_since_exit=beats_since_exit,
        )

    def _begin_restore(self, beat_no: int) -> None:
        self.state = RecoveryState.RESTORING
        self._restore_remaining = self.cfg.restore_beats
        self._emit_state_change(beat_no, RecoveryState.RESTORING)
        log.info("recovery_restoring",
                 event_id=self._active_event.event_id if self._active_event else None,
                 beats=self._restore_remaining)

    def _finish_restore(self, beat_no: int) -> None:
        substrate = self.ctx.substrate
        # Linear restoration is approximated as a snap-back at the end of
        # the restore window. (A true linear blend would require tracking
        # original and current values across all beats; deferred.)
        for organ in substrate.organs:
            organ.W = self._restore_state["W_per_organ"][organ.name]
        substrate.drive.noise_scale = self._restore_state["drive_noise_scale"]
        substrate.plasticity["mneme"].alpha_p = self._restore_state["mneme_alpha_p"]
        # Restore perturbation_scheduler magnitude (best-effort)
        if self.ctx.has("perturbation_scheduler"):
            with suppress(Exception):
                self.ctx.perturbation_scheduler.default_magnitude = (
                    self.ctx.perturbation_scheduler.default_magnitude * 2.0
                )

        # Compute RecoveryQuality (F1: smoothness over LAST 50 beats)
        quality = self._compute_recovery_quality(beat_no)
        event = self._active_event
        if event is not None:
            event.ended_at_beat = beat_no
            event.quality = quality
            event.quality_finalized = True
            self.history.append(event)
            self.ctx.emit_sync("recovery_event_finalized", event)
            # Notify learner
            efficacy, adopted = self.learner.update(self.history)
            log.info(
                "recovery_exit",
                event_id=event.event_id,
                quality=asdict(quality),
                learner_efficacy=efficacy.value,
                adopted=adopted,
            )

        self._active_event = None
        self._restore_state = {}
        self.state = RecoveryState.BASELINE
        RECOVERY_ACTIVE.set(0)
        self._emit_state_change(beat_no, RecoveryState.BASELINE)

    def _compute_recovery_quality(self, end_beat: int) -> RecoveryQuality:
        """F1: smoothness from the LAST 50 beats of the recovery window."""
        if not self.ctx.has("theta_short") or self._active_event is None:
            return RecoveryQuality()
        engine = self.ctx.get("theta_short")
        history = engine.history()  # [(beat_no, theta), ...]
        if not history:
            return RecoveryQuality()
        event = self._active_event
        # Full recovery window = [started_at_beat, end_beat]
        full_window = [
            (b, t) for b, t in history
            if event.started_at_beat <= b <= end_beat
        ]
        if not full_window:
            return RecoveryQuality()

        # F1: smoothness windowed to the LAST 50 beats only
        smoothness_window = full_window[-50:] if len(full_window) >= 50 else full_window
        sm_thetas = np.array([t for _, t in smoothness_window], dtype=np.float64)
        sm_mean = float(sm_thetas.mean())
        smoothness = (
            max(0.0, 1.0 - float(sm_thetas.std()) / sm_mean) if sm_mean > 1e-6 else 0.0
        )

        # Completeness: end theta vs baseline (using first reading as baseline proxy)
        baseline = float(full_window[0][1])
        end_theta = float(full_window[-1][1])
        if abs(baseline) > 1e-6:
            completeness = max(0.0, 1.0 - abs(end_theta - baseline) / abs(baseline))
        else:
            completeness = 0.0

        composite = 0.4 * smoothness + 0.4 * completeness + 0.2 * 1.0  # durability=1.0 until updated

        return RecoveryQuality(
            smoothness=smoothness,
            completeness=completeness,
            durability=None,  # finalized later when next fragmentation OR 3000-beat watchdog
            composite_score=composite,
            smoothness_window_beats=len(smoothness_window),
        )

    def _emit_state_change(self, beat_no: int, new_state: RecoveryState) -> None:
        self.ctx.emit_sync(
            "recovery_state_change",
            {"beat_no": beat_no, "state": new_state.value},
        )

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "beats_remaining": self._beats_remaining,
            "restore_remaining": self._restore_remaining,
            "test_mode": self.test_mode,
            "active_event": (
                _recovery_event_to_dict(self._active_event)
                if self._active_event is not None
                else None
            ),
            "history": [_recovery_event_to_dict(e) for e in self.history.events],
            "learner": self.learner.to_dict(),
            "rejection_escalator": {
                "consecutive_rejects": self.rejection_escalator.consecutive_rejects,
                "episode_start_beat": self.rejection_escalator.episode_start_beat,
                "last_warning_beat": self.rejection_escalator.last_warning_beat,
            },
        }

    def load_state(self, snapshot: dict[str, Any]) -> None:
        self.state = RecoveryState(snapshot.get("state", "baseline"))
        self._beats_remaining = int(snapshot.get("beats_remaining", 0))
        self._restore_remaining = int(snapshot.get("restore_remaining", 0))
        self.test_mode = bool(snapshot.get("test_mode", False))
        ae = snapshot.get("active_event")
        self._active_event = _recovery_event_from_dict(ae) if ae else None
        self.history.events.clear()
        for d in snapshot.get("history", []):
            self.history.events.append(_recovery_event_from_dict(d))
        self.learner.load_dict(snapshot.get("learner", {}))
        re_state = snapshot.get("rejection_escalator", {})
        self.rejection_escalator.consecutive_rejects = int(re_state.get("consecutive_rejects", 0))
        self.rejection_escalator.episode_start_beat = re_state.get("episode_start_beat")
        self.rejection_escalator.last_warning_beat = re_state.get("last_warning_beat")


__all__ = [
    "PARAM_RANGES",
    "LearnerEfficacy",
    "LearnerParams",
    "RecoveryDecision",
    "RecoveryEvent",
    "RecoveryHistory",
    "RecoveryLearner",
    "RecoveryProtocol",
    "RecoveryQuality",
    "RecoveryRejectionRunWarning",
    "RecoveryRequest",
    "RecoveryState",
    "RejectionEscalator",
]
