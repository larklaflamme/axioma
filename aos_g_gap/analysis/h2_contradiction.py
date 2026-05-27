"""H2 — Contradiction increases gap by >20% (post/pre).

Pass criterion: mean(delta_norm, beats 200-230) > 1.2 × mean(delta_norm, beats 170-200)
in the direct_contradiction condition. Compared against baseline as control.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import stats

from ..config import H2_POST_WINDOW, H2_PRE_WINDOW, H2_RATIO_THRESHOLD
from ._loader import load_summaries, load_trajectories, trials_by_condition


def _pre_post_means(traj: np.ndarray) -> tuple[float, float]:
    pre = float(traj[H2_PRE_WINDOW[0] : H2_PRE_WINDOW[1]].mean())
    post = float(traj[H2_POST_WINDOW[0] : H2_POST_WINDOW[1]].mean())
    return pre, post


def run(out_root: Path) -> dict:
    summaries = load_summaries(out_root)
    by_cond = trials_by_condition(summaries)
    out_per_cond: dict[str, dict] = {}
    for cond, trials in by_cond.items():
        pres = []
        posts = []
        for t in trials:
            tr = load_trajectories(Path(t["trial_dir"]))
            pre, post = _pre_post_means(tr["delta_norm"])
            pres.append(pre)
            posts.append(post)
        pres_arr = np.array(pres)
        posts_arr = np.array(posts)
        diffs = posts_arr - pres_arr
        # Paired t-test across the 3 seeds.
        t_stat, p_val = stats.ttest_rel(posts_arr, pres_arr) if len(diffs) >= 2 else (float("nan"), float("nan"))
        out_per_cond[cond] = {
            "n_seeds": len(trials),
            "pre_mean": float(pres_arr.mean()),
            "post_mean": float(posts_arr.mean()),
            "ratio": float(posts_arr.mean() / pres_arr.mean()) if pres_arr.mean() > 1e-9 else float("nan"),
            "per_seed_ratios": [float(p / r) if r > 1e-9 else float("nan")
                                for r, p in zip(pres, posts)],
            "diff_mean": float(diffs.mean()),
            "diff_std": float(diffs.std(ddof=1)) if len(diffs) > 1 else 0.0,
            "t_stat": float(t_stat) if not np.isnan(t_stat) else None,
            "p_value": float(p_val) if not np.isnan(p_val) else None,
        }

    contradiction = out_per_cond.get("direct_contradiction", {})
    passed = (
        contradiction.get("ratio", 0.0) > H2_RATIO_THRESHOLD
    )
    return {
        "hypothesis": "H2",
        "criterion": f"direct_contradiction post/pre > {H2_RATIO_THRESHOLD}",
        "per_condition": out_per_cond,
        "contradiction_ratio": contradiction.get("ratio"),
        "passed": bool(passed),
    }
