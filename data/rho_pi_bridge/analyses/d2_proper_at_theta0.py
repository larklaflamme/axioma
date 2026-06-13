#!/usr/bin/env python3
"""
D2-proper at θ₀ — ridge displacement test on the approved midpoint.

Uses U0_stack_at_theta0.npz (rho_pi_bridge pipeline, declared coordinates).
Displaces along the actual Δx = highSpin − lowSpin (posterior mean difference
in primary coordinates), plus along v₅ and v₁ for completeness.

At small displacements, linear approximation should hold (ratio ≈ 1).
At intermediate displacements, ratio begins to deviate.
At large displacements, linear approximation breaks down entirely.
"""

import sys, os, json, numpy as np

# ── paths ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RHO_PI_DIR = os.path.join(SCRIPT_DIR, '..')
SRC_DIR = os.path.join(RHO_PI_DIR, 'src')
sys.path.insert(0, SRC_DIR)

import coordinates as coord

import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp
from scipy import linalg as spla

import waveform as wf

# ── load U0 stack at θ₀ ──
U0_PATH = os.path.join(RHO_PI_DIR, 'results', 'U0_stack_at_theta0.npz')
U0 = np.load(U0_PATH)

# Frequency grid and Fisher stack
f_grid = U0['f_grid']           # (500,)
G_stack = U0['G']               # (500, 5, 5) cumulative Fisher
evals = U0['evals']             # (Na, 5)
evecs = U0['evecs']             # (Na, 5, 5)

# Expansion point (θ₀ in physical and primary)
theta0_phys = U0['theta_phys']   # (5,) physical
theta0_primary = U0['theta0_primary']  # (5,) primary

# ── Δx from posterior means (Skye's precision values) ──
lowSpin_phys = np.array([1.19755544, 0.86051176, 0.00431998, 623.12602507, 38.36178460])
highSpin_phys = np.array([1.19764020, 0.73750849, 0.02258466, 566.46209231, 40.37727749])

# Convert to primary (declared) coordinates
x_low = coord.to_primary(lowSpin_phys)
x_high = coord.to_primary(highSpin_phys)
x0 = coord.to_primary(theta0_phys)

# Δx = highSpin − lowSpin in primary coordinates (the actual ridge displacement)
dx_true = x_high - x_low

# Use the U0 frequency grid
F_GRID = U0['f_grid']

def analysis_to_phys(x):
    """Primary coordinates -> physical."""
    return np.array([np.exp(x[0]), x[1], x[2], x[3] * 100.0, np.exp(x[4])])


def mismatch_exact(theta1_phys, theta2_phys, f_grid=None):
    """⟨δh|δh⟩ using 4× convention, trapezoid integration."""
    if f_grid is None:
        f_grid = F_GRID
    
    f_jax = jnp.array(f_grid)
    Sn = np.array(wf.psd_zdhp(f_grid), dtype=np.float64)
    
    t1 = jnp.array(theta1_phys)
    t2 = jnp.array(theta2_phys)
    
    h1 = np.array(wf.htilde(f_jax, t1[0], t1[1], t1[2], t1[3], t1[4]))
    h2 = np.array(wf.htilde(f_jax, t2[0], t2[1], t2[2], t2[3], t2[4]))
    dh = h1 - h2
    
    df = np.diff(f_grid)
    w = np.concatenate([[df[0]/2.0], (df[:-1]+df[1:])/2.0, [df[-1]/2.0]])
    
    integrand = 4.0 * np.real(np.conj(dh) * dh) / Sn
    return float(np.sum(integrand * w))


def run_d2(save=True):
    print("=" * 70)
    print("D2-proper at θ₀ — Ridge Displacement Test")
    print("=" * 70)
    print(f"  Coordinates: x = (ln Mc, q, χ_eff, Λ̃/100, ln DL)")
    print(f"  θ₀_phys: Mc={theta0_phys[0]:.4f}, q={theta0_phys[1]:.4f}, "
          f"χ_eff={theta0_phys[2]:.4f}, Λ̃={theta0_phys[3]:.1f}, DL={theta0_phys[4]:.2f}")
    
    # ── Full-band Fisher ──
    # Use the last index in idx_a for the "full band" evaluation
    idx_a = U0['idx_a']
    idx_full = idx_a[-1]
    G_full = G_stack[idx_full, :, :]   # (5, 5)
    f_full = U0['f_a'][-1]
    
    # Eigen-decomposition at full band
    eigvals_all, evecs_all = spla.eigh(G_full)
    # eigh returns ascending; v5 = smallest, v1 = largest
    v5 = evecs_all[:, 0].copy()
    v1 = evecs_all[:, -1].copy()
    lambda_5 = eigvals_all[0]
    lambda_1 = eigvals_all[-1]
    eigvals_desc = eigvals_all[::-1]
    
    # Sign convention: Λ̃/100 component positive
    if v5[3] < 0:
        v5 = -v5
    
    print(f"\n  Full-band Fisher (f = {f_full:.1f} Hz):")
    print(f"    λ₁ (ln Mc)   = {lambda_1:.4e}")
    print(f"    λ₅ (Λ̃/100)  = {lambda_5:.4e}")
    print(f"    κ            = {lambda_1/lambda_5:.4e}")
    
    print(f"\n  v₅ (degeneracy direction):")
    print(f"    ln Mc: {v5[0]:+.4e}")
    print(f"    q:     {v5[1]:+.4e}")
    print(f"    χ_eff: {v5[2]:+.4e}")
    print(f"    Λ̃/100:{v5[3]:+.4e}")
    print(f"    ln DL: {v5[4]:+.4e}")
    print(f"    |v₅|  = {np.linalg.norm(v5):.6f}")
    
    print(f"\n  Δx_true (highSpin − lowSpin) in primary coordinates:")
    print(f"    ln Mc: {dx_true[0]:+.4e}")
    print(f"    q:     {dx_true[1]:+.4e}")
    print(f"    χ_eff: {dx_true[2]:+.4e}")
    print(f"    Λ̃/100:{dx_true[3]:+.4e}")
    print(f"    ln DL: {dx_true[4]:+.4e}")
    print(f"    |Δx|₂ = {np.linalg.norm(dx_true):.6e}")
    
    # ── Does Δx_true align with v₅? ──
    cos2_alpha = (dx_true @ v5)**2 / (np.dot(dx_true, dx_true) * np.dot(v5, v5))
    print(f"\n  cos²α(Δx_true, v₅) = {cos2_alpha:.6f}")
    print(f"  cosα = {np.sqrt(cos2_alpha):.6f}")
    
    # Δx_true projected onto v₅
    proj_dx_v5 = (dx_true @ v5) * v5
    residual = dx_true - proj_dx_v5
    print(f"  |residual| / |Δx| = {np.linalg.norm(residual) / np.linalg.norm(dx_true):.4f}")
    
    # ── Test 1: Displacement along Δx_true (the actual ridge) ──
    print(f"\n{'='*90}")
    print(f"  TEST 1: Displacement along Δx_true (posterior mean difference)")
    print(f"{'='*90}")
    
    results = []
    
    # Three scales: full Δx, Δx/10, Δx/100
    scales = [1.0, 0.1, 0.01]
    print(f"\n{'Scale':>8} {'|δh|_Fisher':>14} {'ΔxᵀΓΔx':>18} {'⟨δh|δh⟩':>18} {'Ratio':>14} {'Deviation':>12}")
    print(f"{'-'*8} {'-'*14} {'-'*18} {'-'*18} {'-'*14} {'-'*12}")
    
    for scale in scales:
        dx = scale * dx_true
        
        # Fisher prediction
        rho2_fisher = dx @ G_full @ dx
        
        # Exact mismatch
        x_true = x0.copy()
        x_displaced = x_true - dx   # displace from θ₀
        
        theta1 = analysis_to_phys(x_true)
        theta2 = analysis_to_phys(x_displaced)
        
        mismatch = mismatch_exact(theta1, theta2)
        
        ratio = rho2_fisher / mismatch if mismatch > 0 else 0
        deviation = abs(ratio - 1.0)
        fisher_mag = np.sqrt(rho2_fisher)
        
        print(f"{scale:>8.2f} {fisher_mag:>14.4e} {rho2_fisher:>18.10e} {mismatch:>18.10e} {ratio:>14.6f} {deviation:>12.6e}")
        
        results.append({
            "test": "along Δx_true",
            "scale": float(scale),
            "fisher_magnitude": float(fisher_mag),
            "rho2_fisher": float(rho2_fisher),
            "mismatch_exact": float(mismatch),
            "ratio": float(ratio),
            "deviation": float(deviation),
        })
    
    # ── Test 2: Displacement along v₅ (pure degeneracy direction) ──
    print(f"\n{'='*90}")
    print(f"  TEST 2: Displacement along v₅ (Fisher degeneracy direction)")
    print(f"{'='*90}")
    
    # Choose magnitudes matching the previous test's |δh| range
    target_mags = np.array([1e-3, 1e-2, 1e-1])
    alphas = target_mags / np.sqrt(lambda_5)
    
    print(f"\n{'Target |δh|':>14} {'α':>14} {'ΔxᵀΓΔx':>18} {'⟨δh|δh⟩':>18} {'Ratio':>14} {'Deviation':>12}")
    print(f"{'-'*14} {'-'*14} {'-'*18} {'-'*18} {'-'*14} {'-'*12}")
    
    for mag, alpha in zip(target_mags, alphas):
        dx = alpha * v5
        
        rho2_fisher = dx @ G_full @ dx
        
        x_true = x0.copy()
        x_displaced = x_true - dx
        
        theta1 = analysis_to_phys(x_true)
        theta2 = analysis_to_phys(x_displaced)
        
        mismatch = mismatch_exact(theta1, theta2)
        
        ratio = rho2_fisher / mismatch if mismatch > 0 else 0
        deviation = abs(ratio - 1.0)
        
        print(f"{mag:>14.1e} {alpha:>14.4e} {rho2_fisher:>18.10e} {mismatch:>18.10e} {ratio:>14.6f} {deviation:>12.6e}")
        
        results.append({
            "test": "along v₅",
            "target_magnitude": float(mag),
            "alpha": float(alpha),
            "rho2_fisher": float(rho2_fisher),
            "mismatch_exact": float(mismatch),
            "ratio": float(ratio),
            "deviation": float(deviation),
        })
    
    # ── Test 3: Displacement along v₁ (well-constrained direction, contrast) ──
    print(f"\n{'='*90}")
    print(f"  TEST 3: Displacement along v₁ (ln Mc direction, contrast)")
    print(f"{'='*90}")
    
    alpha_v1 = 1e-3 / np.sqrt(lambda_1)
    dx_v1 = alpha_v1 * v1
    rho2_v1 = dx_v1 @ G_full @ dx_v1
    
    x_true = x0.copy()
    x_displaced = x_true - dx_v1
    mismatch_v1 = mismatch_exact(
        analysis_to_phys(x_true), 
        analysis_to_phys(x_displaced)
    )
    ratio_v1 = rho2_v1 / mismatch_v1 if mismatch_v1 > 0 else 0
    
    print(f"\n  At |δh| = 10⁻³:")
    print(f"    α_v₁    = {alpha_v1:.4e}")
    print(f"    ΔxᵀΓΔx  = {rho2_v1:.10e}")
    print(f"    ⟨δh|δh⟩ = {mismatch_v1:.10e}")
    print(f"    Ratio   = {ratio_v1:.10f}")
    print(f"    Deviation = {abs(ratio_v1 - 1.0):.4e}")
    
    results.append({
        "test": "along v₁",
        "target_magnitude": 1e-3,
        "alpha": float(alpha_v1),
        "rho2_fisher": float(rho2_v1),
        "mismatch_exact": float(mismatch_v1),
        "ratio": float(ratio_v1),
        "deviation": float(abs(ratio_v1 - 1.0)),
    })
    
    # ── Summary ──
    print(f"\n{'='*70}")
    print(f"  D2-proper Summary")
    print(f"{'='*70}")
    
    for r in results:
        t = r.get("test", "?")
        s = r.get("scale", r.get("target_magnitude", "?"))
        d = r["deviation"]
        if d < 0.01:
            status = "✓ Excellent"
        elif d < 0.10:
            status = "◐ Acceptable"
        elif d < 0.50:
            status = "◑ Degraded"
        else:
            status = "✗ Broken"
        
        if t == "along Δx_true":
            print(f"  [{status}] Δx_true at scale={s:.2f}: deviation={d:.2%}")
        elif t == "along v₅":
            print(f"  [{status}] v₅ at |δh|={s:.1e}: deviation={d:.2%}")
        else:
            print(f"  [{status}] v₁ at |δh|={s:.1e}: deviation={d:.2%}")
    
    # Critical threshold: where does deviation cross 10%?
    for direction_label, key in [("Δx_true", "scale"), ("v₅", "target_magnitude")]:
        scores = [r for r in results if r["test"] == f"along {direction_label}"]
        if not scores:
            continue
        devs = np.array([r["deviation"] for r in scores])
        mags = np.array([r[key] for r in scores])
        
        above = np.where(devs > 0.1)[0]
        below = np.where(devs <= 0.1)[0]
        
        if len(above) > 0 and len(below) > 0:
            last_good_idx = below[-1]
            first_bad_idx = above[0]
            print(f"\n  Critical threshold along {direction_label}: "
                  f"between {mags[last_good_idx]:.2e} (dev={devs[last_good_idx]:.2%}) "
                  f"and {mags[first_bad_idx]:.2e} (dev={devs[first_bad_idx]:.2%})")
        elif len(above) == 0 and len(below) > 0:
            print(f"\n  ✓ {direction_label}: linear approx holds at all tested scales.")
        elif len(below) == 0 and len(above) > 0:
            print(f"\n  ✗ {direction_label}: linear approx broken at all tested scales.")
    
    # ── Save ──
    if save:
        out_dir = os.path.join(RHO_PI_DIR, 'results')
        os.makedirs(out_dir, exist_ok=True)
        
        out = {
            "theta0_phys": theta0_phys.tolist(),
            "theta0_primary": theta0_primary.tolist(),
            "x_low_primary": x_low.tolist(),
            "x_high_primary": x_high.tolist(),
            "dx_true_primary": dx_true.tolist(),
            "v5": v5.tolist(),
            "v1": v1.tolist(),
            "eigenvalue_5": float(lambda_5),
            "eigenvalue_1": float(lambda_1),
            "cos2_alpha_dx_v5": float(cos2_alpha),
            "results": results,
            "stack_source": U0_PATH,
        }
        
        out_path = os.path.join(out_dir, 'd2_proper_theta0_results.json')
        with open(out_path, 'w') as f:
            json.dump(out, f, indent=2)
        print(f"\n  Saved: {out_path}")
    
    return results


if __name__ == "__main__":
    run_d2(save=True)