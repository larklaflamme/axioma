#!/usr/bin/env python3
"""
T5 — Invariant displacement scalars (Issues #3, #8 → §III)  
T7 — Growth-law slope (Issue #5 → §V derivation check)  
T8 — PSD battery (Issue #7 → §IV)  
T9 — Derived weight trajectory, f*, N(f) (Issue #6 → §V)  

Single pipeline depending on T6's results.  
All results written to manifest.json + manifest.tex.  
"""

import sys, os, json
import numpy as np
from scipy import stats

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import coordinates as coord
import waveform as wf
import fisher as fs
from manifest import get_manifest

F_MIN = 20.0; F_MAX = 2048.0; N_DENSE = 500

MANUSCRIPT_CUTOFFS = np.array([
    22, 25, 30, 35, 45, 50, 60, 75, 100,
    120, 150, 200, 250, 300, 350, 400, 450, 500
], dtype=float)

THETA_LOW  = np.array([1.1976, 0.866, 0.003, 300.0, 40.0])
THETA_HIGH = np.array([1.1976, 0.722, 0.016, 300.0, 40.0])
THETA_MID  = np.array([1.1976, 0.86,  0.01,  300.0, 40.0])


def run():
    mf = get_manifest()
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    
    # ── Load T6 results ────────────────────────────────────────────────
    t6_path = os.path.join(results_dir, "t06_sweep.npz")
    if not os.path.exists(t6_path):
        print("[ERROR] T6 results not found — run t06_fisher_sweep.py first.")
        sys.exit(1)
    
    t6_data = np.load(t6_path)
    f_grid = t6_data["f_grid"]
    G_stack = t6_data["G"]
    C_vals = t6_data["C"]
    lam = t6_data["lam"]
    vs = t6_data["vs"]
    idx_all = t6_data["idx_all"]
    growth = float(t6_data["growth"])
    C_cut = t6_data["C_cut"]
    f_samp = f_grid[idx_all]
    
    print(f"Loaded T6: {len(f_grid)} freq pts, {len(idx_all)} sampled, "
          f"growth={growth:.3e}")
    
    dx = coord.to_primary(THETA_HIGH) - coord.to_primary(THETA_LOW)
    
    # ── T5: Invariant displacement scalars ──────────────────────────────
    print("\n[T5: Invariant displacement scalars]")
    dtheta_phys = THETA_HIGH - THETA_LOW
    print(f"  Δθ (phys): Mc={dtheta_phys[0]:.4f}  q={dtheta_phys[1]:.4f}  "
          f"χeff={dtheta_phys[2]:.4f}  Λ̃={dtheta_phys[3]:.1f}  DL={dtheta_phys[4]:.4f}")
    print(f"  Δx (coord): lnMc={dx[0]:.6f}  q={dx[1]:.4f}  "
          f"χeff={dx[2]:.4f}  Λ̃/100={dx[3]:.4f}  lnDL={dx[4]:.6f}")
    print(f"  |Δx|₄ = {np.linalg.norm(dx[1:]):.4f}  (Mc-orthogonal subspace)")
    
    mf.record("T3.dMc", float(dtheta_phys[0]), section="III", table="displacement",
              note="ΔMc = highSpin_mean - lowSpin_mean, physical units")
    
    # ρ²(f) = Δx^T Γ(f) Δx at full band
    G_last = G_stack[-1]
    rho2_full = dx @ G_last @ dx
    print(f"  ρ²(500 Hz) = {rho2_full:.6e}")
    mf.record("T5.rho2_full_band", float(rho2_full), section="III", table="displacement",
              note="ρ² = Δx^T Γ(500 Hz) Δx, 4× convention (quadratic form)")
    
    # Exact mismatch
    print("  [T5: exact mismatch at full band]")
    f_grid_concrete = np.array(wf.make_f_grid(F_MIN, F_MAX, N_DENSE))
    h_low  = np.array(wf.htilde(f_grid_concrete, *THETA_LOW))
    h_high = np.array(wf.htilde(f_grid_concrete, *THETA_HIGH))
    Sn_arr = np.array(wf.psd_zdhp(f_grid_concrete))
    dh = h_high - h_low
    mismatch_exact_dh = float(wf.inner(dh, dh, f_grid_concrete, Sn_arr))
    print(f"    ⟨δh|δh⟩ exact = {mismatch_exact_dh:.6e}")
    ratio = rho2_full / mismatch_exact_dh if mismatch_exact_dh > 0 else 0.0
    print(f"    ρ² / ⟨δh|δh⟩ = {ratio:.6f}")
    mf.record("T5.mismatch_exact_dh", mismatch_exact_dh, section="III",
              note="Exact ⟨δh|δh⟩ = 4 Re ∫ |h_high-h_low|²/Sn df")
    mf.record("T5.rho2_ratio_exact", float(ratio), section="III",
              note="ρ²_quadratic / ⟨δh|δh⟩_exact — should → 1 in linear regime")
    
    # Alignment with v_d
    vd = vs[-1, :, -1] if np.any(vs) else np.zeros(5)
    vd_4d = vd[1:]
    if np.linalg.norm(vd_4d) > 0 and np.linalg.norm(dx[1:]) > 0:
        cos_a = abs(dx[1:] @ vd_4d) / (np.linalg.norm(dx[1:]) * np.linalg.norm(vd_4d))
        cos2 = cos_a**2
        p_val = 1.0 - stats.beta.cdf(cos2, 0.5, 1.5)
        ang = np.degrees(np.arccos(np.clip(cos_a, 0, 1)))
        print(f"  cos²α = {cos2:.6f}, α = {ang:.2f}°, p = {p_val:.4f}")
        mf.record("T3.cos2a", float(cos2), section="III", table="displacement")
        mf.record("T3.pval", float(p_val), section="III", table="displacement")
        mf.record("T3.angle", float(ang), section="III", table="displacement", unit="deg")
    
    # ── T7: Growth-law slope ────────────────────────────────────────────
    print("\n[T7: Growth-law slope]")
    if np.any(C_vals > 0):
        bands = [(22, 75, "low"), (75, 200, "mid"), (200, 500, "high")]
        for lo, hi, label in bands:
            mask = (f_samp >= lo) & (f_samp <= hi) & (C_vals > 1e-30)
            if np.sum(mask) > 2:
                lf = np.log(f_samp[mask]); lC = np.log(C_vals[mask])
                s, _, r, p, se = stats.linregress(lf, lC)
                print(f"  [{lo}-{hi}] Hz: slope = {s:.4f} ± {se:.4f}, r={r:.4f}")
                mf.record(f"T7.slope_{label}", float(s),
                          ci=(float(s-se), float(s+se)), section="V",
                          note=f"d ln C / d ln f, [{lo}, {hi}] Hz")
        
        mask = (C_vals > 1e-30) & (f_samp >= 22) & (f_samp <= 500)
        lf = np.log(f_samp[mask]); lC = np.log(C_vals[mask])
        s_total, _, r_total, p_total, se_total = stats.linregress(lf, lC)
        print(f"  Overall [22-500]: slope = {s_total:.4f} ± {se_total:.4f}, r={r_total:.4f}")
        mf.record("T7.slope_total", float(s_total),
                  ci=(float(s_total-se_total), float(s_total+se_total)),
                  section="V", note="Overall d ln C / d ln f, [22, 500] Hz")
    
    # ── T8: PSD battery ────────────────────────────────────────────────
    print("\n[T8: PSD battery]")
    psd_set = {"zdhp": wf.psd_zdhp, "early_aligo": wf.psd_early_ligo}
    for psd_name, psd_fn in psd_set.items():
        G_psd, idx_a_psd, idx_m_psd = fs.fisher_cumulative(
            THETA_MID, wf.make_f_grid(), psd_fn)
        ev_psd, evc_psd = fs.eigensweep(G_psd, idx_a_psd)
        C_psd = fs.C_of_f(G_psd, idx_a_psd, ev_psd, evc_psd)
        fv_psd = np.array(wf.make_f_grid())
        C_manu_psd = np.interp(MANUSCRIPT_CUTOFFS, fv_psd[idx_a_psd], C_psd)
        growth_psd = C_manu_psd[-1] / max(C_manu_psd[0], 1e-300)
        mf.record(f"T8.growth_{psd_name}", float(growth_psd), section="IV",
                  table="psd_battery", note=f"C(500)/C(22) under {psd_name}")
        mf.record(f"T8.C500_{psd_name}", float(C_manu_psd[-1]), section="IV",
                  table="psd_battery")
        print(f"  {psd_name}: C(22)={C_manu_psd[0]:.3e}, C(500)={C_manu_psd[-1]:.4e}, "
              f"growth={growth_psd:.2f}")
    
    # ── T9: f* and N(f) ────────────────────────────────────────────────
    print("\n[T9: Derived weight trajectory and f*]")
    rho2_vals = np.array([dx @ G_stack[idx] @ dx for idx in idx_all])
    rho2_manu = np.interp(MANUSCRIPT_CUTOFFS, f_samp, rho2_vals)
    
    from scipy.interpolate import interp1d
    rho2_interp_f = interp1d(rho2_vals, f_samp, bounds_error=False, fill_value=np.nan)
    
    for thresh in [1, 2, 4]:
        f_star = float(rho2_interp_f(thresh))
        if np.isfinite(f_star) and f_star >= F_MIN and f_star <= F_MAX:
            print(f"  f* (ρ²={thresh}) = {f_star:.1f} Hz")
            mf.record(f"T9.fstar_{thresh}", f_star, section="V", table="fstar", unit="Hz")
        else:
            print(f"  f* (ρ²={thresh}) = not bracketed [{F_MIN}-{F_MAX}] Hz")
    
    mf.record("T9.rho2_full_band", float(rho2_vals[-1]), section="V",
              note="ρ² at 500 Hz, 4× convention")
    mf.record("T9.N500", None, section="V",
              note="PLACEHOLDER — populate from GWOSC posterior samples or T1 synthetic batch posteriors")
    
    # ── Write manifest ─────────────────────────────────────────────────
    mf.write(results_dir)
    print("T5/T7/T8/T9 pipeline complete.")


if __name__ == "__main__":
    run()