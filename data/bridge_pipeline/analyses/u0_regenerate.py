#!/usr/bin/env python3
"""
U0 — Regenerate Γ(f) in declared coordinates (ln Mc, q, χ_eff, Λ̃/100, ln DL).

Skye's audit identified that pipeline_data.npz (used in most tests) was computed
in η-coordinates with unscaled Λ̃, giving κ ~ 10¹⁶ — eight orders above
the paper's Table III (κ ~ 10⁸). Every test that touched that stack is suspect.

This script:
  - Computes Γ(f) via JAX autodiff in PHYSICAL params (Mc, q, χ_eff, Λ̃, DL)
  - Chain-rules to declared analysis coordinates
  - Prints κ(f) across the entire sweep
  - Saves the clean stack for downstream tests (D2-proper, T3-revalidation, etc.)

Coordinate convention (Eq. 5 of the paper):
    x = (ln M_c, q, χ_eff, Λ̃/100, ln D_L)
"""

import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp
from jax import jacfwd
import numpy as np
from scipy import linalg as spla
import json, os, sys, argparse

# Path setup
_script_dir = os.path.dirname(os.path.abspath(__file__))
_pipeline_dir = os.path.join(_script_dir, '..')
sys.path.insert(0, _pipeline_dir)

from src import waveform as wf
from src import coordinates as coords
from src import psds as psds_mod

# ── Defaults matching the paper ──────────────────────────────────────
# GW170817-like BNS (Table I / III regime)
DEFAULT_THETA_PHYS = np.array([1.186, 0.85, 0.02, 400.0, 40.0])
# Mc [Msun], q, χ_eff, Λ̃, DL [Mpc]

F_MIN = 22.0
F_MAX = 500.0
N_DENSE = 200          # sampling for smooth curves
N_CUTOFFS = 18         # manuscript cutoffs
PSD_NAME = "ZDHP"

# ── Core computation: cumulative Fisher in analysis coordinates ──────
def compute_gamma_stack(theta_phys, f_grid, psd_values):
    """
    Compute Γ(f) cumulative in declared analysis coordinates.
    
    Uses JAX autodiff for the physical Jacobian, then chain-rules
    to analysis coordinates via diagonal Jacobian.
    
    Args:
        theta_phys: (5,) array [Mc, q, χ_eff, Λ̃, DL] in physical units
        f_grid: (Nf,) frequency array
        psd_values: (Nf,) PSD values
    
    Returns:
        G_stack: (Nf, 5, 5) cumulative Fisher matrices in analysis coords
        G_full:  (5, 5) full-band Fisher
        evals:   (Nf, 5) eigenvalues sorted descending
        evecs:   (Nf, 5, 5) eigenvectors with sign continuity
        conds:   (Nf,) condition numbers κ = λ_max / λ_min
    """
    theta_np = np.array(theta_phys, dtype=np.float64)
    f = np.array(f_grid, dtype=np.float64)
    psd = np.array(psd_values, dtype=np.float64)
    Nf = len(f)
    
    # ── Waveform and Jacobian via JAX ──
    theta_jax = jnp.array(theta_np)
    f_jax = jnp.array(f)
    
    def h_fn(th):
        return wf.taylorf2_htilde(f_jax, th[0], th[1], th[2], th[3], th[4])
    
    h = np.array(h_fn(theta_jax))
    J_phys = np.array(jacfwd(h_fn)(theta_jax), dtype=np.complex128)
    # J_phys: (Nf, 5) where J_phys[:, i] = ∂h/∂θ_i at the physical params
    
    # ── Physical Fisher increments ──
    # dΓ_ij = 4 * Re(∂_i h * conj(∂_j h)) / S_n * df (trapezoid)
    df = np.diff(f)
    w = np.concatenate([[df[0]/2.0], (df[:-1]+df[1:])/2.0, [df[-1]/2.0]])
    
    dG_phys = np.zeros((Nf, 5, 5), dtype=np.float64)
    for i in range(5):
        for j in range(i, 5):
            v = 4.0 * np.real(J_phys[:, i] * np.conj(J_phys[:, j])) / psd
            dG_phys[:, i, j] = v
            dG_phys[:, j, i] = v
    
    # Trapezoidal cumulative sum
    G_cum_phys = np.zeros((Nf, 5, 5), dtype=np.float64)
    running = np.zeros((5, 5), dtype=np.float64)
    for k in range(Nf):
        running += dG_phys[k] * w[k]
        G_cum_phys[k] = running.copy()
    
    # ── Transport to analysis coordinates ──
    # x = (ln Mc, q, χ_eff, Λ̃/100, ln DL)
    # J_analysis = dx/d(theta_phys)
    Mc, DL = theta_np[0], theta_np[4]
    J_analysis = np.eye(5)
    J_analysis[0, 0] = 1.0 / Mc    # d(ln Mc)/dMc
    J_analysis[3, 3] = 1.0 / 100.0 # d(Λ̃/100)/dΛ̃
    J_analysis[4, 4] = 1.0 / DL    # d(ln DL)/dDL
    # q and χ_eff are identity
    
    # Γ_x = J^{-T} Γ_phys J^{-1}
    # Since J is diagonal, J^{-1} is just 1/J_diag
    Jinv = np.linalg.inv(J_analysis)
    JinvT = Jinv.T
    
    G_stack = np.zeros_like(G_cum_phys)
    for k in range(Nf):
        G_stack[k] = JinvT @ G_cum_phys[k] @ Jinv
    
    # ── Eigendecomposition ──
    evals = np.zeros((Nf, 5))
    evecs = np.zeros((Nf, 5, 5))
    conds = np.zeros(Nf)
    
    for k in range(Nf):
        vals, vecs = spla.eigh(G_stack[k])
        # eigh returns ascending; reverse to descending
        vals = vals[::-1]
        vecs = vecs[:, ::-1]
        
        # Sign convention: dominant component positive
        for i in range(5):
            idx_max = np.argmax(np.abs(vecs[:, i]))
            if vecs[idx_max, i] < 0:
                vecs[:, i] = -vecs[:, i]
        
        # Sign continuity with previous cutoff
        if k > 0:
            for i in range(5):
                dot = np.dot(evecs[k-1, :, i], vecs[:, i])
                if dot < 0:
                    vecs[:, i] = -vecs[:, i]
        
        evals[k] = vals
        evecs[k] = vecs
        conds[k] = vals[0] / vals[-1] if vals[-1] > 0 else np.inf
    
    return G_stack, G_cum_phys[-1], evals, evecs, conds


def print_kappa_sweep(f_grid, evals, conds, label=""):
    """Print κ(f) at selected frequencies."""
    print(f"\n{'='*70}")
    print(f"κ(f) sweep — {label}")
    print(f"{'='*70}")
    print(f"{'f (Hz)':>10} {'κ':>16} {'λ₁':>14} {'λ₂':>14} {'λ₃':>14} {'λ₄':>14} {'λ₅':>14}")
    print(f"{'-'*10} {'-'*16} {'-'*14} {'-'*14} {'-'*14} {'-'*14} {'-'*14}")
    
    # Reporting frequencies
    f_report = np.array([22, 25, 30, 35, 45, 60, 75, 100, 150, 200, 300, 400, 500], dtype=np.float64)
    
    for f_target in f_report:
        idx = np.argmin(np.abs(f_grid - f_target))
        f_act = f_grid[idx]
        print(f"{f_act:>10.1f} {conds[idx]:>16.4e} {evals[idx,0]:>14.4e} {evals[idx,1]:>14.4e} "
              f"{evals[idx,2]:>14.4e} {evals[idx,3]:>14.4e} {evals[idx,4]:>14.4e}")


def run_u0(theta_phys=None, psd_name=None, f_min=None, f_max=None, 
           n_dense=None, save=True):
    """Run U0 regeneration and return full results."""
    if theta_phys is None:
        theta_phys = DEFAULT_THETA_PHYS
    if psd_name is None:
        psd_name = PSD_NAME
    if f_min is None:
        f_min = F_MIN
    if f_max is None:
        f_max = F_MAX
    if n_dense is None:
        n_dense = N_DENSE
    
    print("=" * 70)
    print("U0 — Γ(f) Regeneration in Declared Coordinates")
    print("=" * 70)
    print(f"  Physical params: Mc={theta_phys[0]:.3f} Msun, q={theta_phys[1]:.3f}, "
          f"χ_eff={theta_phys[2]:.3f}, Λ̃={theta_phys[3]:.0f}, DL={theta_phys[4]:.0f} Mpc")
    print(f"  Analysis coords: x = (ln Mc, q, χ_eff, Λ̃/100, ln DL)")
    print(f"  Freq range: {f_min:.0f}–{f_max:.0f} Hz, {n_dense} points")
    print(f"  PSD: {psd_name}")
    print()
    
    # Frequency grids
    f_dense = np.logspace(np.log10(f_min), np.log10(f_max), n_dense)
    psd_values = np.array(psds_mod.compute_psd_values(psd_name, f_dense))
    
    # Compute
    G_stack, G_full, evals, evecs, conds = compute_gamma_stack(
        theta_phys, f_dense, psd_values
    )
    
    # Report κ(f)
    print_kappa_sweep(f_dense, evals, conds, label=f"{psd_name}, {theta_phys}")
    
    # Summary stats
    print(f"\n{'='*70}")
    print(f"Summary")
    print(f"{'='*70}")
    print(f"  κ(22 Hz) = {conds[0]:.4e}")
    print(f"  κ(500 Hz) = {conds[-1]:.4e}")
    print(f"  κ growth = {conds[-1]/conds[0]:.4f}x")
    print(f"  v_min(500) = {evecs[-1,:,-1]}")
    print(f"  v_max(500) = {evecs[-1,:,0]}")
    
    # Save
    if save:
        out_dir = os.path.join(_pipeline_dir, 'results', 'u0_output')
        os.makedirs(out_dir, exist_ok=True)
        
        out_path = os.path.join(out_dir, 'u0_gamma_stack.npz')
        np.savez(out_path,
                 f=f_dense,
                 G=G_stack,
                 G_full=G_full,
                 evals=evals,
                 evecs=evecs,
                 conds=conds,
                 theta_phys=theta_phys,
                 psd_name=psd_name,
                 f_min=f_min,
                 f_max=f_max,
                 n_dense=n_dense)
        print(f"\n  Saved: {out_path}")
        
        # Also save a JSON summary
        summary = {
            "theta_phys": theta_phys.tolist(),
            "psd_name": psd_name,
            "f_range": [float(f_min), float(f_max)],
            "n_dense": n_dense,
            "kappa_22": float(conds[0]),
            "kappa_500": float(conds[-1]),
            "kappa_growth": float(conds[-1] / conds[0]),
            "v_min_500": evecs[-1, :, -1].tolist(),
            "v_max_500": evecs[-1, :, 0].tolist(),
            "evals_500": evals[-1].tolist(),
        }
        with open(os.path.join(out_dir, 'u0_summary.json'), 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"  Summary: {os.path.join(out_dir, 'u0_summary.json')}")
    
    return {
        "f": f_dense,
        "G": G_stack,
        "G_full": G_full,
        "evals": evals,
        "evecs": evecs,
        "conds": conds,
        "theta_phys": theta_phys,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="U0 — Γ(f) regeneration in declared coordinates")
    parser.add_argument("--theta", type=float, nargs=5,
                       default=[1.186, 0.85, 0.02, 400.0, 40.0],
                       help="Physical params: Mc q chi_eff Lambda_tilde DL")
    parser.add_argument("--psd", type=str, default="ZDHP",
                       choices=["ZDHP", "Early_aLIGO", "O2_H1", "O2_L1"])
    parser.add_argument("--f-min", type=float, default=22.0)
    parser.add_argument("--f-max", type=float, default=500.0)
    parser.add_argument("--n-dense", type=int, default=200)
    
    args = parser.parse_args()
    run_u0(theta_phys=np.array(args.theta),
           psd_name=args.psd,
           f_min=args.f_min,
           f_max=args.f_max,
           n_dense=args.n_dense)