"""§8.1 synthetic data validation suite.

Five tests:
  1. Known MI recovery: Gaussian copula recovers ≥ 50% of true MI at d<10.
  2. Integration discrimination: θ(high) > θ(none) by ≥ 5×.
  3. Permutation test: θ(none) → p > 0.05; θ(high) → p < 0.01.
  4. Null distribution: 95th percentile of null < 0.01 for d=19, n=500.
  5. GPU/CPU consistency: θ values agree within 10%.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .config import N_PERMUTATIONS
from .schemas import ORGAN_DIMS, ORGAN_ORDER
from .measurement.summaries import SUMMARY_DIMS
from .theta import compute_theta, pairwise_mi_cpu, pairwise_mi_gpu
from .theta.normality import normalize, drop_constant_dims


def generate_known_mi_data(
    n: int, d: int, mi_target: float, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    """Per §8.3 — paired X, Y with target MI in d dims.

    True MI = -d/2 · log(1 - ρ²), so ρ² = 1 - exp(-2·mi_target/d).
    """
    rho_sq = 1.0 - np.exp(-2.0 * mi_target / d)
    rho = float(np.sqrt(max(rho_sq, 0.0)))
    X = rng.standard_normal((n, d)).astype(np.float32)
    Y = (rho * X + np.sqrt(1 - rho**2) * rng.standard_normal((n, d))).astype(np.float32)
    return X, Y


def _organ_window_from_latent(
    n: int, coupling: float, rng: np.random.Generator
) -> dict[str, np.ndarray]:
    """Build organ-shaped windows with shared latent coupling."""
    z = rng.standard_normal((n, 3)).astype(np.float32)
    out = {}
    for organ in ORGAN_ORDER:
        d = ORGAN_DIMS[organ]
        W = (rng.standard_normal((3, d)) / np.sqrt(3)).astype(np.float32)
        signal = z @ W
        noise = rng.standard_normal((n, d)).astype(np.float32)
        out[organ] = coupling * signal + (1.0 - coupling) * noise
    return out


def test_known_mi_recovery(
    n: int = 500, d: int = 5, mi_target: float = 1.0, seed: int = 0
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    X, Y = generate_known_mi_data(n, d, mi_target, rng)
    Z = np.concatenate([X, Y], axis=1)
    Z_norm, _ = normalize(Z, force="zscore")
    Z_norm, _ = drop_constant_dims(Z_norm)
    slices = [("X", slice(0, d)), ("Y", slice(d, 2 * d))]
    _, total_mi = pairwise_mi_cpu(Z_norm, slices)
    recovery = total_mi / mi_target if mi_target > 0 else 0.0
    return {
        "test": "known_mi_recovery",
        "n": n,
        "d": d,
        "mi_target": float(mi_target),
        "mi_estimated": float(total_mi),
        "recovery_fraction": float(recovery),
        "criterion": "recovery >= 0.5",
        "passed": bool(recovery >= 0.5),
    }


def test_integration_discrimination(
    n_perm: int = N_PERMUTATIONS, seed: int = 42
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    win_none = _organ_window_from_latent(500, 0.0, rng)
    win_high = _organ_window_from_latent(500, 0.95, rng)
    r_none = compute_theta(win_none, n_permutations=n_perm, seed=seed)
    r_high = compute_theta(win_high, n_permutations=n_perm, seed=seed + 1)
    ratio = r_high["theta"] / max(r_none["theta"], 1e-10)
    return {
        "test": "integration_discrimination",
        "theta_none": float(r_none["theta"]),
        "theta_high": float(r_high["theta"]),
        "ratio": float(ratio),
        "p_none": float(r_none["p_value"]),
        "p_high": float(r_high["p_value"]),
        "method_none": r_none["method"],
        "method_high": r_high["method"],
        "criterion": "ratio >= 5",
        "passed": bool(ratio >= 5.0),
    }


def test_permutation_significance(
    n_perm: int = N_PERMUTATIONS, seed: int = 42
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    win_none = _organ_window_from_latent(500, 0.0, rng)
    win_high = _organ_window_from_latent(500, 0.95, rng)
    r_none = compute_theta(win_none, n_permutations=n_perm, seed=seed)
    r_high = compute_theta(win_high, n_permutations=n_perm, seed=seed + 1)
    none_ok = r_none["p_value"] > 0.05
    high_ok = r_high["p_value"] < 0.01
    return {
        "test": "permutation_test",
        "p_none": float(r_none["p_value"]),
        "p_high": float(r_high["p_value"]),
        "criterion_none": "p > 0.05",
        "criterion_high": "p < 0.01",
        "passed": bool(none_ok and high_ok),
    }


def test_null_distribution(
    n_perm: int = N_PERMUTATIONS, seed: int = 42
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    win_none = _organ_window_from_latent(500, 0.0, rng)
    r = compute_theta(win_none, n_permutations=n_perm, seed=seed)
    return {
        "test": "null_distribution",
        "null_95th": float(r["null_95th"]),
        "criterion": "null_95th < 0.01 for d=19, n=500",
        "passed": bool(r["null_95th"] < 0.01),
    }


def test_gpu_cpu_consistency(
    n_perm: int = 200, seed: int = 42
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    win = _organ_window_from_latent(500, 0.6, rng)
    r_gpu = compute_theta(win, n_permutations=n_perm, seed=seed, backend="gpu")
    r_cpu = compute_theta(win, n_permutations=n_perm, seed=seed, backend="cpu")
    diff = abs(r_gpu["theta"] - r_cpu["theta"])
    rel = diff / max(abs(r_cpu["theta"]), 1e-10)
    return {
        "test": "gpu_cpu_consistency",
        "theta_gpu": float(r_gpu["theta"]),
        "theta_cpu": float(r_cpu["theta"]),
        "abs_diff": float(diff),
        "rel_diff": float(rel),
        "criterion": "rel_diff <= 0.10",
        "passed": bool(rel <= 0.10),
    }


def run_validation_suite(
    n_permutations: int = N_PERMUTATIONS, seed: int = 42
) -> dict[str, Any]:
    tests = [
        test_known_mi_recovery(seed=seed),
        test_integration_discrimination(n_perm=n_permutations, seed=seed),
        test_permutation_significance(n_perm=n_permutations, seed=seed),
        test_null_distribution(n_perm=n_permutations, seed=seed),
        test_gpu_cpu_consistency(n_perm=min(200, n_permutations), seed=seed),
    ]
    return {
        "n_permutations": n_permutations,
        "seed": seed,
        "tests": tests,
        "all_passed": all(t["passed"] for t in tests),
    }
