"""H4 — Cross-correlation between θ(t) and delta_norm(t) over beats 200-600.

Pass criterion: peak at lag 0 ± 2 with r < -0.5.

Approach:
  We don't have a per-beat θ trajectory (computing θ every beat is expensive).
  Instead we estimate θ on a 200-beat rolling window every 10 beats — fast
  enough — then compute cross-correlation with delta_norm at matching beats.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from organ.schemas import ORGAN_DIMS, ORGAN_ORDER
from organ.theta import compute_theta

from ..config import H4_LAG_TOLERANCE, H4_R_THRESHOLD, H4_WINDOW
from ._loader import load_summaries, load_trajectories


def _split(traj: np.ndarray) -> dict[str, np.ndarray]:
    out = {}
    start = 0
    for o in ORGAN_ORDER:
        d = ORGAN_DIMS[o]
        out[o] = traj[:, start : start + d]
        start += d
    return out


def _rolling_theta(internal_traj: np.ndarray, beats: list[int], window: int, n_perm: int, seed: int) -> np.ndarray:
    out = np.full(len(beats), np.nan)
    for i, b in enumerate(beats):
        if b + 1 < window:
            continue
        sub = internal_traj[b + 1 - window : b + 1]
        win = _split(sub)
        try:
            r = compute_theta(win, n_permutations=n_perm, seed=seed)
            out[i] = float(r["theta"])
        except Exception:
            pass
    return out


def _xcorr(x: np.ndarray, y: np.ndarray, max_lag: int) -> tuple[int, float, dict[int, float]]:
    """Cross-correlation. Returns (peak_lag, peak_r, {lag: r}).

    Convention: positive lag means x leads y (y[t+lag] correlated with x[t]).
    """
    out = {}
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            xs, ys = x[-lag:], y[: len(y) + lag]
        elif lag > 0:
            xs, ys = x[: len(x) - lag], y[lag:]
        else:
            xs, ys = x, y
        mask = (~np.isnan(xs)) & (~np.isnan(ys))
        if mask.sum() < 5:
            out[lag] = float("nan")
            continue
        xs2, ys2 = xs[mask], ys[mask]
        if xs2.std() < 1e-9 or ys2.std() < 1e-9:
            out[lag] = float("nan")
            continue
        out[lag] = float(np.corrcoef(xs2, ys2)[0, 1])
    valid_lags = [k for k, v in out.items() if not np.isnan(v)]
    if not valid_lags:
        return (0, float("nan"), out)
    peak_lag = min(valid_lags, key=lambda k: out[k])  # most negative
    return peak_lag, out[peak_lag], out


def run(out_root: Path, n_perm: int = 100, sample_every: int = 10, window: int = 200) -> dict:
    summaries = load_summaries(out_root)
    # Use the direct_contradiction condition for H4 (richest signal).
    contradiction = [s for s in summaries if s["condition"] == "direct_contradiction"]
    per_seed: list[dict] = []
    for s in contradiction:
        tr = load_trajectories(Path(s["trial_dir"]))
        internal = tr["internal"]
        delta_series = tr["delta_norm"]
        beats = list(range(H4_WINDOW[0], H4_WINDOW[1], sample_every))
        theta_at_beats = _rolling_theta(internal, beats, window=window, n_perm=n_perm, seed=s["seed"])
        delta_at_beats = np.array([delta_series[b] for b in beats], dtype=np.float64)
        peak_lag, peak_r, full = _xcorr(theta_at_beats, delta_at_beats, max_lag=10)
        per_seed.append({
            "seed": s["seed"],
            "n_samples": len(beats),
            "peak_lag": int(peak_lag),
            "peak_r": peak_r,
            "xcorr": {str(k): float(v) for k, v in full.items()},
        })
    avg_peak_lag = float(np.mean([ps["peak_lag"] for ps in per_seed]))
    avg_peak_r = float(np.mean([ps["peak_r"] for ps in per_seed if not np.isnan(ps["peak_r"])]))
    passed = abs(avg_peak_lag) <= H4_LAG_TOLERANCE and avg_peak_r < H4_R_THRESHOLD
    return {
        "hypothesis": "H4",
        "criterion": f"|lag| <= {H4_LAG_TOLERANCE} and r < {H4_R_THRESHOLD}",
        "per_seed": per_seed,
        "mean_peak_lag": avg_peak_lag,
        "mean_peak_r": avg_peak_r,
        "passed": bool(passed),
    }
