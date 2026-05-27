"""Typed organ state dataclasses.

Per ARCH_DESIGN_v1.0.md §4.3 (per-organ specs).

State dimensions (the *rendered* observable state, not the latent):
  - ANIMA:   4 dims (valence, arousal, dominance, mood)
  - EIDOLON: 6 dims (self_coherence, confidence, narrative_continuity,
                     identity_stability, meta_uncertainty, integration_feeling)
  - MNEME:   5 dims (wm_load, retrieval_rate, decay_rate, episodic_freshness,
                     semantic_coherence)
  - NOUS:    6 dims (inference_depth, confidence_spread, cognitive_load,
                     active_hypotheses, novelty, epistemic_uncertainty)
  - PNEUMA:  7 dims (integration_level, global_coherence, fragmentation,
                     awareness_level, attention_focus, buffer_depth,
                     coherence_budget)
                     ^^^ NEW in v1.0 (was 6 in v0.2; +1 for coherence_budget per
                         ARCH §4.8)

Total state dims: 28 (was 27 in v0.2).

State value ranges are non-saturating: the rendered value comes from a linear
rescale of an unbounded latent, then clipped at the field's documented range.
The clip is a safety rail; in normal operation the latent stays well inside.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import ClassVar

import numpy as np

ORGAN_ORDER: tuple[str, ...] = ("anima", "eidolon", "mneme", "nous", "pneuma")

ORGAN_STATE_DIMS: dict[str, int] = {
    "anima": 4,
    "eidolon": 6,
    "mneme": 5,
    "nous": 6,
    "pneuma": 7,  # v1.0: +1 for coherence_budget
}
TOTAL_STATE_DIMS = sum(ORGAN_STATE_DIMS.values())
assert TOTAL_STATE_DIMS == 28, TOTAL_STATE_DIMS


class OrganState:
    """Base class for organ state dataclasses.

    Subclasses use @dataclass(slots=True) and declare ORDER (the canonical
    field order for to_array() serialization).
    """

    ORDER: ClassVar[tuple[str, ...]] = ()

    def to_array(self) -> np.ndarray:
        """Return the canonical-order vector as float32. Integer fields cast."""
        return np.array(
            [float(getattr(self, name)) for name in self.ORDER], dtype=np.float32
        )

    def to_dict(self) -> dict[str, float | int]:
        # OrganState subclasses are dataclasses; asdict accepts dataclass instances.
        # The base class isn't, but it's not directly instantiated either.
        return asdict(self)  # type: ignore[call-overload]

    @classmethod
    def field_names(cls) -> tuple[str, ...]:
        return cls.ORDER

    @classmethod
    def from_array(cls, arr: np.ndarray) -> OrganState:
        """Inverse of to_array. Integer fields cast back via annotation lookup.

        Note: dataclass field .type is usually the *string* form of the
        annotation (e.g. 'int', 'float'), not the type itself, when
        `from __future__ import annotations` is in effect. Use
        typing.get_type_hints() to resolve.
        """
        from typing import get_type_hints
        if arr.shape != (len(cls.ORDER),):
            raise ValueError(
                f"{cls.__name__}.from_array expected shape ({len(cls.ORDER)},), "
                f"got {arr.shape}"
            )
        resolved = get_type_hints(cls)
        kwargs: dict[str, float | int] = {}
        for name, value in zip(cls.ORDER, arr, strict=True):
            hint = resolved.get(name, float)
            # round() returns int when given a single arg; cast for type clarity
            kwargs[name] = round(float(value)) if hint is int else float(value)
        return cls(**kwargs)


@dataclass(slots=True)
class AnimaState(OrganState):
    """ANIMA: emotion. Ranges: valence/mood ∈ [-1,1]; arousal/dominance ∈ [0,1]."""

    valence: float = 0.0
    arousal: float = 0.5
    dominance: float = 0.5
    mood: float = 0.0
    ORDER: ClassVar[tuple[str, ...]] = ("valence", "arousal", "dominance", "mood")


@dataclass(slots=True)
class EidolonState(OrganState):
    """EIDOLON: self-model. All fields ∈ [0,1].

    `integration_feeling` is the subjective sense of integration —
    distinct from the computed θ value.
    """

    self_coherence: float = 0.5
    confidence: float = 0.5
    narrative_continuity: float = 0.5
    identity_stability: float = 0.5
    meta_uncertainty: float = 0.5
    integration_feeling: float = 0.5
    ORDER: ClassVar[tuple[str, ...]] = (
        "self_coherence",
        "confidence",
        "narrative_continuity",
        "identity_stability",
        "meta_uncertainty",
        "integration_feeling",
    )


@dataclass(slots=True)
class MnemeState(OrganState):
    """MNEME: memory. wm_load is integer [0,7]; others [0,1]."""

    wm_load: int = 0
    retrieval_rate: float = 0.5
    decay_rate: float = 0.1
    episodic_freshness: float = 0.5
    semantic_coherence: float = 0.5
    ORDER: ClassVar[tuple[str, ...]] = (
        "wm_load",
        "retrieval_rate",
        "decay_rate",
        "episodic_freshness",
        "semantic_coherence",
    )


@dataclass(slots=True)
class NousState(OrganState):
    """NOUS: reasoning. inference_depth/active_hypotheses are integers."""

    inference_depth: int = 0
    confidence_spread: float = 0.5
    cognitive_load: float = 0.5
    active_hypotheses: int = 0
    novelty: float = 0.5
    epistemic_uncertainty: float = 0.5
    ORDER: ClassVar[tuple[str, ...]] = (
        "inference_depth",
        "confidence_spread",
        "cognitive_load",
        "active_hypotheses",
        "novelty",
        "epistemic_uncertainty",
    )


@dataclass(slots=True)
class PneumaState(OrganState):
    """PNEUMA: integration peer (NO integrate() method per ARCH §4.7).

    `coherence_budget` is new in v1.0 (ARCH §4.8) — load signal, [0,1].
    """

    integration_level: float = 0.5
    global_coherence: float = 0.5
    fragmentation: float = 0.5
    awareness_level: float = 0.5
    attention_focus: float = 0.5
    buffer_depth: int = 0
    coherence_budget: float = 1.0  # v1.0 addition
    ORDER: ClassVar[tuple[str, ...]] = (
        "integration_level",
        "global_coherence",
        "fragmentation",
        "awareness_level",
        "attention_focus",
        "buffer_depth",
        "coherence_budget",
    )


ORGAN_STATE_CLS: dict[str, type[OrganState]] = {
    "anima": AnimaState,
    "eidolon": EidolonState,
    "mneme": MnemeState,
    "nous": NousState,
    "pneuma": PneumaState,
}


# ── Range validation ────────────────────────────────────────────────────────

_RANGES: dict[str, dict[str, tuple[float, float | None]]] = {
    "anima": {
        "valence": (-1.0, 1.0),
        "arousal": (0.0, 1.0),
        "dominance": (0.0, 1.0),
        "mood": (-1.0, 1.0),
    },
    "eidolon": {
        "self_coherence": (0.0, 1.0),
        "confidence": (0.0, 1.0),
        "narrative_continuity": (0.0, 1.0),
        "identity_stability": (0.0, 1.0),
        "meta_uncertainty": (0.0, 1.0),
        "integration_feeling": (0.0, 1.0),
    },
    "mneme": {
        "wm_load": (0.0, 7.0),
        "retrieval_rate": (0.0, 1.0),
        "decay_rate": (0.0, 1.0),
        "episodic_freshness": (0.0, 1.0),
        "semantic_coherence": (0.0, 1.0),
    },
    "nous": {
        "inference_depth": (0.0, None),  # unbounded above
        "confidence_spread": (0.0, 1.0),
        "cognitive_load": (0.0, 1.0),
        "active_hypotheses": (0.0, 20.0),
        "novelty": (0.0, 1.0),
        "epistemic_uncertainty": (0.0, 1.0),
    },
    "pneuma": {
        "integration_level": (0.0, 1.0),
        "global_coherence": (0.0, 1.0),
        "fragmentation": (0.0, 1.0),
        "awareness_level": (0.0, 1.0),
        "attention_focus": (0.0, 1.0),
        "buffer_depth": (0.0, None),
        "coherence_budget": (0.0, 1.0),
    },
}


def organ_ranges(organ: str) -> dict[str, tuple[float, float | None]]:
    """Return the documented value ranges for an organ's fields."""
    return _RANGES[organ]


def validate_state(organ: str, state: OrganState) -> None:
    """Raise ValueError if any field is outside its documented range.

    Used as an invariant check (e.g., every beat in test mode). Not in the
    hot path: in production, the render functions clip into range, so
    validation is for development assurance.
    """
    for name, (lo, hi) in _RANGES[organ].items():
        val = float(getattr(state, name))
        if val < lo or (hi is not None and val > hi):
            raise ValueError(
                f"{organ}.{name}={val} outside [{lo}, {hi if hi is not None else '∞'}]"
            )
