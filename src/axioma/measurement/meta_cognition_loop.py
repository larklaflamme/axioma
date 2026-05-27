"""Meta-cognitive loop — read-only reflection on the measurement layer.

Per ARCH_DESIGN_v1.0.md §6.7 + IMPLEMENTATION_PLAN_v1.0.md §6.1 step 10
(Q4 + F5 + F7 + F8).

Every 100 beats: read 1000-beat θ_long trajectory, 1000-beat ΔΦ history,
200-beat ψ/gap, 1000-beat fragmentation/coherence_budget. Emits a
MetaCognition payload with:
  - integration_trend ∈ {rising, stable, falling}
  - boundary_health_trend ∈ {healthy, watching, concerned}
  - overall_assessment ∈ {nominal, stressed, recovering, exploring, fragmented}
  - confidence (E8 caveat: measures consistency over last 5 emissions, not accuracy)
  - observer_mode ∈ {observer_only, embedded} — F7

Suggestion channel (Q4):
  When threshold conditions hit, emits a MetaCognitionSuggestion via
  AxiomaContext.emit on `meta_cognition_suggestion`. Schema:
    suggested_action, target_parameter, target_value, confidence, rationale, source

F7 observer_mode:
  - observer_only (v1.0 default): loop runs, emits suggestions; RecoveryProtocol
    IGNORES them. SuggestionTracker still records as 'ignored' → F5 escalation
    eventually fires (gives visibility into what meta-cog *would* have done).
  - embedded (v0.7 candidate, reserved): RecoveryProtocol consults suggestions.

F5 SuggestionTracker:
  After 5 consecutive 'ignored' suggestions, emits `meta_cognition_divergence`
  warning on the presence channel + WARN log. Reset after each warning so
  operator sees one per divergence run, not spam.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

import numpy as np

from ..observability import (
    DIVERGENCE_WARNINGS,
    META_COG_PERIOD_BEATS,
    SUGGESTION_DECISIONS,
    get_logger,
)
from ..observability.context import AxiomaContext
from ..persistence.snapshot import Stateful  # noqa: F401
from .engine_base import MeasurementEngine

log = get_logger(__name__)


# ── Public types ──────────────────────────────────────────────────────────


class ObserverMode(StrEnum):
    OBSERVER_ONLY = "observer_only"
    EMBEDDED = "embedded"


class OverallAssessment(StrEnum):
    NOMINAL = "nominal"
    STRESSED = "stressed"
    RECOVERING = "recovering"
    EXPLORING = "exploring"
    FRAGMENTED = "fragmented"


class IntegrationTrend(StrEnum):
    RISING = "rising"
    STABLE = "stable"
    FALLING = "falling"


class BoundaryHealthTrend(StrEnum):
    HEALTHY = "healthy"
    WATCHING = "watching"
    CONCERNED = "concerned"


class SuggestionType(StrEnum):
    REQUEST_RECOVERY = "request_recovery"
    DELAY_RECOVERY = "delay_recovery"
    EXTEND_RECOVERY = "extend_recovery"
    ADJUST_RECOVERY_PARAMETERS = "adjust_recovery_parameters"


# E8 caveat: emitted on every reading
_CONFIDENCE_CAVEAT = (
    "Confidence measures consistency of assessment over the last 5 emissions, "
    "not accuracy. A stable wrong assessment scores high. Accuracy validation "
    "requires ground truth (operator label or subjective report)."
)


@dataclass
class MetaCognition:
    """Per ARCH §6.7.2 + E8 caveat (always emitted) + F7 observer_mode field."""

    beat_no: int = 0
    integration_trend: IntegrationTrend = IntegrationTrend.STABLE
    boundary_health_trend: BoundaryHealthTrend = BoundaryHealthTrend.HEALTHY
    recent_fragmentation_count: int = 0
    recent_recovery_count: int = 0
    overall_assessment: OverallAssessment = OverallAssessment.NOMINAL
    confidence: float = 0.0
    confidence_caveat: str = _CONFIDENCE_CAVEAT
    observer_mode: ObserverMode = ObserverMode.OBSERVER_ONLY
    notes: list[str] = field(default_factory=list)
    valid: bool = False


@dataclass
class MetaCognitionSuggestion:
    """Q4 schema (full 6 fields per IMPLEMENTATION_PLAN §6.7.4)."""

    beat_no: int
    suggested_action: SuggestionType
    target_parameter: str | None
    target_value: float | None
    confidence: float
    rationale: list[str]
    source: Literal["meta_cognition"] = "meta_cognition"


@dataclass
class MetaCognitionDivergenceWarning:
    """F5: emitted when 5 consecutive suggestions are ignored."""

    beat_no: int
    consecutive_ignored: int
    ignored_suggestion_types: list[str]
    ignored_confidence_range: tuple[float, float]
    note: str


# ── SuggestionTracker (F5) ────────────────────────────────────────────────


@dataclass
class _SuggestionDecisionRecord:
    """One record of (suggestion, decision)."""

    beat_no: int
    suggestion: MetaCognitionSuggestion
    decision: Literal["used", "ignored"]


class SuggestionTracker:
    """Tracks meta-cog suggestion decisions. After `consecutive_threshold`
    consecutive ignored, emits a divergence warning.

    Per IMPLEMENTATION_PLAN §6.7.4 F5.
    """

    def __init__(
        self,
        ctx: AxiomaContext,
        *,
        consecutive_threshold: int = 5,
        history_capacity: int = 50,
    ) -> None:
        self.ctx = ctx
        self.consecutive_threshold = consecutive_threshold
        self.recent_decisions: deque[_SuggestionDecisionRecord] = deque(
            maxlen=history_capacity
        )

    def record(
        self,
        suggestion: MetaCognitionSuggestion,
        decision: Literal["used", "ignored"],
    ) -> None:
        self.recent_decisions.append(
            _SuggestionDecisionRecord(
                beat_no=suggestion.beat_no,
                suggestion=suggestion,
                decision=decision,
            )
        )
        SUGGESTION_DECISIONS.labels(decision=decision).inc()
        # Check for 5 consecutive ignored
        if len(self.recent_decisions) >= self.consecutive_threshold:
            last_n = list(self.recent_decisions)[-self.consecutive_threshold :]
            if all(d.decision == "ignored" for d in last_n):
                self._emit_warning(last_n)
                # Per F5: clear so we don't spam (next warning needs fresh 5-in-a-row)
                self.recent_decisions.clear()

    def _emit_warning(self, ignored_run: list[_SuggestionDecisionRecord]) -> None:
        confidences = [d.suggestion.confidence for d in ignored_run]
        warning = MetaCognitionDivergenceWarning(
            beat_no=ignored_run[-1].beat_no,
            consecutive_ignored=self.consecutive_threshold,
            ignored_suggestion_types=[d.suggestion.suggested_action.value for d in ignored_run],
            ignored_confidence_range=(float(min(confidences)), float(max(confidences))),
            note=(
                "Meta-cognitive loop's last 5 suggestions were ignored. "
                "May indicate: (a) meta-cog suggestions systematically wrong; "
                "(b) recovery protocol reject logic too aggressive; "
                "(c) confidence threshold (0.7) too high. Operator review recommended."
            ),
        )
        # Emit on presence channel (operator-facing)
        self.ctx.emit_sync("presence", warning)
        self.ctx.emit_sync("meta_cognition_divergence", warning)
        DIVERGENCE_WARNINGS.inc()
        log.warning(
            "meta_cognition_divergence",
            consecutive_ignored=warning.consecutive_ignored,
            types=warning.ignored_suggestion_types,
            confidence_range=warning.ignored_confidence_range,
        )

    def save_state(self) -> dict[str, Any]:
        return {
            "recent_decisions": [
                {
                    "beat_no": d.beat_no,
                    "decision": d.decision,
                    "suggestion": {
                        "beat_no": d.suggestion.beat_no,
                        "suggested_action": d.suggestion.suggested_action.value,
                        "target_parameter": d.suggestion.target_parameter,
                        "target_value": d.suggestion.target_value,
                        "confidence": d.suggestion.confidence,
                        "rationale": d.suggestion.rationale,
                        "source": d.suggestion.source,
                    },
                }
                for d in self.recent_decisions
            ],
        }

    def load_state(self, snap: dict[str, Any]) -> None:
        self.recent_decisions.clear()
        for d in snap.get("recent_decisions", []):
            s = d["suggestion"]
            self.recent_decisions.append(
                _SuggestionDecisionRecord(
                    beat_no=int(d["beat_no"]),
                    decision=d["decision"],
                    suggestion=MetaCognitionSuggestion(
                        beat_no=int(s["beat_no"]),
                        suggested_action=SuggestionType(s["suggested_action"]),
                        target_parameter=s.get("target_parameter"),
                        target_value=s.get("target_value"),
                        confidence=float(s["confidence"]),
                        rationale=list(s.get("rationale", [])),
                        source=s.get("source", "meta_cognition"),
                    ),
                )
            )


# ── Main loop ─────────────────────────────────────────────────────────────


class MetaCognitionLoop(MeasurementEngine):
    """Reads measurement output every 100 beats; emits MetaCognition + optionally
    Suggestions.

    Read-only on measurement (and on substrate, transitively). Does NOT mutate
    any other engine's state. Suggestions go out on the event bus and are
    consumed by RecoveryProtocol (or ignored, per F7 observer_mode).
    """

    name = "meta_cognition"
    natural_period_beats = 100
    schema_version = 1

    def __init__(
        self,
        ctx: AxiomaContext,
        *,
        observer_mode: ObserverMode = ObserverMode.OBSERVER_ONLY,
        trajectory_window: int = 1000,
        suggestion_confidence_threshold: float = 0.7,
        suggestion_tracker: SuggestionTracker | None = None,
        history_capacity: int = 200,
    ) -> None:
        super().__init__(ctx)
        self.observer_mode = observer_mode
        self.trajectory_window = trajectory_window
        self.suggestion_confidence_threshold = suggestion_confidence_threshold
        self.suggestion_tracker = suggestion_tracker or SuggestionTracker(ctx)
        # Recent emissions (for F8 confidence-as-consistency)
        self._recent_emissions: deque[OverallAssessment] = deque(maxlen=5)
        self._current = MetaCognition(observer_mode=observer_mode)
        self.history: deque[MetaCognition] = deque(maxlen=history_capacity)
        META_COG_PERIOD_BEATS.set(self.natural_period_beats)

    # ── Compute (per natural cadence) ────────────────────────────────────

    def compute(self) -> None:
        beat_no = self._current_beat()
        if beat_no <= 0:
            return

        # Read measurement state
        theta_long_history = self._safe_history("theta_long")
        delta_phi_history = self._safe_history("delta_phi", attr_name="recent_history")
        psi_history = self._safe_history("aos_g", attr_name="recent_history")
        frag_history = self._safe_history("fragmentation_monitor", attr_name="recent_history")
        recovery = self.ctx.get("recovery_protocol") if self.ctx.has("recovery_protocol") else None

        # 1. integration_trend
        integration_trend = self._compute_integration_trend(theta_long_history)
        # 2. boundary_health_trend
        boundary_health_trend = self._compute_boundary_health_trend(psi_history)
        # 3. recent counts (last 1000 beats)
        cutoff = beat_no - self.trajectory_window
        recent_fragmentation_count = sum(
            1 for r in frag_history if r.beat_no >= cutoff and r.current_stage >= 2
        )
        recent_recovery_count = (
            sum(1 for e in recovery.history.events if e.started_at_beat >= cutoff)
            if recovery is not None else 0
        )
        # 4. overall_assessment
        coh_budget = self._current_coherence_budget()
        in_recovery = (
            recovery is not None
            and recovery.state.value != "baseline"
        )
        current_stage = (
            self.ctx.fragmentation_monitor.current_value().current_stage
            if self.ctx.has("fragmentation_monitor") else 0
        )
        s3_recent = (
            float(delta_phi_history[-1].s3_context_variance)
            if delta_phi_history and delta_phi_history[-1].s3_context_variance is not None
            else 0.0
        )
        assessment = self._classify(
            in_recovery=in_recovery,
            current_stage=current_stage,
            coh_budget=coh_budget,
            recent_recovery_count=recent_recovery_count,
            s3_context_variance=s3_recent,
        )
        # 5. confidence (E8: consistency over last 5 emissions)
        self._recent_emissions.append(assessment)
        confidence = self._compute_confidence(self._recent_emissions)
        # 6. notes
        notes = self._compose_notes(
            theta_long_history, delta_phi_history, psi_history,
            integration_trend, boundary_health_trend
        )
        # 7. emit
        reading = MetaCognition(
            beat_no=beat_no,
            integration_trend=integration_trend,
            boundary_health_trend=boundary_health_trend,
            recent_fragmentation_count=recent_fragmentation_count,
            recent_recovery_count=recent_recovery_count,
            overall_assessment=assessment,
            confidence=confidence,
            observer_mode=self.observer_mode,
            notes=notes,
            valid=True,
        )
        self._current = reading
        self.history.append(reading)
        self.ctx.emit_sync("meta_cognition", reading)
        log.info(
            "meta_cognition_emit",
            beat_no=beat_no,
            assessment=assessment.value,
            confidence=confidence,
            observer_mode=self.observer_mode.value,
        )

        # 8. Maybe emit a suggestion
        suggestion = self._maybe_emit_suggestion(
            beat_no=beat_no,
            assessment=assessment,
            current_stage=current_stage,
            in_recovery=in_recovery,
            coh_budget=coh_budget,
            confidence=confidence,
        )
        if suggestion is not None:
            # In observer_only, RecoveryProtocol IGNORES suggestions per F7.
            # We always record the decision regardless of mode; F5 escalation
            # gives the operator visibility either way.
            decision: Literal["used", "ignored"] = (
                "used" if self.observer_mode == ObserverMode.EMBEDDED else "ignored"
            )
            self.suggestion_tracker.record(suggestion, decision)
            self.ctx.emit_sync("meta_cognition_suggestion", suggestion)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _current_beat(self) -> int:
        if self.ctx.has("substrate"):
            return int(self.ctx.substrate.beat_no)
        if self.ctx.has("heartbeat"):
            return int(self.ctx.heartbeat.beat_no)
        return 0

    def _current_coherence_budget(self) -> float:
        if not self.ctx.has("substrate"):
            return 1.0
        try:
            return float(self.ctx.substrate.pneuma.render().coherence_budget)
        except Exception:
            return 1.0

    def _safe_history(self, engine_name: str, *, attr_name: str = "history") -> list[Any]:
        if not self.ctx.has(engine_name):
            return []
        eng = self.ctx.get(engine_name)
        try:
            fn = getattr(eng, attr_name)
            return list(fn() if callable(fn) else fn)
        except Exception:
            return []

    def _compute_integration_trend(self, theta_history: list[Any]) -> IntegrationTrend:
        if not theta_history or len(theta_history) < 6:
            return IntegrationTrend.STABLE
        # theta_history items are (beat_no, theta) tuples
        thetas = [t for _, t in theta_history[-20:]]
        if len(thetas) < 6:
            return IntegrationTrend.STABLE
        first_third = float(np.mean(thetas[: len(thetas) // 3]))
        last_third = float(np.mean(thetas[-len(thetas) // 3 :]))
        rel_diff = (last_third - first_third) / max(abs(first_third), 1e-6)
        if rel_diff > 0.05:
            return IntegrationTrend.RISING
        if rel_diff < -0.05:
            return IntegrationTrend.FALLING
        return IntegrationTrend.STABLE

    def _compute_boundary_health_trend(self, psi_history: list[Any]) -> BoundaryHealthTrend:
        if not psi_history:
            return BoundaryHealthTrend.HEALTHY
        recent_psi = [r.psi for r in psi_history[-10:] if hasattr(r, "psi")]
        if not recent_psi:
            return BoundaryHealthTrend.HEALTHY
        mean_psi = float(np.mean(recent_psi))
        if mean_psi >= 0.7:
            return BoundaryHealthTrend.HEALTHY
        if mean_psi >= 0.3:
            return BoundaryHealthTrend.WATCHING
        return BoundaryHealthTrend.CONCERNED

    def _classify(
        self,
        *,
        in_recovery: bool,
        current_stage: int,
        coh_budget: float,
        recent_recovery_count: int,
        s3_context_variance: float,
    ) -> OverallAssessment:
        # Per ARCH §6.7.2 priority order
        if current_stage >= 3:
            return OverallAssessment.FRAGMENTED
        if in_recovery or recent_recovery_count > 0:
            return OverallAssessment.RECOVERING
        if coh_budget < 0.3:
            return OverallAssessment.STRESSED
        if s3_context_variance > 0.7:
            return OverallAssessment.EXPLORING
        return OverallAssessment.NOMINAL

    def _compute_confidence(self, recent: deque[OverallAssessment]) -> float:
        """E8: consistency over last 5 emissions. 1.0 = all the same; 0 = all
        different. NOT a measure of accuracy."""
        if len(recent) < 2:
            return 0.0
        # Fraction of pairs that agree with the most common
        from collections import Counter
        counts = Counter(recent)
        modal_count = max(counts.values())
        return modal_count / len(recent)

    def _compose_notes(
        self,
        theta_history: list[Any],
        delta_phi_history: list[Any],
        psi_history: list[Any],
        integration_trend: IntegrationTrend,
        boundary_health_trend: BoundaryHealthTrend,
    ) -> list[str]:
        notes: list[str] = []
        if theta_history:
            theta_recent = [t for _, t in theta_history[-10:]]
            if theta_recent:
                notes.append(
                    f"θ_long recent mean = {float(np.mean(theta_recent)):.3f} "
                    f"({integration_trend.value})"
                )
        if delta_phi_history:
            last = delta_phi_history[-1]
            if hasattr(last, "s3_context_variance"):
                notes.append(f"ΔΦ.S3 = {last.s3_context_variance:.4f}")
        if psi_history:
            psi_recent = [r.psi for r in psi_history[-10:] if hasattr(r, "psi")]
            if psi_recent:
                notes.append(
                    f"ψ recent mean = {float(np.mean(psi_recent)):.3f} "
                    f"({boundary_health_trend.value})"
                )
        return notes

    def _maybe_emit_suggestion(
        self,
        *,
        beat_no: int,
        assessment: OverallAssessment,
        current_stage: int,
        in_recovery: bool,
        coh_budget: float,
        confidence: float,
    ) -> MetaCognitionSuggestion | None:
        """Emit a suggestion only when meta-cog has high confidence AND a clear
        condition is met."""
        # Only suggest when reasonably confident; F5 still records all decisions
        if confidence < self.suggestion_confidence_threshold:
            return None
        if current_stage >= 2 and not in_recovery:
            return MetaCognitionSuggestion(
                beat_no=beat_no,
                suggested_action=SuggestionType.REQUEST_RECOVERY,
                target_parameter=None,
                target_value=None,
                confidence=confidence,
                rationale=[f"current_stage={current_stage} but no active recovery"],
            )
        if assessment == OverallAssessment.STRESSED:
            return MetaCognitionSuggestion(
                beat_no=beat_no,
                suggested_action=SuggestionType.ADJUST_RECOVERY_PARAMETERS,
                target_parameter="coupling_reduction_factor",
                target_value=0.7,  # more aggressive reduction
                confidence=confidence,
                rationale=[f"coh_budget={coh_budget:.2f} below stress threshold"],
            )
        return None

    # ── Accessors ────────────────────────────────────────────────────────

    def current_value(self) -> MetaCognition:
        return self._current

    def recent_history(self, n: int | None = None) -> list[MetaCognition]:
        h = list(self.history)
        return h[-n:] if n is not None else h

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "observer_mode": self.observer_mode.value,
            "recent_emissions": [a.value for a in self._recent_emissions],
            "suggestion_tracker": self.suggestion_tracker.save_state(),
            "current": {
                "beat_no": self._current.beat_no,
                "integration_trend": self._current.integration_trend.value,
                "boundary_health_trend": self._current.boundary_health_trend.value,
                "recent_fragmentation_count": self._current.recent_fragmentation_count,
                "recent_recovery_count": self._current.recent_recovery_count,
                "overall_assessment": self._current.overall_assessment.value,
                "confidence": self._current.confidence,
                "observer_mode": self._current.observer_mode.value,
                "notes": self._current.notes,
                "valid": self._current.valid,
            },
        }

    def load_state(self, snap: dict[str, Any]) -> None:
        self.observer_mode = ObserverMode(snap.get("observer_mode", "observer_only"))
        self._recent_emissions = deque(
            (OverallAssessment(v) for v in snap.get("recent_emissions", [])),
            maxlen=5,
        )
        self.suggestion_tracker.load_state(snap.get("suggestion_tracker", {}))
        cur = snap.get("current", {})
        self._current = MetaCognition(
            beat_no=int(cur.get("beat_no", 0)),
            integration_trend=IntegrationTrend(cur.get("integration_trend", "stable")),
            boundary_health_trend=BoundaryHealthTrend(cur.get("boundary_health_trend", "healthy")),
            recent_fragmentation_count=int(cur.get("recent_fragmentation_count", 0)),
            recent_recovery_count=int(cur.get("recent_recovery_count", 0)),
            overall_assessment=OverallAssessment(cur.get("overall_assessment", "nominal")),
            confidence=float(cur.get("confidence", 0.0)),
            observer_mode=ObserverMode(cur.get("observer_mode", "observer_only")),
            notes=list(cur.get("notes", [])),
            valid=bool(cur.get("valid", False)),
        )


__all__ = [
    "BoundaryHealthTrend",
    "IntegrationTrend",
    "MetaCognition",
    "MetaCognitionDivergenceWarning",
    "MetaCognitionLoop",
    "MetaCognitionSuggestion",
    "ObserverMode",
    "OverallAssessment",
    "SuggestionTracker",
    "SuggestionType",
]
