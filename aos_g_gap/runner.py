"""Multi-trial runner for the 21-trial sweep."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from .config import DEFAULT_CONDITIONS, DEFAULT_SEEDS
from .metrics import enrich_events_with_theta, per_trial_summary
from .trial import TrialConfig, TrialResult, run_single_trial


def _save_trial(result: TrialResult, summary: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Per-event JSONL
    with open(out_dir / "compose_events.jsonl", "w") as f:
        for ev in result.per_event:
            f.write(json.dumps(ev, default=_json_default) + "\n")
    # Summary
    with open(out_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=_json_default)
    # Trajectories as compressed NPZ (small enough)
    np.savez_compressed(
        out_dir / "trajectories.npz",
        internal=result.internal_trajectory,
        external=result.external_trajectory,
        delta_norm=result.delta_norm_series,
        integration=result.integration_series,
        self_coherence=result.self_coherence_series,
        **{f"per_organ_delta_{o}": v for o, v in result.per_organ_delta.items()},
        **{f"per_organ_delta_z_{o}": v for o, v in result.per_organ_delta_z.items()},
        **{f"fidelity_{o}": v for o, v in result.fidelity_series.items()},
    )


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(f"Unserializable: {type(o)}")


def run_all_trials(
    conditions: tuple[str, ...] = DEFAULT_CONDITIONS,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
    out_root: Path = Path("results/aos_g_gap"),
    event_window: int = 200,
    event_n_perm: int = 200,
    verbose: bool = True,
) -> list[dict]:
    out_root.mkdir(parents=True, exist_ok=True)
    summaries: list[dict] = []
    total = len(conditions) * len(seeds)
    idx = 0
    t_all = time.monotonic()
    for cond in conditions:
        for seed in seeds:
            idx += 1
            t0 = time.monotonic()
            cfg = TrialConfig(condition=cond, seed=seed)
            result = run_single_trial(cfg, verbose=False)
            enrich_events_with_theta(
                result, event_window=event_window, event_n_perm=event_n_perm
            )
            summary = per_trial_summary(result)
            trial_dir = out_root / "trials" / f"{cond}_s{seed}"
            _save_trial(result, summary, trial_dir)
            summary["trial_dir"] = str(trial_dir)
            summaries.append(summary)
            if verbose:
                print(
                    f"  [{idx:>2}/{total}] {cond:25s} s{seed}  "
                    f"events={summary['n_events']:>3} "
                    f"post/pre={summary['post_pre_ratio']:.2f}  "
                    f"r(θ,Δ)={summary['theta_gap_correlation']:+.3f}  "
                    f"({time.monotonic()-t0:.1f}s)"
                )
    elapsed = time.monotonic() - t_all
    summary_path = out_root / "all_summaries.json"
    with open(summary_path, "w") as f:
        json.dump(summaries, f, indent=2, default=_json_default)
    if verbose:
        print(f"\nDone in {elapsed:.1f}s; summaries → {summary_path}")
    return summaries
