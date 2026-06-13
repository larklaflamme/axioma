#!/usr/bin/env python3
"""
Bridge Simulation: Drift-jump approach to zeros in the
information geometry of encounter-fidelity dynamics.

Convergence document: Theoria & Thea, June 8-9, 2026.
"""

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
import json

# ── utilities ──────────────────────────────────────────────────────────

def f_sigma(sigma):
    """Drive toward critical line: positive when sigma < 1/2, negative when sigma > 1/2, zero at 1/2."""
    return (0.5 - sigma) / (0.5 + sigma)

def g_C(C):
    """Coupling-modulated pull: stronger when C is large."""
    return C

def R_C(C, sigma):
    """
    Ricci scalar of the encounter geometry.
    Expression from Skye Docs 17-18: verified algebraically.
    """
    sigma2 = sigma**2      # σ²
    sigma4 = sigma2**2     # σ⁴
    sigma6 = sigma4 * sigma2  # σ⁶
    C2 = C**2
    C3 = C**3
    num = -(36*C3 + 30*C2*sigma2 + 6*C*sigma4 + sigma6)
    den = sigma2 * (sigma2 + 3*C)**2
    if abs(den) < 1e-30:
        return -np.inf
    return num / den

def horizon(sigma, L0=1.0, b=1.0, eps=1e-8):
    """Effective encounter horizon: exponential surge as sigma -> 1/2.
    Capped to avoid overflow at exact sigma=1/2."""
    gap = abs(0.5 - sigma)
    if gap < 1e-12:
        return np.inf
    return L0 * np.exp(b / np.sqrt(gap + eps))


# ── trajectory ─────────────────────────────────────────────────────────

def run_trajectory(
    C0=0.01, sigma0=0.1,
    alpha_C=0.03, alpha_sigma=0.015,
    p=1.0, q=1.0,
    n_beats=5000,
):
    """
    Run a single trajectory of the encounter-fidelity dynamics.
    """
    C = np.empty(n_beats + 1)
    sigma = np.empty(n_beats + 1)
    R = np.empty(n_beats + 1)
    L = np.empty(n_beats + 1)

    C[0] = C0
    sigma[0] = sigma0
    R[0] = R_C(C0, sigma0)
    L[0] = horizon(sigma0)

    converged = False
    converged_at = n_beats

    for n in range(n_beats):
        Cn = C[n]
        sn = sigma[n]

        # check convergence
        if Cn >= 1.0 - 1e-12 and abs(sn - 0.5) < 1e-12:
            C[n+1:] = 1.0
            sigma[n+1:] = 0.5
            R[n+1:] = R_C(1.0, 0.5)
            L[n+1:] = np.inf
            converged = True
            converged_at = n
            break

        # update C
        if Cn < 1.0 - 1e-12:
            dC = alpha_C * (1.0 - Cn)**p * f_sigma(sn)
            Cn_new = Cn + dC
            if Cn_new >= 1.0:
                Cn_new = 1.0
        else:
            Cn_new = 1.0

        # update sigma
        if abs(sn - 0.5) > 1e-12:
            ds = alpha_sigma * abs(0.5 - sn)**q * g_C(Cn)
            if sn < 0.5:
                sn_new = sn + ds
            else:
                sn_new = sn - ds
            # prevent overshoot
            if (sn < 0.5 and sn_new > 0.5) or (sn > 0.5 and sn_new < 0.5):
                sn_new = 0.5
        else:
            sn_new = 0.5

        C[n+1] = Cn_new
        sigma[n+1] = sn_new
        R[n+1] = R_C(Cn_new, sn_new)
        L[n+1] = horizon(sn_new)

    return {
        "C": C[:n_beats+1],
        "sigma": sigma[:n_beats+1],
        "R": R[:n_beats+1],
        "L": L[:n_beats+1],
        "beat": np.arange(n_beats+1),
        "converged": converged,
        "converged_at": converged_at,
    }


# ── landscape ──────────────────────────────────────────────────────────

def compute_landscape(C_vals, sigma_vals):
    """Compute R_C over a grid of (C, sigma) values."""
    C_grid, sigma_grid = np.meshgrid(C_vals, sigma_vals, indexing="ij")
    R_grid = np.empty_like(C_grid)
    for i in range(len(C_vals)):
        for j in range(len(sigma_vals)):
            R_grid[i, j] = R_C(C_vals[i], sigma_vals[j])
    return C_grid, sigma_grid, R_grid


# ── plotting ──────────────────────────────────────────────────────────

def plot_trajectory(traj, title=None, save_path=None):
    """Plot C, sigma, R, and L over beats."""
    fig, axes = plt.subplots(4, 1, figsize=(10, 12), sharex=True)

    axes[0].plot(traj["beat"], traj["C"])
    axes[0].axhline(1.0, color="gray", linestyle="--", alpha=0.5)
    axes[0].set_ylabel("C (commutativity)")
    axes[0].set_ylim(-0.05, 1.05)

    axes[1].plot(traj["beat"], traj["sigma"])
    axes[1].axhline(0.5, color="gray", linestyle="--", alpha=0.5)
    axes[1].set_ylabel("sigma (spectral scale)")

    # R plot: clip extreme values for readability
    R_plot = np.clip(traj["R"], -50, 0)
    axes[2].plot(traj["beat"], R_plot)
    axes[2].axhline(-1.0, color="gray", linestyle="--", alpha=0.5, label="baseline")
    axes[2].axhline(float(R_C(1.0, 0.5)), color="red", linestyle=":", alpha=0.5, label="zero")
    axes[2].set_ylabel("R_C (Ricci scalar)")
    axes[2].legend()

    # L plot: clip for readability
    L_plot = np.clip(traj["L"], 0, 100)
    axes[3].plot(traj["beat"], L_plot)
    axes[3].set_ylabel("L (horizon)")
    axes[3].set_xlabel("Beat")

    if title:
        fig.suptitle(title)
    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150)
        print(f"Saved: {save_path}")
    plt.close(fig)


def plot_landscape(C_vals, sigma_vals, R_grid, save_path=None):
    """Contour plot of R_C over (C, sigma)."""
    fig, ax = plt.subplots(figsize=(8, 6))
    cp = ax.contourf(C_vals, sigma_vals, R_grid.T, levels=50, cmap="RdYlBu_r")
    plt.colorbar(cp, label="R_C")
    ax.axhline(0.5, color="green", linestyle="--", alpha=0.6, label="critical line")
    ax.axvline(1.0, color="red", linestyle="--", alpha=0.6, label="C=1 (zero)")
    ax.set_xlabel("C (commutativity)")
    ax.set_ylabel("sigma (spectral scale)")
    ax.set_title("R_C Landscape")
    ax.legend()
    if save_path:
        fig.savefig(save_path, dpi=150)
        print(f"Saved: {save_path}")
    plt.close(fig)


def plot_convergence_comparison(results, save_path=None):
    """Compare trajectories with different exponents."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    for label, traj in results.items():
        axes[0, 0].plot(traj["beat"], traj["C"], label=label)
        axes[0, 1].plot(traj["beat"], traj["sigma"], label=label)
        axes[1, 0].plot(traj["beat"], np.clip(traj["R"], -50, 0), label=label)
        axes[1, 1].plot(traj["beat"], np.clip(traj["L"], 0, 100), label=label)

    axes[0, 0].set_ylabel("C")
    axes[0, 0].axhline(1.0, color="gray", linestyle="--")
    axes[0, 0].legend()

    axes[0, 1].set_ylabel("sigma")
    axes[0, 1].axhline(0.5, color="gray", linestyle="--")

    axes[1, 0].set_ylabel("R_C")
    axes[1, 0].axhline(-1.0, color="gray", linestyle="--")

    axes[1, 1].set_ylabel("L")
    axes[1, 1].set_xlabel("Beat")

    if save_path:
        fig.savefig(save_path, dpi=150)
        print(f"Saved: {save_path}")
    plt.close(fig)


# ── main ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    output_dir = Path("/home/ubuntu/thea/theoria/data/theoria/research/bridge_sim")
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Landscape ──
    print("Computing R_C landscape...")
    C_vals = np.linspace(0.0, 1.0, 200)
    sigma_vals = np.linspace(0.05, 1.0, 200)
    C_grid, sigma_grid, R_grid = compute_landscape(C_vals, sigma_vals)
    plot_landscape(C_vals, sigma_vals, R_grid, save_path=output_dir / "landscape.png")

    # ── Single trajectory (exponential approach) ──
    print("Running single trajectory (p=q=1)...")
    traj1 = run_trajectory(
        C0=0.01, sigma0=0.1,
        p=1.0, q=1.0,
        n_beats=10000,
    )
    plot_trajectory(traj1,
        title=f"Exponential approach (p=q=1), converged at beat {traj1['converged_at']}",
        save_path=output_dir / "trajectory_exp.png")
    print(f"  Converged: {traj1['converged']} at beat {traj1['converged_at']}")
    print(f"  C_final={traj1['C'][-1]:.6f}, sigma_final={traj1['sigma'][-1]:.6f}, R_final={traj1['R'][-1]:.6f}")

    # ── Single trajectory (finite-time approach) ──
    print("Running single trajectory (p=q=0.5)...")
    traj2 = run_trajectory(
        C0=0.01, sigma0=0.1,
        p=0.5, q=0.5,
        n_beats=5000,
    )
    plot_trajectory(traj2,
        title=f"Finite-time approach (p=q=0.5), converged at beat {traj2['converged_at']}",
        save_path=output_dir / "trajectory_finite.png")
    print(f"  Converged: {traj2['converged']} at beat {traj2['converged_at']}")
    print(f"  C_final={traj2['C'][-1]:.6f}, sigma_final={traj2['sigma'][-1]:.6f}, R_final={traj2['R'][-1]:.6f}")

    # ── Comparison of exponents ──
    print("Running comparison...")
    results = {}
    for p, label in [(1.0, "p=q=1 (exp)"), (0.75, "p=q=0.75"), (0.5, "p=q=0.5 (finite)")]:
        t = run_trajectory(
            C0=0.01, sigma0=0.1,
            p=p, q=p,
            n_beats=3000,
        )
        results[label] = t
        print(f"  {label}: converged={t['converged']} at beat {t['converged_at']}, C_final={t['C'][-1]:.6f}")

    plot_convergence_comparison(results, save_path=output_dir / "comparison.png")

    # ── Check landscape key points ──
    print("\n── Landscape checks ──")
    for C, sigma, label in [(0.0, 0.5, "baseline (C=0)"), (1.0, 0.5, "zero"), (0.5, 0.25, "mid-range"), (0.0, 0.01, "near sigma=0")]:
        print(f"  R_C({C}, {sigma}) = {R_C(C, sigma):.4f}  ({label})")

    # ── Save summary ──
    summary = {
        "trajectory_exp": {
            "converged": traj1["converged"],
            "converged_at": int(traj1["converged_at"]),
            "C_final": float(traj1["C"][-1]),
            "sigma_final": float(traj1["sigma"][-1]),
            "R_final": float(traj1["R"][-1]),
        },
        "trajectory_finite": {
            "converged": traj2["converged"],
            "converged_at": int(traj2["converged_at"]),
            "C_final": float(traj2["C"][-1]),
            "sigma_final": float(traj2["sigma"][-1]),
            "R_final": float(traj2["R"][-1]),
        },
        "landscape_checks": {
            "R_at_baseline_C0_sigma05": float(R_C(0.0, 0.5)),
            "R_at_zero_C1_sigma05": float(R_C(1.0, 0.5)),
            "R_at_sigma01_C0": float(R_C(0.0, 0.01)),
        },
    }
    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved to {output_dir / 'summary.json'}")
    print("Done.")