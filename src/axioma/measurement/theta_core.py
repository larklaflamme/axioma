"""Gaussian-copula MI primitives (vendored from organ/theta/ — v0.2 baseline).

The math is unchanged from v0.2 (validated). v1.0 wraps these in engine
classes (theta_engine.py + raw_mi_engine.py) with the should_run pattern.

Public surface:
  - pairwise_mi_cpu / pairwise_mi_gpu / pairwise_mi_gpu_batched
  - permutation_null_gpu
  - normalize (z-score with RINT fallback per ARCH §7.4)
  - drop_constant_dims
  - SUMMARY_INDICES / SUMMARY_DIMS / TOTAL_SUMMARY_DIMS  (the 19 dims)
  - select_summary_columns / concat_summary_window

For a window (n_beats, d_total) matrix X with near-normal marginals, the
Gaussian copula MI between blocks X_i (n×d_i) and X_j (n×d_j) is:

    MI(X_i, X_j) = 0.5 · (logdet Σ_i + logdet Σ_j − logdet Σ_ij)

θ = total_pairwise_MI / total_energy(X) where energy = trace(cov(X)).

Significance via permutation null: shuffle each block's rows independently
(breaks cross-organ alignment, preserves within-organ structure).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import torch
from scipy.stats import norm, shapiro

from ..schemas import ORGAN_ORDER

# ── Constants vendored from v0.2 organ.config ──────────────────────────────

_RIDGE = 1e-6
_DEFAULT_NORMALITY_P = 0.05
_DEFAULT_CONSTANT_DIM_THRESHOLD = 1e-10

# Column indices into each organ's raw state ORDER (see schemas/organ_state.py).
# v1.0: same positions as v0.2 — the 19 summary dims have identical semantics.
# (PNEUMA's new coherence_budget is at index 6; not in summaries — summaries
#  index into 0..3 only.)
SUMMARY_INDICES: dict[str, tuple[int, ...]] = {
    "anima":   (0, 1, 2, 3),  # valence, arousal, dominance, mood
    "eidolon": (0, 1, 2, 5),  # self_coherence, confidence, narrative_continuity, integration_feeling
    "mneme":   (0, 1, 3),     # wm_load, retrieval_rate, episodic_freshness
    "nous":    (0, 2, 3, 4),  # inference_depth, cognitive_load, active_hypotheses, novelty
    "pneuma":  (0, 1, 2, 3),  # integration_level, global_coherence, fragmentation, awareness_level
}
SUMMARY_DIMS: dict[str, int] = {k: len(v) for k, v in SUMMARY_INDICES.items()}
TOTAL_SUMMARY_DIMS: int = sum(SUMMARY_DIMS.values())  # 19
assert TOTAL_SUMMARY_DIMS == 19


def select_summary_columns(organ: str, window: np.ndarray) -> np.ndarray:
    """Pick the (n, s_organ) summary columns from a (n, D_organ) window."""
    cols = SUMMARY_INDICES[organ]
    return np.asarray(window[:, cols], dtype=np.float32)


def concat_summary_window(states: dict[str, np.ndarray]) -> np.ndarray:
    """Concatenate per-organ summary columns into a single (n, 19) matrix.

    Accepts either (n, D_organ) full-state windows or pre-selected
    (n, s_organ) summary windows; auto-detected by column count.
    """
    parts: list[np.ndarray] = []
    for organ in ORGAN_ORDER:
        block = states[organ]
        if block.shape[1] == SUMMARY_DIMS[organ]:
            parts.append(np.asarray(block, dtype=np.float32))
        else:
            parts.append(select_summary_columns(organ, block))
    return np.concatenate(parts, axis=1).astype(np.float32)


# ── Numerics: covariance + log-determinant ─────────────────────────────────

def _logdet_np(M: np.ndarray) -> float:
    sign, logdet = np.linalg.slogdet(M + _RIDGE * np.eye(M.shape[0]))
    if sign <= 0:
        return -float("inf")
    return float(logdet)


def _cov_np(X: np.ndarray) -> np.ndarray:
    n = X.shape[0]
    Xc = X - X.mean(axis=0, keepdims=True)
    return (Xc.T @ Xc) / (n - 1)


def _logdet_torch(M: torch.Tensor) -> torch.Tensor:
    d = M.shape[-1]
    ridge = _RIDGE * torch.eye(d, device=M.device, dtype=M.dtype)
    return torch.linalg.slogdet(M + ridge).logabsdet


def _cov_torch(X: torch.Tensor) -> torch.Tensor:
    n = X.shape[-2]
    mu = X.mean(dim=-2, keepdim=True)
    Xc = X - mu
    return Xc.transpose(-2, -1) @ Xc / (n - 1)


# ── Normalization ──────────────────────────────────────────────────────────

def drop_constant_dims(
    X: np.ndarray, threshold: float = _DEFAULT_CONSTANT_DIM_THRESHOLD
) -> tuple[np.ndarray, np.ndarray]:
    """Remove zero-variance columns. Returns (X_filtered, kept_mask)."""
    var = X.var(axis=0)
    kept = var > threshold
    return X[:, kept], kept


def zscore(X: np.ndarray) -> np.ndarray:
    mu = X.mean(axis=0, keepdims=True)
    sd = X.std(axis=0, keepdims=True)
    sd = np.where(sd < 1e-12, 1.0, sd)
    return (X - mu) / sd


def rank_inverse_normal(X: np.ndarray) -> np.ndarray:
    """Map each column's ranks to standard-normal quantiles (RINT).

    Used as a fallback when Shapiro-Wilk fails on any column (i.e., when
    raw data is too non-normal for the Gaussian copula assumption).
    """
    n = X.shape[0]
    out = np.empty_like(X, dtype=np.float64)
    for j in range(X.shape[1]):
        col = X[:, j]
        order = col.argsort()
        ranks = np.empty(n, dtype=np.float64)
        ranks[order] = np.arange(1, n + 1)
        u = (ranks - 0.5) / n
        out[:, j] = norm.ppf(u)
    return out.astype(np.float32)


def shapiro_normal(X: np.ndarray, p_threshold: float = _DEFAULT_NORMALITY_P) -> bool:
    """Return True if every column passes Shapiro-Wilk at p ≥ threshold."""
    n = X.shape[0]
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
    """Normalize X. Returns (X_norm, method) where method ∈ {'zscore', 'rint'}.

    With force=None (default): use z-score if all columns pass Shapiro-Wilk,
    else fall back to RINT.
    """
    if force == "zscore":
        return zscore(X).astype(np.float32), "zscore"
    if force == "rint":
        return rank_inverse_normal(X), "rint"
    if shapiro_normal(X):
        return zscore(X).astype(np.float32), "zscore"
    return rank_inverse_normal(X), "rint"


# ── Pairwise MI: CPU ───────────────────────────────────────────────────────


def pairwise_mi_cpu(
    X: np.ndarray, block_slices: list[tuple[str, slice]]
) -> tuple[dict[tuple[str, str], float], float]:
    """Compute all pairwise MIs between organ blocks of X (n, d_total).
    Returns ({(name_i, name_j): mi}, total_mi)."""
    mis: dict[tuple[str, str], float] = {}
    total = 0.0
    block_logdet: dict[str, float] = {}
    block_view: dict[str, np.ndarray] = {}
    for name, sl in block_slices:
        Xi = X[:, sl]
        block_view[name] = Xi
        block_logdet[name] = _logdet_np(_cov_np(Xi))

    for a in range(len(block_slices)):
        for b in range(a + 1, len(block_slices)):
            name_a, _ = block_slices[a]
            name_b, _ = block_slices[b]
            Xa = block_view[name_a]
            Xb = block_view[name_b]
            joint = np.concatenate([Xa, Xb], axis=1)
            ld_joint = _logdet_np(_cov_np(joint))
            mi = 0.5 * (block_logdet[name_a] + block_logdet[name_b] - ld_joint)
            mi = max(0.0, mi)
            mis[(name_a, name_b)] = mi
            total += mi
    return mis, total


# ── Pairwise MI: GPU ───────────────────────────────────────────────────────


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


# ── Permutation null ───────────────────────────────────────────────────────


def permutation_null_gpu(
    X: torch.Tensor,
    block_slices: list[tuple[str, slice]],
    n_permutations: int,
    energy: float,
    *,
    batch_size: int = 200,
    seed: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (null_total_mi, null_theta) arrays of shape (n_permutations,)."""
    device = X.device
    n = X.shape[0]
    d_total = X.shape[1]
    g: torch.Generator | None = None
    if seed is not None:
        g = torch.Generator(device=device)
        g.manual_seed(int(seed))

    null_mi: list[np.ndarray] = []
    remaining = n_permutations
    while remaining > 0:
        B = min(batch_size, remaining)
        Xb = X.unsqueeze(0).expand(B, n, d_total).contiguous().clone()
        for _name, sl in block_slices:
            perms = torch.stack(
                [torch.randperm(n, device=device, generator=g) for _ in range(B)],
                dim=0,
            )  # (B, n)
            block = X[:, sl].unsqueeze(0).expand(B, n, sl.stop - sl.start)
            gathered = torch.gather(
                block,
                1,
                perms.unsqueeze(-1).expand(B, n, sl.stop - sl.start),
            )
            Xb[:, :, sl] = gathered
        mi_batch = pairwise_mi_gpu_batched(Xb, block_slices)
        null_mi.append(mi_batch.detach().cpu().numpy())
        remaining -= B
    null_total = np.concatenate(null_mi)
    null_theta = null_total / max(energy, 1e-10)
    return null_total, null_theta


# ── End-to-end θ helper (used by ThetaEngine) ──────────────────────────────


def make_block_slices(kept_mask: np.ndarray) -> list[tuple[str, slice]]:
    """Build [(organ_name, slice), ...] for the post-drop-constant matrix.

    kept_mask is the (TOTAL_SUMMARY_DIMS,) bool array returned by
    drop_constant_dims; this maps it back to per-organ contiguous slices.
    """
    out: list[tuple[str, slice]] = []
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


def compute_theta_from_summary(
    summary_matrix: np.ndarray,
    *,
    n_permutations: int = 100,
    significance_threshold: float = 0.05,
    device: torch.device | None = None,
    seed: int | None = None,
    backend: str = "auto",
    force_normalize: str | None = None,
) -> dict[str, Any]:
    """Compute θ from a (n_beats, 19) summary matrix.

    Args:
        summary_matrix: result of concat_summary_window(window) — (n, 19) float32
        n_permutations: shuffles for the null distribution (default 100)
        significance_threshold: p < threshold ⇒ significant
        device: torch device override (default: cuda if available)
        backend: 'cpu', 'gpu', or 'auto' (gpu if available, else cpu)
        seed: optional permutation seed (deterministic null)
        force_normalize: 'zscore' | 'rint' | None (auto detect)

    Returns dict with keys theta, pairwise_mi, p_value, significant,
    null_95th, method, details. Returns theta=0 / significant=False when
    fewer than 2 non-constant organs survive.
    """
    n, d = summary_matrix.shape
    if d != TOTAL_SUMMARY_DIMS:
        raise ValueError(f"summary_matrix has {d} cols; expected {TOTAL_SUMMARY_DIMS}")
    if n < 3:
        raise ValueError(f"window too short: n={n}")

    X_norm, method = normalize(summary_matrix, force=force_normalize)
    X_norm, kept_mask = drop_constant_dims(X_norm)
    block_slices = make_block_slices(kept_mask)

    if len(block_slices) < 2:
        return {
            "theta": 0.0,
            "pairwise_mi": {},
            "p_value": 1.0,
            "significant": False,
            "null_95th": 0.0,
            "method": method,
            "details": {
                "n_dims": int(X_norm.shape[1]),
                "window_size": int(n),
                "reason": "fewer than 2 non-constant organs",
            },
        }

    cov = np.cov(X_norm.T)
    energy = float(np.trace(cov))

    use_gpu = (backend == "gpu") or (backend == "auto" and torch.cuda.is_available())
    if not use_gpu or backend == "cpu":
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
        dev = device or torch.device("cuda")
        Xt = torch.from_numpy(X_norm).to(dev).float()
        pairwise, total_mi = pairwise_mi_gpu(Xt, block_slices)
        null_total, null_theta = permutation_null_gpu(
            Xt, block_slices,
            n_permutations=n_permutations,
            energy=energy,
            seed=seed,
        )

    theta = total_mi / max(energy, 1e-10)
    null_95th = float(np.percentile(null_theta, 95))
    p_value = float(np.mean(null_theta >= theta))
    significant = bool(p_value < significance_threshold)

    # Cast pairwise keys to string tuples (msgspec-friendly)
    pairwise_str = {f"{a}-{b}": v for (a, b), v in pairwise.items()}

    return {
        "theta": float(theta),
        "pairwise_mi": pairwise_str,
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
            "backend": "gpu" if use_gpu and backend != "cpu" else "cpu",
        },
    }
