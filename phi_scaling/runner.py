"""25-trial sweep for the φ-scaling experiment."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from control_experiments.config import BASELINE_WINDOW, PEAK_WINDOW, RECOVERY_FINAL_WINDOW
from control_experiments.metrics import trial_summary
from control_experiments.trial import ControlTrialConfig, run_control_trial
from organ.schemas import ORGAN_DIMS, ORGAN_ORDER

from .config import (
    PHI_SCALE_BEATS, PHI_SCALE_COUNTS, PHI_SCALE_FREEZE_AT_BEAT,
    PHI_SCALE_N_PERM, PHI_SCALE_SEEDS,
)
from .intra_theta import compute_intra_organ_theta


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


def _save(result, summary, out_dir: Path) -> None:
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
    )


def _extract_pneuma_window(internal: np.ndarray, beat_lo: int, beat_hi: int) -> np.ndarray:
    """Slice the PNEUMA columns out of the concatenated 27-dim trajectory."""
    start = 0
    for o in ORGAN_ORDER:
        if o == "pneuma":
            return internal[beat_lo:beat_hi, start : start + ORGAN_DIMS["pneuma"]]
        start += ORGAN_DIMS[o]
    raise KeyError("pneuma not in ORGAN_ORDER")


def run_phi_scale_sweep(
    out_root: Path = Path("results/phi_scaling"),
    counts: tuple[int, ...] = PHI_SCALE_COUNTS,
    seeds: tuple[int, ...] = PHI_SCALE_SEEDS,
    n_beats: int = PHI_SCALE_BEATS,
    n_perm: int = PHI_SCALE_N_PERM,
    freeze_at_beat: int = PHI_SCALE_FREEZE_AT_BEAT,
    verbose: bool = True,
) -> list[dict]:
    out_root.mkdir(parents=True, exist_ok=True)
    trials_root = out_root / "trials"
    summaries: list[dict] = []
    total = len(counts) * len(seeds)
    idx = 0
    t_all = time.monotonic()

    for k in counts:
        for seed in seeds:
            idx += 1
            t0 = time.monotonic()
            cfg = ControlTrialConfig(
                mode="phi_scale",
                perturbation_type="baseline",
                magnitude=1.0,
                seed=int(seed),
                n_beats=int(n_beats),
                mode_kwargs={"organ_count": int(k), "freeze_at_beat": int(freeze_at_beat)},
            )
            result = run_control_trial(cfg)
            summary = trial_summary(result, n_perm=n_perm)
            summary["organ_count"] = int(k)
            summary["trial_id"] = f"k{k}__s{seed}"

            # k=1: override θ_baseline with intra-PNEUMA θ.
            if k == 1:
                pne_win = _extract_pneuma_window(
                    result.internal_trajectory, *BASELINE_WINDOW
                )
                r_base = compute_intra_organ_theta(
                    pne_win, "pneuma",
                    n_permutations=n_perm, seed=int(seed),
                )
                summary["theta_baseline"] = float(r_base["theta"])
                summary["theta_baseline_p_value"] = float(r_base["p_value"])
                summary["theta_baseline_significant"] = bool(r_base["significant"])
                summary["theta_baseline_null_95th"] = float(r_base["null_95th"])
                # Also override theta_peak / theta_final consistently.
                for window_name, window in (
                    ("theta_peak", PEAK_WINDOW),
                    ("theta_final", RECOVERY_FINAL_WINDOW),
                ):
                    pw = _extract_pneuma_window(result.internal_trajectory, *window)
                    r_w = compute_intra_organ_theta(
                        pw, "pneuma", n_permutations=n_perm, seed=int(seed) + 1,
                    )
                    summary[window_name] = float(r_w["theta"])
                summary["theta_method"] = "intra_pneuma"
            else:
                summary["theta_method"] = "cross_organ"

            trial_dir = trials_root / summary["trial_id"]
            _save(result, summary, trial_dir)
            summary["trial_dir"] = str(trial_dir)
            summaries.append(summary)

            if verbose:
                t_total = time.monotonic() - t_all
                tb = summary["theta_baseline"]
                print(
                    f"  [{idx:>2}/{total}] k={k} s{seed}  θ_base={tb:.4f}  "
                    f"({time.monotonic()-t0:.2f}s; total {t_total:.0f}s)"
                )

    elapsed = time.monotonic() - t_all
    summary_path = out_root / "all_summaries.json"
    with open(summary_path, "w") as f:
        json.dump(summaries, f, indent=2, default=_json_default)
    if verbose:
        print(f"\nDone in {elapsed:.1f}s; {len(summaries)} trials → {summary_path}")
    return summaries
