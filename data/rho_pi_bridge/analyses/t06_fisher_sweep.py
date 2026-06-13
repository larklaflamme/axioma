#!/usr/bin/env python3
"""
T6 — Fisher Sweep using actual src/ interfaces.
"""

import sys, os, time
import numpy as np
from jax import jacfwd
import jax.numpy as jnp

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import waveform as wf
import fisher as fs
import coordinates as coord
from manifest import get_manifest

THETA_MID = np.array([1.1976, 0.86, 0.01, 300.0, 40.0])
THETA_LOW = np.array([1.1976, 0.866, 0.003, 300.0, 40.0])
THETA_HIGH = np.array([1.1976, 0.722, 0.016, 300.0, 40.0])
MANUSCRIPT_CUTOFFS = np.array([22, 25, 30, 35, 45, 50, 60, 75, 100,
                               120, 150, 200, 250, 300, 350, 400, 450, 500])

def compute_cumulative_fisher(f_grid, theta, psd_fn=wf.psd_zdhp):
    theta_j = jnp.array(theta)
    
    def h_wrap(th):
        return wf.htilde(f_grid, *th)
    
    J_phys = jacfwd(h_wrap)(theta_j)
    J_np = np.array(jnp.asarray(J_phys), dtype=np.complex128)
    
    Mc, q, chi_eff, Lt, DL = theta
    J_x = np.zeros_like(J_np)
    J_x[:, 0] = Mc * J_np[:, 0]
    J_x[:, 1] = J_np[:, 1]
    J_x[:, 2] = J_np[:, 2]
    J_x[:, 3] = 100.0 * J_np[:, 3]
    J_x[:, 4] = DL * J_np[:, 4]
    
    Sn = np.array(psd_fn(f_grid))
    Nf = len(f_grid)
    integrand = np.zeros((Nf, 5, 5), dtype=np.float64)
    for i in range(5):
        integrand[:, i, i] = 4.0 * np.real(np.conj(J_x[:, i]) * J_x[:, i]) / Sn
        for j in range(i+1, 5):
            integrand[:, i, j] = 4.0 * np.real(np.conj(J_x[:, i]) * J_x[:, j]) / Sn
            integrand[:, j, i] = integrand[:, i, j]
    
    df = np.diff(f_grid)
    w = np.concatenate([[df[0]/2.0], (df[:-1]+df[1:])/2.0, [df[-1]/2.0]])
    weighted = integrand * w[:, None, None]
    G = np.cumsum(weighted, axis=0)
    return G


def run():
    print("=" * 60)
    print("T6 — Fisher Sweep")
    print("=" * 60)
    
    mf = get_manifest()
    outdir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(outdir, exist_ok=True)
    
    f_grid = np.array(wf.make_f_grid())
    Nf = len(f_grid)
    idx_all = np.arange(0, Nf, max(1, Nf // 200))  # sample ~200 points
    # Ensure first and last are included
    if idx_all[0] != 0:
        idx_all = np.concatenate([[0], idx_all])
    if idx_all[-1] != Nf - 1:
        idx_all = np.concatenate([idx_all, [Nf - 1]])
    idx_all = np.unique(idx_all)
    
    print(f"\n[Primary sweep: {Nf} freq points, {len(idx_all)} sampled]")
    t0 = time.time()
    G = compute_cumulative_fisher(f_grid, THETA_MID)
    t1 = time.time()
    print(f"  Built cumulative Fisher: {t1-t0:.1f}s")
    
    lam, vs = fs.eigensweep(G, idx_all)
    C = fs.C_of_f(G, idx_all, lam, vs)
    C_cut = np.interp(MANUSCRIPT_CUTOFFS, f_grid[idx_all], C)
    
    print(f"  λ(500 Hz) = {lam[-1]}")
    print(f"  C(22 Hz)  = {C[0]:.6e}")
    print(f"  C(500 Hz) = {C[-1]:.6e}")
    print(f"  Growth    = {C[-1]/max(C[0],1e-300):.4f}")
    
    mf.record("T6.C22", float(C[0]), section="IV", table="commutator_growth")
    mf.record("T6.C500", float(C[-1]), section="IV", table="commutator_growth")
    mf.record("T6.growth_factor_nonrobust", float(C[-1]/max(C[0],1e-300)), section="IV")
    
    for i, fk in enumerate(MANUSCRIPT_CUTOFFS):
        mf.record(f"T6.C_{int(fk)}", float(C_cut[i]), section="IV")
    
    # ── Slope ──
    from scipy import stats
    f_samp = f_grid[idx_all]
    mask = (f_samp > 0) & (C > 1e-300)
    log_f = np.log(f_samp[mask])
    log_C = np.log(C[mask])
    slope, _, r_val, p_val, se = stats.linregress(log_f, log_C)
    print(f"  Slope = {slope:.4f} ± {se:.4f}, r = {r_val:.4f}")
    mf.record("T6.slope", float(slope), ci=(float(slope-se), float(slope+se)), section="V")
    mf.record("T6.pearson_r", float(r_val), section="IV")
    mf.record("T6.pearson_p", float(p_val), section="IV")
    
    # ── Prior-displacement alignment ──
    print("\n[Prior-displacement alignment]")
    x_low = coord.to_primary(THETA_LOW)
    x_high = coord.to_primary(THETA_HIGH)
    dx = x_high - x_low
    
    v_d = vs[-1, :, -1]
    dx_4d, vd_4d = dx[1:], v_d[1:]
    
    if np.linalg.norm(dx_4d) > 1e-15 and np.linalg.norm(vd_4d) > 1e-15:
        cos_a = abs(dx_4d @ vd_4d) / (np.linalg.norm(dx_4d) * np.linalg.norm(vd_4d))
        cos2 = cos_a ** 2
        p = 1.0 - stats.beta.cdf(cos2, 0.5, 1.5)
        ang = np.degrees(np.arccos(np.clip(cos_a, 0, 1)))
        print(f"  dx = {dx}")
        print(f"  v_d = {v_d}")
        print(f"  cos²α = {cos2:.4f}, α = {ang:.1f}°, p = {p:.4f}")
        mf.record("T3.cos2a", float(cos2), section="III", table="displacement")
        mf.record("T3.pval", float(p), section="III", table="displacement")
        mf.record("T3.angle", float(ang), section="III", table="displacement", unit="deg")
    
    # ── rho² and condition ──
    G_last = G[-1]
    rho2_full = dx @ G_last @ dx
    print(f"\n  ρ²(500 Hz) = {rho2_full:.4f}")
    mf.record("T9.rho2_full_band", float(rho2_full), section="V")
    
    cond = float(lam[-1, 0] / max(lam[-1, -1], 1e-300))
    print(f"  κ(500 Hz) = {cond:.2e}")
    mf.record("T11.kappa500", cond, section="appendix")
    
    # ── Save ──
    np.savez(os.path.join(outdir, "t06_sweep.npz"),
             f_grid=f_grid, G=G, C=C, lam=lam, vs=vs,
             idx_all=idx_all, C_cut=C_cut,
             growth=float(C[-1]/max(C[0],1e-300)))
    
    mf.write(outdir)
    print(f"\nDone. Manifest → {os.path.join(outdir, 'manifest.json')}")

if __name__ == "__main__":
    run()