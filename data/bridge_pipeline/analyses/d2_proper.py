#!/usr/bin/env python3
"""
D2-proper — Actual ridge displacement test.

Skye's audit identified that what was called "D2" in the original pipeline 
checked a trivial identity: a random 1σ displacement satisfies ΔxᵀΓΔx = 1
by definition. The actual test — comparing ΔxᵀΓΔx against ⟨δh, δh⟩ from
two waveform evaluations — was never executed.

This script performs the proper test:
1. Pick the degeneracy direction v₅ from U0 stack
2. Displace along v₅ at 3 magnitudes: |δh| ~ 10⁻³, 10⁻², 10⁻¹
3. Compare ΔxᵀΓΔx (Fisher prediction) vs ⟨δh, δh⟩ (exact mismatch)
4. Report ratio and deviation per magnitude

At small displacements, linear approximation should hold (ratio ≈ 1).
At intermediate displacements, ratio begins to deviate.
At large displacements, linear approximation breaks down entirely.
"""

import sys, os, json, numpy as np

# Point to rho_pi_bridge source
_script_dir = os.path.dirname(os.path.abspath(__file__))
_rhopi_dir = os.path.join(_script_dir, '..', '..', 'rho_pi_bridge')
sys.path.insert(0, os.path.join(_rhopi_dir, 'src'))

import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp
from scipy import linalg as spla

import importlib.util
spec = importlib.util.spec_from_file_location(
    "rhopi_waveform", 
    os.path.join(_rhopi_dir, 'src', 'waveform.py')
)
wf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wf)

# Load U0 stack
U0_PATH = os.path.join(_script_dir, '..', 'results', 'u0_output', 'u0_rhopi_stack.npz')
U0 = np.load(U0_PATH)
F_DENSE = U0['f']
G_STACK = U0['G']          # (200, 5, 5) cumulative Fisher
EVECS = U0['evecs']         # (200, 5, 5)
EVALS = U0['evals']         # (200, 5)

THETA_PHYS = np.array([1.186, 0.85, 0.02, 400.0, 40.0])
# Analysis coords: x = (ln Mc, q, χ_eff, Λ̃/100, ln DL)
x_true = np.array([np.log(1.186), 0.85, 0.02, 400.0/100.0, np.log(40.0)])


def phys_to_analysis(theta_phys):
    """Convert physical params to analysis coordinates."""
    Mc, q, chi, Lt, DL = theta_phys
    return np.array([np.log(Mc), q, chi, Lt/100.0, np.log(DL)])


def analysis_to_phys(x):
    """Inverse."""
    return np.array([np.exp(x[0]), x[1], x[2], x[3]*100.0, np.exp(x[4])])


def mismatch_exact(theta1_phys, theta2_phys, f_grid=None):
    """⟨δh|δh⟩ where δh = h(θ1) - h(θ2), using 4× convention."""
    if f_grid is None:
        f_grid = F_DENSE
    
    f_jax = jnp.array(f_grid)
    Sn = np.array(wf.psd_zdhp(f_grid), dtype=np.float64)
    
    t1 = jnp.array(theta1_phys)
    t2 = jnp.array(theta2_phys)
    
    h1 = np.array(wf.htilde(f_jax, t1[0], t1[1], t1[2], t1[3], t1[4]))
    h2 = np.array(wf.htilde(f_jax, t2[0], t2[1], t2[2], t2[3], t2[4]))
    dh = h1 - h2
    
    # Trapezoid integration
    df = np.diff(f_grid)
    w = np.concatenate([[df[0]/2.0], (df[:-1]+df[1:])/2.0, [df[-1]/2.0]])
    integrand = 4.0 * np.real(np.conj(dh) * dh) / Sn
    return np.sum(integrand * w)


def run_d2(save=True):
    print("=" * 70)
    print("D2-proper — Ridge Displacement Test")
    print("=" * 70)
    print(f"  Analysis coords: x = (ln Mc, q, χ_eff, Λ̃/100, ln DL)")
    print(f"  True params: Mc={THETA_PHYS[0]:.3f}, q={THETA_PHYS[1]:.3f}, "
          f"χ_eff={THETA_PHYS[2]:.3f}, Λ̃={THETA_PHYS[3]:.0f}, DL={THETA_PHYS[4]:.0f}")
    
    # ── Degeneracy direction at full band ──
    v5 = EVECS[-1, :, -1]   # v₅: smallest eigenvalue (degeneracy)
    v4 = EVECS[-1, :, -2]   # v₄: second-smallest
    v1 = EVECS[-1, :, 0]    # v₁: best-constrained (ln Mc)
    
    G_full = G_STACK[-1]    # Full-band Fisher
    
    print(f"\n  Degeneracy direction v₅ (full band):")
    print(f"    ln Mc: {v5[0]:+.4e}")
    print(f"    q:     {v5[1]:+.4e}")
    print(f"    χ_eff: {v5[2]:+.4e}")
    print(f"    Λ̃/100:{v5[3]:+.4e}")
    print(f"    ln DL: {v5[4]:+.4e}")
    print(f"    |v₅| = {np.linalg.norm(v5):.6f}")
    
    # ── Compute displacement magnitudes ──
    # We want |δh| ≈ 10⁻³, 10⁻², 10⁻¹
    # |δh|² = Δxᵀ Γ Δx, so |δh| ≈ √(Δxᵀ Γ Δx)
    # For displacement along v₅: Δx = α · v₅
    # Then |δh|² = α² · v₅ᵀ Γ v₅ = α² · λ₅ since v₅ is eigenvector of Γ
    lambda_5 = EVALS[-1, -1]
    
    target_mags = np.array([1e-3, 1e-2, 1e-1])
    alphas = target_mags / np.sqrt(lambda_5)
    
    print(f"\n  Eigenvalue λ₅ = {lambda_5:.6e}")
    print(f"  Displacement scaling: α = target_magnitude / √λ₅")
    
    results = []
    
    print(f"\n{'='*90}")
    print(f"{'Target |δh|':>14} {'α':>14} {'ΔxᵀΓΔx':>18} {'⟨δh|δh⟩':>18} {'Ratio':>14} {'Deviation':>12}")
    print(f"{'-'*14} {'-'*14} {'-'*18} {'-'*18} {'-'*14} {'-'*12}")
    
    for mag, alpha in zip(target_mags, alphas):
        # Displacement in analysis coords
        dx = alpha * v5
        
        # Fisher prediction
        rho2_fisher = dx @ G_full @ dx
        
        # Physical displacement
        x1 = x_true.copy()       # true point
        x2 = x_true - dx         # displaced point (opposite direction)
        
        theta1 = analysis_to_phys(x1)
        theta2 = analysis_to_phys(x2)
        
        # Exact mismatch
        mismatch = mismatch_exact(theta1, theta2)
        
        ratio = rho2_fisher / mismatch if mismatch > 0 else 0
        deviation = abs(ratio - 1.0)
        
        print(f"{mag:>14.1e} {alpha:>14.4e} {rho2_fisher:>18.10e} {mismatch:>18.10e} {ratio:>14.6f} {deviation:>12.6e}")
        
        results.append({
            "target_magnitude": float(mag),
            "alpha": float(alpha),
            "rho2_fisher": float(rho2_fisher),
            "mismatch_exact": float(mismatch),
            "ratio": float(ratio),
            "deviation": float(deviation),
            "dx_analysis": dx.tolist(),
        })
    
    # ── Also test along v₁ (constrained direction) for contrast ──
    lambda_1 = EVALS[-1, 0]
    alpha_v1 = 1e-3 / np.sqrt(lambda_1)
    dx_v1 = alpha_v1 * v1
    rho2_v1 = dx_v1 @ G_full @ dx_v1
    x1_v1 = x_true.copy()
    x2_v1 = x_true - dx_v1
    mismatch_v1 = mismatch_exact(analysis_to_phys(x1_v1), analysis_to_phys(x2_v1))
    ratio_v1 = rho2_v1 / mismatch_v1 if mismatch_v1 > 0 else 0
    
    print(f"\n  Contrast: displacement along v₁ (ln Mc) at |δh| = 10⁻³:")
    print(f"    α_v₁ = {alpha_v1:.4e}")
    print(f"    ΔxᵀΓΔx  = {rho2_v1:.10e}")
    print(f"    ⟨δh|δh⟩ = {mismatch_v1:.10e}")
    print(f"    Ratio   = {ratio_v1:.6f}")
    
    results.append({
        "target_magnitude": 1e-3,
        "direction": "v1 (ln Mc)",
        "alpha": float(alpha_v1),
        "rho2_fisher": float(rho2_v1),
        "mismatch_exact": float(mismatch_v1),
        "ratio": float(ratio_v1),
        "deviation": float(abs(ratio_v1 - 1.0)),
    })
    
    # ── Summary ──
    print(f"\n{'='*70}")
    print(f"D2-proper Summary")
    print(f"{'='*70}")
    
    # Criterion: at what magnitude does deviation exceed 10%?
    for r in results[:3]:
        if r["deviation"] > 0.1:
            print(f"  ⚠ Linear approx breaks at |δh| ≈ {r['target_magnitude']:.0e}: "
                  f"deviation = {r['deviation']:.2%}")
        else:
            print(f"  ✓ Linear approx holds at |δh| ≈ {r['target_magnitude']:.0e}: "
                  f"deviation = {r['deviation']:.2%}")
    
    # Compute critical displacement where deviation hits 10%
    devs = np.array([r["deviation"] for r in results[:3]])
    mags = np.array([r["target_magnitude"] for r in results[:3]])
    
    # Simple interpolation
    from scipy.interpolate import interp1d
    from scipy.optimize import brentq
    
    # Find where deviation crosses 0.1
    above = np.where(devs > 0.1)[0]
    below = np.where(devs <= 0.1)[0]
    
    if len(above) > 0 and len(below) > 0:
        # Find crossing
        log_mags = np.log(mags)
        log_devs = np.log(devs)
        f_interp = interp1d(log_mags, devs, kind='linear')
        
        # Scan for crossing
        mag_range = np.linspace(mags[0], mags[-1], 1000)
        dev_range = f_interp(np.log(mag_range))
        crossing_idx = np.where(dev_range >= 0.1)[0]
        
        if len(crossing_idx) > 0:
            crit_mag = mag_range[crossing_idx[0]]
            print(f"\n  Critical |δh| for 10% deviation: ≈ {crit_mag:.2e}")
    
    # ── Save ──
    if save:
        out_dir = os.path.join(_script_dir, '..', 'results', 'u0_output')
        os.makedirs(out_dir, exist_ok=True)
        
        out = {
            "theta_true_phys": THETA_PHYS.tolist(),
            "x_true_analysis": x_true.tolist(),
            "v5": v5.tolist(),
            "v1": v1.tolist(),
            "eigenvalue_5": float(lambda_5),
            "eigenvalue_1": float(lambda_1),
            "results": results,
            "critical_magnitude_10pct": float(crit_mag) if len(above) > 0 and len(below) > 0 and len(crossing_idx) > 0 else None,
        }
        
        with open(os.path.join(out_dir, 'd2_proper_results.json'), 'w') as f:
            json.dump(out, f, indent=2)
        print(f"\n  Saved: {os.path.join(out_dir, 'd2_proper_results.json')}")
    
    return results


if __name__ == "__main__":
    run_d2(save=True)