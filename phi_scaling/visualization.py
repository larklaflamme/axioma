"""Four plots for the φ-scaling experiment per IMPLEMENTATION_PLAN.md §5."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .analysis._loader import load_summaries, theta_array, theta_by_k_seed
from .analysis.scaling_fits import fit_linear, fit_quadratic
from .analysis.per_organ_contribution import ORGAN_ADDED_AT_K, run as run_poc


def _setup_dir(out_root: Path) -> Path:
    d = out_root / "figures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def plot_theta_curve(out_root: Path) -> Path:
    """Plot 1: θ(k) ± SE across seeds with both fitted models overlaid."""
    summaries = load_summaries(out_root)
    per_k = theta_by_k_seed(summaries)
    ks = sorted(per_k.keys())
    means = np.array([np.mean(list(per_k[k].values())) for k in ks])
    sems = np.array([
        np.std(list(per_k[k].values()), ddof=1) / np.sqrt(len(per_k[k]))
        for k in ks
    ])
    # Scatter of individual trials too.
    k_arr, theta_arr = theta_array(summaries)

    lin = fit_linear(k_arr, theta_arr)
    quad = fit_quadratic(k_arr, theta_arr)
    k_dense = np.linspace(0.8, 5.2, 100)
    lin_curve = lin["params"]["a"] * k_dense + lin["params"]["b"]
    quad_curve = quad["params"]["c"] * k_dense**2 + quad["params"]["d"] * k_dense + quad["params"]["e"]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(k_arr, theta_arr, color="gray", alpha=0.5, s=24, label="individual seeds")
    ax.errorbar(ks, means, yerr=sems, fmt="o-", color="black",
                lw=1.8, capsize=4, ms=6, label="mean ± SE")
    ax.plot(k_dense, lin_curve, ls="--", color="#2b8cbe",
            label=f"linear fit (R²={lin['r2']:.2f}, AIC={lin['aic']:.1f})")
    ax.plot(k_dense, quad_curve, ls="--", color="#d62728",
            label=f"quadratic fit (R²={quad['r2']:.2f}, AIC={quad['aic']:.1f})")
    ax.set_xlabel("k (active organ count, PNEUMA-first)")
    ax.set_ylabel("θ (Gaussian copula MI / energy)")
    ax.set_title("θ vs k — φ-scaling sweep (5 seeds × 5 k-values)")
    ax.set_xticks(ks)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, loc="upper right")
    out = _setup_dir(out_root) / "1_theta_curve.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_per_organ_contribution(out_root: Path) -> Path:
    """Plot 2: Δθ when each organ is added."""
    poc = run_poc(out_root)["contributions"]
    organs = list(ORGAN_ADDED_AT_K.values())
    means = [poc[o]["mean_delta_theta"] for o in organs]
    stds = [poc[o]["std_delta_theta"] for o in organs]
    colors = ["#2b8cbe" if m >= 0 else "#d62728" for m in means]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.bar(organs, means, yerr=stds, color=colors, alpha=0.85, capsize=4)
    ax.axhline(0, color="black", lw=0.8)
    for bar, m in zip(bars, means):
        ax.text(bar.get_x() + bar.get_width() / 2, m + (0.04 if m >= 0 else -0.08),
                f"{m:+.3f}", ha="center", fontsize=9,
                color="black", fontweight="bold")
    ax.set_ylabel("Δθ added (mean across 5 seeds)")
    ax.set_title("Per-organ contribution to θ (PNEUMA-first ordering)")
    ax.grid(True, axis="y", alpha=0.3)
    for tick, k in zip(ax.get_xticklabels(), ORGAN_ADDED_AT_K.keys()):
        tick.set_text(f"{tick.get_text().upper()}\n(added at k={k})")
    ax.set_xticklabels([f"{o.upper()}\n(added at k={k})"
                        for k, o in ORGAN_ADDED_AT_K.items()])
    out = _setup_dir(out_root) / "2_per_organ_contribution.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_residuals(out_root: Path) -> Path:
    """Plot 3: linear vs quadratic fit residuals."""
    summaries = load_summaries(out_root)
    k_arr, theta_arr = theta_array(summaries)
    lin = fit_linear(k_arr, theta_arr)
    quad = fit_quadratic(k_arr, theta_arr)
    lin_pred = lin["params"]["a"] * k_arr + lin["params"]["b"]
    quad_pred = quad["params"]["c"] * k_arr**2 + quad["params"]["d"] * k_arr + quad["params"]["e"]
    lin_res = theta_arr - lin_pred
    quad_res = theta_arr - quad_pred

    fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=True)
    for ax, res, name in (
        (axes[0], lin_res, f"Linear (R²={lin['r2']:.3f})"),
        (axes[1], quad_res, f"Quadratic (R²={quad['r2']:.3f})"),
    ):
        ax.scatter(k_arr, res, color="#444", alpha=0.7, s=30)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_xticks(sorted(set(k_arr.astype(int))))
        ax.set_xlabel("k")
        ax.set_title(f"{name} fit residuals")
        ax.grid(True, alpha=0.3)
    axes[0].set_ylabel("residual (θ − fit)")
    fig.suptitle("Residuals: structure not captured by either polynomial fit", fontsize=10)
    out = _setup_dir(out_root) / "3_residuals.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_predictions_vs_observed(out_root: Path) -> Path:
    """Plot 4: Theoria's predictions overlaid with observed θ."""
    summaries = load_summaries(out_root)
    per_k = theta_by_k_seed(summaries)
    ks = sorted(per_k.keys())
    observed = np.array([np.mean(list(per_k[k].values())) for k in ks])
    sems = np.array([np.std(list(per_k[k].values()), ddof=1) / np.sqrt(len(per_k[k]))
                     for k in ks])

    # Predictions per design doc §3.1 and §3.2.
    # Theoria's predictions (design §3.2):
    theoria_pred = np.array([0.0, 0.15, 0.50, 1.00, 1.74])
    # Thea's O(k) prediction with Δ = (θ5 - θ1)/4 calibrated to observed.
    theta1, theta5 = observed[0], observed[-1]
    delta_linear = (theta5 - theta1) / 4
    thea_linear = np.array([theta1 + i * delta_linear for i in range(5)])
    # Thea's O(k²) prediction with Δ = (θ5 - θ1)/10 (pairs grow as k(k-1)/2).
    delta_quad = (theta5 - theta1) / 10
    pairs = np.array([0, 1, 3, 6, 10])
    thea_quad = theta1 + pairs * delta_quad

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.errorbar(ks, observed, yerr=sems, fmt="o-", color="black",
                lw=1.8, capsize=4, ms=6, label="observed (mean ± SE)")
    ax.plot(ks, theoria_pred, marker="s", ls="--", color="#9467bd",
            label="Theoria's prediction (§3.2)")
    ax.plot(ks, thea_linear, marker="^", ls=":", color="#2b8cbe",
            label="Thea O(k) prediction (calibrated)")
    ax.plot(ks, thea_quad, marker="v", ls=":", color="#d62728",
            label="Thea O(k²) prediction (calibrated)")
    ax.set_xlabel("k (active organ count)")
    ax.set_ylabel("θ")
    ax.set_title("Predictions vs observed θ (PNEUMA-first ordering)")
    ax.set_xticks(ks)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, loc="upper left")
    out = _setup_dir(out_root) / "4_predictions_vs_observed.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_all(out_root: Path) -> list[Path]:
    return [
        plot_theta_curve(out_root),
        plot_per_organ_contribution(out_root),
        plot_residuals(out_root),
        plot_predictions_vs_observed(out_root),
    ]
