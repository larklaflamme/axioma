"""
U0 — Regenerated Fisher stack in declared coordinates.

Issue: pipeline_data.npz used η coordinates with unscaled Λ̃, giving κ ~ 10^16
and χ_eff-dominated vd. The paper's Table III reports κ ~ 10^8 with Λ̃/100-dominated
vd. This generator creates a clean stack using the rho_pi_bridge's verified
infrastructure: JAX waveform, correct PSD normalization (SN_REF = 1.6e-46),
declared coordinates (ln Mc, q, χ_eff, Λ̃/100, ln DL).

Output: /home/ubuntu/axioma/data/rho_pi_bridge/results/U0_stack.npz
Keys: f_grid, G_full_stack (Nf,5,5), f_a (idx_a indices), f_m (manuscript),
      evals (Na,5), evecs (Na,5,5), C_vals (Na), κ_vals (Na),
      vd (5), theta_phys (5,)
"""

import sys, os, json, time
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "..", "src")
sys.path.insert(0, SRC)

import waveform as wf
import fisher as fs

# ----- Parameters -----
THETA_PHYS = np.array([1.186, 0.85, 0.02, 400.0, 40.0])  # Mc, q, χ_eff, Λ̃, DL
F_MIN, F_MAX = 22.0, 500.0   # match paper frequency range
N = 500                       # match paper's N=500 point grid
PSD_FUNC = wf.psd_zdhp        # aLIGO ZDHP design, SN_REF = 1.6e-46

OUTPUT_PATH = os.path.join(BASE, "..", "results", "U0_stack.npz")


def run():
    t0 = time.time()
    print("=" * 60)
    print("U0: Regenerate Fisher stack in declared coordinates")
    print("=" * 60)
    print(f"  θ_phys = {THETA_PHYS}")
    print(f"  f ∈ [{F_MIN}, {F_MAX}] Hz, N={N}")
    print(f"  PSD: ZDHP (SN_REF = 1.6e-46)")
    print(f"  Coordinates: ln Mc, q, χ_eff, Λ̃/100, ln DL")

    # ---- Use the module's run_fisher_sweep which does everything correctly ----
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
    vd = evecs[-1, :, -1]
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
    print(f"    λ_max    = {evals[-1, 0]:.6e}")
    print(f"    λ_min    = {evals[-1, -1]:.6e}")
    print(f"    vd       = {vd}")
    print(f"    vd[3] (Λ̃/100) = {vd[3]:.4f}, vd[2] (χ_eff) = {vd[2]:.4f}")

    # ---- Compare with paper Table III target ----
    print(f"\n  {'='*44}")
    print(f"  COMPARISON WITH PAPER TABLE III")
    print(f"  {'='*44}")
    print(f"    κ (paper):   ~10^8")
    print(f"    κ (U0):      {conds[-1]:.2e}")
    print(f"    Match: {'YES ✓' if 1e7 < conds[-1] < 1e9 else 'NO ✗'}")
    growth = C_vals[-1] / C_vals[0] if C_vals[0] > 0 else float('inf')
    print(f"    Growth (U0): {growth:.2e}x")

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
             )
    print(f"\n  Saved to {OUTPUT_PATH}")

    # ---- Summary ----
    summary = {
        "U0_κ_full": float(conds[-1]),
        "U0_C_full": float(C_vals[-1]),
        "U0_C_first": float(C_vals[0]),
        "U0_growth": float(growth),
        "U0_vd": [float(v) for v in vd],
        "U0_λ_max": float(evals[-1, 0]),
        "U0_λ_min": float(evals[-1, -1]),
        "U0_elapsed_s": t1 - t0,
    }
    summary_path = os.path.join(BASE, "..", "results", "U0_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Summary saved to {summary_path}")

    return summary


if __name__ == "__main__":
    run()