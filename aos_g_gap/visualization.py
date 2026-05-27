"""Five plots per design §6.3.

Plots saved to <out_root>/figures/.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from organ.schemas import ORGAN_ORDER

from .analysis._loader import load_summaries, load_trajectories, trials_by_condition


def _setup_dir(out_root: Path) -> Path:
    fig_dir = out_root / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    return fig_dir


def plot_gap_time_series(out_root: Path) -> Path:
    """Plot 1: delta_norm vs beat per condition, mean ± SE bands across seeds."""
    summaries = load_summaries(out_root)
    by_cond = trials_by_condition(summaries)
    conditions = list(by_cond.keys())
    fig, axes = plt.subplots(len(conditions), 1, figsize=(10, 2.2 * len(conditions)), sharex=True)
    if len(conditions) == 1:
        axes = [axes]
    for ax, cond in zip(axes, conditions):
        seeds_data = []
        for t in by_cond[cond]:
            tr = load_trajectories(Path(t["trial_dir"]))
            seeds_data.append(tr["delta_norm"])
        D = np.stack(seeds_data, axis=0)  # (n_seeds, n_beats)
        mu = D.mean(axis=0)
        se = D.std(axis=0, ddof=1) / np.sqrt(D.shape[0])
        beats = np.arange(D.shape[1])
        ax.fill_between(beats, mu - se, mu + se, alpha=0.3, label="±SE across seeds")
        ax.plot(beats, mu, lw=1.0)
        ax.axvspan(200, 220, color="red", alpha=0.08, label="perturbation")
        ax.set_ylabel(cond, fontsize=8)
        ax.tick_params(axis="y", labelsize=7)
    axes[-1].set_xlabel("beat")
    fig.suptitle("AOS-G gap (delta_norm) by condition", fontsize=11)
    out = _setup_dir(out_root) / "1_gap_time_series.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_per_organ_heatmap(out_root: Path) -> Path:
    """Plot 2: organ × beat heatmap for the direct_contradiction condition."""
    summaries = load_summaries(out_root)
    by_cond = trials_by_condition(summaries)
    cond = "direct_contradiction"
    Z_stack = []
    for t in by_cond[cond]:
        tr = load_trajectories(Path(t["trial_dir"]))
        z = np.stack([tr[f"per_organ_delta_z_{o}"] for o in ORGAN_ORDER], axis=0)
        Z_stack.append(z)
    Z = np.mean(np.stack(Z_stack, axis=0), axis=0)  # (5, n_beats)

    fig, ax = plt.subplots(figsize=(10, 3.5))
    im = ax.imshow(
        Z,
        aspect="auto",
        cmap="RdBu_r",
        vmin=-5,
        vmax=5,
        interpolation="nearest",
    )
    ax.set_yticks(range(len(ORGAN_ORDER)))
    ax.set_yticklabels([o.upper() for o in ORGAN_ORDER])
    ax.set_xlabel("beat")
    ax.set_title(f"Per-organ z-normalized delta — {cond}, mean across seeds")
    ax.axvline(200, color="black", lw=0.8, ls=":")
    ax.axvline(220, color="black", lw=0.8, ls=":")
    cbar = fig.colorbar(im, ax=ax, fraction=0.025)
    cbar.set_label("z (vs pre-perturbation baseline)", fontsize=8)
    out = _setup_dir(out_root) / "2_per_organ_heatmap.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_theta_gap_scatter(out_root: Path) -> Path:
    """Plot 3: θ vs delta_norm at each compose event, colored by condition."""
    summaries = load_summaries(out_root)
    fig, ax = plt.subplots(figsize=(8, 6))
    palette = plt.cm.tab10.colors
    cond_color = {}
    for i, c in enumerate(set(s["condition"] for s in summaries)):
        cond_color[c] = palette[i % len(palette)]
    xs_all, ys_all = [], []
    for s in summaries:
        td = Path(s["trial_dir"])
        events = [json.loads(l) for l in open(td / "compose_events.jsonl")]
        xs = [e["internal_theta"] for e in events if e.get("internal_theta") is not None]
        ys = [e["delta_norm"] for e in events if e.get("internal_theta") is not None]
        ax.scatter(xs, ys, color=cond_color[s["condition"]], alpha=0.5, s=10, edgecolor="none")
        xs_all.extend(xs); ys_all.extend(ys)
    # Single legend
    for c, color in cond_color.items():
        ax.scatter([], [], color=color, label=c)
    ax.legend(fontsize=7, loc="upper left", framealpha=0.9)
    ax.set_xlabel("internal θ")
    ax.set_ylabel("delta_norm (AOS-G gap)")
    if len(xs_all) >= 5:
        r = float(np.corrcoef(xs_all, ys_all)[0, 1])
        ax.set_title(f"θ vs delta_norm (pooled events; r = {r:+.3f})")
    out = _setup_dir(out_root) / "3_theta_gap_scatter.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_cascade_delays(out_root: Path) -> Path:
    """Plot 4: time-to-peak per organ × condition (differential vs baseline)."""
    summaries = load_summaries(out_root)
    by_cond = trials_by_condition(summaries)
    if "baseline" not in by_cond:
        return Path()

    baseline_by_seed = {t["seed"]: load_trajectories(Path(t["trial_dir"])) for t in by_cond["baseline"]}

    conditions = [c for c in by_cond if c != "baseline"]
    time_to_peak = {c: {o: [] for o in ORGAN_ORDER} for c in conditions}
    for cond in conditions:
        for t in by_cond[cond]:
            tr = load_trajectories(Path(t["trial_dir"]))
            base = baseline_by_seed.get(t["seed"])
            if base is None:
                continue
            for o in ORGAN_ORDER:
                diff = tr[f"per_organ_delta_{o}"] - base[f"per_organ_delta_{o}"]
                seg = diff[200:260]
                time_to_peak[cond][o].append(200 + int(np.argmax(seg)))

    # Bar chart
    fig, ax = plt.subplots(figsize=(10, 5))
    n_cond = len(conditions)
    x = np.arange(len(ORGAN_ORDER))
    width = 0.8 / n_cond
    for i, cond in enumerate(conditions):
        means = [float(np.mean(time_to_peak[cond][o])) for o in ORGAN_ORDER]
        errs = [float(np.std(time_to_peak[cond][o])) for o in ORGAN_ORDER]
        ax.bar(x + i * width - 0.4 + width / 2, means, width, label=cond, yerr=errs, capsize=2)
    ax.set_xticks(x)
    ax.set_xticklabels([o.upper() for o in ORGAN_ORDER])
    ax.set_ylabel("Time-to-peak (beat)")
    ax.set_title("Cascade time-to-peak per organ (differential vs baseline)")
    ax.axhline(200, color="black", ls=":", lw=0.7, label="perturbation start")
    ax.legend(fontsize=7, ncol=2)
    out = _setup_dir(out_root) / "4_cascade_delays.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_granger_network(out_root: Path) -> Path:
    """Plot 5: Granger causality directed graph between organs (direct_contradiction)."""
    from statsmodels.tsa.stattools import grangercausalitytests
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning)

    summaries = load_summaries(out_root)
    contradiction = [s for s in summaries if s["condition"] == "direct_contradiction"]
    if not contradiction:
        return Path()
    baseline_by_seed = {s["seed"]: load_trajectories(Path(s["trial_dir"]))
                       for s in summaries if s["condition"] == "baseline"}
    # Pooled differential per-organ delta time series across seeds.
    pooled = {o: [] for o in ORGAN_ORDER}
    for s in contradiction:
        tr = load_trajectories(Path(s["trial_dir"]))
        base = baseline_by_seed.get(s["seed"])
        if base is None:
            continue
        for o in ORGAN_ORDER:
            pooled[o].append(tr[f"per_organ_delta_{o}"][180:300] - base[f"per_organ_delta_{o}"][180:300])
    for o in ORGAN_ORDER:
        pooled[o] = np.concatenate(pooled[o])

    edges = {}
    for src in ORGAN_ORDER:
        for dst in ORGAN_ORDER:
            if src == dst:
                continue
            data = np.column_stack([pooled[dst], pooled[src]])
            try:
                res = grangercausalitytests(data, maxlag=5, verbose=False)
                ps = [v[0]["ssr_ftest"][1] for v in res.values()]
                edges[(src, dst)] = float(min(ps))
            except Exception:
                edges[(src, dst)] = 1.0

    # Layout: circle.
    fig, ax = plt.subplots(figsize=(7, 7))
    n = len(ORGAN_ORDER)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    pos = {o: (np.cos(a), np.sin(a)) for o, a in zip(ORGAN_ORDER, angles)}
    for o, (x, y) in pos.items():
        ax.scatter(x, y, s=600, color="#cccccc", edgecolor="black", zorder=2)
        ax.text(x, y, o.upper(), ha="center", va="center", fontsize=8, zorder=3)
    for (src, dst), p in edges.items():
        if p < 0.05:
            x0, y0 = pos[src]; x1, y1 = pos[dst]
            # Shorten the line so it doesn't cover the marker.
            dx, dy = x1 - x0, y1 - y0
            length = np.hypot(dx, dy)
            ux, uy = dx / length, dy / length
            sx, sy = x0 + 0.13 * ux, y0 + 0.13 * uy
            ex, ey = x1 - 0.13 * ux, y1 - 0.13 * uy
            weight = -np.log10(max(p, 1e-12))
            lw = 0.5 + min(weight / 3.0, 3.0)
            color = plt.cm.Reds(min(1.0, weight / 6.0))
            ax.annotate(
                "",
                xy=(ex, ey),
                xytext=(sx, sy),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw),
                zorder=1,
            )
    ax.set_xlim(-1.4, 1.4)
    ax.set_ylim(-1.4, 1.4)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title("Granger causality network — direct_contradiction\n(edges: p < 0.05; thicker / darker = lower p)", fontsize=10)
    out = _setup_dir(out_root) / "5_granger_network.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_all(out_root: Path) -> list[Path]:
    return [
        plot_gap_time_series(out_root),
        plot_per_organ_heatmap(out_root),
        plot_theta_gap_scatter(out_root),
        plot_cascade_delays(out_root),
        plot_granger_network(out_root),
    ]
