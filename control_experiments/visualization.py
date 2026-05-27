"""Six plots for Stream 4 controls per IMPLEMENTATION_PLAN.md §7."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from organ.schemas import ORGAN_ORDER

from .analysis._loader import filter_summaries, load_summaries, load_trajectories
from .config import ALL_MODES, MAGNITUDES, MODE_LABELS, PERTURBATION_TYPES


_MODE_COLOR = {
    "baseline":  "#2b8cbe",
    "control1":  "#e34a33",
    "control2":  "#fdae61",
    "control3":  "#d62728",
    "control4":  "#5fb12c",
}


def _setup_dir(out_root: Path) -> Path:
    d = out_root / "figures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def plot_theta_per_mode(out_root: Path) -> Path:
    """Plot 1: θ_baseline distribution per mode (box plots)."""
    summaries = load_summaries(out_root)
    fig, ax = plt.subplots(figsize=(8, 5))
    data = []
    for m in ALL_MODES:
        vals = [s["theta_baseline"] for s in summaries
                if s["mode"] == m and s["theta_baseline"] is not None]
        data.append(vals)
    bp = ax.boxplot(data, labels=[MODE_LABELS[m].split("—")[-1].strip() if "—" in MODE_LABELS[m] else MODE_LABELS[m]
                                  for m in ALL_MODES], patch_artist=True, widths=0.6)
    for patch, m in zip(bp["boxes"], ALL_MODES):
        patch.set_facecolor(_MODE_COLOR[m])
        patch.set_alpha(0.55)
    ax.set_ylabel("θ_baseline (beats 100-200 internal trajectory)")
    ax.set_title("θ comparison across control modes")
    ax.grid(True, axis="y", alpha=0.3)
    ax.tick_params(axis="x", rotation=14, labelsize=8)
    out = _setup_dir(out_root) / "1_theta_per_mode.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_dr_u_curves(out_root: Path) -> Path:
    """Plot 2: DR_ratio U-curves per mode (one line per perturbation type)."""
    summaries = load_summaries(out_root)
    fig, axes = plt.subplots(1, len(ALL_MODES), figsize=(16, 4), sharey=True)
    for ax, m in zip(axes, ALL_MODES):
        for ptype in PERTURBATION_TYPES:
            curve = []
            for mag in MAGNITUDES:
                subset = filter_summaries(summaries, mode=m, perturbation_type=ptype, magnitude=mag)
                drs = [s["dr_ratio"] for s in subset if s["dr_ratio"] is not None]
                curve.append(np.mean(drs) if drs else np.nan)
            ax.plot(MAGNITUDES, curve, marker="o", label=ptype, lw=1.2)
        ax.axhline(2.0, color="black", ls=":", lw=0.8, label="conscious thresh (DR=2)")
        ax.set_title(MODE_LABELS[m], fontsize=8)
        ax.set_xlabel("perturbation magnitude")
        ax.grid(True, alpha=0.3)
        ax.tick_params(axis="x", labelsize=8)
    axes[0].set_ylabel("DR_ratio = θ_peak / θ_baseline")
    axes[-1].legend(fontsize=6, loc="upper right")
    fig.suptitle("S1 Dynamic Range: DR(magnitude) per mode × type", fontsize=11)
    fig.tight_layout()
    out = _setup_dir(out_root) / "2_dr_u_curves.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_recovery_bars(out_root: Path) -> Path:
    """Plot 3: recovery_profile mean per (mode, perturbation_type)."""
    summaries = load_summaries(out_root)
    fig, ax = plt.subplots(figsize=(12, 4))
    n_modes = len(ALL_MODES)
    n_types = len(PERTURBATION_TYPES)
    x = np.arange(n_modes)
    width = 0.8 / n_types
    for i, ptype in enumerate(PERTURBATION_TYPES):
        means = []
        errs = []
        for m in ALL_MODES:
            subset = filter_summaries(summaries, mode=m, perturbation_type=ptype)
            rps = [s["recovery_profile"] for s in subset if s["recovery_profile"] is not None]
            means.append(np.mean(rps) if rps else np.nan)
            errs.append(np.std(rps, ddof=1) if len(rps) > 1 else 0.0)
        ax.bar(x + i * width - 0.4 + width / 2, means, width, yerr=errs, label=ptype, capsize=2)
    ax.axhline(0.5, color="black", ls=":", lw=0.8, label="conscious thresh (0.5)")
    ax.set_xticks(x)
    ax.set_xticklabels([m for m in ALL_MODES], rotation=10, fontsize=8)
    ax.set_ylabel("recovery_profile = (θ_final − θ_peak)/(θ_baseline − θ_peak)")
    ax.set_title("S2 Recovery Dynamics per (mode, type)")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, axis="y", alpha=0.3)
    out = _setup_dir(out_root) / "3_recovery_bars.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_cs_heatmap(out_root: Path) -> Path:
    """Plot 4: Context-sensitivity heatmap (mode × magnitude)."""
    summaries = load_summaries(out_root)
    M = np.full((len(ALL_MODES), len(MAGNITUDES)), np.nan)
    for i, m in enumerate(ALL_MODES):
        for j, mag in enumerate(MAGNITUDES):
            type_means = []
            for ptype in PERTURBATION_TYPES:
                subset = filter_summaries(summaries, mode=m, perturbation_type=ptype, magnitude=mag)
                vals = [s["theta_peak"] for s in subset if s["theta_peak"] is not None]
                if vals:
                    type_means.append(np.mean(vals))
            if len(type_means) >= 2:
                mu = float(np.mean(type_means))
                sd = float(np.std(type_means, ddof=1))
                M[i, j] = sd / mu if abs(mu) > 1e-9 else np.nan

    fig, ax = plt.subplots(figsize=(6, 4))
    im = ax.imshow(M, aspect="auto", cmap="viridis", vmin=0, vmax=0.3)
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            ax.text(j, i, f"{M[i,j]:.3f}" if not np.isnan(M[i, j]) else "—",
                    ha="center", va="center", fontsize=8, color="white")
    ax.set_xticks(range(len(MAGNITUDES))); ax.set_xticklabels([f"{m:.1f}" for m in MAGNITUDES])
    ax.set_yticks(range(len(ALL_MODES))); ax.set_yticklabels(ALL_MODES)
    ax.set_xlabel("perturbation magnitude"); ax.set_ylabel("control mode")
    ax.set_title("S3 Context Sensitivity  (σ/μ across types; conscious thresh = 0.20)")
    fig.colorbar(im, ax=ax, fraction=0.04)
    out = _setup_dir(out_root) / "4_cs_heatmap.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_cascade_ladder(out_root: Path) -> Path:
    """Plot 5: cascade time-to-peak per organ per mode (direct_contradiction)."""
    summaries = load_summaries(out_root)
    fig, ax = plt.subplots(figsize=(10, 5))
    n_modes = len(ALL_MODES)
    width = 0.8 / n_modes
    x = np.arange(len(ORGAN_ORDER))
    for i, m in enumerate(ALL_MODES):
        subset = filter_summaries(summaries, mode=m, perturbation_type="direct_contradiction")
        means = []
        for o in ORGAN_ORDER:
            ttp = [s["cascade_time_to_peak"][o] for s in subset
                   if s.get("cascade_time_to_peak", {}).get(o) is not None]
            means.append(np.mean(ttp) if ttp else np.nan)
        ax.bar(x + i * width - 0.4 + width / 2, means, width,
               label=m, color=_MODE_COLOR[m], alpha=0.85)
    ax.set_xticks(x); ax.set_xticklabels([o.upper() for o in ORGAN_ORDER])
    ax.set_ylabel("time-to-peak (beat)")
    ax.axhline(200, color="black", ls=":", lw=0.8, label="perturbation start")
    ax.set_ylim(195, 250)
    ax.set_title("Self-model cascade — direct_contradiction, time-to-peak per organ")
    ax.legend(fontsize=7, ncol=3)
    out = _setup_dir(out_root) / "5_cascade_ladder.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_aos_g_per_mode(out_root: Path) -> Path:
    """Plot 6: AOS-G gap mean ± SE per mode."""
    summaries = load_summaries(out_root)
    fig, ax = plt.subplots(figsize=(7, 4))
    xs = np.arange(len(ALL_MODES))
    means = []
    errs = []
    for m in ALL_MODES:
        vals = [s["aos_g_mean"] for s in summaries if s["mode"] == m]
        means.append(np.mean(vals) if vals else 0.0)
        errs.append(np.std(vals, ddof=1) / np.sqrt(len(vals)) if len(vals) > 1 else 0.0)
    ax.bar(xs, means, yerr=errs, capsize=3,
           color=[_MODE_COLOR[m] for m in ALL_MODES], alpha=0.85)
    for i, v in enumerate(means):
        ax.text(i, v + 0.05, f"{v:.2f}", ha="center", fontsize=8)
    ax.set_xticks(xs); ax.set_xticklabels(ALL_MODES, rotation=10)
    ax.set_ylabel("mean AOS-G gap (delta_norm)")
    ax.set_title("AOS-G gap per mode — Control 4 is 0 by construction")
    ax.grid(True, axis="y", alpha=0.3)
    out = _setup_dir(out_root) / "6_aos_g_per_mode.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_all(out_root: Path) -> list[Path]:
    return [
        plot_theta_per_mode(out_root),
        plot_dr_u_curves(out_root),
        plot_recovery_bars(out_root),
        plot_cs_heatmap(out_root),
        plot_cascade_ladder(out_root),
        plot_aos_g_per_mode(out_root),
    ]
