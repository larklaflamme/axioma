"""325-trial sweep for Stream 4 control experiments."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from .config import ALL_MODES, MAGNITUDES, PERTURBATION_TYPES, SEEDS
from .metrics import trial_summary
from .trial import ControlTrialConfig, run_control_trial


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


def _save_trial(result, summary, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=_json_default)
    np.savez_compressed(
        out_dir / "trajectories.npz",
        internal=result.internal_trajectory,
        external=result.external_trajectory,
        delta_norm=result.delta_norm_series,
        integration=result.integration_series,
        self_coherence=result.self_coherence_series,
        **{f"per_organ_delta_{o}": v for o, v in result.per_organ_delta.items()},
        **{f"fidelity_{o}": v for o, v in result.fidelity_series.items()},
        dt_history=(result.dt_history if result.dt_history is not None
                    else np.zeros(0, dtype=np.float32)),
    )


def run_all_trials(
    out_root: Path = Path("results/control_experiments"),
    n_perm: int = 100,
    verbose: bool = True,
) -> list[dict]:
    """Run 5 modes × 4 types × 3 magnitudes × 5 seeds + 5 modes × baseline × 5 seeds."""
    out_root.mkdir(parents=True, exist_ok=True)
    trials_root = out_root / "trials"
    summaries: list[dict] = []
    t_all = time.monotonic()
    total = (len(ALL_MODES) * len(PERTURBATION_TYPES) * len(MAGNITUDES) * len(SEEDS)
             + len(ALL_MODES) * len(SEEDS))
    idx = 0

    def _run(cfg: ControlTrialConfig, tag: str) -> dict:
        nonlocal idx
        idx += 1
        t0 = time.monotonic()
        r = run_control_trial(cfg)
        s = trial_summary(r, n_perm=n_perm)
        trial_dir = trials_root / s["trial_id"]
        _save_trial(r, s, trial_dir)
        s["trial_dir"] = str(trial_dir)
        if verbose and idx % 10 == 1:
            elapsed_all = time.monotonic() - t_all
            print(
                f"  [{idx:>3}/{total}] {cfg.mode:9s} {cfg.perturbation_type:22s} "
                f"m={cfg.magnitude:.1f} s{cfg.seed}  ({time.monotonic()-t0:.2f}s; "
                f"total {elapsed_all:.0f}s)"
            )
        return s

    # Sweep: 5 × 4 × 3 × 5 = 300 trials.
    for mode in ALL_MODES:
        for ptype in PERTURBATION_TYPES:
            for mag in MAGNITUDES:
                for seed in SEEDS:
                    cfg = ControlTrialConfig(
                        mode=mode, perturbation_type=ptype,
                        magnitude=float(mag), seed=int(seed),
                    )
                    summaries.append(_run(cfg, tag="sweep"))

    # No-perturbation reference: 5 modes × 5 seeds = 25 trials.
    for mode in ALL_MODES:
        for seed in SEEDS:
            cfg = ControlTrialConfig(
                mode=mode, perturbation_type="baseline",
                magnitude=1.0, seed=int(seed),
            )
            summaries.append(_run(cfg, tag="no_pert"))

    elapsed = time.monotonic() - t_all
    summary_path = out_root / "all_summaries.json"
    with open(summary_path, "w") as f:
        json.dump(summaries, f, indent=2, default=_json_default)
    if verbose:
        print(f"\nDone in {elapsed:.1f}s; {len(summaries)} trials → {summary_path}")
    return summaries
