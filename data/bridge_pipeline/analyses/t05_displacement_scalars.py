"""
T5 — Invariant displacement scalars.

Computes ρ²(f) = Δx^T Γ(f) Δx at all cutoffs, exact mismatch,
and the linear-signal validity factor.
"""

import numpy as np
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src import waveform as wf
from src import coordinates as coords
from src import fisher as fisher_mod
from src import psds as psds_mod

def run(config=None):
    print("=" * 60)
    print("T5: Displacement scalars")
    print("=" * 60)
    
    f_min, f_max = 22.0, 500.0
    n_cutoffs = 18
    f_cutoffs = np.logspace(np.log10(f_min), np.log10(f_max), n_cutoffs)
    n_dense = 200
    f_dense = np.logspace(np.log10(f_min), np.log10(f_max), n_dense)
    psd_values = psds_mod.compute_psd_values("ZDHP", f_dense)
    
    theta_low = np.array([1.186, 0.88, 0.005, 380, 40.0])
    theta_high = np.array([1.186, 0.75, 0.06, 450, 40.0])
    
    x_low = coords.to_primary(theta_low.reshape(1, -1))[0]
    x_high = coords.to_primary(theta_high.reshape(1, -1))[0]
    dx = x_high - x_low
    
    theta_mid = (theta_low + theta_high) / 2.0
    
    results = {"T5": {}}
    
    G_cum, G_full = fisher_mod.fisher_cumulative(theta_mid, f_dense, psd_values)
    eigvals, eigvecs = fisher_mod.eigensweep(G_cum)
    
    # ρ²(f) at each cutoff
    rho2_vals = fisher_mod.rho2(G_cum, dx)
    
    # Exact mismatch at each cutoff
    exact_mismatch = []
    for k in range(n_dense):
        f_cut = f_dense[k]
        idx = f_dense <= f_cut
        if np.sum(idx) < 5:
            exact_mismatch.append(0.0)
            continue
        
        h_low = np.array(wf.taylorf2_htilde(
            f_dense[idx], theta_low[0], theta_low[1], theta_low[2], theta_low[3], theta_low[4]
        ))
        h_high = np.array(wf.taylorf2_htilde(
            f_dense[idx], theta_high[0], theta_high[1], theta_high[2], theta_high[3], theta_high[4]
        ))
        dh = h_low - h_high
        
        # Compute inner product
        integrand = 4.0 * np.real(dh * np.conj(dh)) / psd_values[idx]
        df_padded = np.diff(f_dense[idx])
        if len(df_padded) > 0:
            df_pad = np.concatenate([[df_padded[0]], df_padded])
            exact_val = np.sum(integrand * df_pad)
        else:
            exact_val = 0.0
        exact_mismatch.append(float(exact_val))
    
    exact_mismatch = np.array(exact_mismatch)
    
    # Ratio of quadratic to exact at full band
    G_full_x, _ = fisher_mod.fisher_cumulative(theta_mid, f_dense, psd_values)
    rho2_full = dx @ G_full_x[-1] @ dx
    exact_full = exact_mismatch[-1]
    quad_to_exact = rho2_full / exact_full if exact_full > 0 else 1.0
    
    # Information fraction on smallest-λ direction
    frac_vd = []
    for k in range(n_dense):
        vd_k = eigvecs[k, :, -1]
        lam_vd = eigvals[k, -1]
        rho2_k = rho2_vals[k]
        frac_k = lam_vd * (vd_k @ dx) ** 2 / rho2_k if rho2_k > 0 else 0
        frac_vd.append(float(frac_k))
    
    results["T5"] = {
        "rho2_at_cutoffs": {
            f"f_{int(f)}": round(float(rho2_vals[i]), 4)
            for i, f in enumerate(f_cutoffs)
        },
        "exact_mismatch_full": round(float(exact_full), 4),
        "quadratic_rho2_full": round(float(rho2_full), 4),
        "quadratic_to_exact_ratio": round(float(quad_to_exact), 4),
        "vd_information_fraction_full": round(float(frac_vd[-1]), 4),
        "minimum_vd_fraction": round(float(np.min(frac_vd)), 4),
    }
    
    print(f"  ρ²(full band, quadratic): {rho2_full:.4f}")
    print(f"  Exact mismatch (full band): {exact_full:.4f}")
    print(f"  Qudratic/exact ratio: {quad_to_exact:.4f}")
    print(f"  vd info fraction: {frac_vd[-1]:.4f}")
    
    return results


if __name__ == "__main__":
    results = run()
    print(json.dumps(results, indent=2, default=str))