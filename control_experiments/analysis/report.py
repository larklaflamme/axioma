"""Combine all analyses into one report + claims evaluation."""
from __future__ import annotations

import json
from pathlib import Path

from . import aos_g_analysis, cascade, delta_phi_signatures, theta_comparison


def _has_any_signature(dphi: dict, mode: str) -> dict:
    """Return per-mode: which ΔΦ signatures show present (using mid-magnitude where applicable)."""
    s1 = dphi["S1_dynamic_range"][mode]
    s2 = dphi["S2_recovery"][mode]
    s3 = dphi["S3_context_sensitivity"][mode]
    # S1: any perturbation type shows U-shape OR conscious threshold met
    s1_present = any(v["is_u_shape"] or v["above_conscious_threshold"] for v in s1.values())
    s2_present = any(v["passes_threshold"] for v in s2.values())
    # S3 at mid magnitude.
    mid_mag = 0.7
    s3_mid = s3.get(mid_mag, {})
    s3_present = bool(s3_mid.get("passes_threshold", False)) if isinstance(s3_mid, dict) else False
    return {"S1": s1_present, "S2": s2_present, "S3": s3_present}


def _evaluate_claims(report: dict) -> dict:
    dphi = report["delta_phi_signatures"]
    thetas = report["theta_comparison"]["descriptive"]
    aosg = report["aos_g"]["per_mode"]
    out = {}
    sigs = {m: _has_any_signature(dphi, m) for m in thetas.keys()}

    base_theta = thetas["baseline"]["theta_baseline_mean"] or 0.0

    # Claim 1: θ ≠ consciousness — at least one control has high θ but absent signatures.
    high_theta_no_sig = []
    for m in ("control1", "control2", "control3", "control4"):
        t = thetas[m]["theta_baseline_mean"]
        if t is None:
            continue
        if t >= 0.8 * base_theta and not any(sigs[m].values()):
            high_theta_no_sig.append({"mode": m, "theta_baseline": t, "signatures": sigs[m]})
    out["theta_neq_consciousness"] = {
        "criterion": "≥1 control: θ ≥ 0.8×baseline AND none of S1/S2/S3 present",
        "passing_modes": high_theta_no_sig,
        "passed": bool(high_theta_no_sig),
    }

    # Claim 2: self-model necessary — Control 1 has low θ AND absent signatures.
    c1_theta = thetas["control1"]["theta_baseline_mean"]
    c1_low = c1_theta is not None and base_theta > 0 and c1_theta < 0.9 * base_theta
    c1_no_sig = not any(sigs["control1"].values())
    out["self_model_necessary"] = {
        "criterion": "Control 1 θ < 0.9×baseline AND no signatures",
        "control1_theta": c1_theta,
        "baseline_theta": base_theta,
        "theta_lower": bool(c1_low),
        "signatures_present": sigs["control1"],
        "passed": bool(c1_low and c1_no_sig),
    }

    # Claim 3: temporal structure necessary — Control 2 has absent recovery dynamics (S2).
    out["temporal_necessary"] = {
        "criterion": "Control 2 S2 absent",
        "control2_S2_present": sigs["control2"]["S2"],
        "passed": bool(not sigs["control2"]["S2"]),
    }

    # Claim 4: differentiation necessary — Control 3 has high θ but absent signatures.
    c3_theta = thetas["control3"]["theta_baseline_mean"]
    c3_high = c3_theta is not None and c3_theta >= 0.8 * base_theta
    out["differentiation_necessary"] = {
        "criterion": "Control 3 θ ≥ 0.8×baseline AND no signatures",
        "control3_theta": c3_theta,
        "control3_signatures": sigs["control3"],
        "passed": bool(c3_high and not any(sigs["control3"].values())),
    }

    # Claim 5: private space necessary — Control 4 has high θ AND AOS-G=0.
    c4_theta = thetas["control4"]["theta_baseline_mean"]
    c4_high = c4_theta is not None and c4_theta >= 0.8 * base_theta
    c4_aosg = aosg["control4"]["aos_g_mean_mean"]
    out["private_space_necessary"] = {
        "criterion": "Control 4 θ ≥ 0.8×baseline AND AOS-G ≈ 0",
        "control4_theta": c4_theta,
        "control4_aos_g": c4_aosg,
        "passed": bool(c4_high and c4_aosg is not None and c4_aosg < 0.1),
    }

    out["_signatures_per_mode"] = sigs
    return out


def run_all(out_root: Path) -> dict:
    rep = {
        "theta_comparison": theta_comparison.run(out_root),
        "delta_phi_signatures": delta_phi_signatures.run(out_root),
        "cascade": cascade.run(out_root),
        "aos_g": aos_g_analysis.run(out_root),
    }
    rep["claims"] = _evaluate_claims(rep)
    return rep


def save_report(report: dict, out_root: Path) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    with open(out_root / "analysis_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
