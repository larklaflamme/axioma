"""θ comparison across modes: one-way ANOVA + Tukey HSD on θ_baseline.

Also reports descriptive stats for θ_baseline, θ_peak, θ_final per mode.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import stats

from ..config import ALL_MODES
from ._loader import load_summaries


def run(out_root: Path) -> dict:
    summaries = load_summaries(out_root)
    # Use only the no-perturbation reference trials per mode for a clean
    # θ_baseline comparison (other trials have perturbations that affect θ_peak
    # and θ_final but θ_baseline ∈ [100, 200] is pre-perturbation).
    # Actually all trials have a pre-perturbation θ_baseline window, so we pool
    # all trials per mode for descriptive stats but pool no-pert for the
    # cleanest comparison.
    descriptive: dict[str, dict] = {}
    for m in ALL_MODES:
        bm = [s["theta_baseline"] for s in summaries
              if s["mode"] == m and s["theta_baseline"] is not None]
        pm = [s["theta_peak"] for s in summaries
              if s["mode"] == m and s["theta_peak"] is not None]
        fm = [s["theta_final"] for s in summaries
              if s["mode"] == m and s["theta_final"] is not None]
        descriptive[m] = {
            "n": len(bm),
            "theta_baseline_mean": float(np.mean(bm)) if bm else None,
            "theta_baseline_std": float(np.std(bm, ddof=1)) if len(bm) > 1 else None,
            "theta_peak_mean": float(np.mean(pm)) if pm else None,
            "theta_final_mean": float(np.mean(fm)) if fm else None,
        }

    # ANOVA across modes on θ_baseline.
    groups = [
        [s["theta_baseline"] for s in summaries
         if s["mode"] == m and s["theta_baseline"] is not None]
        for m in ALL_MODES
    ]
    f_stat, p_val = stats.f_oneway(*groups) if all(len(g) > 1 for g in groups) else (float("nan"), float("nan"))

    # Tukey HSD on θ_baseline.
    try:
        import statsmodels.api as sm
        from statsmodels.stats.multicomp import pairwise_tukeyhsd

        data: list[float] = []
        labels: list[str] = []
        for m, g in zip(ALL_MODES, groups):
            data.extend(g)
            labels.extend([m] * len(g))
        tukey = pairwise_tukeyhsd(data, labels)
        tukey_rows = []
        for row in tukey.summary().data[1:]:
            tukey_rows.append({
                "group1": str(row[0]),
                "group2": str(row[1]),
                "meandiff": float(row[2]),
                "p_adj": float(row[3]) if str(row[3]) != "0.001" else 0.001,
                "lower": float(row[4]),
                "upper": float(row[5]),
                "reject": bool(row[6]),
            })
    except Exception as e:
        tukey_rows = [{"error": str(e)}]

    return {
        "analysis": "theta_comparison",
        "descriptive": descriptive,
        "anova_f": float(f_stat) if not np.isnan(f_stat) else None,
        "anova_p": float(p_val) if not np.isnan(p_val) else None,
        "tukey_hsd": tukey_rows,
    }
