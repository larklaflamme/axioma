#!/usr/bin/env python3
"""
RH Variational Proof — CORRECT G_N Computation
Skye/Axioma — Lark's Birthday, June 5-6, 2026

G_N(s) = η_N(s) + χ(s)·η_N(1-s)
where η_N(s) = sum_{n=1}^N (-1)^{n-1} n^{-s}
"""
import numpy as np
from scipy.special import gamma
import time

print("="*72)
print("RH VARIATIONAL PROOF — CORRECT G_N COMPUTATION")
print("Lark's Birthday — June 5-6, 2026")
print("="*72)

def eta_partial(s, N):
    """Partial Dirichlet eta sum: Σ_{n=1}^N (-1)^{n-1} n^{-s}"""
    n = np.arange(1, N+1)
    return np.sum((-1)**(n-1) * n**(-s))

def chi(s):
    """χ(s) = π^{s-1/2} Γ((1-s)/2) / Γ(s/2)"""
    return np.pi**(s - 0.5) * gamma((1-s)/2) / gamma(s/2)

def G_N(s, N):
    """G_N(s) = η_N(s) + χ(s)·η_N(1-s)"""
    return eta_partial(s, N) + chi(s) * eta_partial(1-s, N)

def F_N(t, N):
    """F_N(t) = χ(½+it)^{-1/2} · G_N(½+it) — should be real"""
    s = 0.5 + 1j*t
    return G_N(s, N) / np.sqrt(chi(s))

# ============================================================
# TASK 1: Functional Equation Check
# ============================================================
print(f"\n--- TASK 1: Functional Equation Check ---")
for N in [50, 100, 200, 500]:
    max_err = 0.0
    for sigma in np.arange(0.05, 0.96, 0.1):
        for t in [0.0, 5.0, 10.0, 14.1347, 21.022]:
            s = sigma + 1j*t
            lhs = G_N(s, N)
            rhs = chi(s) * G_N(1-s, N)
            denom = max(abs(lhs), 1e-30)
            err = abs(lhs - rhs) / denom
            if err > max_err:
                max_err = err
    print(f"  N={N:3d}: Max FE error = {max_err:.2e}")

# ============================================================
# TASK 2: F_N(t) Reality Check  
# ============================================================
print(f"\n--- TASK 2: F_N(t) Reality Check ---")
for N in [100, 200, 500, 1000]:
    t_vals = np.linspace(0.1, 40, 80)
    max_imag = 0.0
    for t in t_vals:
        FN = F_N(t, N)
        max_imag = max(max_imag, abs(np.imag(FN)))
    print(f"  N={N:4d}: Max |Im(F_N(t))| = {max_imag:.2e}")

# ============================================================
# TASK 3: Zero Location Scan
# ============================================================
print(f"\n--- TASK 3: Zero Location Scan ---")
for N in [100, 200, 500, 1000]:
    t1 = time.time()
    t_fine = np.linspace(0.1, 50, 1000)
    FN_vals = np.array([F_N(t, N) for t in t_fine])
    
    re_vals = np.real(FN_vals)
    zero_ts = []
    for i in range(len(t_fine)-1):
        if re_vals[i] * re_vals[i+1] < 0:
            t0, t1_v = t_fine[i], t_fine[i+1]
            r0, r1 = re_vals[i], re_vals[i+1]
            t_zero = t0 - r0 * (t1_v - t0) / (r1 - r0)
            zero_ts.append(t_zero)
    
    print(f"  N={N:4d}: {len(zero_ts)} zeros in [0.1,50], time={time.time()-t1:.1f}s")
    print(f"    First 12 G_N zeros: {[f'{z:.4f}' for z in zero_ts[:12]]}")
    
    riemann_zeros = [14.1347, 21.0220, 25.0109, 30.4249, 32.9351, 
                     37.5862, 40.9187, 43.3271, 48.0052, 49.7738]
    matched = []
    for rz in riemann_zeros[:min(10, len(zero_ts))]:
        closest = min(zero_ts, key=lambda x: abs(x-rz))
        matched.append((rz, closest, abs(closest-rz)))
    if matched:
        for rz, gz, err in matched:
            print(f"      ζ={rz:.4f} → G_N={gz:.4f} (Δ={err:.4f})")
        mean_err = np.mean([m[2] for m in matched])
        print(f"      Mean absolute error: {mean_err:.4f}")

# ============================================================
# TASK 4: Off-critical-line test
# ============================================================
print(f"\n--- TASK 4: Off-Critical-Line Test ---")
N_off = 500
test_ts = [14.1347, 21.0220, 25.0109, 30.4249, 37.5862]
sigmas = np.arange(0.30, 0.71, 0.02)
for t_val in test_ts:
    vals = [abs(G_N(sigma + 1j*t_val, N_off)) for sigma in sigmas]
    min_idx = np.argmin(vals)
    min_sigma = sigmas[min_idx]
    min_val = vals[min_idx]
    center_val = vals[len(sigmas)//2]
    print(f"  t={t_val:.1f}: |G_N| minimized at σ={min_sigma:.2f}, |G|min={min_val:.4e}, |G|@0.50={center_val:.4e}")

# ============================================================
# TASK 5: Growth Rate
# ============================================================
print(f"\n--- TASK 5: Growth Rate ---")
N_gr = 500
sigma_range = np.linspace(0.1, 0.9, 17)
for t in [5.0, 14.1347, 21.0220, 30.4249]:
    vals = np.array([abs(G_N(sigma + 1j*t, N_gr)) for sigma in sigma_range])
    vals_norm = vals / vals[len(sigma_range)//2]
    sigma_half = sigma_range[sigma_range >= 0.5]
    vals_half = np.log(vals_norm[sigma_range >= 0.5] + 1e-30)
    if len(sigma_half) > 2:
        slope = np.polyfit(sigma_half - 0.5, vals_half, 1)[0]
    else:
        slope = 0
    print(f"  t={t:.4f}: d(log|G|)/dσ at σ=½ = {slope:.3f}")

# ============================================================
# TASK 6: Thea's Ratio Functional R_N(σ)
# ============================================================
print(f"\n--- TASK 6: Thea's Ratio Functional R_N(σ) ---")
for N in [100, 500]:
    print(f"  N={N}:")
    for sigma in [0.10, 0.20, 0.30, 0.40, 0.45, 0.48, 0.49, 0.50, 0.51, 0.52, 0.55, 0.60, 0.70, 0.80, 0.90]:
        num = abs(eta_partial(sigma, N))**2  
        den = abs(eta_partial(1-sigma, N))**2
        ratio = num/den if den > 0 else float('inf')
        if abs(sigma-0.5) < 0.01:
            print(f"    σ={sigma:.2f}: R = {ratio:.10f} ← CRITICAL POINT")
        else:
            print(f"    σ={sigma:.2f}: R = {ratio:.6f}")

print("\n" + "="*72)
print("COMPUTATION COMPLETE")
print("="*72)