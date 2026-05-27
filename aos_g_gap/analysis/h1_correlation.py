"""H1 — Pearson r(θ, delta_norm) across all compose events with bootstrap CI.

Pass criterion: r < -0.5.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..config import H1_R_THRESHOLD
from ._loader import all_events, load_summaries


def _pearson_r(x: np.ndarray, y: np.ndarray) -> float:
    if x.std() < 1e-12 or y.std() < 1e-12:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _bootstrap_ci(
    x: np.ndarray, y: np.ndarray, n: int = 1000, alpha: float = 0.05, seed: int = 0
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    n_obs = len(x)
    rs = np.empty(n)
    for i in range(n):
        idx = rng.integers(0, n_obs, size=n_obs)
        rs[i] = _pearson_r(x[idx], y[idx])
    rs = rs[~np.isnan(rs)]
    if len(rs) == 0:
        return (float("nan"), float("nan"))
    return float(np.percentile(rs, 100 * alpha / 2)), float(np.percentile(rs, 100 * (1 - alpha / 2)))


def run(out_root: Path) -> dict:
    summaries = load_summaries(out_root)
    events = all_events(summaries)
    pairs = [(e["internal_theta"], e["delta_norm"])
             for e in events
             if e.get("internal_theta") is not None and e.get("delta_norm") is not None]
    if len(pairs) < 5:
        return {"hypothesis": "H1", "passed": False, "reason": "insufficient pairs", "n": len(pairs)}
    x = np.array([p[0] for p in pairs], dtype=np.float64)
    y = np.array([p[1] for p in pairs], dtype=np.float64)
    r_all = _pearson_r(x, y)
    ci_lo, ci_hi = _bootstrap_ci(x, y, n=1000, seed=42)

    # Per-condition correlations (more diagnostic).
    by_cond: dict[str, list[tuple[float, float]]] = {}
    for e in events:
        if e.get("internal_theta") is None:
            continue
        by_cond.setdefault(e["condition"], []).append((e["internal_theta"], e["delta_norm"]))
    per_condition_r = {
        c: _pearson_r(
            np.array([p[0] for p in v], dtype=np.float64),
            np.array([p[1] for p in v], dtype=np.float64),
        )
        for c, v in by_cond.items() if len(v) >= 5
    }

    return {
        "hypothesis": "H1",
        "criterion": f"r < {H1_R_THRESHOLD}",
        "n_pairs": len(pairs),
        "r": r_all,
        "ci_95": [ci_lo, ci_hi],
        "per_condition_r": per_condition_r,
        "passed": bool(r_all < H1_R_THRESHOLD),
    }
