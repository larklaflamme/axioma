"""AOS-G gap computation per §9.

Given paired internal and external state vectors / windows, returns:
  delta_norm: Euclidean distance
  mi: Gaussian copula MI between internal and external
  delta_theta: difference in θ
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from .copula import pairwise_mi_cpu
from .normality import normalize, drop_constant_dims


def _scalar_mi_via_pair(internal: np.ndarray, external: np.ndarray) -> float:
    """Compute MI between two windows by treating each as one 'organ block'.

    Inputs are (n, d_a) and (n, d_b). Normalize jointly, drop constant dims, then
    use pairwise_mi_cpu with two blocks.
    """
    X = np.concatenate([internal, external], axis=1).astype(np.float32)
    X_norm, _ = normalize(X)
    X_norm, kept = drop_constant_dims(X_norm)
    d_int = int(kept[: internal.shape[1]].sum())
    d_ext = int(kept[internal.shape[1]:].sum())
    if d_int == 0 or d_ext == 0:
        return 0.0
    blocks = [("internal", slice(0, d_int)), ("external", slice(d_int, d_int + d_ext))]
    mis, total = pairwise_mi_cpu(X_norm, blocks)
    return float(total)


def compute_aos_g_gap(
    internal: np.ndarray,
    external: np.ndarray,
    internal_theta: Optional[float] = None,
    external_theta: Optional[float] = None,
) -> dict:
    """Compute the AOS-G gap between an internal and an external state pair.

    Both arrays can be either (d,) single snapshots or (n, d) windows; if 1-D
    they are treated as single observations and the MI / theta diff are skipped.

    Args:
        internal: internal state(s) — post-beat / pre-compose.
        external: external state(s) — at compose/send.
        internal_theta, external_theta: optional precomputed θ values for the
            difference; if omitted, delta_theta is left as None.
    Returns:
        dict with delta_norm, mi (or None for single snapshots), delta_theta.
    """
    internal = np.asarray(internal, dtype=np.float32)
    external = np.asarray(external, dtype=np.float32)
    if internal.shape != external.shape:
        # Allow dim mismatch by padding to the longer.
        d = max(internal.shape[-1], external.shape[-1])
        def _pad(a):
            if a.shape[-1] == d:
                return a
            pad_width = [(0, 0)] * (a.ndim - 1) + [(0, d - a.shape[-1])]
            return np.pad(a, pad_width, mode="constant")
        internal = _pad(internal)
        external = _pad(external)

    delta_norm = float(np.linalg.norm(internal - external))
    mi: Optional[float]
    if internal.ndim == 2 and internal.shape[0] >= 3:
        mi = _scalar_mi_via_pair(internal, external)
    else:
        mi = None
    delta_theta = None
    if internal_theta is not None and external_theta is not None:
        delta_theta = float(internal_theta) - float(external_theta)
    return {
        "delta_norm": delta_norm,
        "mi": mi,
        "delta_theta": delta_theta,
    }
