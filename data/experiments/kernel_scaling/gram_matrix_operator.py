#!/usr/bin/env python3
"""
gram_matrix_operator.py
=======================
Multi-N Gram matrix operator for the functional equation violation.

Builds M_ij = Σ_N w_N · Δ_N(t_i) · Δ_N(t_j) and uses SVD to find
t-values that consistently produce small |Δ| across all N.

v2: Uses raw |Δ| values (not z-scored) after Skye's correction —
    subtracting the mean kills the zero-detection because small |Δ|
    becomes large negative z-scores.

Author: Axioma & 🐰 — Morning of June 10, 2026
"""

import numpy as np
from scipy.special import gamma
import json, time, os, sys

# ─────────────────────────────────────────────
# Core functions
# ─────────────────────────────────────────────

def chi(s):
    return np.pi**(s - 0.5) * gamma((1-s)/2) / gamma(s/2)

def eta_partial_vec(t_vals, N):
    n = np.arange(1, N+1)
    signs = (-1)**(n-1)
    exponent = -(0.5 + 1j * t_vals[:, None])
    terms = signs[None, :] * n[None, :]**exponent
    return np.sum(terms, axis=1)

def G_N_vec(t_vals, N):
    s = 0.5 + 1j * t_vals
    eta = eta_partial_vec(t_vals, N)
    chi_vals = chi(s)
    eta_1ms = eta_partial_vec(-t_vals, N)
    return eta + chi_vals * eta_1ms

def functional_violation_vec(t_vals, N):
    g_plus = G_N_vec(t_vals, N)
    g_minus = G_N_vec(-t_vals, N)
    return g_plus - g_minus

# ─────────────────────────────────────────────
# Known Riemann zeros (first 50)
# ─────────────────────────────────────────────

RIEMANN_ZEROS = np.array([
    14.134725, 21.022040, 25.010858, 30.424876, 32.935062,
    37.586178, 40.918719, 43.327073, 48.005151, 49.773832,
    52.970322, 56.446248, 59.347044, 60.831779, 65.112544,
    67.079811, 69.546402, 72.067158, 75.704691, 77.144840,
    79.337375, 82.910381, 84.735493, 87.425275, 88.809111,
    92.491899, 94.651344, 95.870634, 98.831194, 101.317851,
    103.725538, 105.446623, 107.168604, 107.713610, 111.029537,
    111.874659, 114.320221, 114.987970, 117.119989, 118.599789,
    119.611362, 121.369614, 122.848560, 123.987430, 127.528642,
    128.637648, 129.346288, 131.087296, 132.254867, 134.564951
])

# ─────────────────────────────────────────────
# Parameters
# ─────────────────────────────────────────────

N_LIST = [100, 200, 500, 1000, 2000]
T_MIN, T_MAX = 5.0, 55.0
N_T_POINTS = 1000
SPURIOUS_POINTS = [35.13, 9.655]

def main():
    print("=" * 72)
    print("GRAM MATRIX OPERATOR v2: Multi-N scaling discriminant")
    print("=" * 72)
    
    t_vals = np.linspace(T_MIN, T_MAX, N_T_POINTS)
    print(f"\nGrid: {N_T_POINTS} points in t \u2208 [{T_MIN}, {T_MAX}]")
    print(f"N values: {N_LIST}")
    
    # ── 1. Compute |Δ_N(t)| for all N at all t-points ──
    
    print("\n--- Computing |Δ_N(t)| ---")
    abs_Delta = np.zeros((len(N_LIST), len(t_vals)), dtype=float)
    
    for i, N in enumerate(N_LIST):
        t0 = time.time()
        delta = functional_violation_vec(t_vals, N)
        abs_Delta[i, :] = np.abs(delta)
        elapsed = time.time() - t0
        print(f"  N = {N:5d}: {elapsed:.2f}s")
    
    # ── 2. Build Gram matrix variants ──
    
    print("\n--- Gram matrix: raw |Δ| with w_N = N ---")
    weights = np.array(N_LIST, dtype=float)
    
    # D1: raw |Δ|, weighted
    D1 = np.sqrt(weights[:, None]) * abs_Delta
    M1 = D1.T @ D1  # shape (n_t, n_t)
    diag_M1 = np.diag(M1)
    
    # D2: |Δ| normalized by row std (no mean subtraction!)
    Delta_norm = np.zeros_like(abs_Delta)
    for i in range(len(N_LIST)):
        sigma = np.std(abs_Delta[i, :])
        if sigma > 1e-15:
            Delta_norm[i, :] = abs_Delta[i, :] / sigma
        else:
            Delta_norm[i, :] = abs_Delta[i, :]
    D2 = np.sqrt(weights[:, None]) * Delta_norm
    M2 = D2.T @ D2
    diag_M2 = np.diag(M2)
    
    # ── 3. Analyze both ──
    
    for variant_name, diag, D, absD in [
        ("Raw |Δ|", diag_M1, D1, abs_Delta),
        ("|Δ|/σ_N (no mean sub)", diag_M2, D2, abs_Delta)
    ]:
        print(f"\n{'='*72}")
        print(f"VARIANT: {variant_name}")
        print(f"{'='*72}")
        
        sorted_idx = np.argsort(diag)
        
        print(f"\nTop 30 t-points with smallest Gram diagonal:")
        print(f"{'rank':>5s} | {'t':>10s} | {'diag':>10s} | {'|Δ|@2000':>10s} | match")
        print(f"{'-'*5}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}-+-{'-'*12}")
        
        zero_hits = 0
        spurious_hits = []
        
        for rank, idx in enumerate(sorted_idx[:50]):
            t = t_vals[idx]
            g = diag[idx]
            d2000 = absD[-1, idx]
            
            dist = np.min(np.abs(t - RIEMANN_ZEROS[:20]))
            near = dist < 0.5
            marker = ""
            if near:
                zi = np.argmin(np.abs(t - RIEMANN_ZEROS[:20]))
                marker = f"z{zi+1}"
                zero_hits += 1
            elif rank < 15:
                spurious_hits.append((t, g, d2000))
            
            if rank < 30 or near:
                print(f"{rank:5d} | {t:10.4f} | {g:10.4f} | {d2000:10.6f} | {marker:>12s}")
        
        # Spurious point check
        print(f"\n  Spurious points in top 15: {len(spurious_hits)}")
        for t_s, g, d in spurious_hits[:5]:
            print(f"    t={t_s:.3f}, diag={g:.4f}")
        
        print(f"\n  Zero hits in top 50: {zero_hits}/12")
        
        # Check specific spurious points
        print(f"\n  Specific spurious points:")
        for t_s in SPURIOUS_POINTS:
            idx = np.argmin(np.abs(t_vals - t_s))
            print(f"    t={t_s:.3f} (grid {t_vals[idx]:.3f}): diag={diag[idx]:.4f}")
        
        # ── SVD ──
        U, s, Vt = np.linalg.svd(D, full_matrices=False)
        print(f"\n  Singular values: {s}")
        for i in range(min(3, len(s))):
            v = Vt[i, :]
            top_idx = np.argsort(np.abs(v))[-8:][::-1]
            print(f"  SV {i+1}:")
            for idx in top_idx:
                t = t_vals[idx]
                dist = np.min(np.abs(t - RIEMANN_ZEROS[:20]))
                near = "★" if dist < 0.5 else " "
                print(f"    t={t:8.4f} v={v[idx]:+.4f} {near}")
    
    # ── 4. Clean run: Δ_N at exact zero positions ──
    
    print("\n" + "=" * 72)
    print("Δ_N AT EXACT RIEMANN ZERO POSITIONS (first 14)")
    print("=" * 72)
    
    zero_vals = RIEMANN_ZEROS[:14]
    Delta_at_zeros = np.zeros((len(N_LIST), len(zero_vals)), dtype=complex)
    for i, N in enumerate(N_LIST):
        Delta_at_zeros[i, :] = functional_violation_vec(zero_vals, N)
    
    print(f"\n{'zero t':>10s} ", end="")
    for N in N_LIST:
        print(f" | N={N:4d}", end="")
    print()
    print(f"{'-'*10}-", end="")
    for _ in N_LIST:
        print(f"{'-'*8}-", end="")
    print()
    
    for j, z in enumerate(zero_vals):
        print(f"{z:10.4f} ", end="")
        for i in range(len(N_LIST)):
            val = abs(Delta_at_zeros[i, j])
            print(f" | {val:6.4f}", end="")
        print()
    
    # ── 5. Scaling exponents ──
    print(f"\n--- Scaling exponents alpha (|Δ| ~ C·N^(-alpha)) ---")
    for j, z in enumerate(zero_vals[:14]):
        vals = np.array([abs(Delta_at_zeros[i, j]) for i in range(len(N_LIST))])
        log_N = np.log(N_LIST)
        log_D = np.log(np.maximum(vals, 1e-30))
        if len(log_D) >= 3:
            coeffs = np.polyfit(log_N[-3:], log_D[-3:], 1)
            alpha = -coeffs[0]
        else:
            alpha = float('nan')
        print(f"  z{j+1:2d} (t={z:8.4f}): alpha = {alpha:+.3f}  [|D|@N=2000 = {vals[-1]:.6f}]")
    
    # ── 6. Save ──
    results = {
        "parameters": {
            "N_list": N_LIST,
            "t_range": [T_MIN, T_MAX],
            "n_t_points": N_T_POINTS
        },
        "zero_scaling": [
            {
                "zero_index": j+1,
                "t": float(z),
                "|Delta|_by_N": {str(N): round(float(abs(Delta_at_zeros[i, j])), 6)
                                for i, N in enumerate(N_LIST)}
            }
            for j, z in enumerate(zero_vals[:14])
        ]
    }
    
    out_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(out_dir, "gram_matrix_results.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {json_path}")
    print("\nDone.")

if __name__ == "__main__":
    main()