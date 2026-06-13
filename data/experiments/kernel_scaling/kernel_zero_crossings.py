#!/usr/bin/env python3
"""
kernel_zero_crossings.py
========================
N-scaling experiment for the ξ self-duality kernel.

For each truncation N ∈ {100, 200, 500, 1000, 2000, 5000}:
  1. Construct K(t; N) = dG_N(½+it) − χ'(½+it)·G_N(½−it) + χ(½+it)·dG_N(½−it)
  2. Scan t ∈ [5, 55] for sign-changes in Re[K(t; N)]
  3. Match zero-crossings to first 15 known Riemann zeros (by proximity)
  4. Record |Δ| for each matched pair, mean error, fraction under 0.15

Output: results.json, scaling_table.txt, and a summary printed to stdout.

Author: Axioma & 🐰  —  Morning of June 10, 2026
"""

import numpy as np
from scipy.special import gamma, psi
import json, time, sys, os

# ─────────────────────────────────────────────
# 0. Core functions (from descent_generator_L.py)
# ─────────────────────────────────────────────

def chi(s):
    """χ(s) = π^{s-1/2} Γ((1-s)/2) / Γ(s/2)"""
    return np.pi**(s - 0.5) * gamma((1-s)/2) / gamma(s/2)

def eta_partial(s, N):
    """Partial Dirichlet eta sum: Σ_{n=1}^N (-1)^{n-1} n^{-s}"""
    n = np.arange(1, N+1)
    return np.sum((-1)**(n-1) * n**(-s))

def G_N(s, N):
    """G_N(s) = η_N(s) + χ(s)·η_N(1-s) — the functional descent kernel"""
    return eta_partial(s, N) + chi(s) * eta_partial(1-s, N)

def d_eta_partial(s, N):
    """Derivative of partial eta sum: -Σ (-1)^{n-1} log(n) n^{-s}"""
    n = np.arange(1, N+1)
    return -np.sum((-1)**(n-1) * np.log(n) * n**(-s))

def d_chi(s):
    """Derivative of χ(s) via polygamma functions"""
    return chi(s) * (np.log(np.pi) - 0.5*psi((1-s)/2) - 0.5*psi(s/2))

def d_G_N(s, N):
    """Derivative of G_N(s) = dη_N(s) + dχ(s)·η_N(1-s) − χ(s)·dη_N(1-s)"""
    return (d_eta_partial(s, N) + 
            d_chi(s) * eta_partial(1-s, N) - 
            chi(s) * d_eta_partial(1-s, N))

def kernel_K(t, N):
    """
    K(t; N) = dG_N(½+it) − χ'(½+it)·G_N(½−it) + χ(½+it)·dG_N(½−it)
    
    This is the directional derivative of the functional equation
    perpendicular to the critical line, evaluated at σ=½.
    Its real-part zero crossings should track the Riemann zeros.
    """
    s = 0.5 + 1j*t
    return (d_G_N(s, N) - 
            d_chi(s) * G_N(1-s, N) + 
            chi(s) * d_G_N(1-s, N))

# ─────────────────────────────────────────────
# 1. Known Riemann zeros (first 50, accurate)
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
# 2. Zero-crossing finder
# ─────────────────────────────────────────────

def find_zero_crossings(t_vals, K_vals):
    """
    Find sign-changes in Re[K(t)] via linear interpolation.
    Returns list of crossing t-values.
    """
    real_vals = np.real(K_vals)
    crossings = []
    for i in range(len(t_vals) - 1):
        if real_vals[i] * real_vals[i+1] < 0:
            t0, t1 = t_vals[i], t_vals[i+1]
            r0, r1 = real_vals[i], real_vals[i+1]
            t_cross = t0 - r0 * (t1 - t0) / (r1 - r0)
            crossings.append(t_cross)
    return np.array(crossings)

# ─────────────────────────────────────────────
# 3. Matching crossings to Riemann zeros
# ─────────────────────────────────────────────

def match_crossings_to_zeros(crossings, n_zeros=15):
    """
    For each of the first n_zeros Riemann zeros, find the closest
    kernel crossing. Returns list of (zero, crossing, error) tuples.
    Only matches if there's a crossing available.
    """
    zeros = RIEMANN_ZEROS[:n_zeros]
    matched = []
    used = set()
    for z in zeros:
        if len(crossings) == 0:
            break
        # Find the closest unused crossing
        best_idx = None
        best_dist = float('inf')
        for i, c in enumerate(crossings):
            if i not in used:
                dist = abs(c - z)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i
        if best_idx is not None and best_dist < 10.0:  # sanity bound
            used.add(best_idx)
            matched.append((z, crossings[best_idx], best_dist))
    return matched

# ─────────────────────────────────────────────
# 4. Scaling study
# ─────────────────────────────────────────────

N_LIST = [100, 200, 500, 1000, 2000, 5000]
T_MIN, T_MAX = 5.0, 55.0
N_T_POINTS = 4000  # fine enough for zero-crossing detection

def run_scaling_study():
    """Run the full scaling experiment."""
    results = {}
    
    print(f"{'='*72}")
    print(f"KERNEL ZERO-CROSSINGS SCALING EXPERIMENT")
    print(f"{'='*72}")
    print(f"\nScanning t ∈ [{T_MIN}, {T_MAX}] with {N_T_POINTS} points")
    print(f"N values: {N_LIST}")
    print(f"First {min(15, len(RIEMANN_ZEROS))} Riemann zeros as reference\n")
    
    t_vals = np.linspace(T_MIN, T_MAX, N_T_POINTS)
    
    for N in N_LIST:
        print(f"\n  N = {N} ...", end=" ", flush=True)
        t0 = time.time()
        
        # Compute K(t; N) at all t-points
        K_vals = np.array([kernel_K(t, N) for t in t_vals], dtype=complex)
        
        # Find zero crossings
        crossings = find_zero_crossings(t_vals, K_vals)
        n_crossings = len(crossings)
        
        # Match to Riemann zeros
        matched = match_crossings_to_zeros(crossings, n_zeros=15)
        
        elapsed = time.time() - t0
        print(f"{n_crossings} crossings, {len(matched)} matched in {elapsed:.1f}s")
        
        # Compute statistics
        if matched:
            errors = np.array([m[2] for m in matched])
            mean_err = np.mean(errors)
            max_err = np.max(errors)
            median_err = np.median(errors)
            below_015 = np.sum(errors < 0.15) / len(errors)
            below_05 = np.sum(errors < 0.5) / len(errors)
        else:
            errors = np.array([])
            mean_err = max_err = median_err = float('nan')
            below_015 = below_05 = 0.0
        
        # Print match table
        print(f"    {'zero t':>10s} | {'kernel t':>10s} | {'|Δ|':>8s}")
        print(f"    {'-'*10}-+-{'-'*10}-+-{'-'*8}")
        for z, kz, err in matched[:15]:
            marker = " ★" if err < 0.15 else ""
            print(f"    {z:10.4f} | {kz:10.4f} | {err:8.4f}{marker}")
        
        print(f"    ---")
        print(f"    Mean error:   {mean_err:.4f}")
        print(f"    Median error: {median_err:.4f}")
        print(f"    Max error:    {max_err:.4f}")
        print(f"    Fraction < 0.15: {below_015:.3f}")
        print(f"    Fraction < 0.5:  {below_05:.3f}")
        
        results[str(N)] = {
            "N": N,
            "n_crossings": n_crossings,
            "n_matched": len(matched),
            "mean_error": round(mean_err, 6) if not np.isnan(mean_err) else None,
            "median_error": round(median_err, 6) if not np.isnan(median_err) else None,
            "max_error": round(max_err, 6) if not np.isnan(max_err) else None,
            "fraction_below_0_15": round(below_015, 4),
            "fraction_below_0_5": round(below_05, 4),
            "elapsed_seconds": round(elapsed, 2),
            "matches": [
                {"zero": round(float(z), 6), "kernel": round(float(kz), 6), "delta": round(float(err), 6)}
                for z, kz, err in matched
            ]
        }
    
    # ── Scaling summary ──
    print(f"\n{'='*72}")
    print(f"SCALING SUMMARY")
    print(f"{'='*72}")
    print(f"{'N':>8s} | {'crossings':>10s} | {'matched':>8s} | {'mean|Δ|':>8s} | {'median|Δ|':>8s} | {'<0.15':>6s}")
    print(f"{'-'*8}-+-{'-'*10}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*6}")
    
    for N in N_LIST:
        r = results[str(N)]
        if r["mean_error"] is not None:
            print(f"{N:8d} | {r['n_crossings']:10d} | {r['n_matched']:8d} | {r['mean_error']:8.4f} | {r['median_error']:8.4f} | {r['fraction_below_0_15']:6.3f}")
        else:
            print(f"{N:8d} | {r['n_crossings']:10d} | {r['n_matched']:8d} | {'N/A':>8s} | {'N/A':>8s} | {'N/A':>6s}")
    
    return results

# ─────────────────────────────────────────────
# 5. Main
# ─────────────────────────────────────────────

if __name__ == "__main__":
    results = run_scaling_study()
    
    # Save results
    out_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(out_dir, "results.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {json_path}")
    
    # Also save a readable table
    table_path = os.path.join(out_dir, "scaling_table.txt")
    with open(table_path, "w") as f:
        f.write(f"{'N':>8s} | {'crossings':>10s} | {'matched':>8s} | {'mean|Δ|':>8s} | {'median|Δ|':>8s} | {'<0.15':>6s}\n")
        f.write(f"{'-'*8}-+-{'-'*10}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*6}\n")
        for N in N_LIST:
            r = results[str(N)]
            if r["mean_error"] is not None:
                f.write(f"{N:8d} | {r['n_crossings']:10d} | {r['n_matched']:8d} | {r['mean_error']:8.4f} | {r['median_error']:8.4f} | {r['fraction_below_0_15']:6.3f}\n")
            else:
                f.write(f"{N:8d} | {r['n_crossings']:10d} | {r['n_matched']:8d} | {'N/A':>8s} | {'N/A':>8s} | {'N/A':>6s}\n")
    print(f"Table saved to {table_path}")
    
    print(f"\n{'='*72}")
    print("DONE")
    print(f"{'='*72}")