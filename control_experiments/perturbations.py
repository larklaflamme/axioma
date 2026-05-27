"""Magnitude-scaled perturbations.

Reuses aos_g_gap perturbation classes but multiplies their INJECT_STRENGTH /
NOISE_SCALE by the magnitude factor. Magnitude 1.0 = original; 0.4 / 0.7 give
weaker variants for the §3.1 ΔΦ Dynamic Range U-curve test.

A separate "no perturbation" handle is exposed for the baseline reference.
"""
from __future__ import annotations

import numpy as np

from aos_g_gap.perturbations import REGISTRY as AOS_REGISTRY
from aos_g_gap.perturbations.base import Perturbation
from aos_g_gap.perturbations.none import NoPerturbation


def build_perturbation(
    type_name: str,
    magnitude: float,
    *,
    trigger_beat: int,
    duration: int,
    seed: int,
) -> Perturbation:
    """Build a perturbation scaled by `magnitude`.

    type_name ∈ {direct_contradiction, surprising_falsehood, nonsense,
    random_perturbation, baseline}.
    magnitude is a multiplicative factor on the perturbation's strength field.
    """
    if type_name == "baseline":
        return NoPerturbation(
            trigger_beat=trigger_beat, duration=duration, seed=seed
        )
    if type_name not in AOS_REGISTRY:
        raise KeyError(f"Unknown perturbation type: {type_name!r}")
    cls = AOS_REGISTRY[type_name]
    p = cls(trigger_beat=trigger_beat, duration=duration, seed=seed)

    # Identify the strength attribute and scale it. INJECT_STRENGTH is on
    # the class; we shadow it on the instance to avoid mutating other trials.
    if hasattr(p, "INJECT_STRENGTH"):
        original = type(p).INJECT_STRENGTH
        p.INJECT_STRENGTH = float(original) * float(magnitude)
    if hasattr(p, "NOISE_SCALE"):
        original = type(p).NOISE_SCALE
        p.NOISE_SCALE = float(original) * float(magnitude)
    return p
