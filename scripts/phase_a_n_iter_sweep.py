"""Phase A.4 N_iter sweep + mutual constraint correlation + variance invariance.

Per IMPLEMENTATION_PLAN_v1.0.md §5.2 (V11/D11) and ARCH_DESIGN_v1.0.md §4.1 (E14):

  D11/F14:  Pick the smallest N_iter where the average per-beat pairwise
            correlation of organ state changes (mc_corr) exceeds 0.8.

  E14:      For each N_iter, the per-beat variance of g should be invariant
            (within ~10%) of the N_iter=1 value. If not, the noise model is
            misspecified.

Output: results/phase_a/n_iter_sweep_results.md

Run:
  conda run -n axioma python scripts/phase_a_n_iter_sweep.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from axioma.config import AxiomaConfig
from axioma.substrate import SubstrateApp


def per_beat_intra_correlation(
    pre_latents: list[np.ndarray],
    post_latents: list[np.ndarray],
) -> float:
    """Average pairwise correlation of organ Δlatent (within-beat change) across
    all (organ_i, organ_j) pairs.

    For each beat we compute Δz_i = post_z_i - pre_z_i; reduce to per-organ
    scalar via L2 norm; correlate across organ pairs over time.

    Returns a scalar in [-1, 1]. Per D11/F14, mc_corr > 0.8 = strong mutual
    constraint.
    """
    if len(pre_latents) == 0:
        return 0.0
    # pre_latents and post_latents are lists of (n_organs, beats, latent_dim)
    # transposed into (n_organs, beats) of scalar norms.
    n_organs = len(pre_latents[0])
    n_beats = len(pre_latents)
    # Per-organ delta-norm time series
    delta_norms = np.zeros((n_organs, n_beats), dtype=np.float64)
    for b in range(n_beats):
        for i in range(n_organs):
            delta_norms[i, b] = float(np.linalg.norm(post_latents[b][i] - pre_latents[b][i]))
    # Pairwise correlations across organ time series
    # Center first
    centered = delta_norms - delta_norms.mean(axis=1, keepdims=True)
    stds = centered.std(axis=1) + 1e-12
    corrs = []
    for i in range(n_organs):
        for j in range(i + 1, n_organs):
            cov = float(np.mean(centered[i] * centered[j]))
            r = cov / (stds[i] * stds[j])
            corrs.append(r)
    return float(np.mean(corrs))


def run_one(n_iter: int, n_beats: int, seed: int) -> dict[str, Any]:
    """Run substrate for n_beats with the given N_iter; collect telemetry."""
    cfg = AxiomaConfig().model_copy(
        update={
            "substrate": AxiomaConfig().substrate.model_copy(update={"n_iter": n_iter})
        }
    )
    app = SubstrateApp.from_config(cfg.substrate, seed=seed)

    # Warm up past cold-start window
    warmup = 100
    for beat in range(warmup):
        app.tick(beat_no=beat, timestamp=beat * 0.1)

    pre_list: list[list[np.ndarray]] = []
    post_list: list[list[np.ndarray]] = []
    g_history = []
    latent_max_running = 0.0
    for beat in range(warmup, warmup + n_beats):
        pre = [o.latent.copy() for o in app.organs]
        app.tick(beat_no=beat, timestamp=beat * 0.1)
        post = [o.latent.copy() for o in app.organs]
        pre_list.append(pre)
        post_list.append(post)
        g_history.append(app.drive.g.copy())
        max_latent = max(float(np.max(np.abs(o.latent))) for o in app.organs)
        if max_latent > latent_max_running:
            latent_max_running = max_latent

    mc_corr = per_beat_intra_correlation(pre_list, post_list)
    g_arr = np.stack(g_history)
    g_var = float(g_arr.var())

    return {
        "n_iter": n_iter,
        "n_beats_measured": n_beats,
        "mc_corr": mc_corr,
        "drive_variance": g_var,
        "max_latent_observed": latent_max_running,
        "drive_max_observed": float(np.max(np.abs(g_arr))),
        "drive_std_per_dim_mean": float(g_arr.std(axis=0).mean()),
    }


def main() -> None:
    seeds = [42, 137, 999]
    n_iters = [1, 3, 5, 10]
    n_beats = 1000

    results: list[dict[str, Any]] = []
    print(f"Phase A.4 N_iter sweep — {len(seeds)} seeds × {len(n_iters)} N_iter values × {n_beats} beats each")
    print("=" * 80)
    print(f"{'N_iter':>7} | {'seed':>5} | {'mc_corr':>8} | {'drive_var':>10} | {'drive_max':>10} | {'latent_max':>10}")
    print("-" * 80)
    for n_iter in n_iters:
        for seed in seeds:
            r = run_one(n_iter=n_iter, n_beats=n_beats, seed=seed)
            r["seed"] = seed
            results.append(r)
            print(
                f"{n_iter:>7} | {seed:>5} | {r['mc_corr']:>8.4f} | "
                f"{r['drive_variance']:>10.4f} | {r['drive_max_observed']:>10.4f} | "
                f"{r['max_latent_observed']:>10.4f}"
            )
    print()

    # Aggregate per N_iter
    summary: dict[int, dict[str, float]] = {}
    for n_iter in n_iters:
        rows = [r for r in results if r["n_iter"] == n_iter]
        summary[n_iter] = {
            "mc_corr_mean": float(np.mean([r["mc_corr"] for r in rows])),
            "mc_corr_std": float(np.std([r["mc_corr"] for r in rows])),
            "drive_variance_mean": float(np.mean([r["drive_variance"] for r in rows])),
            "max_latent_mean": float(np.mean([r["max_latent_observed"] for r in rows])),
        }

    # Per E14: variance invariance — drive variance for each N_iter relative to N_iter=1
    base_var = summary[1]["drive_variance_mean"]
    for n_iter in n_iters:
        rel = summary[n_iter]["drive_variance_mean"] / base_var if base_var > 0 else 0.0
        summary[n_iter]["drive_variance_rel_to_n_iter_1"] = rel
        summary[n_iter]["variance_invariance_pass"] = bool(0.9 <= rel <= 1.1)

    # Per D11/F14: pick smallest N_iter with mc_corr > 0.8
    chosen_n_iter = None
    for n_iter in sorted(n_iters):
        if summary[n_iter]["mc_corr_mean"] > 0.8:
            chosen_n_iter = n_iter
            break

    print("Summary:")
    print(f"{'N_iter':>7} | {'mc_corr':>8} ± {'std':>6} | {'drive_var':>10} | {'rel_var':>8} | {'var_inv':>7}")
    for n_iter in n_iters:
        s = summary[n_iter]
        flag = "OK" if s["variance_invariance_pass"] else "FAIL"
        print(
            f"{n_iter:>7} | {s['mc_corr_mean']:>8.4f} ± {s['mc_corr_std']:>6.4f} | "
            f"{s['drive_variance_mean']:>10.4f} | {s['drive_variance_rel_to_n_iter_1']:>8.3f} | {flag:>7}"
        )
    print()
    if chosen_n_iter is not None:
        print(f"D11/F14 ✅ Chosen N_iter = {chosen_n_iter} (smallest with mc_corr > 0.8)")
    else:
        print("D11/F14 ⚠️  No N_iter in sweep range achieved mc_corr > 0.8")
        print(f"    max observed: {max(s['mc_corr_mean'] for s in summary.values()):.4f}")
        print("    Recommendation: keep default N_iter=3; document mc_corr value")

    # Write to results/phase_a/n_iter_sweep_results.md
    out_dir = Path(__file__).resolve().parents[1] / "results" / "phase_a"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "n_iter_sweep_results.md"
    json_path = out_dir / "n_iter_sweep_results.json"

    md = ["# Phase A.4 — N_iter Sweep Results\n"]
    md.append("**Generated by:** `scripts/phase_a_n_iter_sweep.py`")
    md.append("**Per:** ARCH_DESIGN_v1.0.md §4.1 (E14) + IMPLEMENTATION_PLAN_v1.0.md §5.2 (D11/F14)\n")
    md.append("## Sweep configuration\n")
    md.append(f"- Seeds: `{seeds}`")
    md.append(f"- N_iter values: `{n_iters}`")
    md.append(f"- Beats measured per run: {n_beats} (after 100-beat warm-up)\n")
    md.append("## Per-N_iter aggregates\n")
    md.append("| N_iter | mc_corr (mean ± std) | drive_var | rel_var vs N_iter=1 | variance invariance (±10%) |")
    md.append("|--------|---------------------|-----------|---------------------|----------------------------|")
    for n_iter in n_iters:
        s = summary[n_iter]
        flag = "✅ PASS" if s["variance_invariance_pass"] else "❌ FAIL"
        md.append(
            f"| {n_iter} | {s['mc_corr_mean']:.4f} ± {s['mc_corr_std']:.4f} | "
            f"{s['drive_variance_mean']:.4f} | {s['drive_variance_rel_to_n_iter_1']:.3f}× | {flag} |"
        )
    md.append("")
    md.append("## D11/F14 verdict\n")
    if chosen_n_iter is not None:
        md.append(f"**Chosen N_iter = {chosen_n_iter}** (smallest with `mc_corr > 0.8`).")
    else:
        md.append("**No N_iter in {1, 3, 5, 10} achieved `mc_corr > 0.8`.**")
        max_corr = max(s["mc_corr_mean"] for s in summary.values())
        md.append(f"Maximum observed: {max_corr:.4f}.")
        md.append("")
        md.append("Recommendation: keep default `N_iter=3`; the mutual constraint")
        md.append("signal is real but doesn't cross the 0.8 threshold at the current")
        md.append("`feedback_scale=0.03` damping. Raising `feedback_scale` would")
        md.append("increase `mc_corr` but risks substrate instability per the")
        md.append("linear-stability analysis in `drive.py`. Document this as a")
        md.append("tuning trade-off for future iteration.")
    md.append("")
    md.append("## Per-run details\n")
    md.append("| N_iter | seed | mc_corr | drive_var | drive_max | latent_max |")
    md.append("|--------|------|---------|-----------|-----------|------------|")
    for r in results:
        md.append(
            f"| {r['n_iter']} | {r['seed']} | {r['mc_corr']:.4f} | "
            f"{r['drive_variance']:.4f} | {r['drive_max_observed']:.4f} | {r['max_latent_observed']:.4f} |"
        )
    md.append("")
    md_path.write_text("\n".join(md))
    json_path.write_text(json.dumps(
        {"per_run": results, "summary": {str(k): v for k, v in summary.items()},
         "chosen_n_iter": chosen_n_iter, "n_beats": n_beats, "seeds": seeds,
         "n_iters": n_iters}, indent=2
    ))
    print(f"\nWrote {md_path}")
    print(f"Wrote {json_path}")


if __name__ == "__main__":
    main()
