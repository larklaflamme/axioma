"""Intra-organ θ for the k=1 case.

The standard θ pipeline (organ.theta.pipeline.compute_theta) early-exits with
θ=0 when fewer than 2 organ blocks survive `drop_constant_dims`. At k=1 only
PNEUMA is active; we measure *intra-PNEUMA* integration by splitting PNEUMA's
4 summary columns into two halves (cols 0,1 vs 2,3) and computing pairwise MI
between them with the same Gaussian-copula machinery + permutation null.

Same return shape as `compute_theta`, with `method="intra"` in details.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import torch

from organ.config import N_PERMUTATIONS, SIGNIFICANCE_THRESHOLD
from organ.measurement.summaries import select_summary_columns
from organ.theta.copula import pairwise_mi_cpu, pairwise_mi_gpu
from organ.theta.normality import drop_constant_dims, normalize
from organ.theta.permutation import permutation_null_gpu


def _empty(reason: str) -> dict:
    return {
        "theta": 0.0,
        "pairwise_mi": {},
        "p_value": 1.0,
        "significant": False,
        "null_95th": 0.0,
        "method": "intra/empty",
        "details": {"reason": reason},
    }


def compute_intra_organ_theta(
    organ_window: np.ndarray,
    organ_name: str = "pneuma",
    *,
    n_permutations: int = N_PERMUTATIONS,
    significance_threshold: float = SIGNIFICANCE_THRESHOLD,
    seed: int | None = None,
    backend: str = "gpu",
) -> dict:
    """Compute θ within one organ by splitting its summary columns in half.

    Args:
        organ_window: (n, D_organ) raw per-beat state for the chosen organ.
        organ_name: which organ this is (drives the column selection).

    Returns:
        dict with keys theta, pairwise_mi, p_value, significant, null_95th,
        method, details — same shape as compute_theta.
    """
    cols = select_summary_columns(organ_name, organ_window)  # (n, s_organ)
    n, s = cols.shape
    if s < 2 or n < 3:
        return _empty(f"insufficient cols ({s}) or beats ({n})")

    X_norm, method = normalize(cols)
    X_norm, kept = drop_constant_dims(X_norm)
    d = X_norm.shape[1]
    if d < 2:
        return _empty(f"after drop_constant_dims, only {d} non-constant column(s)")

    # Split surviving columns into two halves (preserve order).
    mid = d // 2
    block_slices = [
        ("left",  slice(0, mid)),
        ("right", slice(mid, d)),
    ]

    cov = np.cov(X_norm.T)
    energy = float(np.trace(cov)) if cov.ndim == 2 else float(cov)
    if energy < 1e-10:
        return _empty("zero energy after normalization")

    if backend == "cpu" or not torch.cuda.is_available():
        pairwise, total_mi = pairwise_mi_cpu(X_norm, block_slices)
        rng = np.random.default_rng(seed)
        null_total = np.empty(n_permutations, dtype=np.float64)
        for b in range(n_permutations):
            Xp = X_norm.copy()
            for _, sl in block_slices:
                perm = rng.permutation(n)
                Xp[:, sl] = Xp[perm, sl]
            _, mi_b = pairwise_mi_cpu(Xp, block_slices)
            null_total[b] = mi_b
        null_theta = null_total / max(energy, 1e-10)
    else:
        device = torch.device("cuda")
        Xt = torch.from_numpy(X_norm).to(device).float()
        pairwise, total_mi = pairwise_mi_gpu(Xt, block_slices)
        _, null_theta = permutation_null_gpu(
            Xt, block_slices, n_permutations=n_permutations,
            energy=energy, seed=seed,
        )

    theta = total_mi / max(energy, 1e-10)
    null_95th = float(np.percentile(null_theta, 95))
    p_value = float(np.mean(null_theta >= theta))
    significant = bool(p_value < significance_threshold)

    return {
        "theta": float(theta),
        "pairwise_mi": {f"{organ_name}-left::{organ_name}-right": float(pairwise[("left", "right")])},
        "p_value": p_value,
        "significant": significant,
        "null_95th": null_95th,
        "method": f"intra_{organ_name}::{method}",
        "details": {
            "total_mi": float(total_mi),
            "total_energy": float(energy),
            "n_dims": int(d),
            "window_size": int(n),
            "n_permutations": int(n_permutations),
            "n_blocks": 2,
            "organ": organ_name,
        },
    }
