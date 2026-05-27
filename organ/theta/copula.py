"""Gaussian copula MI.

Given X with standard-normal (or near-normal) marginals, the Gaussian copula
MI between blocks X_i (n×d_i) and X_j (n×d_j) is:

    MI(X_i, X_j) = 0.5 * (logdet Σ_i + logdet Σ_j − logdet Σ_ij)

where Σ_i = cov(X_i), Σ_ij = cov([X_i, X_j]).

Two implementations:
  - pairwise_mi_cpu: NumPy, used for the §8.1 GPU/CPU consistency check.
  - pairwise_mi_gpu / pairwise_mi_gpu_batched: PyTorch, used in the live pipeline
    and the permutation null.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import torch

# Small ridge term added to covariance before logdet for numerical stability.
_RIDGE = 1e-6


def _logdet_np(M: np.ndarray) -> float:
    sign, logdet = np.linalg.slogdet(M + _RIDGE * np.eye(M.shape[0]))
    if sign <= 0:
        # Highly degenerate; treat as zero info.
        return -np.inf
    return float(logdet)


def _cov_np(X: np.ndarray) -> np.ndarray:
    """Sample covariance, ddof=1."""
    n = X.shape[0]
    Xc = X - X.mean(axis=0, keepdims=True)
    return (Xc.T @ Xc) / (n - 1)


def pairwise_mi_cpu(
    X: np.ndarray, block_slices: list[tuple[str, slice]]
) -> tuple[dict[tuple[str, str], float], float]:
    """Compute all pairwise MIs between organ blocks of X (n, d_total).

    Returns ({(name_i, name_j): mi}, total_mi).
    """
    mis: dict[tuple[str, str], float] = {}
    total = 0.0
    # Per-block covariance + logdet (cache).
    block_logdet: dict[str, float] = {}
    block_cov: dict[str, np.ndarray] = {}
    block_view: dict[str, np.ndarray] = {}
    for name, sl in block_slices:
        Xi = X[:, sl]
        block_view[name] = Xi
        block_cov[name] = _cov_np(Xi)
        block_logdet[name] = _logdet_np(block_cov[name])

    for a in range(len(block_slices)):
        for b in range(a + 1, len(block_slices)):
            name_a, _ = block_slices[a]
            name_b, _ = block_slices[b]
            Xa = block_view[name_a]
            Xb = block_view[name_b]
            joint = np.concatenate([Xa, Xb], axis=1)
            ld_joint = _logdet_np(_cov_np(joint))
            mi = 0.5 * (block_logdet[name_a] + block_logdet[name_b] - ld_joint)
            # Guard against tiny negatives from numerical noise.
            mi = max(0.0, mi)
            mis[(name_a, name_b)] = mi
            total += mi
    return mis, total


def _logdet_torch(M: torch.Tensor) -> torch.Tensor:
    """Batched log-determinant with ridge for stability.

    Expects M of shape (*, d, d). Returns shape (*).
    """
    d = M.shape[-1]
    ridge = _RIDGE * torch.eye(d, device=M.device, dtype=M.dtype)
    return torch.linalg.slogdet(M + ridge).logabsdet


def _cov_torch(X: torch.Tensor) -> torch.Tensor:
    """Sample covariance, ddof=1. Supports batched X (*, n, d)."""
    n = X.shape[-2]
    mu = X.mean(dim=-2, keepdim=True)
    Xc = X - mu
    return Xc.transpose(-2, -1) @ Xc / (n - 1)


def pairwise_mi_gpu(
    X: torch.Tensor, block_slices: list[tuple[str, slice]]
) -> tuple[dict[tuple[str, str], float], float]:
    """Single (n, d_total) tensor MI computation on GPU."""
    block_ld: dict[str, torch.Tensor] = {}
    block_view: dict[str, torch.Tensor] = {}
    for name, sl in block_slices:
        Xi = X[:, sl]
        block_view[name] = Xi
        block_ld[name] = _logdet_torch(_cov_torch(Xi))

    mis: dict[tuple[str, str], float] = {}
    total = X.new_zeros(())
    names = [n for n, _ in block_slices]
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            Xa = block_view[names[a]]
            Xb = block_view[names[b]]
            joint = torch.cat([Xa, Xb], dim=-1)
            ld_joint = _logdet_torch(_cov_torch(joint))
            mi = 0.5 * (block_ld[names[a]] + block_ld[names[b]] - ld_joint)
            mi = torch.clamp(mi, min=0.0)
            mis[(names[a], names[b])] = float(mi.item())
            total = total + mi
    return mis, float(total.item())


def pairwise_mi_gpu_batched(
    X_batch: torch.Tensor, block_slices: list[tuple[str, slice]]
) -> torch.Tensor:
    """Batched MI for permutation null.

    X_batch: (B, n, d_total) — each batch element is an (n, d_total) realization.
    Returns: (B,) total MI per batch element (sum over pairs).
    """
    # Per-block logdet across batches.
    names = [n for n, _ in block_slices]
    block_view = {n: X_batch[:, :, sl] for n, sl in block_slices}
    block_ld = {n: _logdet_torch(_cov_torch(block_view[n])) for n in names}

    B = X_batch.shape[0]
    total = X_batch.new_zeros(B)
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            joint = torch.cat([block_view[names[a]], block_view[names[b]]], dim=-1)
            ld_joint = _logdet_torch(_cov_torch(joint))
            mi = 0.5 * (block_ld[names[a]] + block_ld[names[b]] - ld_joint)
            mi = torch.clamp(mi, min=0.0)
            total = total + mi
    return total
