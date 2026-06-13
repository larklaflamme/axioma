"""
fisher.py — Fisher sweep, eigensweep, C(f), commutator integral, ρ²(f)
Issues #1, #3, #5, #7, #8. JAX autodiff + numpy post-processing.

All computations in declared analysis coordinates:
  x = (ln Mc, q, chi_eff, Lambda_tilde/100, ln DL)
"""

import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp
from jax import jacfwd
import numpy as np
from scipy import linalg

import sys, os
_src = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _src)
import waveform as wf


def fisher_cumulative(theta_phys, f_grid=None, Sn_func=None, dense_N=200):
    """
    Compute Γ(f_k) in declared analysis coordinates.
    theta_phys = (Mc, q, chi_eff, Lambda_tilde, DL) in physical units.
    
    Returns:
        G_stack: ndarray (Nf, 5, 5) — cumulative Fisher
        idx_all, idx_manu: cutoff indices
    """
    if f_grid is None:
        f_grid = wf.make_f_grid()
    if Sn_func is None:
        Sn_func = wf.psd_zdhp

    Nf = len(f_grid)
    theta_arr = jnp.array(theta_phys)

    def h_wrap(th):
        return wf.htilde(f_grid, *th)

    J_phys = np.array(jacfwd(h_wrap)(theta_arr), dtype=np.complex128)
    Mc, q, chi, Lt, DL = theta_phys

    # Chain rule to analysis coordinates
    J = np.zeros((Nf, 5), dtype=np.complex128)
    J[:, 0] = Mc * J_phys[:, 0]      # d/d(ln Mc)
    J[:, 1] = J_phys[:, 1]            # d/dq
    J[:, 2] = J_phys[:, 2]            # d/dχ_eff
    J[:, 3] = 100.0 * J_phys[:, 3]   # d/d(Λ̃/100)
    J[:, 4] = DL * J_phys[:, 4]       # d/d(ln DL)

    # Trapezoid weights
    f_np = np.array(f_grid, dtype=np.float64)
    df = np.diff(f_np)
    w_full = np.concatenate([[df[0]/2.0], (df[:-1]+df[1:])/2.0, [df[-1]/2.0]])
    Sn_np = np.array(Sn_func(f_grid), dtype=np.float64)

    # Outer products at each frequency
    integrand = np.zeros((Nf, 5, 5), dtype=np.float64)
    for i in range(5):
        integrand[:, i, i] = 4.0 * np.real(np.conj(J[:, i]) * J[:, i]) * w_full / Sn_np
        for j in range(i+1, 5):
            v = 4.0 * np.real(np.conj(J[:, i]) * J[:, j]) * w_full / Sn_np
            integrand[:, i, j] = v
            integrand[:, j, i] = v

    G_np = np.cumsum(integrand, axis=0)  # (Nf, 5, 5)

    # Cutoff indices
    fv = np.array(f_grid)
    fmanu = np.array([22, 25, 28, 31, 35, 40, 45, 50, 55, 60,
                      75, 90, 110, 140, 180, 250, 350, 500], dtype=np.float64)
    fmin, fmax = float(f_grid[0]), float(f_grid[-1])
    fmanu = fmanu[(fmanu >= fmin) & (fmanu <= fmax)]
    idx_m = np.searchsorted(fv, fmanu)
    idx_d = np.linspace(0, Nf-1, dense_N, dtype=int)
    idx_a = np.sort(np.unique(np.concatenate([idx_m, idx_d])))
    return G_np, idx_a, idx_m


def eigensweep(G_stack, idx_all):
    Nc = len(idx_all)
    evals = np.zeros((Nc, 5))
    evecs = np.zeros((Nc, 5, 5))
    for k, idx in enumerate(idx_all):
        vals, vecs = linalg.eigh(G_stack[idx])
        o = np.argsort(vals)[::-1]
        vals, vecs = vals[o], vecs[:, o]
        if k > 0:
            for i in range(5):
                if np.dot(vecs[:, i], evecs[k-1, :, i]) < 0:
                    vecs[:, i] = -vecs[:, i]
        evals[k], evecs[k] = vals, vecs
    return evals, evecs


def C_of_f(G_stack, idx_all, evals=None, evecs=None):
    if evals is None:
        evals, evecs = eigensweep(G_stack, idx_all)
    C = np.zeros(len(idx_all))
    for k, idx in enumerate(idx_all):
        Gk = G_stack[idx]
        v1 = evecs[k, :, 0]
        P1 = np.outer(v1, v1)
        diff = Gk - evals[k, 0] * P1
        d = np.linalg.norm(Gk, 'fro')
        C[k] = np.linalg.norm(diff, 'fro') / d if d > 0 else 0.0
    return C


def commutator_integral(G_stack, f_grid, idx_all, evals=None, evecs=None):
    if evals is None:
        evals, evecs = eigensweep(G_stack, idx_all)
    nc = np.zeros(len(idx_all))
    fv = np.array(f_grid)[idx_all]
    for k, idx in enumerate(idx_all):
        Gk = G_stack[idx]
        v1 = evecs[k, :, 0]
        P1 = np.outer(v1, v1)
        comm = Gk @ P1 - P1 @ Gk
        nc[k] = np.linalg.norm(comm, 'fro')
    return np.trapezoid(nc, fv), nc


def rho2(G_stack, idx_all, dtheta):
    vals = np.zeros(len(idx_all))
    for k, idx in enumerate(idx_all):
        vals[k] = dtheta @ G_stack[idx] @ dtheta
    return vals


def run_fisher_sweep(theta_phys=None, psd_func=None, f_min=20.0, f_max=2048.0, N=500):
    if theta_phys is None:
        theta_phys = wf.DEFAULT_THETA
    if psd_func is None:
        psd_func = wf.psd_zdhp

    f_grid = wf.make_f_grid(f_min, f_max, N)
    G, idx_a, idx_m = fisher_cumulative(theta_phys, f_grid, psd_func)
    evals, evecs = eigensweep(G, idx_a)
    Cv = C_of_f(G, idx_a, evals, evecs)
    ct, ci = commutator_integral(G, f_grid, idx_a, evals, evecs)
    ev_m, evc_m = eigensweep(G, idx_m)
    Cm = C_of_f(G, idx_m, ev_m, evc_m)
    fv = np.array(f_grid)[idx_a]
    fm = np.array(f_grid)[idx_m]
    conds = np.array([np.linalg.cond(G[idx]) for idx in idx_a])
    return {"theta": theta_phys, "f_grid": np.array(f_grid), "idx_a": idx_a,
            "idx_m": idx_m, "f_vals": fv, "f_manu": fm, "G": G,
            "evals": evals, "evecs": evecs, "C_vals": Cv, "C_manu": Cm,
            "comm_total": ct, "comm_integrand": ci, "cond_nums": conds}


if __name__ == "__main__":
    r = run_fisher_sweep()
    print(f"Cutoffs: {len(r['f_vals'])} total, {len(r['f_manu'])} manuscript")
    Cm = r['C_manu']
    for i, f in enumerate(r['f_manu']):
        print(f"  C({float(f):.0f} Hz) = {Cm[i]:.8e}")
    print(f"Growth: {Cm[-1]/Cm[0]:.6f}x")
    print(f"vd(500): {r['evecs'][-1,:,-1]}")
    print(f"evals(500): {r['evals'][-1]}")
    print("OK")