"""
T6 — C(f) sweep + robustness battery.

Primary C(f) computation across 18 cutoffs + dense grid, with robustness
envelope across conventions and expansion points (Issue #3, #4, #5).
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
    print("T6: C(f) sweep + robustness battery")
    print("=" * 60)
    
    f_min, f_max = 22.0, 500.0
    n_cutoffs = 18
    f_cutoffs = np.logspace(np.log10(f_min), np.log10(f_max), n_cutoffs)
    n_dense = 200
    f_dense = np.logspace(np.log10(f_min), np.log10(f_max), n_dense)
    psd_values = psds_mod.compute_psd_values("ZDHP", f_dense)
    
    # Three expansion points spanning ridge
    theta_lo = np.array([1.186, 0.88, 0.005, 380, 40.0])
    theta_mid = np.array([1.186, 0.85, 0.02, 400, 40.0])
    theta_hi = np.array([1.186, 0.75, 0.06, 450, 40.0])
    
    expansion_points = {
        "lowSpin_mean": theta_lo,
        "midpoint": theta_mid,
        "highSpin_mean": theta_hi,
    }
    
    conventions = ["primary", "ALT-A", "ALT-B"]
    
    # Store C(f) curves for all combinations
    all_C = {}
    
    for conv in conventions:
        all_C[conv] = {}
        for label, theta in expansion_points.items():
            G_cum, G_full = fisher_mod.fisher_cumulative(theta, f_dense, psd_values, convention=conv)
            C_vals, eigvals, eigvecs = fisher_mod.C_of_f(G_cum)
            
            # Values at reporting cutoffs
            C_at_cutoffs = {}
            for f_target in f_cutoffs:
                idx = np.argmin(np.abs(f_dense - f_target))
                C_at_cutoffs[f"f_{int(f_target)}"] = float(C_vals[idx])
            
            growth_factor = float(C_vals[-1] / C_vals[0])
            
            all_C[conv][label] = {
                "C_at_cutoffs": C_at_cutoffs,
                "C_full": float(C_vals[-1]),
                "C_low": float(C_vals[0]),
                "growth_factor": growth_factor,
                "vd_outside_block": float(1.0 - eigvecs[-1, 1, -1]**2 - eigvecs[-1, 2, -1]**2 - eigvecs[-1, 3, -1]**2),
            }
    
    # Primary values (midpoint, primary convention)
    primary = all_C["primary"]["midpoint"]
    
    # Robustness envelope
    all_growth = []
    for conv in conventions:
        for label in expansion_points:
            all_growth.append(all_C[conv][label]["growth_factor"])
    
    growth_central = primary["growth_factor"]
    growth_min = min(all_growth)
    growth_max = max(all_growth)
    growth_envelope = max(growth_central - growth_min, growth_max - growth_central)
    
    # Values at specific cutoffs for the table
    f_table = [22, 35, 75, 200, 500]
    C_table = {}
    for f_t in f_table:
        idx = np.argmin(np.abs(f_dense - f_t))
        C_table[f"C{f_t}"] = round(float(primary["C_at_cutoffs"][f"f_{f_t}"]), 4)
    
    results = {
        "T6": {
            "growth_factor": round(growth_central, 2),
            "growth_envelope": round(growth_envelope, 2),
            "growth_min": round(growth_min, 2),
            "growth_max": round(growth_max, 2),
            "C_low": round(primary["C_low"], 4),
            "C_full": round(primary["C_full"], 4),
            "vd_outside_block": round(primary["vd_outside_block"], 4),
            "ridge_uniformity_band": f"{growth_min:.2f}-{growth_max:.2f}",
            "C_at_reporting": {k: round(v, 4) for k, v in primary["C_at_cutoffs"].items()},
        }
    }
    
    print(f"  Primary growth factor: {growth_central:.2f}x")
    print(f"  Envelope: [{growth_min:.2f}, {growth_max:.2f}]")
    print(f"  C(22 Hz) = {primary['C_low']:.4f}, C(500 Hz) = {primary['C_full']:.4f}")
    
    return results


if __name__ == "__main__":
    results = run()
    print(json.dumps(results, indent=2, default=str))