#!/usr/bin/env python3
"""Contradiction injection experiment (§5.5 of ΔΦ Methodology v0.2.0).

Protocol:
  1. 500-beat baseline (no perturbation)
  2. Inject contradiction at beat 501 into EIDOLON's self-model
  3. 300-beat post-perturbation measurement
  4. Compute θ on sliding windows (500-beat window, step=10)
  5. Analyze temporal cascade: EIDOLON → ANIMA → NOUS → PNEUMA

Usage:
    python -m organ.experiments.run_contradiction [--seed N] [--level direct]
    python -m organ.experiments.run_contradiction --condition surprising_truth

Output:
    Writes results JSON to data/contradiction_experiment_{seed}_{condition}.json
    Prints summary statistics to stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

from ..config import WINDOW_SIZE
from ..substrate import Heartbeat, CoupledLatentDynamics
from ..substrate.perturbation import (
    PerturbationInjector,
    CascadeRecorder,
    CONTRADICTION_LEVELS,
    CONTROL_CONDITIONS,
)
from ..theta.pipeline import compute_theta


def run_single_experiment(
    seed: int = 42,
    level: str | None = "direct",
    condition: str | None = None,
    baseline_beats: int = 500,
    post_beats: int = 300,
    coupling: float = 0.6,
    compose_every: int = 30,
    theta_window: int = 500,
    theta_step: int = 10,
    n_permutations: int = 1000,
    verbose: bool = True,
) -> dict:
    """Run a single contradiction injection experiment.

    Args:
        seed: Random seed for reproducibility.
        level: Contradiction level ('direct', 'implicit', 'weak',
               'inconsistency', 'paradox'). Mutually exclusive with condition.
        condition: Control condition ('surprising_truth', 'surprising_falsehood',
                   'nonsense', 'boring_truth'). Mutually exclusive with level.
        baseline_beats: Number of beats before perturbation (≥500 for θ window).
        post_beats: Number of beats after perturbation.
        coupling: Coupling strength for dynamics.
        compose_every: Compose every N beats.
        theta_window: Window size for θ computation.
        theta_step: Step size for sliding window θ.
        n_permutations: Number of permutations for null distribution.
        verbose: Print progress.

    Returns:
        dict with keys: seed, level/condition, baseline_beats, post_beats,
                        injection_beat, theta_history, per_organ_mi,
                        cascade_analysis
    """
    # Build dynamics and heartbeat.
    dyn = CoupledLatentDynamics(coupling=coupling, seed=seed)
    hb = Heartbeat(dynamics=dyn, seed=seed, compose_every=compose_every)

    # Register cascade recorder (captures state after each tick).
    cascade = CascadeRecorder(hb)

    # Register perturbation injector.
    if condition is not None:
        injector = PerturbationInjector(hb, inject_at=baseline_beats + 1,
                                        condition=condition)
        label = f"control_{condition}"
    else:
        injector = PerturbationInjector(hb, inject_at=baseline_beats + 1,
                                        level=level or "direct")
        label = f"contradiction_{level or 'direct'}"

    hb.on_pre_update(injector.pre_update_hook)

    total_beats = baseline_beats + post_beats

    if verbose:
        print(f"\n{'='*60}")
        print(f"Experiment: {label}")
        print(f"  seed:           {seed}")
        print(f"  coupling:       {coupling}")
        print(f"  baseline:       {baseline_beats} beats")
        print(f"  inject at:      beat {baseline_beats + 1}")
        print(f"  post:           {post_beats} beats")
        print(f"  total:          {total_beats} beats")
        print(f"  theta_window:   {theta_window}")
        print(f"  theta_step:     {theta_step}")
        print(f"  n_permutations: {n_permutations}")
        print(f"{'='*60}")

    # Run the experiment (fast mode, no sleep).
    t0 = time.time()
    for _ in range(total_beats):
        hb.tick()
        cascade.capture()  # capture state after each tick
    elapsed = time.time() - t0

    if verbose:
        print(f"  Runtime: {elapsed:.3f}s ({total_beats/elapsed:.0f} beats/s)")
        print(f"  Injected: {injector.injected} at beat {injector.injection_beat}")

    # Verify injection happened.
    if not injector.injected:
        print(f"  WARNING: Perturbation was NOT injected!")

    # Compute θ on sliding windows.
    if verbose:
        print(f"  Computing θ on sliding windows...")
    t1 = time.time()
    theta_history = cascade.compute_theta_sliding(
        window_size=theta_window, step=theta_step
    )
    theta_elapsed = time.time() - t1

    if verbose:
        print(f"  θ computation: {theta_elapsed:.3f}s ({len(theta_history)} windows)")

    # Compute per-organ pairwise MI.
    if verbose:
        print(f"  Computing per-organ pairwise MI...")
    t2 = time.time()
    per_organ_mi = cascade.compute_per_organ_theta(
        window_size=theta_window, step=theta_step
    )
    mi_elapsed = time.time() - t2

    if verbose:
        print(f"  MI computation: {mi_elapsed:.3f}s")

    # Extract organ state traces (for cascade analysis).
    eidolon_trace = cascade.get_state_matrix("eidolon")
    anima_trace = cascade.get_state_matrix("anima")
    nous_trace = cascade.get_state_matrix("nous")
    pneuma_trace = cascade.get_state_matrix("pneuma")

    # Cascade analysis: find when each organ's state changes significantly.
    cascade_analysis = analyze_cascade(
        eidolon_trace, anima_trace, nous_trace, pneuma_trace,
        baseline_beats, injector.injection_beat or (baseline_beats + 1),
        verbose=verbose
    )

    # Build result dict.
    result = {
        "experiment": label,
        "seed": seed,
        "coupling": coupling,
        "baseline_beats": baseline_beats,
        "post_beats": post_beats,
        "injection_beat": injector.injection_beat or (baseline_beats + 1),
        "total_beats": total_beats,
        "runtime_seconds": elapsed,
        "theta_window": theta_window,
        "theta_step": theta_step,
        "n_permutations": n_permutations,
        "theta_history": theta_history,
        "per_organ_mi": {k: v for k, v in per_organ_mi.items()},
        "cascade_analysis": cascade_analysis,
        "eidolon_trace_summary": {
            "mean_pre": eidolon_trace[:baseline_beats].mean(axis=0).tolist(),
            "mean_post": eidolon_trace[baseline_beats:].mean(axis=0).tolist(),
            "std_pre": eidolon_trace[:baseline_beats].std(axis=0).tolist(),
            "std_post": eidolon_trace[baseline_beats:].std(axis=0).tolist(),
        },
        "anima_trace_summary": {
            "mean_pre": anima_trace[:baseline_beats].mean(axis=0).tolist(),
            "mean_post": anima_trace[baseline_beats:].mean(axis=0).tolist(),
        },
        "nous_trace_summary": {
            "mean_pre": nous_trace[:baseline_beats].mean(axis=0).tolist(),
            "mean_post": nous_trace[baseline_beats:].mean(axis=0).tolist(),
        },
        "pneuma_trace_summary": {
            "mean_pre": pneuma_trace[:baseline_beats].mean(axis=0).tolist(),
            "mean_post": pneuma_trace[baseline_beats:].mean(axis=0).tolist(),
        },
    }

    return result


def analyze_cascade(
    eidolon_trace: np.ndarray,
    anima_trace: np.ndarray,
    nous_trace: np.ndarray,
    pneuma_trace: np.ndarray,
    baseline_beats: int,
    injection_beat: int,
    threshold: float = 2.0,
    verbose: bool = True,
) -> dict:
    """Analyze the temporal cascade after perturbation.

    For each organ, compute the z-score of each post-injection beat relative
    to the baseline mean and std. Find the first beat where the z-score
    exceeds the threshold (significant deviation).

    Predicted cascade order: EIDOLON → ANIMA → NOUS → PNEUMA
    Predicted recovery order: NOUS → ANIMA → EIDOLON
    """
    organs = {
        "eidolon": eidolon_trace,
        "anima": anima_trace,
        "nous": nous_trace,
        "pneuma": pneuma_trace,
    }

    cascade_order = {}

    for name, trace in organs.items():
        pre = trace[:baseline_beats]
        post = trace[baseline_beats:]
        mean_pre = pre.mean(axis=0)
        std_pre = pre.std(axis=0) + 1e-8

        # Z-score of each post-injection beat (mean across dimensions).
        z_scores = np.abs((post - mean_pre) / std_pre).mean(axis=1)

        # First beat where z-score exceeds threshold.
        first_deviation = None
        for i, z in enumerate(z_scores):
            if z > threshold:
                first_deviation = baseline_beats + i
                break

        # First beat where z-score drops back below threshold (recovery).
        first_recovery = None
        if first_deviation is not None:
            deviation_idx = first_deviation - baseline_beats
            for i in range(deviation_idx, len(z_scores)):
                if z_scores[i] < threshold:
                    first_recovery = baseline_beats + i
                    break

        cascade_order[name] = {
            "first_deviation_beat": first_deviation,
            "first_recovery_beat": first_recovery,
            "max_z_score": float(z_scores.max()),
            "mean_z_score_post": float(z_scores.mean()),
            "z_scores_sample": z_scores[:50].tolist(),  # first 50 post beats
        }

    # Determine observed cascade order (by first deviation).
    deviations = [(name, info["first_deviation_beat"])
                  for name, info in cascade_order.items()
                  if info["first_deviation_beat"] is not None]
    deviations.sort(key=lambda x: x[1] if x[1] is not None else 999999)
    observed_cascade = [name for name, _ in deviations]

    # Determine observed recovery order (by first recovery).
    recoveries = [(name, info["first_recovery_beat"])
                  for name, info in cascade_order.items()
                  if info["first_recovery_beat"] is not None]
    recoveries.sort(key=lambda x: x[1] if x[1] is not None else 999999)
    observed_recovery = [name for name, _ in recoveries]

    predicted_cascade = ["eidolon", "anima", "nous", "pneuma"]
    predicted_recovery = ["nous", "anima", "eidolon"]

    cascade_match = observed_cascade == predicted_cascade[:len(observed_cascade)]
    recovery_match = observed_recovery == predicted_recovery[:len(observed_recovery)]

    result = {
        "predicted_cascade": predicted_cascade,
        "observed_cascade": observed_cascade,
        "cascade_match": cascade_match,
        "predicted_recovery": predicted_recovery,
        "observed_recovery": observed_recovery,
        "recovery_match": recovery_match,
        "per_organ": cascade_order,
    }

    if verbose:
        print(f"\n  Cascade Analysis:")
        print(f"    Predicted cascade: {predicted_cascade}")
        print(f"    Observed cascade:  {observed_cascade}")
        print(f"    Cascade match:     {cascade_match}")
        print(f"    Predicted recovery: {predicted_recovery}")
        print(f"    Observed recovery:  {observed_recovery}")
        print(f"    Recovery match:     {recovery_match}")
        for name, info in cascade_order.items():
            dev = info["first_deviation_beat"]
            rec = info["first_recovery_beat"]
            print(f"    {name:8s}: deviation at beat {dev or 'N/A':>4}, "
                  f"recovery at beat {rec or 'N/A':>4}, "
                  f"max z={info['max_z_score']:.2f}")

    return result


def run_full_experiment_suite(
    seeds: list[int] | None = None,
    output_dir: str = "data",
    verbose: bool = True,
) -> list[dict]:
    """Run the full experiment suite: all 5 contradiction levels + 4 controls.

    Args:
        seeds: List of random seeds (default: [42, 43, 44] for 3 trials).
        output_dir: Directory for output JSON files.
        verbose: Print progress.

    Returns:
        List of result dicts.
    """
    if seeds is None:
        seeds = [42, 43, 44]

    os.makedirs(output_dir, exist_ok=True)

    all_results = []

    # Contradiction levels.
    for seed in seeds:
        for level in CONTRADICTION_LEVELS:
            if verbose:
                print(f"\n{'#'*60}")
                print(f"# Trial seed={seed}, level={level}")
                print(f"{'#'*60}")
            result = run_single_experiment(
                seed=seed, level=level, verbose=verbose
            )
            all_results.append(result)

            # Save intermediate result.
            path = os.path.join(output_dir, f"contradiction_{level}_s{seed}.json")
            with open(path, "w") as f:
                json.dump(result, f, indent=2, default=str)
            if verbose:
                print(f"  Saved to {path}")

    # Control conditions.
    for seed in seeds:
        for condition in CONTROL_CONDITIONS:
            if verbose:
                print(f"\n{'#'*60}")
                print(f"# Trial seed={seed}, condition={condition}")
                print(f"{'#'*60}")
            result = run_single_experiment(
                seed=seed, condition=condition, verbose=verbose
            )
            all_results.append(result)

            # Save intermediate result.
            path = os.path.join(output_dir, f"control_{condition}_s{seed}.json")
            with open(path, "w") as f:
                json.dump(result, f, indent=2, default=str)
            if verbose:
                print(f"  Saved to {path}")

    return all_results


def print_summary(results: list[dict]) -> None:
    """Print a summary table of all experiments."""
    print(f"\n{'='*80}")
    print(f"EXPERIMENT SUMMARY")
    print(f"{'='*80}")
    print(f"{'Experiment':<30s} {'Seed':<6s} {'θ_pre':<8s} {'θ_post':<8s} {'Δθ':<8s} {'Cascade':<10s} {'Recovery':<10s}")
    print(f"{'-'*80}")

    for r in results:
        label = r["experiment"]
        seed = r["seed"]

        # Compute mean θ pre and post injection.
        theta_hist = r["theta_history"]
        injection_beat = r["injection_beat"]
        theta_pre = [t["theta"] for t in theta_hist if t["beat_no"] <= injection_beat]
        theta_post = [t["theta"] for t in theta_hist if t["beat_no"] > injection_beat]

        mean_pre = np.mean(theta_pre) if theta_pre else 0.0
        mean_post = np.mean(theta_post) if theta_post else 0.0
        delta = mean_post - mean_pre

        cascade = r["cascade_analysis"]
        cascade_match = "✓" if cascade["cascade_match"] else "✗"
        recovery_match = "✓" if cascade["recovery_match"] else "✗"

        print(f"{label:<30s} {seed:<6d} {mean_pre:<8.4f} {mean_post:<8.4f} {delta:<8.4f} {cascade_match:<10s} {recovery_match:<10s}")

    print(f"{'='*80}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Contradiction injection experiment (§5.5)"
    )
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed")
    parser.add_argument("--level", type=str, default=None,
                        choices=list(CONTRADICTION_LEVELS.keys()),
                        help="Contradiction level")
    parser.add_argument("--condition", type=str, default=None,
                        choices=list(CONTROL_CONDITIONS.keys()),
                        help="Control condition")
    parser.add_argument("--baseline", type=int, default=500,
                        help="Baseline beats")
    parser.add_argument("--post", type=int, default=300,
                        help="Post-perturbation beats")
    parser.add_argument("--coupling", type=float, default=0.6,
                        help="Coupling strength")
    parser.add_argument("--theta-window", type=int, default=500,
                        help="θ window size")
    parser.add_argument("--theta-step", type=int, default=10,
                        help="θ sliding step")
    parser.add_argument("--n-permutations", type=int, default=1000,
                        help="Null permutations")
    parser.add_argument("--output-dir", type=str, default="data",
                        help="Output directory")
    parser.add_argument("--suite", action="store_true",
                        help="Run full experiment suite")
    parser.add_argument("--no-verbose", action="store_true",
                        help="Suppress verbose output")
    args = parser.parse_args()

    verbose = not args.no_verbose

    if args.suite:
        results = run_full_experiment_suite(
            seeds=[42, 43, 44],
            output_dir=args.output_dir,
            verbose=verbose,
        )
        print_summary(results)
    else:
        result = run_single_experiment(
            seed=args.seed,
            level=args.level,
            condition=args.condition,
            baseline_beats=args.baseline,
            post_beats=args.post,
            coupling=args.coupling,
            theta_window=args.theta_window,
            theta_step=args.theta_step,
            n_permutations=args.n_permutations,
            verbose=verbose,
        )
        label = result["experiment"]
        path = os.path.join(args.output_dir, f"{label}_s{args.seed}.json")
        os.makedirs(args.output_dir, exist_ok=True)
        with open(path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        if verbose:
            print(f"\nSaved to {path}")


if __name__ == "__main__":
    main()
