"""
T4 — GW150914 contrast.

Computes condition number and lensing gain for GW150914 vs GW170817.
Replaces TaylorF2 with proper IMR treatment for T4 (Issue #5).
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
    print("T4: GW150914 contrast")
    print("=" * 60)
    
    f_min, f_max = 22.0, 500.0
    n_dense = 500
    f_dense = np.logspace(np.log10(f_min), np.log10(f_max), n_dense)
    psd_values = psds_mod.compute_psd_values("ZDHP", f_dense)
    
    # GW150914 parameters (BBH, no tidal)
    theta_150914 = np.array([28.1, 0.81, -0.06, 0, 410.0])
    
    # GW170817 parameters (BNS, tidal)
    theta_170817 = np.array([1.186, 0.85, 0.02, 400, 40.0])
    
    results = {"T4": {}}
    
    for label, theta in [("GW150914", theta_150914), ("GW170817", theta_170817)]:
        G_cum, G_full = fisher_mod.fisher_cumulative(theta, f_dense, psd_values)
        
        # For BBH: use 4D parameter space (drop tidal)
        if label == "GW150914":
            G_4d = G_full[:4, :4]  # (ln Mc, q, chi_eff, ln DL)
            kappa = fisher_mod.condition_number(G_4d)
            lam_min = np.linalg.eigvalsh(G_4d)[0]
        else:
            kappa = fisher_mod.condition_number(G_full)
            lam_min = np.linalg.eigvalsh(G_full)[0]
        
        gain = 1.0 / lam_min
        
        results["T4"][label] = {
            "condition_number": round(float(kappa), 1),
            "lensing_gain": round(float(gain), 1),
            "dimensions": 4 if label == "GW150914" else 5,
        }
        
        print(f"  {label}: κ = {kappa:.1f}, gain = {gain:.1f}, dim = {4 if label == 'GW150914' else 5}")
    
    # Ratio (restricted to common 4D block for fair comparison)
    G_170817_4d = fisher_mod.fisher_cumulative(theta_170817, f_dense, psd_values)[1][:4, :4]
    kappa_170817_4d = fisher_mod.condition_number(G_170817_4d)
    kappa_150914_4d = fisher_mod.condition_number(
        fisher_mod.fisher_cumulative(theta_150914, f_dense, psd_values)[1][:4, :4]
    )
    kappa_ratio = kappa_170817_4d / kappa_150914_4d
    
    results["T4"]["common_4d_block"] = {
        "kappa_GW170817_4d": round(float(kappa_170817_4d), 1),
        "kappa_GW150914_4d": round(float(kappa_150914_4d), 1),
        "kappa_ratio": round(float(kappa_ratio), 1),
    }
    
    print(f"  Common 4D block: κ_170817/κ_150914 = {kappa_ratio:.1f}")
    
    return results


if __name__ == "__main__":
    results = run()
    print(json.dumps(results, indent=2, default=str))