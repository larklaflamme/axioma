"""PerturbationScheduler — internal cadence + admin endpoint + event log.

Per ARCH_DESIGN_v1.0.md §6.4 + IMPLEMENTATION_PLAN_v1.0.md §6.1 step 8 (Q3 P14).

Two paths in:
  1. Internal scheduler: every N beats (default 600), round-robin through
     a battery {CONTRADICTION, IMPULSE, STEP}, emit PerturbationEvent.
  2. Admin endpoint: POST /admin/perturb (Phase D) calls inject_now() with
     arbitrary spec — same code path; tagged source="external_admin".

One path out:
  - Emits `perturbation_injected` event on AxiomaContext bus with PerturbationContext.
  - Maintains log of recent events for DeltaPhiEngine's perturbation-relative
    recording and HTTP /perturbations endpoint.

PERTURBATION_SPECS (Q3 v0.3) maps each kind to its substrate-side target,
direction, and duration. The scheduler dispatches to substrate via
apply_perturbation() which directly mutates the targeted organ's render-time
fields (this is the *one* path through which non-substrate code writes to
substrate state — deliberately separated from the measurement layer).
"""
from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np

from ..observability import PERTURBATIONS_TOTAL, get_logger
from ..observability.context import AxiomaContext
from ..persistence.snapshot import Stateful  # noqa: F401
from ..schemas import ORGAN_ORDER, PerturbationContext
from .engine_base import MeasurementEngine

log = get_logger(__name__)


# ── Perturbation kinds ─────────────────────────────────────────────────────


class PerturbationKind(StrEnum):
    """Architecturally-supported perturbation kinds (Q3 v0.3).

    Default battery: {CONTRADICTION, IMPULSE, STEP}.
    Admin-only: {NOVELTY, ATTENTION, NOISE_BURST}.
    """

    CONTRADICTION = "contradiction"  # EIDOLON self_coherence + confidence → negate
    IMPULSE = "impulse"              # shared_drive → spike (unit-vector add)
    STEP = "step"                    # ANIMA valence → offset (sustained N beats)
    NOVELTY = "novelty"              # NOUS.novelty + ANIMA.arousal → spike
    ATTENTION = "attention_shift"    # PNEUMA.attention_focus → offset
    NOISE_BURST = "noise_burst"      # shared_drive → multi-beat Gaussian noise add


@dataclass(frozen=True)
class PerturbationSpec:
    """Per-kind specification (Q3 v0.3 table)."""

    kind: PerturbationKind
    target: str  # 'eidolon' | 'shared_drive' | 'anima' | 'nous_anima' | 'pneuma'
    fields_affected: tuple[str, ...]
    duration_beats: int
    direction: str  # 'negate' | 'spike' | 'offset' | 'noise'


PERTURBATION_SPECS: dict[PerturbationKind, PerturbationSpec] = {
    PerturbationKind.CONTRADICTION: PerturbationSpec(
        kind=PerturbationKind.CONTRADICTION,
        target="eidolon",
        fields_affected=("self_coherence", "confidence"),
        duration_beats=1,
        direction="negate",
    ),
    PerturbationKind.IMPULSE: PerturbationSpec(
        kind=PerturbationKind.IMPULSE,
        target="shared_drive",
        fields_affected=("g",),
        duration_beats=1,
        direction="spike",
    ),
    PerturbationKind.STEP: PerturbationSpec(
        kind=PerturbationKind.STEP,
        target="anima",
        fields_affected=("valence",),
        duration_beats=20,
        direction="offset",
    ),
    PerturbationKind.NOVELTY: PerturbationSpec(
        kind=PerturbationKind.NOVELTY,
        target="nous_anima",
        fields_affected=("nous.novelty", "anima.arousal"),
        duration_beats=5,
        direction="spike",
    ),
    PerturbationKind.ATTENTION: PerturbationSpec(
        kind=PerturbationKind.ATTENTION,
        target="pneuma",
        fields_affected=("attention_focus",),
        duration_beats=10,
        direction="offset",
    ),
    PerturbationKind.NOISE_BURST: PerturbationSpec(
        kind=PerturbationKind.NOISE_BURST,
        target="shared_drive",
        fields_affected=("g",),
        duration_beats=10,
        direction="noise",
    ),
}

DEFAULT_BATTERY: tuple[PerturbationKind, ...] = (
    PerturbationKind.CONTRADICTION,
    PerturbationKind.IMPULSE,
    PerturbationKind.STEP,
)


@dataclass
class PerturbationEvent:
    """Recorded perturbation event for logs + DeltaPhi consumption."""

    event_id: str
    beat_no: int
    source: str  # 'internal_scheduler' | 'external_admin'
    kind: PerturbationKind
    target: str
    magnitude: float
    duration_beats: int
    tag: str | None = None


# ── Application of perturbation to substrate state ─────────────────────────


def apply_perturbation(
    substrate: Any,
    spec: PerturbationSpec,
    magnitude: float,
    *,
    rng: np.random.Generator | None = None,
) -> None:
    """Apply a single-beat perturbation to substrate state.

    For multi-beat perturbations (STEP, NOVELTY, ATTENTION, NOISE_BURST),
    the scheduler invokes apply_perturbation() once per beat of the
    duration window; each call adds magnitude (or noise) once.

    This is the *one* path that directly mutates substrate state from
    outside the substrate's own tick. It is deliberately separated from
    the measurement layer (which is read-only per ARCH §6.8).
    """
    if rng is None:
        rng = np.random.default_rng()

    if spec.target == "shared_drive":
        if spec.direction == "spike":
            # Add magnitude * unit-vector spike. Direction is random per call.
            v = rng.standard_normal(substrate.drive.drive_dim).astype(np.float32)
            v /= max(float(np.linalg.norm(v)), 1e-8)
            substrate.drive.g = substrate.drive.g + magnitude * v
        elif spec.direction == "noise":
            # Multi-beat Gaussian noise burst: each beat adds N(0, magnitude²·I)
            noise = (
                magnitude
                * rng.standard_normal(substrate.drive.drive_dim).astype(np.float32)
            )
            substrate.drive.g = substrate.drive.g + noise
        else:
            log.warning("unknown_drive_direction", direction=spec.direction)
        return

    if spec.target == "nous_anima":
        # Multi-organ spike — both NOUS.novelty and ANIMA.arousal
        substrate.nous.latent[4] = float(substrate.nous.latent[4]) + magnitude  # novelty
        substrate.anima.latent[1] = float(substrate.anima.latent[1]) + magnitude  # arousal
        return

    # Single-organ targets
    if spec.target not in ORGAN_ORDER:
        log.warning("unknown_perturbation_target", target=spec.target)
        return
    organ = substrate.get_organ(spec.target)
    # Map field name to latent dim. The render functions interpret each
    # latent dim as a specific observable field (see substrate/anima.py etc).
    # For simplicity we mutate the latent at the corresponding dim index;
    # the next render then reflects the change.
    field_to_latent_idx = {
        "anima": {"valence": 0, "arousal": 1, "dominance": 2, "mood": 3},
        "eidolon": {
            "self_coherence": 0, "confidence": 1, "narrative_continuity": 2,
            "identity_stability": 3, "meta_uncertainty": 4, "integration_feeling": 5,
        },
        "mneme": {"wm_load": 0, "retrieval_rate": 1, "decay_rate": 2,
                  "episodic_freshness": 3, "semantic_coherence": 4},
        "nous": {"inference_depth": 0, "confidence_spread": 1, "cognitive_load": 2,
                 "active_hypotheses": 3, "novelty": 4, "epistemic_uncertainty": 5},
        "pneuma": {"integration_level": 0, "global_coherence": 1, "fragmentation": 2,
                   "awareness_level": 3, "attention_focus": 4},  # buffer_depth/coherence_budget skipped
    }
    organ_map = field_to_latent_idx.get(spec.target, {})
    for f in spec.fields_affected:
        idx = organ_map.get(f)
        if idx is None or idx >= organ.latent_dim:
            log.warning(
                "perturbation_field_unknown", organ=spec.target, field=f
            )
            continue
        current = float(organ.latent[idx])
        if spec.direction == "negate":
            # Multiply latent by (1 - magnitude) — pulls it toward zero
            new = current * (1.0 - magnitude)
        elif spec.direction == "offset" or spec.direction == "spike":
            new = current + magnitude
        else:
            log.warning("unknown_organ_direction", direction=spec.direction)
            continue
        organ.latent[idx] = new


# ── Scheduler ──────────────────────────────────────────────────────────────


class PerturbationScheduler(MeasurementEngine):
    """Internal cadence + admin hook + event emission.

    Built as a MeasurementEngine for cadence + logging hygiene, even though
    its compute() is a write path to substrate (the one architecturally
    permitted exception per ARCH §6.4). Subscribers see `perturbation_injected`
    events with PerturbationContext payloads.

    Default cadence: internal scheduler injects every `period_beats` beats
    (default 600 = 1 min @ 10 Hz). Pick is round-robin from `battery`.

    External admin can call `inject_now(spec, magnitude, tag)` at any time.
    """

    name = "perturbation_scheduler"
    natural_period_beats = 1  # we check every beat (gated internally)
    schema_version = 1

    def __init__(
        self,
        ctx: AxiomaContext,
        *,
        enabled: bool = True,
        period_beats: int = 600,
        battery: tuple[PerturbationKind, ...] = DEFAULT_BATTERY,
        default_magnitude: float = 0.3,
        history_capacity: int = 200,
        seed: int | None = None,
    ) -> None:
        super().__init__(ctx)
        if period_beats < 10:
            raise ValueError(f"period_beats must be >= 10, got {period_beats}")
        if not battery:
            raise ValueError("battery must be non-empty")
        for kind in battery:
            if kind not in PERTURBATION_SPECS:
                raise ValueError(f"unknown perturbation kind in battery: {kind}")
        self.enabled = enabled
        self.period_beats = period_beats
        self.battery = battery
        self.default_magnitude = default_magnitude
        self.rng = np.random.default_rng(seed)
        # Round-robin pointer
        self._battery_idx = 0
        # In-flight perturbation: tracks multi-beat events
        self._active_event: PerturbationEvent | None = None
        self._active_remaining: int = 0
        # Recent event history (for DeltaPhi consumption + /perturbations endpoint)
        self.history: deque[PerturbationEvent] = deque(maxlen=history_capacity)

    # ── Cadence-driven (called by Heartbeat each beat) ──────────────────

    def compute(self) -> None:
        if not self.ctx.has("substrate"):
            return
        substrate = self.ctx.substrate
        beat_no = substrate.beat_no
        # Continue an in-flight multi-beat perturbation
        if self._active_event is not None and self._active_remaining > 0:
            spec = PERTURBATION_SPECS[self._active_event.kind]
            apply_perturbation(
                substrate, spec, self._active_event.magnitude, rng=self.rng
            )
            self._active_remaining -= 1
            if self._active_remaining <= 0:
                self._active_event = None
            return
        # Otherwise, check internal scheduler cadence
        if not self.enabled:
            return
        if beat_no <= 0 or beat_no % self.period_beats != 0:
            return
        # Time to inject: pick next from battery
        kind = self.battery[self._battery_idx % len(self.battery)]
        self._battery_idx += 1
        self._inject(kind, self.default_magnitude, source="internal_scheduler", tag=None)

    # ── External entry point (admin endpoint hook) ──────────────────────

    def inject_now(
        self,
        kind: PerturbationKind | str,
        magnitude: float | None = None,
        *,
        tag: str | None = None,
        target_override: str | None = None,
    ) -> PerturbationEvent | None:
        """Inject a perturbation immediately. Called by admin endpoint.

        Returns the created PerturbationEvent (or None if substrate not registered).
        """
        if not self.ctx.has("substrate"):
            log.warning("perturbation_no_substrate")
            return None
        if isinstance(kind, str):
            try:
                kind = PerturbationKind(kind)
            except ValueError as e:
                raise ValueError(f"unknown perturbation kind: {kind}") from e
        return self._inject(
            kind,
            magnitude if magnitude is not None else self.default_magnitude,
            source="external_admin",
            tag=tag,
            target_override=target_override,
        )

    # ── Internals ────────────────────────────────────────────────────────

    def _inject(
        self,
        kind: PerturbationKind,
        magnitude: float,
        *,
        source: str,
        tag: str | None,
        target_override: str | None = None,
    ) -> PerturbationEvent:
        substrate = self.ctx.substrate
        spec = PERTURBATION_SPECS[kind]
        target = target_override or spec.target
        event = PerturbationEvent(
            event_id=str(uuid.uuid4()),
            beat_no=substrate.beat_no,
            source=source,
            kind=kind,
            target=target,
            magnitude=magnitude,
            duration_beats=spec.duration_beats,
            tag=tag,
        )
        # Apply first beat now
        apply_perturbation(substrate, spec, magnitude, rng=self.rng)
        # If multi-beat, remember to continue in subsequent calls
        if spec.duration_beats > 1:
            self._active_event = event
            self._active_remaining = spec.duration_beats - 1
        # Record + announce
        self.history.append(event)
        PERTURBATIONS_TOTAL.labels(source=source, kind=kind.value).inc()
        log.info(
            "perturbation_injected",
            event_id=event.event_id,
            beat_no=event.beat_no,
            source=source,
            kind=kind.value,
            target=target,
            magnitude=magnitude,
            duration_beats=spec.duration_beats,
            tag=tag,
        )
        # Emit on the context bus for ΔΦ / CadenceController / JSONL writer
        ctx_payload = PerturbationContext(
            event_id=event.event_id,
            kind=kind.value,
            target=target,
            magnitude=magnitude,
            started_at_beat=event.beat_no,
            duration_beats=spec.duration_beats,
            tag=tag,
        )
        # Synchronous emit (no async needed; subscribers handle their own state)
        self.ctx.emit_sync("perturbation_injected", ctx_payload)
        return event

    # ── Accessors ────────────────────────────────────────────────────────

    def current_value(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "period_beats": self.period_beats,
            "battery": [k.value for k in self.battery],
            "active_event": self._active_event.event_id if self._active_event else None,
            "active_remaining_beats": self._active_remaining,
            "events_in_history": len(self.history),
            "next_battery_kind": self.battery[self._battery_idx % len(self.battery)].value,
        }

    def recent_events(self, n: int | None = None) -> list[PerturbationEvent]:
        events = list(self.history)
        return events[-n:] if n is not None else events

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "period_beats": self.period_beats,
            "battery_idx": self._battery_idx,
            "active_event": (
                {
                    "event_id": self._active_event.event_id,
                    "beat_no": self._active_event.beat_no,
                    "source": self._active_event.source,
                    "kind": self._active_event.kind.value,
                    "target": self._active_event.target,
                    "magnitude": self._active_event.magnitude,
                    "duration_beats": self._active_event.duration_beats,
                    "tag": self._active_event.tag,
                }
                if self._active_event is not None
                else None
            ),
            "active_remaining": self._active_remaining,
            "history": [
                {
                    "event_id": e.event_id, "beat_no": e.beat_no,
                    "source": e.source, "kind": e.kind.value, "target": e.target,
                    "magnitude": e.magnitude, "duration_beats": e.duration_beats,
                    "tag": e.tag,
                }
                for e in self.history
            ],
        }

    def load_state(self, snapshot: dict[str, Any]) -> None:
        self.enabled = bool(snapshot.get("enabled", True))
        self._battery_idx = int(snapshot.get("battery_idx", 0))
        ae = snapshot.get("active_event")
        if ae is not None:
            self._active_event = PerturbationEvent(
                event_id=ae["event_id"], beat_no=int(ae["beat_no"]),
                source=ae["source"], kind=PerturbationKind(ae["kind"]),
                target=ae["target"], magnitude=float(ae["magnitude"]),
                duration_beats=int(ae["duration_beats"]),
                tag=ae.get("tag"),
            )
        else:
            self._active_event = None
        self._active_remaining = int(snapshot.get("active_remaining", 0))
        self.history.clear()
        for e in snapshot.get("history", []):
            self.history.append(
                PerturbationEvent(
                    event_id=e["event_id"], beat_no=int(e["beat_no"]),
                    source=e["source"], kind=PerturbationKind(e["kind"]),
                    target=e["target"], magnitude=float(e["magnitude"]),
                    duration_beats=int(e["duration_beats"]),
                    tag=e.get("tag"),
                )
            )


__all__ = [
    "DEFAULT_BATTERY",
    "PERTURBATION_SPECS",
    "PerturbationEvent",
    "PerturbationKind",
    "PerturbationScheduler",
    "PerturbationSpec",
    "apply_perturbation",
]
