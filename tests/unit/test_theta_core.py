"""Vendored θ primitives: summaries, normalization, pairwise MI."""
from __future__ import annotations

import numpy as np
import pytest
import torch

from axioma.measurement.theta_core import (
    SUMMARY_DIMS,
    SUMMARY_INDICES,
    TOTAL_SUMMARY_DIMS,
    compute_theta_from_summary,
    concat_summary_window,
    drop_constant_dims,
    make_block_slices,
    normalize,
    pairwise_mi_cpu,
    pairwise_mi_gpu,
    rank_inverse_normal,
    select_summary_columns,
    shapiro_normal,
    zscore,
)
from axioma.schemas import ORGAN_ORDER


def test_summary_dims_sum_to_19() -> None:
    assert TOTAL_SUMMARY_DIMS == 19
    assert sum(SUMMARY_DIMS.values()) == 19


def test_summary_indices_within_state_dims() -> None:
    """Each summary index must be within its organ's state_dim."""
    from axioma.schemas import ORGAN_STATE_DIMS
    for organ, idxs in SUMMARY_INDICES.items():
        for i in idxs:
            assert 0 <= i < ORGAN_STATE_DIMS[organ], f"{organ} index {i} out of range"


def test_select_summary_columns_shape() -> None:
    # 100-beat ANIMA window of shape (100, 4)
    window = np.random.randn(100, 4).astype(np.float32)
    s = select_summary_columns("anima", window)
    assert s.shape == (100, 4)  # all 4 ANIMA dims are summaries


def test_select_summary_columns_picks_right_indices() -> None:
    # NOUS summary indices are (0, 2, 3, 4); make column 1 distinctive
    window = np.tile(np.arange(6, dtype=np.float32), (10, 1))
    s = select_summary_columns("nous", window)
    # Should pick cols 0, 2, 3, 4 — value [0,2,3,4]
    assert s.shape == (10, 4)
    np.testing.assert_allclose(s[0], [0, 2, 3, 4])


def test_concat_summary_window_shape() -> None:
    # Fake (n, D_organ) per-organ windows
    n = 50
    from axioma.schemas import ORGAN_STATE_DIMS
    states = {
        o: np.random.randn(n, ORGAN_STATE_DIMS[o]).astype(np.float32)
        for o in ORGAN_ORDER
    }
    concat = concat_summary_window(states)
    assert concat.shape == (n, 19)


def test_concat_summary_window_accepts_preselected() -> None:
    """If blocks are already summary-shape, concat doesn't re-select."""
    n = 50
    states = {
        o: np.random.randn(n, SUMMARY_DIMS[o]).astype(np.float32)
        for o in ORGAN_ORDER
    }
    concat = concat_summary_window(states)
    assert concat.shape == (n, 19)


def test_drop_constant_dims_removes_constants() -> None:
    X = np.random.randn(50, 5).astype(np.float32)
    X[:, 2] = 5.0  # constant column
    filtered, kept = drop_constant_dims(X)
    assert filtered.shape == (50, 4)
    assert not kept[2]
    assert all(kept[i] for i in (0, 1, 3, 4))


def test_zscore() -> None:
    """zscore divides by population std (ddof=0); standardized data has
    mean 0 and population-std 1 as a result."""
    X = np.array([[0.0, 10.0], [2.0, 12.0], [4.0, 14.0]], dtype=np.float32)
    Z = zscore(X)
    np.testing.assert_allclose(Z.mean(axis=0), [0, 0], atol=1e-6)
    # After zscore, std (ddof=0) = 1.0 by construction
    np.testing.assert_allclose(Z.std(axis=0), [1.0, 1.0], atol=1e-3)


def test_rank_inverse_normal_makes_normal() -> None:
    """RINT of any monotone-mapped data should produce ~standard normal."""
    rng = np.random.default_rng(0)
    # Heavy-tailed input
    X = rng.standard_t(df=3, size=(1000, 2)).astype(np.float32)
    Y_rint = rank_inverse_normal(X)
    # Should be approximately standard normal
    np.testing.assert_allclose(Y_rint.mean(axis=0), [0, 0], atol=0.05)
    np.testing.assert_allclose(Y_rint.std(axis=0), [1, 1], atol=0.05)


def test_shapiro_normal_on_gaussian() -> None:
    rng = np.random.default_rng(0)
    X = rng.standard_normal((100, 3)).astype(np.float32)
    assert shapiro_normal(X) is True


def test_shapiro_normal_on_heavy_tail() -> None:
    rng = np.random.default_rng(0)
    X = rng.standard_t(df=2, size=(100, 3)).astype(np.float32)
    assert shapiro_normal(X) is False


def test_normalize_uses_zscore_on_normal_data() -> None:
    rng = np.random.default_rng(0)
    X = rng.standard_normal((100, 3)).astype(np.float32)
    _, method = normalize(X)
    assert method == "zscore"


def test_normalize_falls_back_to_rint_on_nonnormal() -> None:
    rng = np.random.default_rng(0)
    X = rng.standard_t(df=2, size=(100, 3)).astype(np.float32)
    _, method = normalize(X)
    assert method == "rint"


def test_normalize_force_works() -> None:
    rng = np.random.default_rng(0)
    X = rng.standard_normal((100, 3)).astype(np.float32)
    _, m = normalize(X, force="rint")
    assert m == "rint"
    _, m = normalize(X, force="zscore")
    assert m == "zscore"


def test_pairwise_mi_cpu_independent_data_near_zero() -> None:
    """For independent blocks, MI should be near zero."""
    rng = np.random.default_rng(0)
    n = 500
    X = rng.standard_normal((n, 4)).astype(np.float32)
    X = zscore(X)  # standardize
    block_slices = [("a", slice(0, 2)), ("b", slice(2, 4))]
    mis, total = pairwise_mi_cpu(X, block_slices)
    assert ("a", "b") in mis
    assert total < 0.05  # small for independent data


def test_pairwise_mi_cpu_correlated_data_nonzero() -> None:
    """Block A and B share signal → MI > 0."""
    rng = np.random.default_rng(0)
    n = 500
    shared = rng.standard_normal(n).astype(np.float32)
    A = np.stack([shared + 0.1 * rng.standard_normal(n).astype(np.float32),
                  rng.standard_normal(n).astype(np.float32)], axis=1)
    B = np.stack([shared + 0.1 * rng.standard_normal(n).astype(np.float32),
                  rng.standard_normal(n).astype(np.float32)], axis=1)
    X = np.concatenate([A, B], axis=1)
    X = zscore(X)
    block_slices = [("a", slice(0, 2)), ("b", slice(2, 4))]
    _, total = pairwise_mi_cpu(X, block_slices)
    assert total > 0.5


def test_pairwise_mi_gpu_matches_cpu() -> None:
    """GPU and CPU should agree on the same data."""
    rng = np.random.default_rng(0)
    n = 200
    X = zscore(rng.standard_normal((n, 6)).astype(np.float32))
    block_slices = [("a", slice(0, 3)), ("b", slice(3, 6))]
    cpu_mis, cpu_total = pairwise_mi_cpu(X, block_slices)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    Xt = torch.from_numpy(X).to(device)
    gpu_mis, gpu_total = pairwise_mi_gpu(Xt, block_slices)
    assert abs(cpu_total - gpu_total) < 1e-4
    for k in cpu_mis:
        assert abs(cpu_mis[k] - gpu_mis[k]) < 1e-4


def test_make_block_slices_handles_dropped_organs() -> None:
    """A constant-dim organ should be dropped from block_slices."""
    # ANIMA (4 dims) all constants → mask[:4] = False; others True
    mask = np.array([False, False, False, False] + [True] * 15)
    slices = make_block_slices(mask)
    organs_present = [name for name, _ in slices]
    assert "anima" not in organs_present
    assert all(o in organs_present for o in ("eidolon", "mneme", "nous", "pneuma"))


def test_compute_theta_from_summary_smoke() -> None:
    """Smoke test on a fake (100, 19) summary matrix."""
    rng = np.random.default_rng(0)
    X = rng.standard_normal((100, 19)).astype(np.float32)
    result = compute_theta_from_summary(X, n_permutations=20, backend="cpu")
    assert isinstance(result["theta"], float)
    assert 0.0 <= result["p_value"] <= 1.0
    assert result["details"]["n_blocks"] == 5


def test_compute_theta_short_window_raises() -> None:
    X = np.random.randn(2, 19).astype(np.float32)
    with pytest.raises(ValueError, match="too short"):
        compute_theta_from_summary(X, n_permutations=5, backend="cpu")


def test_compute_theta_wrong_dims_raises() -> None:
    X = np.random.randn(100, 18).astype(np.float32)
    with pytest.raises(ValueError, match="cols"):
        compute_theta_from_summary(X, n_permutations=5, backend="cpu")
