"""Per-organ contribution: how much θ changes when each organ is added."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ._loader import load_summaries, theta_by_k_seed

# Per design §2.1: PNEUMA, ANIMA, EIDOLON, MNEME, NOUS — added in that order.
ORGAN_ADDED_AT_K = {2: "anima", 3: "eidolon", 4: "mneme", 5: "nous"}


def run(out_root: Path) -> dict:
    per_k_seed = theta_by_k_seed(load_summaries(out_root))
    contributions = {}
    for k, organ in ORGAN_ADDED_AT_K.items():
        prev_k = k - 1
        common = sorted(set(per_k_seed[k].keys()) & set(per_k_seed[prev_k].keys()))
        deltas = np.array([per_k_seed[k][s] - per_k_seed[prev_k][s] for s in common])
        contributions[organ] = {
            "added_at_k": k,
            "n_seeds": len(common),
            "mean_delta_theta": float(deltas.mean()),
            "std_delta_theta": float(deltas.std(ddof=1)) if len(deltas) > 1 else 0.0,
            "min_delta_theta": float(deltas.min()),
            "max_delta_theta": float(deltas.max()),
        }

    # Rank organs by contribution magnitude.
    ranking = sorted(contributions.items(),
                     key=lambda kv: -abs(kv[1]["mean_delta_theta"]))
    return {
        "analysis": "per_organ_contribution",
        "added_at_k": ORGAN_ADDED_AT_K,
        "contributions": contributions,
        "ranking_by_abs_contribution": [name for name, _ in ranking],
    }
