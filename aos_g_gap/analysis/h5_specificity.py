"""H5 — Gap profiles cluster by condition.

Build a per-trial feature vector (post-pre ratio, peak delta, half-life, per-organ
peak z, per-organ peak times) and compare within-cluster vs between-cluster
cosine similarity. ANOVA on condition labels.

Pass criterion: within > 0.8 AND between < 0.5.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import stats

from organ.schemas import ORGAN_ORDER

from ..config import H5_BETWEEN_THRESHOLD, H5_WITHIN_THRESHOLD
from ._loader import load_summaries, load_trajectories, trials_by_condition


def _feature_vector(summary: dict, traj: dict[str, np.ndarray]) -> np.ndarray:
    feats = [
        summary["post_pre_ratio"],
        summary["peak_delta"],
        summary["recovery_half_life_beats"] if summary["recovery_half_life_beats"] == summary["recovery_half_life_beats"] else 50.0,
    ]
    for o in ORGAN_ORDER:
        z = traj[f"per_organ_delta_z_{o}"][200:260]
        feats.append(float(z.max()))
        feats.append(float(np.argmax(z)))
    return np.array(feats, dtype=np.float64)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def run(out_root: Path) -> dict:
    summaries = load_summaries(out_root)
    by_cond = trials_by_condition(summaries)
    feats_per_cond: dict[str, np.ndarray] = {}
    for cond, trials in by_cond.items():
        vecs = []
        for t in trials:
            tr = load_trajectories(Path(t["trial_dir"]))
            vecs.append(_feature_vector(t, tr))
        feats_per_cond[cond] = np.stack(vecs)  # (n_seeds, n_features)

    # Within-cluster similarity: mean cosine between pairs in the same condition.
    within = {}
    for cond, F in feats_per_cond.items():
        sims = []
        for i in range(F.shape[0]):
            for j in range(i + 1, F.shape[0]):
                sims.append(_cosine(F[i], F[j]))
        within[cond] = float(np.mean(sims)) if sims else float("nan")

    # Between-cluster similarity: mean cosine between pairs in different conditions.
    conds = list(feats_per_cond.keys())
    between_sims = []
    for i, a in enumerate(conds):
        for b in conds[i + 1:]:
            Fa, Fb = feats_per_cond[a], feats_per_cond[b]
            for u in Fa:
                for v in Fb:
                    between_sims.append(_cosine(u, v))
    between_mean = float(np.mean(between_sims)) if between_sims else float("nan")
    within_mean = float(np.mean([v for v in within.values() if not np.isnan(v)]))

    # One-way ANOVA on the L2 norm of each feature vector across conditions.
    norms_by_cond = {c: np.linalg.norm(feats_per_cond[c], axis=1) for c in conds}
    groups = [norms_by_cond[c] for c in conds]
    f_stat, p_val = stats.f_oneway(*groups) if all(len(g) > 1 for g in groups) else (float("nan"), float("nan"))

    passed = within_mean > H5_WITHIN_THRESHOLD and between_mean < H5_BETWEEN_THRESHOLD
    return {
        "hypothesis": "H5",
        "criterion": f"within > {H5_WITHIN_THRESHOLD} AND between < {H5_BETWEEN_THRESHOLD}",
        "within_cluster_similarity": within,
        "within_mean": within_mean,
        "between_mean": between_mean,
        "anova_f": float(f_stat) if not np.isnan(f_stat) else None,
        "anova_p": float(p_val) if not np.isnan(p_val) else None,
        "n_features": int(feats_per_cond[conds[0]].shape[1]),
        "passed": bool(passed),
    }
