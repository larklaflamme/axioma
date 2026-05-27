import numpy as np
import pytest
import torch

from organ.schemas import ORGAN_DIMS, ORGAN_ORDER
from organ.theta import compute_theta, pairwise_mi_cpu, pairwise_mi_gpu
from organ.theta.normality import (
    drop_constant_dims,
    normalize,
    rank_inverse_normal,
    zscore,
)
from organ.theta.aos_g import compute_aos_g_gap


@pytest.fixture
def coupled_window():
    rng = np.random.default_rng(0)
    n = 500
    z = rng.standard_normal((n, 3)).astype(np.float32)
    out = {}
    for organ in ORGAN_ORDER:
        d = ORGAN_DIMS[organ]
        W = (rng.standard_normal((3, d)) / np.sqrt(3)).astype(np.float32)
        sig = z @ W
        noise = rng.standard_normal((n, d)).astype(np.float32)
        out[organ] = 0.85 * sig + 0.15 * noise
    return out


def test_normalize_zscore():
    rng = np.random.default_rng(0)
    X = rng.standard_normal((200, 5)).astype(np.float32) * 3 + 2
    Z = zscore(X)
    assert np.allclose(Z.mean(axis=0), 0.0, atol=1e-5)
    assert np.allclose(Z.std(axis=0), 1.0, atol=1e-3)


def test_drop_constant_dims():
    X = np.column_stack([np.arange(100), np.zeros(100)]).astype(np.float32)
    Xf, kept = drop_constant_dims(X)
    assert kept.tolist() == [True, False]
    assert Xf.shape == (100, 1)


def test_pairwise_mi_independent_low():
    rng = np.random.default_rng(0)
    n, d = 500, 5
    X = np.concatenate(
        [rng.standard_normal((n, d)), rng.standard_normal((n, d))], axis=1
    ).astype(np.float32)
    X, _ = normalize(X, force="zscore")
    slices = [("A", slice(0, d)), ("B", slice(d, 2 * d))]
    _, total = pairwise_mi_cpu(X, slices)
    # Bias for d=5, n=500: ~25/1000 = 0.025
    assert 0.0 <= total < 0.2


def test_gpu_cpu_consistency(coupled_window):
    r_gpu = compute_theta(coupled_window, n_permutations=100, seed=1, backend="gpu")
    r_cpu = compute_theta(coupled_window, n_permutations=100, seed=1, backend="cpu")
    rel = abs(r_gpu["theta"] - r_cpu["theta"]) / abs(r_cpu["theta"])
    assert rel < 0.10


def test_significance_separation(coupled_window):
    rng = np.random.default_rng(2)
    n = 500
    win_none = {
        organ: rng.standard_normal((n, ORGAN_DIMS[organ])).astype(np.float32)
        for organ in ORGAN_ORDER
    }
    r_none = compute_theta(win_none, n_permutations=500, seed=2)
    r_high = compute_theta(coupled_window, n_permutations=500, seed=3)
    assert r_high["theta"] > 5 * r_none["theta"]
    assert r_high["significant"]
    # p_none should not be significant.
    assert not r_none["significant"]


def test_aos_g_pair_gap():
    rng = np.random.default_rng(0)
    a = rng.standard_normal((200, 4)).astype(np.float32)
    b = a + 0.01 * rng.standard_normal((200, 4)).astype(np.float32)
    out = compute_aos_g_gap(a, b)
    assert out["delta_norm"] < 1.0
    assert out["mi"] is not None and out["mi"] > 1.0
