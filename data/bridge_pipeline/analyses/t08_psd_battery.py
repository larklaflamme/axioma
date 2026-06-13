"""
T8 — PSD robustness battery.

Tests commutator metrics across 4 PSDs (analytic and measured).
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
    print("T8: PSD robustness battery")
    print("=" * 60)
    
    f_min, f_max = 22.0, 500.0
    n_dense = 200
    f_dense = np.logspace(np.log10(f_min), np.log10(f_max), n_dense)
    
    theta_mid = np.array([1.186, 0.85, 0.02, 400, 40.0])
    
    psd_names = ["ZDHP", "Early_aLIGO", "O2_H1", "O2_L1"]
    
    results = {"T8": {}}
    
    all_C22 = []
    all_C500 = []
    all_comm_int = []
    
    for psd_name in psd_names:
        psd_values = psds_mod.compute_psd_values(psd_name, f_dense)
        
        G_cum, G_full = fisher_mod.fisher_cumulative(theta_mid, f_dense, psd_values)
        C_vals, eigvals, eigvecs = fisher_mod.C_of_f(G_cum)
        comm_int, _ = fisher_mod.commutator_integral(G_cum)
        
        f_22_idx = np.argmin(np.abs(f_dense - 22))
        f_500_idx = np.argmin(np.abs(f_dense - 500))
        
        C22 = float(C_vals[f_22_idx])
        C500 = float(C_vals[f_500_idx])
        
        results["T8"][psd_name] = {
            "commutator_integral": round(float(comm_int), 4),
            "C_at_22Hz": round(C22, 4),
            "C_at_500Hz": round(C500, 4),
        }
        
        all_C22.append(C22)
        all_C500.append(C500)
        all_comm_int.append(float(comm_int))
        
        print(f"  {psd_name}: C(22)={C22:.4f}, C(500)={C500:.4f}, int={comm_int:.4f}")
    
    # Variation across PSDs
    C500_variation = max(all_C500) - min(all_C500)
    C500_variation_rel = C500_variation / np.mean(all_C500)
    
    results["T8"]["max_variation"] = round(C500_variation_rel * 100, 2)  # percent
    results["T8"]["max_variation_absolute"] = round(C500_variation, 4)
    
    print(f"  Max C(500) variation: {C500_variation_rel*100:.2f}%")
    
    return results


if __name__ == "__main__":
    results = run()
    print(json.dumps(results, indent=2, default=str))