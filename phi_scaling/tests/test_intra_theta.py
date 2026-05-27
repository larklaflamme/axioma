import numpy as np
import pytest

from organ.schemas import ORGAN_DIMS
from phi_scaling.intra_theta import compute_intra_organ_theta


def test_independent_halves_yield_low_theta():
    rng = np.random.default_rng(0)
    n = 500
    # PNEUMA has 6 dims; summary selects cols 0,1,2,3 → 4 summary cols total.
    # Build a window where left and right halves are independent.
    win = rng.standard_normal((n, ORGAN_DIMS["pneuma"])).astype(np.float32)
    r = compute_intra_organ_theta(win, "pneuma", n_permutations=200, seed=0)
    assert r["theta"] < 0.1, f"expected low θ for independent halves, got {r['theta']}"


def test_correlated_halves_yield_high_theta():
    rng = np.random.default_rng(0)
    n = 500
    # Force the 4 summary cols to be highly correlated via a shared latent.
    z = rng.standard_normal((n, 1)).astype(np.float32)
    W = rng.standard_normal((1, ORGAN_DIMS["pneuma"])).astype(np.float32)
    win = (z @ W + 0.1 * rng.standard_normal((n, ORGAN_DIMS["pneuma"]))).astype(np.float32)
    r = compute_intra_organ_theta(win, "pneuma", n_permutations=200, seed=0)
    assert r["theta"] > 0.5, f"expected high θ for shared-latent halves, got {r['theta']}"
    assert r["significant"], "expected significance with strong intra-coupling"


def test_constant_window_returns_empty():
    win = np.zeros((100, ORGAN_DIMS["pneuma"]), dtype=np.float32)
    r = compute_intra_organ_theta(win, "pneuma", n_permutations=50, seed=0)
    assert r["theta"] == 0.0
    assert "reason" in r["details"]
