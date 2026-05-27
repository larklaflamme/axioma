"""Organ state schemas per REAL_ORGAN_DESIGN.md v0.2 §2.

27 total dimensions across 5 organs. All dataclasses produce a deterministic
float32 array via to_array(); integer dims are stored as int.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, asdict
from typing import ClassVar

import numpy as np

ORGAN_ORDER = ("anima", "eidolon", "mneme", "nous", "pneuma")
ORGAN_DIMS = {"anima": 4, "eidolon": 6, "mneme": 5, "nous": 6, "pneuma": 6}
TOTAL_DIMS = 27

SUMMARY_NAMES = {
    "anima": ("mean_valence", "mean_arousal", "mean_dominance", "mean_mood"),
    "eidolon": (
        "mean_coherence",
        "mean_confidence",
        "mean_narrative_cont",
        "mean_integration_feeling",
    ),
    "mneme": ("mean_wm_load", "mean_retrieval_rate", "mean_episodic_freshness"),
    "nous": (
        "mean_inference_depth",
        "mean_cognitive_load",
        "mean_active_hypotheses",
        "mean_novelty",
    ),
    "pneuma": (
        "mean_integration_level",
        "mean_global_coherence",
        "mean_fragmentation",
        "mean_awareness",
    ),
}
TOTAL_SUMMARIES = sum(len(v) for v in SUMMARY_NAMES.values())
assert TOTAL_SUMMARIES == 19


class OrganState:
    """Base for organ state dataclasses."""

    ORDER: ClassVar[tuple[str, ...]]

    def to_array(self) -> np.ndarray:
        return np.array(
            [getattr(self, name) for name in self.ORDER], dtype=np.float32
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class AnimaState(OrganState):
    valence: float = 0.0
    arousal: float = 0.5
    dominance: float = 0.5
    mood: float = 0.0
    ORDER: ClassVar = ("valence", "arousal", "dominance", "mood")


@dataclass(slots=True)
class EidolonState(OrganState):
    self_coherence: float = 0.5
    confidence: float = 0.5
    narrative_continuity: float = 0.5
    identity_stability: float = 0.5
    meta_uncertainty: float = 0.5
    integration_feeling: float = 0.5
    ORDER: ClassVar = (
        "self_coherence",
        "confidence",
        "narrative_continuity",
        "identity_stability",
        "meta_uncertainty",
        "integration_feeling",
    )


@dataclass(slots=True)
class MnemeState(OrganState):
    wm_load: int = 0
    retrieval_rate: float = 0.5
    decay_rate: float = 0.1
    episodic_freshness: float = 0.5
    semantic_coherence: float = 0.5
    ORDER: ClassVar = (
        "wm_load",
        "retrieval_rate",
        "decay_rate",
        "episodic_freshness",
        "semantic_coherence",
    )


@dataclass(slots=True)
class NousState(OrganState):
    inference_depth: int = 0
    confidence_spread: float = 0.5
    cognitive_load: float = 0.5
    active_hypotheses: int = 0
    novelty: float = 0.5
    epistemic_uncertainty: float = 0.5
    ORDER: ClassVar = (
        "inference_depth",
        "confidence_spread",
        "cognitive_load",
        "active_hypotheses",
        "novelty",
        "epistemic_uncertainty",
    )


@dataclass(slots=True)
class PneumaState(OrganState):
    integration_level: float = 0.5
    global_coherence: float = 0.5
    fragmentation: float = 0.5
    awareness_level: float = 0.5
    attention_focus: float = 0.5
    buffer_depth: int = 0
    ORDER: ClassVar = (
        "integration_level",
        "global_coherence",
        "fragmentation",
        "awareness_level",
        "attention_focus",
        "buffer_depth",
    )


ORGAN_STATE_CLS = {
    "anima": AnimaState,
    "eidolon": EidolonState,
    "mneme": MnemeState,
    "nous": NousState,
    "pneuma": PneumaState,
}


def validate_ranges(organ: str, state: OrganState) -> None:
    """Raise ValueError if any dim is outside the design-spec range."""
    def _check(name: str, val: float, lo: float, hi: float | None) -> None:
        if val < lo or (hi is not None and val > hi):
            raise ValueError(f"{organ}.{name}={val} outside [{lo}, {hi}]")

    if organ == "anima":
        _check("valence", state.valence, -1.0, 1.0)
        _check("arousal", state.arousal, 0.0, 1.0)
        _check("dominance", state.dominance, 0.0, 1.0)
        _check("mood", state.mood, -1.0, 1.0)
    elif organ == "eidolon":
        for f in EidolonState.ORDER:
            _check(f, getattr(state, f), 0.0, 1.0)
    elif organ == "mneme":
        _check("wm_load", state.wm_load, 0, 7)
        _check("retrieval_rate", state.retrieval_rate, 0.0, 1.0)
        _check("decay_rate", state.decay_rate, 0.0, 1.0)
        _check("episodic_freshness", state.episodic_freshness, 0.0, 1.0)
        _check("semantic_coherence", state.semantic_coherence, 0.0, 1.0)
    elif organ == "nous":
        _check("inference_depth", state.inference_depth, 0, None)
        _check("confidence_spread", state.confidence_spread, 0.0, 1.0)
        _check("cognitive_load", state.cognitive_load, 0.0, 1.0)
        _check("active_hypotheses", state.active_hypotheses, 0, 20)
        _check("novelty", state.novelty, 0.0, 1.0)
        _check("epistemic_uncertainty", state.epistemic_uncertainty, 0.0, 1.0)
    elif organ == "pneuma":
        _check("integration_level", state.integration_level, 0.0, 1.0)
        _check("global_coherence", state.global_coherence, 0.0, 1.0)
        _check("fragmentation", state.fragmentation, 0.0, 1.0)
        _check("awareness_level", state.awareness_level, 0.0, 1.0)
        _check("attention_focus", state.attention_focus, 0.0, 1.0)
        _check("buffer_depth", state.buffer_depth, 0, None)
    else:
        raise KeyError(organ)
