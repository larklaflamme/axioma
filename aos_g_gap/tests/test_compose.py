import numpy as np
import pytest

from aos_g_gap.compose import ComposeFunction
from organ.schemas import ORGAN_DIMS, ORGAN_ORDER


def _internal_arrays(seed: int):
    rng = np.random.default_rng(seed)
    return {o: rng.standard_normal(ORGAN_DIMS[o]).astype(np.float32) for o in ORGAN_ORDER}


def test_identity_at_f_one():
    """If fidelity = 1.0, composed equals internal exactly."""
    cf = ComposeFunction(weights={o: 5.0 for o in ORGAN_ORDER}, noise_factor=0.0, seed=0)
    # weight 5.0 × integ 1 × coh 1 = 5 → clamp via multiplier; the formula yields
    # external = 5*internal + (1-5)*mu; force μ=internal so external == internal.
    internal = _internal_arrays(1)
    for _ in range(50):
        cf.update_rolling(internal)
    # μ = internal (constant). f = 5. compose = 5*internal + (1-5)*internal = internal.
    out = cf.compose(internal, integration_level=1.0, self_coherence=1.0)
    for o in ORGAN_ORDER:
        assert np.allclose(out.external_arrays[o], internal[o], atol=1e-5)


def test_pure_mean_at_f_zero():
    """If fidelity = 0, composed equals running mean (plus tiny noise)."""
    cf = ComposeFunction(noise_factor=0.0, seed=0)
    internal_pile = [_internal_arrays(i) for i in range(60)]
    for inner in internal_pile:
        cf.update_rolling(inner)
    # f = integration_level=0 × ... = 0
    out = cf.compose(internal_pile[-1], integration_level=0.0, self_coherence=1.0)
    for o in ORGAN_ORDER:
        assert np.allclose(out.external_arrays[o], cf.rolling[o].mean, atol=1e-5)


def test_fidelity_monotone_in_integration():
    cf = ComposeFunction(seed=0)
    internal = _internal_arrays(3)
    for _ in range(30):
        cf.update_rolling(internal)
    fs_low = cf.fidelity_factor("eidolon", 0.1, 0.9)
    fs_high = cf.fidelity_factor("eidolon", 0.9, 0.9)
    assert fs_high > fs_low


def test_fidelity_uses_weights():
    cf = ComposeFunction(weights={**{o: 0.20 for o in ORGAN_ORDER}, "eidolon": 0.5}, seed=0)
    f_eid = cf.fidelity_factor("eidolon", 0.5, 0.5)
    f_oth = cf.fidelity_factor("anima", 0.5, 0.5)
    assert f_eid > f_oth


def test_compose_output_shapes():
    cf = ComposeFunction(seed=0)
    internal = _internal_arrays(0)
    cf.update_rolling(internal)
    out = cf.compose(internal, 0.5, 0.5)
    for o in ORGAN_ORDER:
        assert out.external_arrays[o].shape == (ORGAN_DIMS[o],)
    assert set(out.fidelity_factors.keys()) == set(ORGAN_ORDER)
