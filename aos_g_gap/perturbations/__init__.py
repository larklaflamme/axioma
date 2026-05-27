"""Perturbation injectors per design §4.2."""
from .base import Perturbation
from .none import NoPerturbation
from .eidolon_contradiction import EidolonContradiction
from .eidolon_falsehood import EidolonFalsehood
from .eidolon_truth import EidolonTruth
from .eidolon_nonsense import EidolonNonsense
from .mneme_disruption import MnemeDisruption
from .random_all import RandomAll


REGISTRY: dict[str, type[Perturbation]] = {
    "baseline": NoPerturbation,
    "direct_contradiction": EidolonContradiction,
    "surprising_falsehood": EidolonFalsehood,
    "surprising_truth": EidolonTruth,
    "nonsense": EidolonNonsense,
    "mneme_disruption": MnemeDisruption,
    "random_perturbation": RandomAll,
}


def build(condition: str, *, trigger_beat: int, duration: int, seed: int) -> Perturbation:
    if condition not in REGISTRY:
        raise KeyError(f"Unknown condition {condition!r}")
    return REGISTRY[condition](trigger_beat=trigger_beat, duration=duration, seed=seed)


__all__ = [
    "Perturbation",
    "NoPerturbation",
    "EidolonContradiction",
    "EidolonFalsehood",
    "EidolonTruth",
    "EidolonNonsense",
    "MnemeDisruption",
    "RandomAll",
    "REGISTRY",
    "build",
]
