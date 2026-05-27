"""Theta pipeline: window → summaries → normalize → MI → θ + significance.

Implements §7.3 with v0.2 additions: normality check + RINT fallback, 1000-shuffle
permutation null, and returns p_value / significant / null_95th.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import torch

from ..config import (
    N_PERMUTATIONS,
    SIGNIFICANCE_THRESHOLD,
    WINDOW_SIZE,
)
from ..measurement.summaries import (
    SUMMARY_DIMS,
    select_all_summary_columns,
    concat_summary_window,
)
from ..schemas import ORGAN_ORDER
from .copula import pairwise_mi_cpu, pairwise_mi_gpu
from .normality import normalize, drop_constant_dims
from .permutation import permutation_null_gpu


@dataclass
class ThetaResult:
    theta: float
    pairwise_mi: dict[tuple[str, str], float]
    p_value: float
    significant: bool
    null_95th: float
    method: str
    details: dict = field(default_factory=dict)


def _make_block_slices(kept_mask: np.ndarray) -> list[tuple[str, slice]]:
    """Build [(organ_name, slice), ...] after constant-dim removal."""
    out = []
    start = 0
    src_start = 0
    for organ in ORGAN_ORDER:
        s = SUMMARY_DIMS[organ]
        block_mask = kept_mask[src_start : src_start + s]
        kept = int(block_mask.sum())
        if kept > 0:
            out.append((organ, slice(start, start + kept)))
        start += kept
        src_start += s
    return out


def compute_theta(
    window: dict[str, np.ndarray],
    *,
    n_permutations: int = N_PERMUTATIONS,
    significance_threshold: float = SIGNIFICANCE_THRESHOLD,
    device: str | None = None,
    seed: int | None = None,
    backend: str = "gpu",  # 'gpu' or 'cpu'
    force_normalize: str | None = None,
) -> dict:
    """Compute θ from a window of per-organ state arrays.

    Args:
        window: dict {organ_name: (n, D_organ) float32} (raw per-beat state).
        n_permutations: number of shuffles for the null distribution.
        significance_threshold: p < threshold ⇒ significant.
        device: torch device override (default: cuda if available).
        seed: optional permutation seed (deterministic null).
        backend: 'gpu' or 'cpu' for pairwise MI computation.
        force_normalize: 'zscore' / 'rint' / None (auto).

    Returns: dict with keys theta, pairwise_mi, p_value, significant, null_95th,
             method, details.
    """
    # 1. Select summary columns and concatenate → (n, 19).
    cols = select_all_summary_columns(window)
    X = concat_summary_window(cols)
    n, d = X.shape
    if n < 3:
        raise ValueError(f"Window too short: n={n}")

    # 2. Normalize (z-score with RINT fallback if non-normal).
    X_norm, method = normalize(X, force=force_normalize)
    # 3. Drop constant dims.
    X_norm, kept_mask = drop_constant_dims(X_norm)
    block_slices = _make_block_slices(kept_mask)
    if len(block_slices) < 2:
        return {
            "theta": 0.0,
            "pairwise_mi": {},
            "p_value": 1.0,
            "significant": False,
            "null_95th": 0.0,
            "method": method,
            "details": {"n_dims": int(X_norm.shape[1]), "window_size": int(n), "reason": "fewer than 2 non-constant organs"},
        }

    # 4. Energy = trace(cov) on normalized matrix.
    cov = np.cov(X_norm.T)
    energy = float(np.trace(cov))

    if backend == "cpu" or not torch.cuda.is_available():
        pairwise, total_mi = pairwise_mi_cpu(X_norm, block_slices)
        # Permutation null on CPU for parity (slow but correct).
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
        dev = torch.device(device or "cuda")
        Xt = torch.from_numpy(X_norm).to(dev).float()
        pairwise, total_mi = pairwise_mi_gpu(Xt, block_slices)
        null_total, null_theta = permutation_null_gpu(
            Xt,
            block_slices,
            n_permutations=n_permutations,
            energy=energy,
            seed=seed,
        )

    theta = total_mi / max(energy, 1e-10)
    null_95th = float(np.percentile(null_theta, 95))
    p_value = float(np.mean(null_theta >= theta))
    significant = bool(p_value < significance_threshold)

    return {
        "theta": float(theta),
        "pairwise_mi": pairwise,
        "p_value": p_value,
        "significant": significant,
        "null_95th": null_95th,
        "method": method,
        "details": {
            "total_mi": float(total_mi),
            "total_energy": float(energy),
            "n_dims": int(X_norm.shape[1]),
            "window_size": int(n),
            "n_permutations": int(n_permutations),
            "n_blocks": len(block_slices),
        },
    }
