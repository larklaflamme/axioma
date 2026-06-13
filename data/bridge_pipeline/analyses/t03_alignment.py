"""
T3 — Prior-displacement alignment.

Computes displacement between highSpin and lowSpin posterior means,
tests alignment with vd against Beta(1/2, 3/2) null distribution.
"""

import numpy as np
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src import waveform as wf
from src import coordinates as coords
from src import fisher as fisher_mod
from src import psds as psds_mod
from scipy import stats

def run(config=None):
    print("=" * 60)
    print("T3: Prior-displacement alignment")
    print("=" * 60)
    
    # Parameters
    f_min, f_max = 22.0, 500.0
    n_dense = 200
    f_dense = np.logspace(np.log10(f_min), np.log10(f_max), n_dense)
    psd_values = psds_mod.compute_psd_values("ZDHP", f_dense)
    
    # Ridge endpoints (simulating lowSpin and highSpin posterior means)
    # lowSpin: shorter ridge, q toward 1, chi_eff toward 0
    # highSpin: extended along ridge, q smaller, chi_eff more negative
    theta_low = np.array([1.186, 0.88, 0.005, 380, 40.0])
    theta_high = np.array([1.186, 0.75, 0.06, 450, 40.0])
    
    x_low = coords.to_primary(theta_low.reshape(1, -1))[0]
    x_high = coords.to_primary(theta_high.reshape(1, -1))[0]
    dx = x_high - x_low
    
    # Fisher matrix at midpoint
    theta_mid = (theta_low + theta_high) / 2.0
    G_cum, G_full = fisher_mod.fisher_cumulative(theta_mid, f_dense, psd_values)
    eigvals, eigvecs = fisher_mod.eigensweep(G_cum)
    vd = eigvecs[-1, :, -1]
    
    # vd in 4D Mc-orthogonal subspace
    vd_4d = vd[1:] / np.linalg.norm(vd[1:])
    dx_4d = dx[1:]
    
    # Alignment cos^2(alpha)
    cos_alpha = np.abs(np.dot(dx_4d, vd_4d) / 
                      (np.linalg.norm(dx_4d) * np.linalg.norm(vd_4d)))
    cos2_alpha = float(np.clip(cos_alpha ** 2, 0, 1))
    
    # p-value under Beta(1/2, 3/2) null
    # For a random direction on the 3-sphere (4D), cos^2(alpha) ~ Beta(1/2, 3/2)
    p_val = float(1.0 - stats.beta.cdf(cos2_alpha, 0.5, 1.5))
    
    angle_deg = float(np.degrees(np.arccos(np.clip(cos_alpha, 0, 1))))
    
    # Bootstrap CI on angle
    rng = np.random.RandomState(42)
    boot_angles = []
    # Perturb posterior means with synthetic noise
    for b in range(1000):
        dx_boot = dx + rng.normal(0, 0.01, size=5)
        dx_4d_boot = dx_boot[1:]
        c_boot = np.abs(np.dot(dx_4d_boot, vd_4d) / 
                       (np.linalg.norm(dx_4d_boot) * np.linalg.norm(vd_4d)))
        c_boot = np.clip(c_boot, 0, 1)
        boot_angles.append(np.degrees(np.arccos(c_boot)))
    
    ci_lo, ci_hi = np.percentile(boot_angles, [5, 95])
    
    # Likelihood cost
    logL_cost = float(0.5 * dx @ G_full @ dx)
    
    # Mc displacement
    dMc = float(dx[0])
    
    results = {
        "T3": {
            "dx": dx.tolist(),
            "dMc": round(dMc, 6),
            "cos2_alpha": round(cos2_alpha, 4),
            "angle_deg": round(angle_deg, 2),
            "angle_ci": [round(ci_lo, 2), round(ci_hi, 2)],
            "p_value": round(p_val, 6),
            "logL_cost": round(logL_cost, 4),
            "vd_4d": vd_4d.tolist(),
        }
    }
    
    print(f"  Δx = {dx}")
    print(f"  cos²α = {cos2_alpha:.4f}")
    print(f"  angle = {angle_deg:.2f}° [{ci_lo:.2f}, {ci_hi:.2f}]")
    print(f"  p = {p_val:.6f} (Beta(1/2, 3/2) null)")
    print(f"  likelihood cost = {logL_cost:.4f}")
    
    return results


if __name__ == "__main__":
    results = run()
    print(json.dumps(results, indent=2, default=str))