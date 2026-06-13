#!/usr/bin/env python3
"""
T4 — GW150914 contrast with IMR approximant (Issue #5 fix).
Review: TaylorF2 misses merger-ringdown for GW150914.
Fix: Use IMRPhenomD (lalsuite) or approximate via Fisher scaling.

Also: compare restricted to common (ln Mc, q, chi_eff, ln DL) block.
GW150914 has no tidal sector → 4D space, so no dimensionality mismatch.
"""

import sys, os, json, numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import waveform as wf
import fisher as fs
import coordinates as coord

RESULTS = os.path.join(os.path.dirname(__file__), "..", "results")


def run():
    print("=" * 60)
    print("T4 — GW150914 Contrast (IMR approximant, 4D common block)")
    print("=" * 60)
    
    # ── GW150914 parameters (from published median) ────────────────────
    # Physical params: (Mc, q, chi_eff, DL)
    # GW150914: Mc ≈ 28 Msun, q ≈ 0.8, chi_eff ≈ -0.01, DL ≈ 410 Mpc
    # No tidal deformability for BBH
    theta_gw150914 = np.array([28.0, 0.8, -0.01, 0.0, 410.0])  # Lt=0 placeholder
    
    # GW170817 parameters (midpoint)
    theta_gw170817 = np.array([1.1976, 0.86, 0.01, 300.0, 40.0])
    
    f_grid = wf.make_f_grid(20.0, 500.0, 500)
    
    # ── Compute Fisher at full band (500 Hz) ───────────────────────────
    # For GW150914: use IMRPhenomD approximation.
    # Since lalsuite is unavailable, use TaylorF2 but restrict band to
    # [20, 80] Hz (inspiral-only) for a *conservative* comparison that
    # doesn't claim to represent the merger. This is honest about the
    # approximant limitation.
    # 
    # For GW170817: full band [20, 500] Hz with TaylorF2 is appropriate.
    print("\n[GW150914 — inspiral-band Fisher (20-80 Hz, TaylorF2)]")
    f_grid_gw150 = wf.make_f_grid(20.0, 80.0, 200)
    G_150, idx_a_150, _ = fs.fisher_cumulative(theta_gw150914, f_grid_gw150, wf.psd_zdhp)
    ev_150, evc_150 = fs.eigensweep(G_150, idx_a_150)
    cond_150 = ev_150[-1, 0] / max(ev_150[-1, -1], 1e-300)
    
    print(f"  Condition number κ(80 Hz) = {cond_150:.2e}")
    print(f"  Eigenvalues: {ev_150[-1]}")
    
    print("\n[GW170817 — full-band Fisher (20-500 Hz, TaylorF2)]")
    G_817, idx_a_817, _ = fs.fisher_cumulative(theta_gw170817, f_grid, wf.psd_zdhp)
    ev_817, evc_817 = fs.eigensweep(G_817, idx_a_817)
    cond_817 = ev_817[-1, 0] / max(ev_817[-1, -1], 1e-300)
    
    print(f"  Condition number κ(500 Hz) = {cond_817:.2e}")
    print(f"  Eigenvalues: {ev_817[-1]}")
    
    # ── Common 4D block comparison ─────────────────────────────────────
    # Both problems: (ln Mc, q, chi_eff, ln DL) — remove tidal dimension
    print("\n[Common 4D block comparison]")
    print("  Parameter set: (ln Mc, q, chi_eff, ln DL)")
    
    # Extract 4D Fisher sub-blocks from the last cutoff
    G4_150 = G_150[-1][[0, 1, 2, 4], :][:, [0, 1, 2, 4]]
    G4_817 = G_817[-1][[0, 1, 2, 4], :][:, [0, 1, 2, 4]]
    
    cond4_150 = np.linalg.cond(G4_150) if np.all(np.linalg.eigvalsh(G4_150) > 0) else np.inf
    cond4_817 = np.linalg.cond(G4_817) if np.all(np.linalg.eigvalsh(G4_817) > 0) else np.inf
    
    print(f"  GW150914 κ₄(80 Hz)  = {cond4_150:.2e}")
    print(f"  GW170817 κ₄(500 Hz) = {cond4_817:.2e}")
    print(f"  Ratio κ₈₁₇/κ₁₅₀     = {cond4_817/cond4_150:.2e}")
    
    # ── Prior-induced displacement comparison ──────────────────────────
    # For GW150914: the prior perturbation is effectively zero (no two-prior contrast exists)
    # So the "order of magnitude" claim must be restricted to the Fisher condition ratio.
    # The review says: compare restricted to common (ln Mc, q, chi_eff, ln DL) block.
    
    # Save to manifest-compatible format
    results = {
        "T4.condition_GW150914_4D": float(cond4_150),
        "T4.condition_GW170817_4D": float(cond4_817),
        "T4.condition_ratio": float(cond4_817 / cond4_150),
        "T4.event": "GW150914 (inspiral 20-80 Hz) vs GW170817 (20-500 Hz)",
        "T4.note": "Common 4D block (ln Mc, q, chi_eff, ln DL); GW150914 TaylorF2 restricted to inspiral band; IMR approximant needed for full comparison",
    }
    
    # Write to results
    path = os.path.join(RESULTS, "t04_gw150914_contrast.json")
    os.makedirs(RESULTS, exist_ok=True)
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved {path}")
    
    # Print manifest entries
    print("\n=== MANIFEST ENTRIES ===")
    print(f"  condition_GW150914_4D: {cond4_150:.2e}")
    print(f"  condition_GW170817_4D: {cond4_817:.2e}")
    print(f"  condition_ratio:       {cond4_817/cond4_150:.2e}")


if __name__ == "__main__":
    run()