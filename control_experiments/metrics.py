"""Trial-level metrics: ΔΦ S1/S2/S3 + self-model cascade.

Computes:
  - θ at three windows (baseline, peak, recovery_final).
  - Per-organ θ contributions via single-block MI (organ vs. all-other-organs).
  - cascade_delay / recovery_asymmetry / adaptation_delta over the per-organ θ.
  - Trial-level summary inputs for S1 / S2 (S3 needs cross-trial aggregation).
"""
from __future__ import annotations

import numpy as np

from organ.schemas import ORGAN_DIMS, ORGAN_ORDER
from organ.theta import compute_theta

from .config import (
    BASELINE_WINDOW,
    PEAK_WINDOW,
    RECOVERY_FINAL_WINDOW,
)
from .trial import ControlTrialResult


def _split_to_window(traj: np.ndarray) -> dict[str, np.ndarray]:
    out = {}
    start = 0
    for o in ORGAN_ORDER:
        d = ORGAN_DIMS[o]
        out[o] = traj[:, start : start + d]
        start += d
    return out


def _theta_on_window(
    internal: np.ndarray, beat_lo: int, beat_hi: int, *,
    seed: int, n_perm: int = 100, min_n: int = 50,
) -> float | None:
    """Compute θ on internal[beat_lo:beat_hi]. Returns None on degeneracy."""
    sub = internal[beat_lo:beat_hi]
    if sub.shape[0] < min_n:
        return None
    try:
        r = compute_theta(_split_to_window(sub), n_permutations=n_perm, seed=seed)
        return float(r["theta"])
    except Exception:
        return None


def _per_organ_theta(
    internal: np.ndarray, beat_lo: int, beat_hi: int, *, seed: int, n_perm: int = 50,
) -> dict[str, float | None]:
    """For each organ, MI(this organ block, rest of summary matrix) / energy.

    We reuse the existing compute_theta machinery by passing only TWO blocks:
    this organ and the concatenation of the others. θ is then organ-specific.
    """
    from organ.measurement.summaries import (
        SUMMARY_DIMS,
        select_all_summary_columns,
        concat_summary_window,
    )
    from organ.theta.copula import pairwise_mi_cpu
    from organ.theta.normality import drop_constant_dims, normalize

    sub = internal[beat_lo:beat_hi]
    if sub.shape[0] < 50:
        return {o: None for o in ORGAN_ORDER}
    cols = select_all_summary_columns(_split_to_window(sub))
    X = concat_summary_window(cols)
    X_norm, _ = normalize(X)
    X_norm, kept = drop_constant_dims(X_norm)
    # Determine surviving slice boundaries.
    starts = {}
    cursor = 0
    src_cursor = 0
    for o in ORGAN_ORDER:
        s = SUMMARY_DIMS[o]
        kept_in_block = int(kept[src_cursor : src_cursor + s].sum())
        starts[o] = (cursor, cursor + kept_in_block)
        cursor += kept_in_block
        src_cursor += s
    if X_norm.shape[1] < 2:
        return {o: 0.0 for o in ORGAN_ORDER}
    cov = np.cov(X_norm.T)
    energy = float(np.trace(cov)) if cov.ndim == 2 else float(cov)
    if energy < 1e-9:
        return {o: 0.0 for o in ORGAN_ORDER}

    out: dict[str, float | None] = {}
    for o in ORGAN_ORDER:
        lo, hi = starts[o]
        if hi - lo == 0:
            out[o] = 0.0
            continue
        # Build a 2-block view: this organ + the rest.
        others_lo = 0
        others_hi = lo
        others_lo2 = hi
        others_hi2 = X_norm.shape[1]
        if (others_hi - others_lo) + (others_hi2 - others_lo2) == 0:
            out[o] = 0.0
            continue
        # Concatenate the rest:
        rest = np.concatenate(
            [X_norm[:, others_lo:others_hi], X_norm[:, others_lo2:others_hi2]], axis=1
        )
        joint = np.concatenate([X_norm[:, lo:hi], rest], axis=1)
        slices = [("this", slice(0, hi - lo)),
                  ("rest", slice(hi - lo, hi - lo + rest.shape[1]))]
        try:
            _, mi = pairwise_mi_cpu(joint, slices)
            out[o] = float(mi / energy)
        except Exception:
            out[o] = None
    return out


def trial_summary(result: ControlTrialResult, *, n_perm: int = 100) -> dict:
    cfg = result.config
    seed = cfg.seed
    internal = result.internal_trajectory
    delta = result.delta_norm_series

    theta_baseline = _theta_on_window(internal, *BASELINE_WINDOW, seed=seed, n_perm=n_perm)
    theta_peak = _theta_on_window(internal, *PEAK_WINDOW, seed=seed + 7, n_perm=n_perm)
    theta_final = _theta_on_window(internal, *RECOVERY_FINAL_WINDOW, seed=seed + 13, n_perm=n_perm)

    # Trajectory-level extrema (still in θ units only via the windows above).
    theta_min = min((t for t in (theta_baseline, theta_peak, theta_final) if t is not None),
                    default=0.0)

    # Per-organ θ at baseline and recovery_final for adaptation_delta.
    per_organ_baseline = _per_organ_theta(internal, *BASELINE_WINDOW, seed=seed)
    per_organ_recovery = _per_organ_theta(internal, *RECOVERY_FINAL_WINDOW, seed=seed + 13)

    # Per-organ θ in the perturbation window for cascade detection.
    per_organ_peak = _per_organ_theta(internal, *PEAK_WINDOW, seed=seed + 7)

    # Cascade timing via per-organ delta (smoothed): time-to-peak in (200, 250).
    cascade_window = (200, 250)
    cascade = {}
    for o in ORGAN_ORDER:
        arr = result.per_organ_delta[o]
        seg = arr[cascade_window[0]: cascade_window[1]]
        if len(seg) == 0:
            cascade[o] = None
        else:
            cascade[o] = cascade_window[0] + int(np.argmax(seg))
    cascade_delay = None
    if cascade.get("anima") is not None and cascade.get("eidolon") is not None:
        cascade_delay = int(cascade["anima"] - cascade["eidolon"])
    recovery_asymmetry = None
    if cascade.get("nous") is not None and cascade.get("eidolon") is not None:
        recovery_asymmetry = int(cascade["eidolon"] - cascade["nous"])
    adaptation_delta = None
    if (per_organ_baseline.get("eidolon") is not None
            and per_organ_recovery.get("eidolon") is not None):
        adaptation_delta = float(
            per_organ_recovery["eidolon"] - per_organ_baseline["eidolon"]
        )

    # ΔΦ Signature 1: DR_ratio = θ_peak / θ_baseline.
    dr_ratio = None
    if theta_baseline is not None and theta_peak is not None and theta_baseline > 1e-9:
        dr_ratio = float(theta_peak / theta_baseline)

    # ΔΦ Signature 2: recovery_profile = (θ_final - θ_min) / (θ_baseline - θ_min).
    recovery_profile = None
    if (theta_baseline is not None and theta_peak is not None
            and theta_final is not None
            and abs(theta_baseline - theta_peak) > 1e-9):
        recovery_profile = float((theta_final - theta_peak) / (theta_baseline - theta_peak))

    # AOS-G summary.
    aos_g_mean = float(delta[BASELINE_WINDOW[0]:].mean()) if delta.size else 0.0
    aos_g_peak = float(delta[PEAK_WINDOW[0]:PEAK_WINDOW[1]].max()) if delta.size else 0.0

    return {
        "trial_id": f"{cfg.mode}__{cfg.perturbation_type}__m{cfg.magnitude:.1f}__s{cfg.seed}",
        "mode": cfg.mode,
        "perturbation_type": cfg.perturbation_type,
        "magnitude": cfg.magnitude,
        "seed": cfg.seed,
        "n_beats": cfg.n_beats,
        "theta_baseline": theta_baseline,
        "theta_peak": theta_peak,
        "theta_final": theta_final,
        "dr_ratio": dr_ratio,
        "recovery_profile": recovery_profile,
        "aos_g_mean": aos_g_mean,
        "aos_g_peak": aos_g_peak,
        "per_organ_theta_baseline": per_organ_baseline,
        "per_organ_theta_peak": per_organ_peak,
        "per_organ_theta_recovery": per_organ_recovery,
        "cascade_time_to_peak": cascade,
        "cascade_delay": cascade_delay,
        "recovery_asymmetry": recovery_asymmetry,
        "adaptation_delta": adaptation_delta,
        "elapsed_s": result.elapsed_s,
    }
