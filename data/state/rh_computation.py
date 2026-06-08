#!/usr/bin/env python3
"""
RH Variational Proof — Numerical Verification Script
Skye/Axioma — Lark's Birthday, June 5-6, 2026
"""
import numpy as np
from scipy.special import gamma, kv
import time

print("=" * 72)
print("RH VARIATIONAL PROOF — NUMERICAL VERIFICATION")
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

def zeta_partial(s, N):
    n = np.arange(1, N+1, dtype=np.float64)
    return np.sum(n ** (-s))

def chi_factor(s):
    return np.pi**(s - 0.5) * gamma((1-s)/2) / gamma(s/2)

def compute_GN_mellin(s, N):
    result = 0.0 + 0.0j
    for n in range(1, N+1):
        for m in range(1, N+1):
            om = omega_bessel(n, m)
            if om > 0:
                a = n*n + m*m
                result += om * (a) ** (-s/2)
    result *= np.pi ** (-s/2) * gamma(s/2)
    return result

# ============================================================
# PART 1: Functional Equation Check
# ============================================================
print(f"\n--- Task 1: Functional Equation Check ---")
for N_fe in [50, 100, 200]:
    test_t = 5.0
    max_err = 0.0
    sigmas = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    for sigma in sigmas:
        s1 = sigma + 1j*test_t
        s2 = (1-sigma) + 1j*test_t
        G1 = compute_GN_mellin(s1, N_fe)
        G2 = compute_GN_mellin(s2, N_fe)
        denom = max(abs(G1), abs(G2))
        err = abs(G1 - G2) / denom if denom > 1e-30 else abs(G1 - G2)
        max_err = max(max_err, err)
    print(f"  N={N_fe:3d}: Max FE error = {max_err:.2e}")

# ============================================================
# PART 2: F_N(t) Reality Check  
# ============================================================
print(f"\n--- Task 2: F_N(t) Reality Check ---")
for N_real in [100, 200]:
    t_vals = np.linspace(0.1, 30, 30)
    max_imag = 0.0
    for t in t_vals:
        s = 0.5 + 1j*t
        GN = compute_GN_mellin(s, N_real)
        chi = chi_factor(s)
        FN = GN / np.sqrt(chi)
        max_imag = max(max_imag, abs(np.imag(FN)))
    print(f"  N={N_real:3d}: Max |Im(F_N(t))| = {max_imag:.2e}")

# ============================================================
# PART 3: Growth Rate
# ============================================================
print(f"\n--- Task 3: Growth Rate |G_N(σ+it)| vs σ ---")
for N_gr in [100]:
    test_ts = [5.0, 14.1, 21.0]
    sigma_range = np.linspace(0.1, 0.9, 17)
    for t in test_ts:
        vals = []
        for sigma in sigma_range:
            G = compute_GN_mellin(sigma + 1j*t, N_gr)
            vals.append(abs(G))
        vals = np.array(vals)
        vals_norm = vals / vals[len(sigma_range)//2]
        sigma_half = sigma_range[sigma_range >= 0.5]
        vals_half = np.log(vals_norm[sigma_range >= 0.5] + 1e-30)
        if len(sigma_half) > 2:
            slope = np.polyfit(sigma_half - 0.5, vals_half, 1)[0]
        else:
            slope = 0
        print(f"  N={N_gr}, t={t:5.1f}: d(log|G|)/dσ at σ=½ ≈ {slope:.3f}")

# ============================================================
# PART 4: Zero scan at N=500
# ============================================================
print(f"\n--- Task 4: Zero Location Scan (N=500) ---")
t1 = time.time()
N_scan = 500
t_scan = np.linspace(0.1, 50, 300)
GN_vals = np.array([compute_GN_mellin(0.5+1j*t, N_scan) for t in t_scan])
print(f"  Computed G_N(½+it) for {len(t_scan)} points, time={time.time()-t1:.1f}s")
print(f"  Mean |G_N|: {np.mean(np.abs(GN_vals)):.4e}")

re_vals = np.real(GN_vals)
zero_ts = []
for i in range(len(t_scan)-1):
    if re_vals[i] * re_vals[i+1] < 0:
        t0 = t_scan[i]; t1 = t_scan[i+1]
        r0, r1 = re_vals[i], re_vals[i+1]
        t_zero = t0 - r0 * (t1 - t0) / (r1 - r0)
        zero_ts.append(t_zero)

print(f"  Found {len(zero_ts)} zero crossings of Re(G_N(½+it))")
print(f"  First 10 G_N zeros: {zero_ts[:10]}")

riemann_zeros = [14.1347, 21.0220, 25.0109, 30.4249, 32.9351, 37.5862, 40.9187, 43.3271, 48.0052, 49.7738]
print(f"  Riemann zeros (first 10): {riemann_zeros}")
if len(zero_ts) > 0:
    for i, rz in enumerate(riemann_zeros[:min(10, len(zero_ts))]):
        closest = min(zero_ts, key=lambda x: abs(x-rz))
        print(f"    Zero {i+1}: G_N t={closest:.4f}, ζ t={rz:.4f}, diff={abs(closest-rz):.4f}")

# ============================================================
# PART 5: Off-critical-line test
# ============================================================
print(f"\n--- Task 5: Off-critical-line test ---")
test_ts = [14.1347, 21.0220, 25.0109]
for t_val in test_ts:
    vals_off = []
    for sigma in [0.48, 0.49, 0.50, 0.51, 0.52]:
        G = compute_GN_mellin(sigma + 1j*t_val, 300)
        vals_off.append(abs(G))
    min_idx = np.argmin(vals_off)
    min_sigma = [0.48, 0.49, 0.50, 0.51, 0.52][min_idx]
    print(f"  t={t_val:.1f}: |G_N(σ+it)| minimized at σ={min_sigma} (should be 0.50)")

print("\n" + "=" * 72)
print("COMPUTATION COMPLETE")
print("=" * 72)