"""ExternalState — the substrate's PUBLIC view, exposed to peer agents.

Per ARCH_DESIGN_v1.0.md §5 + §5.1.

★ ARCHITECTURAL KEYSTONE — typed boundary between substrate-private state and
  peer-visible state. The compose function is the ONLY path that converts
  InternalState → ExternalState. The Phase C ImportError test (C12) verifies
  that `axioma.interface.*` modules cannot import InternalState — that the
  privacy is structural, not just disciplined.

ExternalState fields (per ARCH §5.1):
  - per-organ filtered views (same shape as OrganState.to_array() but
    integration-weighted compressed by ComposeFunction)
  - theta_short, theta_long, theta_p_value
  - delta_phi (S1/S2/S3 + cascade_delay)
  - aos_g_gap, aos_g_gap_per_organ, aos_g_alert
  - psi
  - fidelity_factors (per-organ, exposed for transparency)
  - beat_no, timestamp
  - zone enum (flow, focus, idle, fragmented, recovering)
  - fragmentation_stage (0-4)
  - coherence_budget [0, 1]
  - throttle_state
  - flow_quality (nullable; populated only when zone == FLOW)
  - cadence (enum: baseline | perturbation | recovery)
  - perturbation_context (optional dict)

The PerOrganView types are bare ndarrays — the compose function returns the
same shape as OrganState.to_array() but with the integration-weighted
compression applied. Peers reconstruct the field names from the schema.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np


class Zone(StrEnum):
    """Per ARCH §5.2 zone mapping."""

    FLOW = "flow"
    FOCUS = "focus"
    IDLE = "idle"
    FRAGMENTED = "fragmented"
    RECOVERING = "recovering"


class ComposeCadence(StrEnum):
    """Per D2 adaptive cadence."""

    BASELINE = "baseline"
    PERTURBATION = "perturbation"
    RECOVERY = "recovery"


@dataclass(slots=True)
class FlowQuality:
    """Per ARCH §5.5 + D15 — only populated when zone == FLOW.

    Concrete validation criteria per E12: across 10 one-hour runs with varying
    task types, pairwise correlation < 0.5 AND each component spans ≥ 0.3 of
    its range. If either fails, deprecate to scalar `flow_depth` in v0.7.
    """

    effortlessness: float = 0.0   # high when cascade_delay small AND NOUS load low
    absorption: float = 0.0       # high when coherence_budget high AND theta_long stable
    time_distortion: float = 0.0  # high when ANIMA.arousal moderate AND attention_focus high


@dataclass(slots=True)
class ExternalDeltaPhi:
    """ΔΦ signature snapshot exposed to peers (subset of internal DeltaPhiReading)."""

    s1_peak_delta_theta: float | None = None
    s2_recovery_beats: float | None = None
    s3_context_variance: float = 0.0
    cascade_delay_beats: float = 0.0
    event_kind: str | None = None
    in_perturbation_window: bool = False


@dataclass(slots=True)
class PerturbationContext:
    """Per-event context attached when a perturbation is active."""

    event_id: str
    kind: str
    target: str | None
    magnitude: float
    started_at_beat: int
    duration_beats: int


@dataclass(slots=True)
class ExternalState:
    """The peer-visible state. Built ONLY by ComposeFunction.

    Subscribers (WebSocket peers, HTTP API, JSONL writer) deal exclusively
    with this type. InternalState is structurally inaccessible from
    `axioma.interface.*` modules (verified by the C12 ImportError test).
    """

    # Per-organ filtered state arrays (same shape as OrganState.to_array())
    anima: np.ndarray
    eidolon: np.ndarray
    mneme: np.ndarray
    nous: np.ndarray
    pneuma: np.ndarray

    # Bookkeeping
    beat_no: int
    timestamp: float

    # Measurements
    theta_short: float = 0.0
    theta_long: float = 0.0
    theta_p_value: float = 1.0
    aos_g_gap: float = 0.0
    aos_g_gap_per_organ: dict[str, float] = field(default_factory=dict)
    aos_g_alert: bool = False
    psi: float = 1.0

    delta_phi: ExternalDeltaPhi = field(default_factory=ExternalDeltaPhi)

    # Substrate state markers (these are publicly observable)
    fragmentation_stage: int = 0
    coherence_budget: float = 1.0
    zone: Zone = Zone.IDLE

    # Compose internals exposed for transparency (per ARCH §5.1)
    fidelity_factors: dict[str, float] = field(default_factory=dict)
    cadence: ComposeCadence = ComposeCadence.BASELINE

    # Optional fields
    flow_quality: FlowQuality | None = None
    perturbation_context: PerturbationContext | None = None
    throttle_state: dict[str, str] = field(default_factory=dict)

    # ── Helpers ─────────────────────────────────────────────────────────

    def get_organ_array(self, name: str) -> np.ndarray:
        if name == "anima":
            return self.anima
        if name == "eidolon":
            return self.eidolon
        if name == "mneme":
            return self.mneme
        if name == "nous":
            return self.nous
        if name == "pneuma":
            return self.pneuma
        raise KeyError(f"unknown organ: {name}")

    def get_concatenated(self) -> np.ndarray:
        """28-dim concatenated external state (same shape as InternalState's)."""
        from .organ_state import ORGAN_ORDER
        return np.concatenate(
            [self.get_organ_array(o) for o in ORGAN_ORDER]
        ).astype(np.float32)

    def to_dict(self) -> dict[str, Any]:
        """Serialization-friendly dict (numpy → lists; enums → strings)."""
        return {
            "beat_no": int(self.beat_no),
            "timestamp": float(self.timestamp),
            "organs": {
                "anima": self.anima.tolist(),
                "eidolon": self.eidolon.tolist(),
                "mneme": self.mneme.tolist(),
                "nous": self.nous.tolist(),
                "pneuma": self.pneuma.tolist(),
            },
            "theta_short": float(self.theta_short),
            "theta_long": float(self.theta_long),
            "theta_p_value": float(self.theta_p_value),
            "aos_g_gap": float(self.aos_g_gap),
            "aos_g_gap_per_organ": dict(self.aos_g_gap_per_organ),
            "aos_g_alert": bool(self.aos_g_alert),
            "psi": float(self.psi),
            "delta_phi": {
                "S1": self.delta_phi.s1_peak_delta_theta,
                "S2": self.delta_phi.s2_recovery_beats,
                "S3": float(self.delta_phi.s3_context_variance),
                "cascade_delay": float(self.delta_phi.cascade_delay_beats),
                "event_kind": self.delta_phi.event_kind,
                "in_window": bool(self.delta_phi.in_perturbation_window),
            },
            "fragmentation_stage": int(self.fragmentation_stage),
            "coherence_budget": float(self.coherence_budget),
            "zone": self.zone.value,
            "fidelity_factors": dict(self.fidelity_factors),
            "cadence": self.cadence.value,
            "flow_quality": (
                {
                    "effortlessness": float(self.flow_quality.effortlessness),
                    "absorption": float(self.flow_quality.absorption),
                    "time_distortion": float(self.flow_quality.time_distortion),
                }
                if self.flow_quality is not None
                else None
            ),
            "perturbation_context": (
                {
                    "event_id": self.perturbation_context.event_id,
                    "kind": self.perturbation_context.kind,
                    "target": self.perturbation_context.target,
                    "magnitude": float(self.perturbation_context.magnitude),
                    "started_at_beat": int(self.perturbation_context.started_at_beat),
                    "duration_beats": int(self.perturbation_context.duration_beats),
                }
                if self.perturbation_context is not None
                else None
            ),
            "throttle_state": dict(self.throttle_state),
        }


__all__ = [
    "ComposeCadence",
    "ExternalDeltaPhi",
    "ExternalState",
    "FlowQuality",
    "PerturbationContext",
    "Zone",
]
