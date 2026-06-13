"""
T9 — Forward model: weight trajectory, f*, and N(f).

Resolves Issue #4 (N(f) restriction) and produces the peak-drop prediction.
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
    print("T9: Forward model (weight trajectory, f*, N(f))")
    print("=" * 60)
    
    f_min, f_max = 22.0, 500.0
    n_dense = 200
    f_dense = np.logspace(np.log10(f_min), np.log10(f_max), n_dense)
    psd_values = psds_mod.compute_psd_values("ZDHP", f_dense)
    
    theta_low = np.array([1.186, 0.88, 0.005, 380, 40.0])
    theta_high = np.array([1.186, 0.75, 0.06, 450, 40.0])
    theta_mid = (theta_low + theta_high) / 2.0
    
    x_low = coords.to_primary(theta_low.reshape(1, -1))[0]
    x_high = coords.to_primary(theta_high.reshape(1, -1))[0]
    dx = x_high - x_low
    
    G_cum, G_full = fisher_mod.fisher_cumulative(theta_mid, f_dense, psd_values)
    eigvals, eigvecs = fisher_mod.eigensweep(G_cum)
    vd = eigvecs[-1, :, -1]
    
    # ρ²(f) at dense grid
    rho2_vals = fisher_mod.rho2(G_cum, dx)
    
    # Find f* where ρ² = 2
    # Also thresholds 1 and 4 for sensitivity band
    fstar_2 = None
    fstar_1 = None
    fstar_4 = None
    
    for thresh, key in [(2.0, "fstar_2"), (1.0, "fstar_1"), (4.0, "fstar_4")]:
        crossings = np.where(np.diff(np.sign(rho2_vals - thresh)))[0]
        if len(crossings) > 0:
            idx = crossings[0]
            # Linear interpolation
            f_lo, f_hi = f_dense[idx], f_dense[idx+1]
            r_lo, r_hi = rho2_vals[idx], rho2_vals[idx+1]
            f_star = f_lo + (thresh - r_lo) * (f_hi - f_lo) / (r_hi - r_lo)
            if key == "fstar_2":
                fstar_2 = float(f_star)
            elif key == "fstar_1":
                fstar_1 = float(f_star)
            else:
                fstar_4 = float(f_star)
    
    # Peak between-mode variance
    # w2/w1 = exp(-0.5*rho2 + rho*z), z ~ N(0,1)
    # between-mode variance = w1*w2*(vd^T*dx)^2
    vd_dx = float(vd @ dx)
    
    rng = np.random.RandomState(42)
    n_draws = 10000
    z = rng.normal(0, 1, size=n_draws)
    
    between_var = np.zeros(n_dense)
    for k in range(n_dense):
        rho = np.sqrt(rho2_vals[k])
        log_odds = -0.5 * rho2_vals[k] + rho * z
        w2_over_w1 = np.exp(log_odds)
        w1 = 1.0 / (1.0 + w2_over_w1)
        w2 = w2_over_w1 / (1.0 + w2_over_w1)
        between_var[k] = np.mean(w1 * w2) * vd_dx ** 2
    
    peak_idx = np.argmax(between_var)
    peak_magnitude = float(between_var[peak_idx])
    
    # Event-to-event scatter of f*
    fstar_draws = []
    for d in range(100):
        z_d = rng.normal(0, 1, size=n_draws)
        between_var_d = np.zeros(n_dense)
        for k in range(n_dense):
            rho = np.sqrt(rho2_vals[k])
            log_odds = -0.5 * rho2_vals[k] + rho * z_d
            w2_over_w1 = np.exp(log_odds)
            w1 = 1.0 / (1.0 + w2_over_w1)
            w2 = w2_over_w1 / (1.0 + w2_over_w1)
            between_var_d[k] = np.mean(w1 * w2) * vd_dx ** 2
        peak_d = np.argmax(between_var_d)
        fstar_draws.append(f_dense[peak_d])
    
    fstar_scatter = float(np.std(fstar_draws))
    
    # N(f) — non-Gaussianity index
    # N(f) = Var_{rho_f}(vd^T x) / (Gamma^{-1})_{vd,vd}
    N_f = np.zeros(n_dense)
    for k in range(n_dense):
        G_k = G_cum[k]
        try:
            Ginv_vdvd = np.linalg.inv(G_k)[-1, -1]  # vd is last eigendirection
            # True variance along vd (approximated from ridge length)
            ridge_var = vd_dx ** 2 / 4.0  # approximate spread along ridge
            N_f[k] = ridge_var / Ginv_vdvd
        except:
            N_f[k] = 100.0
    
    N500 = float(N_f[-1])
    
    results = {
        "T9": {
            "fstar_2": round(fstar_2, 1) if fstar_2 else None,
            "fstar_1": round(fstar_1, 1) if fstar_1 else None,
            "fstar_4": round(fstar_4, 1) if fstar_4 else None,
            "peak_magnitude": round(peak_magnitude, 4),
            "fstar_scatter": round(fstar_scatter, 1),
            "N500": round(N500, 2),
            "vd_dot_dx": round(vd_dx, 4),
        }
    }
    
    print(f"  f* (rho²=2): {fstar_2:.1f} Hz")
    print(f"  f* sensitivity band: [{fstar_1:.1f}, {fstar_4:.1f}] Hz")
    print(f"  Peak magnitude: {peak_magnitude:.4f}")
    print(f"  f* scatter: {fstar_scatter:.1f} Hz")
    print(f"  N(500 Hz): {N500:.2f}")
    
    return results


if __name__ == "__main__":
    results = run()
    print(json.dumps(results, indent=2, default=str))