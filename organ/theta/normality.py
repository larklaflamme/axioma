"""Normalization: z-score with RINT fallback if any dim fails Shapiro-Wilk.

Per design v0.2 §7.1, §7.4 limitation 5.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import norm, shapiro

from ..config import NORMALITY_P_THRESHOLD, CONSTANT_DIM_THRESHOLD


def drop_constant_dims(
    X: np.ndarray, threshold: float = CONSTANT_DIM_THRESHOLD
) -> tuple[np.ndarray, np.ndarray]:
    """Remove zero-variance columns; return (X_filtered, kept_mask)."""
    var = X.var(axis=0)
    kept = var > threshold
    return X[:, kept], kept


def zscore(X: np.ndarray) -> np.ndarray:
    mu = X.mean(axis=0, keepdims=True)
    sd = X.std(axis=0, keepdims=True)
    sd = np.where(sd < 1e-12, 1.0, sd)
    return (X - mu) / sd


def rank_inverse_normal(X: np.ndarray) -> np.ndarray:
    """Map each column's ranks to standard-normal quantiles (RINT)."""
    n = X.shape[0]
    out = np.empty_like(X, dtype=np.float64)
    for j in range(X.shape[1]):
        col = X[:, j]
        order = col.argsort()
        ranks = np.empty(n, dtype=np.float64)
        ranks[order] = np.arange(1, n + 1)
        # Apply offset to avoid 0/1 at the tails.
        u = (ranks - 0.5) / n
        out[:, j] = norm.ppf(u)
    return out.astype(np.float32)


def shapiro_normal(X: np.ndarray, p_threshold: float = NORMALITY_P_THRESHOLD) -> bool:
    """Return True if every column passes Shapiro-Wilk at p>=threshold."""
    n = X.shape[0]
    # Shapiro-Wilk is reliable for 3 <= n <= 5000.
    n_eff = min(n, 5000)
    if n_eff < 3:
        return True
    idx = np.linspace(0, n - 1, n_eff).astype(int)
    sample = X[idx]
    for j in range(sample.shape[1]):
        try:
            _, p = shapiro(sample[:, j])
        except Exception:
            return False
        if p < p_threshold:
            return False
    return True


def normalize(X: np.ndarray, force: str | None = None) -> tuple[np.ndarray, str]:
    """Normalize X (n, d). Returns (X_norm, method) where method ∈ {'zscore','rint'}.

    If `force` is given ('zscore' or 'rint'), use it directly. Otherwise check
    normality and fall back to RINT if Shapiro-Wilk fails on any column.
    """
    if force == "zscore":
        return zscore(X), "zscore"
    if force == "rint":
        return rank_inverse_normal(X), "rint"
    if shapiro_normal(X):
        return zscore(X), "zscore"
    return rank_inverse_normal(X), "rint"
