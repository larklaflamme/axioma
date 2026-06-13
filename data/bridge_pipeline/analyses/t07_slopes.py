"""
T7 — Growth-law slope fitting.

Fits d ln C / d ln f piecewise over PN transition bands.
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
    print("T7: Growth-law slopes")
    print("=" * 60)
    
    f_min, f_max = 22.0, 500.0
    n_dense = 200
    f_dense = np.logspace(np.log10(f_min), np.log10(f_max), n_dense)
    psd_values = psds_mod.compute_psd_values("ZDHP", f_dense)
    
    theta_mid = np.array([1.186, 0.85, 0.02, 400, 40.0])
    
    G_cum, G_full = fisher_mod.fisher_cumulative(theta_mid, f_dense, psd_values)
    C_vals, eigvals, eigvecs = fisher_mod.C_of_f(G_cum)
    
    # PN transition bands
    bands = [
        ("low", 22, 75, "22-75 Hz (0PN-1PN)"),
        ("mid", 75, 200, "75-200 Hz (1PN-2.5PN)"),
        ("high", 200, 500, "200-500 Hz (2.5PN-3.5PN+tidal)"),
    ]
    
    results = {"T7": {}}
    
    overall_slope_loglog = (
        np.log(C_vals[-1] / C_vals[0]) / np.log(f_dense[-1] / f_dense[0])
    )
    
    for band_name, f_lo, f_hi, desc in bands:
        idx = (f_dense >= f_lo) & (f_dense <= f_hi)
        f_band = f_dense[idx]
        C_band = C_vals[idx]
        
        if len(f_band) < 3:
            continue
        
        # Log-log linear fit
        log_f = np.log(f_band)
        log_C = np.log(C_band + 1e-16)
        
        slope, intercept = np.polyfit(log_f, log_C, 1)
        residuals = log_C - (slope * log_f + intercept)
        rms_residual = np.sqrt(np.mean(residuals ** 2))
        
        results["T7"][band_name] = {
            "f_range": [f_lo, f_hi],
            "description": desc,
            "slope": round(float(slope), 4),
            "intercept": round(float(intercept), 4),
            "rms_residual": round(float(rms_residual), 4),
            "n_points": int(len(f_band)),
        }
        
        print(f"  {desc}: dlnC/dlnf = {slope:.4f}, rms = {rms_residual:.4f}")
    
    # Overall slope
    results["T7"]["overall"] = {
        "slope": round(float(overall_slope_loglog), 4),
        "analytic_prediction": 0.25,  # approximate from PN power counting
        "tolerance": 0.25,  # 25% agreement
    }
    
    print(f"  Overall dlnC/dlnf = {overall_slope_loglog:.4f}")
    
    return results


if __name__ == "__main__":
    results = run()
    print(json.dumps(results, indent=2, default=str))