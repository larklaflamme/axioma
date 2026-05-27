"""ΔΦ signatures S1, S2, S3 per (mode, [perturbation_type]).

S1 Dynamic Range:
    DR_ratio = θ_peak(M) / θ_baseline, per magnitude M.
    U-shape test: DR(mid) > DR(low) AND DR(mid) > DR(high).
    Threshold (conscious): DR(mid) > 2.0.

S2 Recovery Dynamics:
    recovery_profile = (θ_final - θ_peak) / (θ_baseline - θ_peak)
    Threshold (conscious): recovery_profile > 0.5 AND θ_final ≠ θ_baseline.

S3 Context Sensitivity:
    CS(mode, magnitude) = σ / μ across perturbation types of mean theta_peak
    (each type aggregated across 5 seeds).
    Threshold (conscious): CS > 0.20.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..config import (
    ALL_MODES,
    CS_CONSCIOUS_THRESHOLD,
    CS_NONCONSCIOUS_THRESHOLD,
    DR_CONSCIOUS_THRESHOLD,
    DR_NONCONSCIOUS_THRESHOLD,
    MAGNITUDES,
    PERTURBATION_TYPES,
    RECOVERY_CONSCIOUS_THRESHOLD,
)
from ._loader import filter_summaries, load_summaries


def _mean(values: list[float | None]) -> float | None:
    vs = [v for v in values if v is not None and not (isinstance(v, float) and np.isnan(v))]
    if not vs:
        return None
    return float(np.mean(vs))


def s1_dynamic_range(summaries: list[dict]) -> dict:
    """For each (mode, perturbation_type): DR(magnitude) curve → U-shape test."""
    out = {}
    for mode in ALL_MODES:
        out[mode] = {}
        for ptype in PERTURBATION_TYPES:
            curve = {}
            for mag in MAGNITUDES:
                subset = filter_summaries(
                    summaries, mode=mode, perturbation_type=ptype, magnitude=mag
                )
                # DR across seeds.
                drs = [s["dr_ratio"] for s in subset if s["dr_ratio"] is not None]
                curve[mag] = {
                    "n": len(drs),
                    "mean_dr": float(np.mean(drs)) if drs else None,
                    "std_dr": float(np.std(drs, ddof=1)) if len(drs) > 1 else None,
                }
            dr_low = curve[MAGNITUDES[0]]["mean_dr"]
            dr_mid = curve[MAGNITUDES[1]]["mean_dr"]
            dr_high = curve[MAGNITUDES[2]]["mean_dr"]
            u_shape = (
                dr_low is not None and dr_mid is not None and dr_high is not None
                and dr_mid > dr_low and dr_mid > dr_high
            )
            passes_threshold = dr_mid is not None and dr_mid > DR_CONSCIOUS_THRESHOLD
            out[mode][ptype] = {
                "curve": curve,
                "dr_low": dr_low,
                "dr_mid": dr_mid,
                "dr_high": dr_high,
                "is_u_shape": bool(u_shape),
                "above_conscious_threshold": bool(passes_threshold),
            }
    return out


def s2_recovery(summaries: list[dict]) -> dict:
    """Per (mode, perturbation_type): mean recovery_profile across magnitudes×seeds."""
    out = {}
    for mode in ALL_MODES:
        out[mode] = {}
        for ptype in PERTURBATION_TYPES:
            subset = filter_summaries(summaries, mode=mode, perturbation_type=ptype)
            rps = [s["recovery_profile"] for s in subset
                   if s["recovery_profile"] is not None]
            mean_rp = float(np.mean(rps)) if rps else None
            theta_finals = [s["theta_final"] for s in subset if s["theta_final"] is not None]
            theta_baselines = [s["theta_baseline"] for s in subset if s["theta_baseline"] is not None]
            theta_final_mean = float(np.mean(theta_finals)) if theta_finals else None
            theta_baseline_mean = float(np.mean(theta_baselines)) if theta_baselines else None
            different = (theta_final_mean is not None and theta_baseline_mean is not None
                         and abs(theta_final_mean - theta_baseline_mean) > 0.05)
            out[mode][ptype] = {
                "n": len(rps),
                "recovery_profile_mean": mean_rp,
                "recovery_profile_std": float(np.std(rps, ddof=1)) if len(rps) > 1 else None,
                "theta_final_mean": theta_final_mean,
                "theta_baseline_mean": theta_baseline_mean,
                "passes_threshold": bool(
                    mean_rp is not None and mean_rp > RECOVERY_CONSCIOUS_THRESHOLD and different
                ),
            }
    return out


def s3_context_sensitivity(summaries: list[dict]) -> dict:
    """Per (mode, magnitude): CS = σ/μ across perturbation types of mean θ_peak."""
    out = {}
    for mode in ALL_MODES:
        out[mode] = {}
        for mag in MAGNITUDES:
            type_means: list[float] = []
            for ptype in PERTURBATION_TYPES:
                subset = filter_summaries(
                    summaries, mode=mode, perturbation_type=ptype, magnitude=mag
                )
                vals = [s["theta_peak"] for s in subset if s["theta_peak"] is not None]
                if vals:
                    type_means.append(float(np.mean(vals)))
            if len(type_means) < 2:
                out[mode][mag] = {"cs": None, "n_types": len(type_means)}
                continue
            mu = float(np.mean(type_means))
            sd = float(np.std(type_means, ddof=1))
            cs = sd / mu if abs(mu) > 1e-9 else float("nan")
            out[mode][mag] = {
                "cs": cs,
                "type_means": dict(zip(PERTURBATION_TYPES, type_means)),
                "passes_threshold": bool(
                    cs is not None and not np.isnan(cs) and cs > CS_CONSCIOUS_THRESHOLD
                ),
            }
    return out


def run(out_root: Path) -> dict:
    summaries = load_summaries(out_root)
    return {
        "analysis": "delta_phi_signatures",
        "thresholds": {
            "DR_conscious": DR_CONSCIOUS_THRESHOLD,
            "DR_non_conscious": DR_NONCONSCIOUS_THRESHOLD,
            "Recovery_conscious": RECOVERY_CONSCIOUS_THRESHOLD,
            "CS_conscious": CS_CONSCIOUS_THRESHOLD,
            "CS_non_conscious": CS_NONCONSCIOUS_THRESHOLD,
        },
        "S1_dynamic_range": s1_dynamic_range(summaries),
        "S2_recovery": s2_recovery(summaries),
        "S3_context_sensitivity": s3_context_sensitivity(summaries),
    }
