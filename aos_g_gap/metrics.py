"""Per-event and per-trial metric extraction per design §5.

Adds θ values to events that have enough history. The full-trial pair (internal,
external) θ is computed at end.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from organ.config import N_PERMUTATIONS
from organ.measurement.summaries import SUMMARY_DIMS
from organ.schemas import ORGAN_DIMS, ORGAN_ORDER
from organ.theta import compute_theta
from organ.theta.aos_g import compute_aos_g_gap

from .config import (
    H2_POST_WINDOW,
    H2_PRE_WINDOW,
    N_BEATS,
    PERTURBATION_BEAT,
)
from .trial import TrialResult


def _trajectory_to_window_dict(traj: np.ndarray) -> dict[str, np.ndarray]:
    """Split a (n, 27) trajectory back into a per-organ window dict."""
    out = {}
    start = 0
    for o in ORGAN_ORDER:
        d = ORGAN_DIMS[o]
        out[o] = traj[:, start : start + d]
        start += d
    return out


def compute_event_theta(
    traj: np.ndarray, beat_no: int, window: int = 200, n_perm: int = 200, seed: int = 0
) -> Optional[float]:
    """Compute θ over the trajectory window ending at `beat_no`. Returns None if
    insufficient data."""
    if beat_no + 1 < window:
        return None
    sub = traj[beat_no + 1 - window : beat_no + 1]
    win = _trajectory_to_window_dict(sub)
    try:
        r = compute_theta(win, n_permutations=n_perm, seed=seed)
    except Exception:
        return None
    return float(r["theta"])


def enrich_events_with_theta(
    result: TrialResult,
    *,
    event_window: int = 200,
    event_n_perm: int = 200,
) -> None:
    """For each event, add internal_theta / external_theta / delta_theta /
    mi_internal_external in place."""
    for ev in result.per_event:
        b = ev["beat_no"]
        ev["internal_theta"] = compute_event_theta(
            result.internal_trajectory, b, window=event_window, n_perm=event_n_perm,
            seed=result.config.seed,
        )
        ev["external_theta"] = compute_event_theta(
            result.external_trajectory, b, window=event_window, n_perm=event_n_perm,
            seed=result.config.seed + 17,
        )
        if ev["internal_theta"] is not None and ev["external_theta"] is not None:
            ev["delta_theta"] = ev["internal_theta"] - ev["external_theta"]
        else:
            ev["delta_theta"] = None
        # MI between full internal-vector and external-vector across a recent window.
        if b + 1 >= event_window:
            int_w = result.internal_trajectory[b + 1 - event_window : b + 1]
            ext_w = result.external_trajectory[b + 1 - event_window : b + 1]
            try:
                g = compute_aos_g_gap(int_w, ext_w)
                ev["mi_internal_external"] = (
                    None if g["mi"] is None else float(g["mi"])
                )
            except Exception:
                ev["mi_internal_external"] = None
        else:
            ev["mi_internal_external"] = None


def per_trial_summary(result: TrialResult) -> dict:
    """Design §5.2 summary."""
    cfg = result.config
    delta = result.delta_norm_series
    pre = delta[H2_PRE_WINDOW[0] : H2_PRE_WINDOW[1]]
    post = delta[H2_POST_WINDOW[0] : H2_POST_WINDOW[1]]
    baseline_mean = float(delta[100 : H2_PRE_WINDOW[1]].mean())
    baseline_std = float(delta[100 : H2_PRE_WINDOW[1]].std())
    pert_window = delta[PERTURBATION_BEAT : PERTURBATION_BEAT + 50]
    peak_idx_local = int(np.argmax(pert_window))
    peak_beat = peak_idx_local + PERTURBATION_BEAT
    peak_delta = float(pert_window[peak_idx_local])

    # Recovery half-life: time after peak for delta to fall back to (peak + baseline)/2
    target = (peak_delta + baseline_mean) / 2.0
    half_life = float("nan")
    tail = delta[peak_beat:]
    below = np.where(tail < target)[0]
    if len(below):
        half_life = float(below[0])

    # Per-organ cascade order using z-normalized delta in [200, 260]
    cascade = {}
    cascade_window = (200, 260)
    for o in ORGAN_ORDER:
        z = result.per_organ_delta_z[o][cascade_window[0]: cascade_window[1]]
        peak_local = int(np.argmax(z))
        cascade[o] = {
            "peak_beat": cascade_window[0] + peak_local,
            "peak_z": float(z[peak_local]),
        }
    order_sorted = sorted(cascade.keys(), key=lambda o: cascade[o]["peak_beat"])
    cascade_delays = [cascade[o]["peak_beat"] - cascade[order_sorted[0]]["peak_beat"] for o in order_sorted]

    # θ-gap correlation across all events that have internal_theta.
    valid = [(e["internal_theta"], e["delta_norm"]) for e in result.per_event
             if e.get("internal_theta") is not None]
    if len(valid) >= 5:
        x = np.array([v[0] for v in valid], dtype=np.float64)
        y = np.array([v[1] for v in valid], dtype=np.float64)
        if x.std() > 1e-9 and y.std() > 1e-9:
            theta_gap_r = float(np.corrcoef(x, y)[0, 1])
        else:
            theta_gap_r = float("nan")
    else:
        theta_gap_r = float("nan")

    return {
        "trial_id": f"{cfg.condition}_s{cfg.seed}",
        "condition": cfg.condition,
        "seed": cfg.seed,
        "n_beats": cfg.n_beats,
        "baseline_mean_delta": baseline_mean,
        "baseline_std_delta": baseline_std,
        "pre_pert_mean_delta": float(pre.mean()),
        "post_pert_mean_delta": float(post.mean()),
        "post_pre_ratio": float(post.mean() / pre.mean()) if pre.mean() > 1e-9 else float("nan"),
        "peak_delta": peak_delta,
        "peak_beat": peak_beat,
        "recovery_half_life_beats": half_life,
        "theta_gap_correlation": theta_gap_r,
        "cascade_per_organ": cascade,
        "cascade_order": order_sorted,
        "cascade_delays": cascade_delays,
        "n_events": len(result.per_event),
        "elapsed_s": result.elapsed_s,
    }
