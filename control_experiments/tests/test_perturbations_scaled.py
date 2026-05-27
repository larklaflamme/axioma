import numpy as np

from aos_g_gap.perturbations.eidolon_contradiction import EidolonContradiction
from aos_g_gap.perturbations.random_all import RandomAll
from control_experiments.perturbations import build_perturbation


def test_magnitude_scales_inject_strength():
    p1 = build_perturbation("direct_contradiction", magnitude=1.0, trigger_beat=0, duration=10, seed=0)
    p_low = build_perturbation("direct_contradiction", magnitude=0.4, trigger_beat=0, duration=10, seed=0)
    assert p1.INJECT_STRENGTH == EidolonContradiction.INJECT_STRENGTH
    assert p_low.INJECT_STRENGTH == 0.4 * EidolonContradiction.INJECT_STRENGTH


def test_magnitude_scales_noise_scale():
    p1 = build_perturbation("random_perturbation", magnitude=1.0, trigger_beat=0, duration=10, seed=0)
    p_low = build_perturbation("random_perturbation", magnitude=0.4, trigger_beat=0, duration=10, seed=0)
    assert p1.NOISE_SCALE == RandomAll.NOISE_SCALE
    assert p_low.NOISE_SCALE == 0.4 * RandomAll.NOISE_SCALE


def test_baseline_returns_noop():
    from aos_g_gap.perturbations.none import NoPerturbation
    p = build_perturbation("baseline", magnitude=1.0, trigger_beat=0, duration=10, seed=0)
    assert isinstance(p, NoPerturbation)
