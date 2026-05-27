"""Self-model cascade metrics per ΔΦ §6: cascade_delay, recovery_asymmetry,
adaptation_delta. Aggregated across (mode, perturbation_type)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..config import ALL_MODES, PERTURBATION_TYPES
from ._loader import filter_summaries, load_summaries


def run(out_root: Path) -> dict:
    summaries = load_summaries(out_root)
    out = {"analysis": "cascade", "per_mode_type": {}}
    for mode in ALL_MODES:
        out["per_mode_type"][mode] = {}
        for ptype in PERTURBATION_TYPES:
            subset = filter_summaries(summaries, mode=mode, perturbation_type=ptype)
            cd = [s["cascade_delay"] for s in subset if s["cascade_delay"] is not None]
            ra = [s["recovery_asymmetry"] for s in subset if s["recovery_asymmetry"] is not None]
            ad = [s["adaptation_delta"] for s in subset if s["adaptation_delta"] is not None]
            out["per_mode_type"][mode][ptype] = {
                "n": len(subset),
                "cascade_delay_mean": float(np.mean(cd)) if cd else None,
                "cascade_delay_std": float(np.std(cd, ddof=1)) if len(cd) > 1 else None,
                "recovery_asymmetry_mean": float(np.mean(ra)) if ra else None,
                "adaptation_delta_mean": float(np.mean(ad)) if ad else None,
                "adaptation_delta_abs_mean": float(np.mean(np.abs(ad))) if ad else None,
            }
    return out
