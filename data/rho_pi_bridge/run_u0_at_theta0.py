"""
U0 regeneration at θ₀ (Skye's physical midpoint of lowSpin and highSpin posterior means).

θ₀_phys = [1.197598, 0.799010, 0.013452, 594.794, 39.3695]
  Mc = 1.197598 Msun
  q  = 0.799010
  χ_eff = 0.013452
  Λ̃ = 594.794
  DL = 39.3695 Mpc

Coordinates: ln Mc, q, χ_eff, Λ̃/100, ln DL
PSD: aLIGO ZDHP (SN_REF = 1.6e-46)
Frequency: 20–500 Hz, 500 points log-spaced
Output: U0_stack_at_theta0.npz in results/
"""

import sys, os, json, time
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import waveform as wf
import fisher as fs
import coordinates as coord

# ----- Approved midpoint θ₀ (physical parameters) -----
# From Skye's calculation: arithmetic mean of lowSpin and highSpin posterior means
THETA_PHYS = np.array([1.197598, 0.799010, 0.013452, 594.794, 39.3695])

# Frequency range: match paper (20-500 Hz)
F_MIN, F_MAX = 20.0, 500.0
N = 500  # frequency points, log-spaced
PSD_FUNC = wf.psd_zdhp  # aLIGO ZDHP design, SN_REF = 1.6e-46

OUTPUT_PATH = os.path.join(BASE, "results", "U0_stack_at_theta0.npz")
SUMMARY_PATH = os.path.join(BASE, "results", "U0_theta0_summary.json")


def run():
    t0 = time.time()
    print("=" * 60)
    print("U0: Regenerate Fisher stack at θ₀ (midpoint expansion)")
    print("=" * 60)
    print(f"  θ₀_phys = {THETA_PHYS}")
    phys_names = ["Mc (Msun)", "q", "χ_eff", "Λ̃", "DL (Mpc)"]
    for i, (val, name) in enumerate(zip(THETA_PHYS, phys_names)):
        print(f"    {name}: {val}")
    
    # Convert to declared coordinates for display
    x0 = coord.to_primary(THETA_PHYS)
    coord_names = ["ln Mc", "q", "χ_eff", "Λ̃/100", "ln DL"]
    print(f"\n  θ₀ in declared coordinates:")
    for i, (val, name) in enumerate(zip(x0, coord_names)):
        print(f"    {name}: {val:.6f}")

    print(f"\n  f ∈ [{F_MIN}, {F_MAX}] Hz, N={N}, log-spaced")
    print(f"  PSD: ZDHP (SN_REF = {wf.SN_REF:.1e})")
    print(f"  Coordinates: ln Mc, q, χ_eff, Λ̃/100, ln DL")
    print(f"\n  Computing...")

    # ---- Run the full Fisher sweep ----
    result = fs.run_fisher_sweep(
        theta_phys=THETA_PHYS,
        psd_func=PSD_FUNC,
        f_min=F_MIN,
        f_max=F_MAX,
        N=N,
    )

    t1 = time.time()
    print(f"\n  Computed in {t1-t0:.1f}s")

    # ---- Extract key results ----
    f_grid = result["f_grid"]
    G_full = result["G"]           # (Nf, 5, 5)
    idx_a = result["idx_a"]         # evaluation indices
    idx_m = result["idx_m"]         # manuscript cutoff indices
    f_a = result["f_vals"]          # frequencies at idx_a
    f_m = result["f_manu"]          # manuscript frequencies
    evals = result["evals"]         # (Na, 5)
    evecs = result["evecs"]         # (Na, 5, 5)
    C_vals = result["C_vals"]       # (Na,)
    C_manu = result["C_manu"]       # (Nm,)
    conds = result["cond_nums"]     # (Na,)

    # Degeneracy direction at full band (last evaluation point)
    vd = evecs[-1, :, -1].copy()
    # Sign convention: make Λ̃/100 component positive
    if vd[3] < 0:
        vd = -vd

    # ---- Report manuscript cutoffs ----
    print(f"\n  {'f (Hz)':>10s} {'C(f)':>14s} {'κ(f)':>14s}")
    print(f"  {'-'*44}")
    for i, f_val in enumerate(f_m):
        print(f"  {f_val:10.1f} {C_manu[i]:14.6e} {np.linalg.cond(G_full[idx_m[i]]):14.6e}")

    print(f"\n  Full-band results (f = {f_a[-1]:.1f} Hz):")
    print(f"    κ        = {conds[-1]:.6e}")
    print(f"    C        = {C_vals[-1]:.6e}")
    print(f"    C_first  = {C_vals[0]:.6e}")
    growth = C_vals[-1] / C_vals[0] if C_vals[0] > 0 else float('inf')
    print(f"    Growth   = {growth:.2e}x")
    print(f"    λ_max    = {evals[-1, 0]:.6e}")
    print(f"    λ_min    = {evals[-1, -1]:.6e}")
    print(f"    λ ratios = {evals[-1]}")
    print(f"    vd       = {vd}")
    print(f"    vd[3] (Λ̃/100) = {vd[3]:.4f}, vd[1] (q) = {vd[1]:.4f}, vd[2] (χ_eff) = {vd[2]:.4f}")

    # ---- Compute κ at full band for comparison ----
    print(f"\n  {'='*44}")
    print(f"  COMPARISON")
    print(f"  {'='*44}")
    print(f"    κ(500 Hz) θ₀:       {conds[-1]:.2e}")
    print(f"    κ(500 Hz) old U0:   3.01e10  (θ=[1.186,0.85,0.02,400,40])")
    print(f"    C growth θ₀:        {growth:.2e}x")
    print(f"    C growth old U0:    5.35e05x")

    # ---- Save ----
    np.savez(OUTPUT_PATH,
             f_grid=f_grid,
             G=G_full,
             idx_a=idx_a,
             idx_m=idx_m,
             f_a=f_a,
             f_m=f_m,
             evals=evals,
             evecs=evecs,
             C_vals=C_vals,
             C_manu=C_manu,
             κ_vals=conds,
             κ_manu=np.array([np.linalg.cond(G_full[i]) for i in idx_m]),
             vd=vd,
             theta_phys=THETA_PHYS,
             theta0_primary=x0,
             )
    print(f"\n  Saved to {OUTPUT_PATH}")

    # ---- Summary JSON ----
    summary = {
        "theta_phys": [float(v) for v in THETA_PHYS],
        "theta0_primary": [float(v) for v in x0],
        "kappa_full": float(conds[-1]),
        "C_full": float(C_vals[-1]),
        "C_first": float(C_vals[0]),
        "growth_factor": float(growth),
        "vd": [float(v) for v in vd],
        "lambda_max": float(evals[-1, 0]),
        "lambda_min": float(evals[-1, -1]),
        "lambda_all": [float(v) for v in evals[-1]],
        "f_min": F_MIN,
        "f_max": F_MAX,
        "N_freq": N,
        "psd": "ZDHP",
        "sn_ref": wf.SN_REF,
        "elapsed_s": t1 - t0,
    }
    with open(SUMMARY_PATH, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Summary saved to {SUMMARY_PATH}")

    return summary


if __name__ == "__main__":
    s = run()