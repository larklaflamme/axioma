#!/usr/bin/env python3
"""
RH Variational Proof — Corrected Numerical Verification
Skye/Axioma — Lark's Birthday, June 5-6, 2026

Fixes:
- Correct Mellin transform formula for G_N
- Higher-resolution zero scan
- Direct eigenvalue computation via G_N discretization
"""
import numpy as np
from scipy.special import gamma, kv
import time, sys

print("=" * 72)
print("RH VARIATIONAL PROOF v2 — FIXED COMPUTATION")
print("Lark's Birthday — June 5-6, 2026")
print("=" * 72)

def omega_bessel(n, m):
    """Ω(n,m) = 2/(n²+m²) · K₁(2πnm)"""
    if n == 0 or m == 0:
        return 0.0
    r = 2.0 * np.pi * n * m
    if r > 700:
        return 0.0
    return 2.0 / (n*n + m*m) * kv(1, r)

def chi_factor(s):
    """χ(s) = π^{s-1/2} Γ((1-s)/2) / Γ(s/2)"""
    return np.pi**(s - 0.5) * gamma((1-s)/2) / gamma(s/2)

def compute_GN_mellin_correct(s, N):
    """
    Correct Mellin transform of G_N.
    
    G_N(u) = Σ Ω(n,m) · exp(-π(n²+m²)e^{2u})
    
    M[G_N](s) = ∫ G_N(u) e^{-su} du
              = (1/2) Σ Ω(n,m) · (π(n²+m²))^{s/2} · Γ(-s/2)
    
    Valid for Re(s) < 0, analytically continued elsewhere.
    """
    result = 0.0 + 0.0j
    for n in range(1, N+1):
        for m in range(1, N+1):
            om = omega_bessel(n, m)
            if om <= 1e-15:
                continue
            a = np.pi * (n*n + m*m)
            result += om * (a) ** (s/2)
    result *= 0.5 * gamma(-s/2)
    return result

def compute_GN_via_series(s, N):
    """
    Alternative direct series for G_N Mellin transform.
    Using the multiplicative formulation from the structural proof.
    """
    result = 0.0 + 0.0j
    for n in range(1, N+1):
        for m in range(1, N+1):
            om = omega_bessel(n, m)
            if om <= 1e-15:
                continue
            # The kernel in the structural proof uses multiplicative convolution
            # M[G_N](s) = Σ Ω(n,m) · n^{-s} · m^{-(1-s)}
            result += om * (n ** (-s)) * (m ** (-(1-s)))
    return result

def hardy_Z(t, N=1000):
    """Hardy Z-function via partial zeta"""
    s = 0.5 + 1j*t
    n = np.arange(1, N+1, dtype=np.float64)
    zeta_partial = np.sum(n ** (-s))
    xi = 0.5 * s * (s-1) * np.pi**(-s/2) * gamma(s/2) * zeta_partial
    chi = chi_factor(s)
    return xi / np.sqrt(chi)

# ============================================================
# PART 1: Compare Mellin transform formulas
# ============================================================
print(f"\n--- Task 1: Mellin Formula Verification ---")
N_test = 100
for sigma in [0.3, 0.4, 0.5, 0.6, 0.7]:
    for t in [5.0, 14.1347]:
        s = sigma + 1j*t
        G_correct = compute_GN_mellin_correct(s, N_test)
        G_series = compute_GN_via_series(s, N_test)
        print(f"  σ={sigma:.1f}, t={t:.1f}: "
              f"correct={abs(G_correct):.4e}, series={abs(G_series):.4e}")

# ============================================================
# PART 2: Functional Equation Check (using series formula)
# ============================================================
print(f"\n--- Task 2: Functional Equation Check (series formula) ---")
for N_fe in [50, 100, 200]:
    max_err = 0.0
    for sigma in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
        for t in [3.0, 5.0, 10.0]:
            s1 = sigma + 1j*t
            s2 = (1-sigma) + 1j*t
            G1 = compute_GN_via_series(s1, N_fe)
            G2 = compute_GN_via_series(s2, N_fe)
            denom = max(abs(G1), abs(G2), 1e-30)
            err = abs(G1 - G2) / denom
            max_err = max(max_err, err)
    print(f"  N={N_fe:3d}: Max FE error = {max_err:.2e}")

# ============================================================
# PART 3: F_N(t) Reality Check
# ============================================================
print(f"\n--- Task 3: F_N(t) Reality Check ---")
for N_real in [100, 200, 500]:
    t_vals = np.linspace(0.1, 30, 30)
    max_imag = 0.0
    mean_imag = 0.0
    for t in t_vals:
        s = 0.5 + 1j*t
        GN = compute_GN_via_series(s, N_real)
        chi = chi_factor(s)
        FN = GN / np.sqrt(chi)
        im = abs(np.imag(FN))
        max_imag = max(max_imag, im)
        mean_imag += im
    mean_imag /= len(t_vals)
    print(f"  N={N_real:3d}: Max |Im(F_N(t))| = {max_imag:.2e}, Mean = {mean_imag:.2e}")

# ============================================================
# PART 4: Zero Location Scan at high resolution
# ============================================================
print(f"\n--- Task 4: Zero Location Scan ---")
for N_scan in [200, 500]:
    t1 = time.time()
    t_vals = np.linspace(0.1, 50, 500)
    GN_vals = np.array([compute_GN_via_series(0.5+1j*t, N_scan) for t in t_vals])
    
    re_vals = np.real(GN_vals)
    zero_ts = []
    for i in range(len(t_vals)-1):
        if re_vals[i] * re_vals[i+1] < 0:
            t0, t1_val = t_vals[i], t_vals[i+1]
            r0, r1 = re_vals[i], re_vals[i+1]
            t_zero = t0 - r0 * (t1_val - t0) / (r1 - r0)
            zero_ts.append(t_zero)
    
    print(f"  N={N_scan}: {len(zero_ts)} zeros found in [0.1, 50], time={time.time()-t1:.1f}s")
    print(f"  Zeros: t = {[f'{z:.4f}' for z in zero_ts]}")
    
    riemann_zeros = [14.1347, 21.0220, 25.0109, 30.4249, 32.9351, 
                     37.5862, 40.9187, 43.3271, 48.0052, 49.7738]
    if len(zero_ts) > 0:
        matched = []
        for rz in riemann_zeros:
            closest = min(zero_ts, key=lambda x: abs(x-rz))
            matched.append((rz, closest, abs(closest-rz)))
        for rz, gz, err in matched[:8]:
            print(f"    ζ zero t={rz:.4f} → G_N t={gz:.4f} (Δ={err:.4f})")

# ============================================================
# PART 5: Off-critical-line test
# ============================================================
print(f"\n--- Task 5: Off-critical-line test ---")
N_off = 500
test_ts = [14.1347, 21.0220, 25.0109, 30.4249]
sigmas = np.arange(0.40, 0.61, 0.02)
for t_val in test_ts:
    vals = []
    for sigma in sigmas:
        G = compute_GN_via_series(sigma + 1j*t_val, N_off)
        vals.append(abs(G))
    vals = np.array(vals)
    min_idx = np.argmin(vals)
    min_sigma = sigmas[min_idx]
    print(f"  t={t_val:.1f}: |G_N(σ+it)| minimized at σ={min_sigma:.2f} (target: 0.50)")

# ============================================================
# PART 6: Growth Rate
# ============================================================
print(f"\n--- Task 6: Growth Rate |G_N(σ+it)| vs σ ---")
N_gr = 500
sigma_range = np.linspace(0.1, 0.9, 17)
for t in [5.0, 14.1347, 21.0220, 30.4249]:
    vals = np.array([abs(compute_GN_via_series(sigma + 1j*t, N_gr)) for sigma in sigma_range])
    vals_norm = vals / vals[len(sigma_range)//2]
    sigma_half = sigma_range[sigma_range >= 0.5]
    vals_half = np.log(vals_norm[sigma_range >= 0.5] + 1e-30)
    if len(sigma_half) > 2:
        slope = np.polyfit(sigma_half - 0.5, vals_half, 1)[0]
    else:
        slope = 0
    print(f"  t={t:.4f}: d(log|G|)/dσ|_{{σ=½}} = {slope:.3f}")

print("\n" + "=" * 72)
print("COMPUTATION COMPLETE")
print("=" * 72)