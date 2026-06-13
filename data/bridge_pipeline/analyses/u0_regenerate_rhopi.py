#!/usr/bin/env python3
"""
U0 — Regenerate Γ(f) in DECLARED COORDINATES using the rho_pi_bridge stack.

The rho_pi_bridge is the paper pipeline: uses SN_REF = 1.6e-46 Hz^{-1}
PSD normalization so that ⟨h|h⟩ ≈ SNR² ~ O(10-100) for BNS at 40 Mpc.
This gives κ ~ 10⁹ (matching Table III), not 10¹⁶ from bridge_pipeline.

Declared coordinates (Eq. 5): x = (ln M_c, q, χ_eff, Λ̃/100, ln D_L)
"""

import sys, os, json, numpy as np

# Point to the rho_pi_bridge source
_script_dir = os.path.dirname(os.path.abspath(__file__))
_rhopi_dir = os.path.join(_script_dir, '..', '..', 'rho_pi_bridge')
sys.path.insert(0, os.path.join(_rhopi_dir, 'src'))

import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp
from jax import jacfwd
from scipy import linalg as spla

import importlib.util
spec = importlib.util.spec_from_file_location(
    "rhopi_waveform", 
    os.path.join(_rhopi_dir, 'src', 'waveform.py')
)
wf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wf)

# ── Defaults ──────────────────────────────────────────────────────
DEFAULT_THETA_PHYS = np.array([1.186, 0.85, 0.02, 400.0, 40.0])
F_MIN, F_MAX = 22.0, 500.0
N_DENSE = 200


def compute_gamma_stack(theta_phys, f_grid, psd_func=None):
    if psd_func is None:
        psd_func = wf.psd_zdhp

    theta_np = np.array(theta_phys, dtype=np.float64)
    f = np.array(f_grid, dtype=np.float64)
    Nf = len(f)
    
    theta_jax = jnp.array(theta_np)
    f_jax = jnp.array(f)
    
    def h_fn(th):
        return wf.htilde(f_jax, th[0], th[1], th[2], th[3], th[4])
    
    h = np.array(h_fn(theta_jax))
    J_phys = np.array(jacfwd(h_fn)(theta_jax), dtype=np.complex128)
    
    Sn = np.array(psd_func(f), dtype=np.float64)
    
    # Chain rule to analysis coordinates
    Mc, q, chi, Lt, DL = theta_np
    J = np.zeros((Nf, 5), dtype=np.complex128)
    J[:, 0] = Mc * J_phys[:, 0]       # d/d(ln Mc)
    J[:, 1] = J_phys[:, 1]             # d/dq
    J[:, 2] = J_phys[:, 2]             # d/dχ_eff
    J[:, 3] = 100.0 * J_phys[:, 3]    # d/d(Λ̃/100)
    J[:, 4] = DL * J_phys[:, 4]        # d/d(ln DL)
    
    df = np.diff(f)
    w = np.concatenate([[df[0]/2.0], (df[:-1]+df[1:])/2.0, [df[-1]/2.0]])
    
    dG = np.zeros((Nf, 5, 5), dtype=np.float64)
    for i in range(5):
        for j in range(i, 5):
            v = 4.0 * np.real(np.conj(J[:, i]) * J[:, j]) / Sn * w
            dG[:, i, j] = v
            dG[:, j, i] = v
    
    G_stack = np.cumsum(dG, axis=0)
    
    evals = np.zeros((Nf, 5))
    evecs = np.zeros((Nf, 5, 5))
    conds = np.full(Nf, np.inf)
    
    for k in range(Nf):
        vals, vecs = spla.eigh(G_stack[k])
        vals = vals[::-1]
        vecs = vecs[:, ::-1]
        
        for i in range(5):
            idx_max = np.argmax(np.abs(vecs[:, i]))
            if vecs[idx_max, i] < 0:
                vecs[:, i] = -vecs[:, i]
        
        if k > 0:
            for i in range(5):
                if np.dot(evecs[k-1, :, i], vecs[:, i]) < 0:
                    vecs[:, i] = -vecs[:, i]
        
        evals[k] = vals
        evecs[k] = vecs
        if vals[-1] > 0:
            conds[k] = vals[0] / vals[-1]
    
    return G_stack, evals, evecs, conds


def print_full_report(f_grid, evals, evecs, conds, label=""):
    f_report = np.array([22, 25, 30, 35, 45, 60, 75, 100, 150, 200, 300, 400, 500],
                        dtype=np.float64)
    
    print(f"\n{'='*90}")
    print(f"κ(f) sweep — {label}")
    print(f"{'='*90}")
    hdr = f"{'f (Hz)':>8} {'κ':>16} {'λ₁':>14} {'λ₂':>14} {'λ₃':>14} {'λ₄':>14} {'λ₅':>14}"
    print(hdr)
    print("-" * 90)
    
    for f_target in f_report:
        idx = np.argmin(np.abs(f_grid - f_target))
        f_act = f_grid[idx]
        kstr = f"{conds[idx]:>16.4e}" if np.isfinite(conds[idx]) else f"{'∞':>16}"
        print(f"{f_act:>8.1f} {kstr} "
              f"{evals[idx,0]:>14.6e} {evals[idx,1]:>14.6e} "
              f"{evals[idx,2]:>14.6e} {evals[idx,3]:>14.6e} "
              f"{evals[idx,4]:>14.6e}")
    
    print(f"\n  Eigenvectors at 500 Hz (declared coords):")
    for i in range(5):
        print(f"  v{i+1}: {evecs[-1,:,i]}")
    
    # Component decomposition of v_min
    v5 = evecs[-1,:,-1]
    print(f"\n  v₅ decomposition (degeneracy direction):")
    print(f"    ln Mc component:  {v5[0]:.6e}")
    print(f"    q component:      {v5[1]:.6e}")
    print(f"    χ_eff component:  {v5[2]:.6e}")
    print(f"    Λ̃/100 component: {v5[3]:.6e}")
    print(f"    ln DL component:  {v5[4]:.6e}")


def run_u0(theta_phys=None, f_min=None, f_max=None, n_dense=None, save=True):
    if theta_phys is None:
        theta_phys = DEFAULT_THETA_PHYS
    if f_min is None: f_min = F_MIN
    if f_max is None: f_max = F_MAX
    if n_dense is None: n_dense = N_DENSE
    
    print("=" * 90)
    print("U0 — Γ(f) Regeneration in Declared Coordinates (rho_pi_bridge)")
    print("=" * 90)
    print(f"  Physical params: Mc={theta_phys[0]:.3f} Msun, q={theta_phys[1]:.3f}, "
          f"χ_eff={theta_phys[2]:.3f}, Λ̃={theta_phys[3]:.0f}, DL={theta_phys[4]:.0f} Mpc")
    print(f"  Analysis coords: x = (ln Mc, q, χ_eff, Λ̃/100, ln DL)")
    print(f"  Freq range: {f_min:.0f}–{f_max:.0f} Hz, {n_dense} points")
    print(f"  PSD: ZDHP (SN_REF = 1.6e-46 Hz⁻¹)")
    
    f_dense = np.logspace(np.log10(f_min), np.log10(f_max), n_dense)
    
    G_stack, evals, evecs, conds = compute_gamma_stack(theta_phys, f_dense)
    
    print_full_report(f_dense, evals, evecs, conds,
                      label=f"ZDHP (paper PSD), θ = {theta_phys}")
    
    # Report manuscript-comparable numbers
    print(f"\n{'='*90}")
    print(f"Summary (cf. Table III)")
    print(f"{'='*90}")
    print(f"  κ(500 Hz)     = {conds[-1]:.4e}  (Table III: ~10⁸)")
    print(f"  λ₁(500 Hz)    = {evals[-1,0]:.6e}  (ln Mc)")
    print(f"  λ₂(500 Hz)    = {evals[-1,1]:.6e}  (q)")
    print(f"  λ₃(500 Hz)    = {evals[-1,2]:.6e}  (χ_eff)")
    print(f"  λ₄(500 Hz)    = {evals[-1,3]:.6e}  (Λ̃/100)")
    print(f"  λ₅(500 Hz)    = {evals[-1,4]:.6e}  (ln DL)")
    print(f"  SNR total     = {np.sqrt(np.trace(G_stack[-1])):.4f}")
    
    if save:
        out_dir = os.path.join(_script_dir, '..', 'results', 'u0_output')
        os.makedirs(out_dir, exist_ok=True)
        
        out_path = os.path.join(out_dir, 'u0_rhopi_stack.npz')
        np.savez(out_path,
                 f=f_dense,
                 G=G_stack,
                 evals=evals,
                 evecs=evecs,
                 conds=conds,
                 theta_phys=theta_phys,
                 f_min=f_min, f_max=f_max, n_dense=n_dense)
        print(f"\n  Saved: {out_path}")
        
        summary = {
            "theta_phys": theta_phys.tolist(),
            "f_range": [float(f_min), float(f_max)],
            "n_dense": n_dense,
            "kappa_500": float(conds[-1]),
            "eigenvalues_500": evals[-1].tolist(),
            "v5_500": evecs[-1, :, -1].tolist(),
            "v1_500": evecs[-1, :, 0].tolist(),
            "snr_total": float(np.sqrt(np.trace(G_stack[-1]))),
        }
        with open(os.path.join(out_dir, 'u0_rhopi_summary.json'), 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"  Summary: {os.path.join(out_dir, 'u0_rhopi_summary.json')}")
    
    return {
        "f": f_dense, "G": G_stack,
        "evals": evals, "evecs": evecs, "conds": conds,
        "theta_phys": theta_phys,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--theta", type=float, nargs=5,
                       default=[1.186, 0.85, 0.02, 400.0, 500.0])
    parser.add_argument("--f-min", type=float, default=22.0)
    parser.add_argument("--f-max", type=float, default=500.0)
    parser.add_argument("--n-dense", type=int, default=200)
    args = parser.parse_args()
    
    run_u0(theta_phys=np.array(args.theta),
           f_min=args.f_min, f_max=args.f_max, n_dense=args.n_dense)