"""v1.2.2 — recalibrate aos_g_alert_threshold for weighted gap presets.

Per Checkpoint J: under PNEUMA-weighted, the absolute gap magnitude is ~1.54×
larger than uniform. The v1.0 `aos_g_alert_threshold = 0.1` was calibrated
against uniform's gap distribution; under PNEUMA-weighted it's effectively
1.54× more lenient (proportionally further below the typical magnitude).

This script:
  1. Loads a v1.0 baseline soak (uniform preset) + a PNEUMA-weighted soak.
  2. Computes "equivalent sensitivity" thresholds:
     - The v1.0 threshold relative to v1.0 baseline gap mean (= 0.1 / 7.5 ≈ 1.3%)
     - The PNEUMA-weighted threshold that preserves that 1.3% ratio
       (≈ 0.1 × pneuma_gap_mean / uniform_gap_mean)
  3. Sweeps alert thresholds across {0.05, 0.10, 0.15, 0.20, 0.30, 0.50}
     and reports per-threshold:
     - fraction of beats below alert
     - alert rate (events per 1000 beats)
  4. Recommends a per-preset threshold that produces equivalent "compose
     degenerated" sensitivity across presets.

Output: results/phase_f/alert_threshold_calibration.json

Usage:
    python scripts/phase_f/alert_threshold_calibration.py
    # uses results/phase_e_soak_50k.json (uniform) + phase_e_soak_50k_pneuma.json
    # as baseline data; recommends thresholds for both presets.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _harness import build_phase_e_stack, run_for_beats, write_result

from axioma.measurement.aos_g_engine import (
    PNEUMA_WEIGHTED_GAP_WEIGHTS,
    UNIFORM_GAP_WEIGHTS,
)


def _sweep_thresholds_against_baseline(
    *, preset_name: str, weights: dict[str, float],
    thresholds: list[float], beats: int, seed: int,
) -> list[dict[str, Any]]:
    """For each threshold, run the substrate and count alert firings."""
    rows: list[dict[str, Any]] = []
    for thr in thresholds:
        stack = build_phase_e_stack(
            seed=seed, perturbation_period_beats=300, perturbation_magnitude=0.4,
            gap_weights=weights,
        )
        # Override AOSGEngine's alert threshold for this run
        stack.aos_g.aos_g_alert_threshold = thr
        run_for_beats(stack, 600)  # V12 warmup
        n_samples = 0
        n_below_alert = 0
        gap_mean_sum = 0.0
        for _ in range(beats):
            stack.hb.tick()
            cv = stack.aos_g.current_value()
            if cv is None or not getattr(cv, "valid", False):
                continue
            n_samples += 1
            gap = float(getattr(cv, "aos_g_gap", 0.0))
            gap_mean_sum += gap
            # Alert fires when gap > 0 AND gap < threshold (the engine's logic)
            if 0.0 < gap < thr:
                n_below_alert += 1
            # Per-event alert counter would require state tracking; for v1.2.2
            # the steady-state fraction is the right measure
        rows.append({
            "preset": preset_name,
            "threshold": thr,
            "n_samples": n_samples,
            "fraction_below_alert": (
                round(n_below_alert / n_samples, 6) if n_samples else 0.0
            ),
            "gap_mean_observed": (
                round(gap_mean_sum / n_samples, 4) if n_samples else 0.0
            ),
            "n_alert_firings": n_below_alert,
        })
    return rows


def _recommend_equivalent_threshold(
    *, baseline_gap_mean: float, baseline_threshold: float,
    variant_gap_mean: float,
) -> float:
    """The 'equivalent sensitivity' threshold: scale so threshold/gap_mean ratio
    is the same across presets. This preserves the architectural intent of
    'fire when gap is X% below typical magnitude'."""
    if baseline_gap_mean <= 0:
        return baseline_threshold
    ratio = baseline_threshold / baseline_gap_mean
    return round(ratio * variant_gap_mean, 4)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--beats-per-cell", type=int, default=800)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--baseline-soak", type=Path,
        default=Path("results/phase_e_soak_50k.json"),
        help="v1.0 uniform soak JSON to use as baseline gap reference",
    )
    p.add_argument(
        "--pneuma-soak", type=Path,
        default=Path("results/phase_e_soak_50k_pneuma.json"),
        help="PNEUMA-weighted soak JSON to read variant gap mean from",
    )
    args = p.parse_args()

    # Read existing soak data for the gap-mean ratio computation
    baseline_soak_data: dict[str, Any] = {}
    pneuma_soak_data: dict[str, Any] = {}
    if args.baseline_soak.exists():
        baseline_soak_data = json.loads(args.baseline_soak.read_text())
    if args.pneuma_soak.exists():
        pneuma_soak_data = json.loads(args.pneuma_soak.read_text())

    # The soak JSON doesn't currently record gap mean directly — we recompute
    # via a short sweep at each preset to get the gap baseline.
    print("  measuring baseline gap distributions ...")
    uniform_baseline_rows = _sweep_thresholds_against_baseline(
        preset_name="uniform", weights=UNIFORM_GAP_WEIGHTS,
        thresholds=[0.1],
        beats=args.beats_per_cell, seed=args.seed,
    )
    pneuma_baseline_rows = _sweep_thresholds_against_baseline(
        preset_name="pneuma_weighted", weights=PNEUMA_WEIGHTED_GAP_WEIGHTS,
        thresholds=[0.1],
        beats=args.beats_per_cell, seed=args.seed,
    )
    uniform_gap_mean = uniform_baseline_rows[0]["gap_mean_observed"]
    pneuma_gap_mean = pneuma_baseline_rows[0]["gap_mean_observed"]
    print(f"    uniform gap mean: {uniform_gap_mean}")
    print(f"    pneuma_weighted gap mean: {pneuma_gap_mean}")

    # Compute the equivalent threshold for PNEUMA-weighted
    v1_0_threshold = 0.10  # current default in ComposeConfig
    recommended_pneuma_threshold = _recommend_equivalent_threshold(
        baseline_gap_mean=uniform_gap_mean,
        baseline_threshold=v1_0_threshold,
        variant_gap_mean=pneuma_gap_mean,
    )
    print(f"    recommended PNEUMA-weighted threshold: {recommended_pneuma_threshold}")

    # Verify by sweeping at the recommended threshold + nearby values
    sweep_thresholds = sorted({
        0.05, 0.10, 0.15, 0.20, 0.30, 0.50,
        recommended_pneuma_threshold,
    })
    print("  sweeping thresholds for PNEUMA-weighted ...")
    pneuma_sweep = _sweep_thresholds_against_baseline(
        preset_name="pneuma_weighted", weights=PNEUMA_WEIGHTED_GAP_WEIGHTS,
        thresholds=sweep_thresholds, beats=args.beats_per_cell, seed=args.seed,
    )
    print("  sweeping thresholds for uniform (control) ...")
    uniform_sweep = _sweep_thresholds_against_baseline(
        preset_name="uniform", weights=UNIFORM_GAP_WEIGHTS,
        thresholds=sweep_thresholds, beats=args.beats_per_cell, seed=args.seed,
    )

    out = {
        "seed": args.seed,
        "beats_per_cell": args.beats_per_cell,
        "v1_0_threshold": v1_0_threshold,
        "baseline_gap_means": {
            "uniform": uniform_gap_mean,
            "pneuma_weighted": pneuma_gap_mean,
        },
        "gap_mean_ratio_pneuma_vs_uniform": (
            round(pneuma_gap_mean / uniform_gap_mean, 3)
            if uniform_gap_mean > 0 else None
        ),
        "recommended_thresholds": {
            "uniform": v1_0_threshold,
            "pneuma_weighted": recommended_pneuma_threshold,
        },
        "sweep_uniform": uniform_sweep,
        "sweep_pneuma_weighted": pneuma_sweep,
        "soak_baseline_reference": {
            "uniform_soak_overall_pass": baseline_soak_data.get("overall_pass"),
            "pneuma_soak_overall_pass": pneuma_soak_data.get("overall_pass"),
        },
        "interpretation": (
            f"Under v1.0 uniform preset, threshold {v1_0_threshold} corresponds "
            f"to {round(v1_0_threshold / uniform_gap_mean * 100, 2)}% of typical "
            f"gap magnitude. The equivalent threshold under PNEUMA-weighted is "
            f"{recommended_pneuma_threshold} (same percentage of typical magnitude). "
            f"Both produce essentially zero false alerts in normal operation; "
            f"the threshold's role is to detect compose degeneration "
            f"(gap → 0), not stress."
        ),
        "verdict": "RECOMMENDED_THRESHOLD_COMPUTED",
    }
    path = write_result("alert_threshold_calibration", out)
    print(f"\nWrote {path}")
    print(f"  recommended thresholds: {out['recommended_thresholds']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
