"""AOS-G gap analysis: mean delta_norm per mode + Tukey HSD."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import stats

from ..config import ALL_MODES
from ._loader import load_summaries


def run(out_root: Path) -> dict:
    summaries = load_summaries(out_root)
    per_mode = {}
    groups = []
    for m in ALL_MODES:
        vals = [s["aos_g_mean"] for s in summaries if s["mode"] == m]
        per_mode[m] = {
            "n": len(vals),
            "aos_g_mean_mean": float(np.mean(vals)) if vals else None,
            "aos_g_mean_std": float(np.std(vals, ddof=1)) if len(vals) > 1 else None,
            "aos_g_peak_mean": float(np.mean(
                [s["aos_g_peak"] for s in summaries if s["mode"] == m])) if vals else None,
        }
        groups.append(vals)

    f_stat, p_val = stats.f_oneway(*groups) if all(len(g) > 1 for g in groups) else (float("nan"), float("nan"))

    try:
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
                "p_adj": float(row[3]),
                "reject": bool(row[6]),
            })
    except Exception as e:
        tukey_rows = [{"error": str(e)}]

    return {
        "analysis": "aos_g",
        "per_mode": per_mode,
        "anova_f": float(f_stat) if not np.isnan(f_stat) else None,
        "anova_p": float(p_val) if not np.isnan(p_val) else None,
        "tukey_hsd": tukey_rows,
    }
