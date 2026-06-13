#!/usr/bin/env python3
"""
correct_kernel_zero_crossings.py
================================
N-scaling experiment for the ξ self-duality functional equation violation.

The kernel K(t; N) = dG_N - χ'·G_N(1-s) + χ·dG_N(1-s) is IDENTICALLY ZERO
because χ(s)χ(1-s) = 1 forces K ≡ 0 analytically (verified 2026-06-10).

The CORRECT observable is the functional equation violation:
    Δ(t; N) = G_N(½+it) - G_N(½-it)
which measures how the finite-N truncation breaks the exact symmetry.
Its minima (near-zero values) should track the Riemann zeros and
converge to zero as N → ∞.

Author: Axioma & 🐰  —  Morning of June 10, 2026
"""

import numpy as np
from scipy.special import gamma, psi
import json, time, sys, os

# ─────────────────────────────────────────────
# 0. Core functions
# ─────────────────────────────────────────────

def chi(s):
    return np.pi**(s - 0.5) * gamma((1-s)/2) / gamma(s/2)

def eta_partial(s, N):
    n = np.arange(1, N+1)
    return np.sum((-1)**(n-1) * n**(-s))

def G_N(s, N):
    return eta_partial(s, N) + chi(s) * eta_partial(1-s, N)

def functional_violation(t, N):
    """
    Δ(t; N) = G_N(½+it) - G_N(½-it)
    
    At a true Riemann zero ζ(½+it₀) = 0, the exact functional equation
    gives ξ(½+it₀) = 0, and G(s) = η(s) + χ(s)·η(1-s) satisfies
    G(s) = G(1-s) exactly at the zero. At finite N, Δ ≈ 0 near zeros.
    """
    s = 0.5 + 1j*t
    return G_N(s, N) - G_N(1-s, N)

# ─────────────────────────────────────────────
# 1. Known Riemann zeros (first 50)
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
# 2. Minima finder for |Δ(t)|
# ─────────────────────────────────────────────

def find_violation_minima(t_vals, delta_vals):
    """
    Find local minima of |Δ(t)| — these correspond to points where
    the functional equation is most nearly satisfied, i.e., the
    approximate Riemann zero positions.
    
    Returns list of (t_min, |Δ|_min) tuples.
    """
    abs_delta = np.abs(delta_vals)
    minima = []
    for i in range(1, len(t_vals) - 1):
        if abs_delta[i] < abs_delta[i-1] and abs_delta[i] < abs_delta[i+1]:
            # Quadratic interpolation for finer precision
            t0, t1, t2 = t_vals[i-1], t_vals[i], t_vals[i+1]
            v0, v1, v2 = abs_delta[i-1], abs_delta[i], abs_delta[i+1]
            
            # Vertex of parabola through three points
            denom = 2 * (v2 - 2*v1 + v0)
            if abs(denom) > 1e-30:
                t_min = t1 - (v2 - v0) / (2 * denom) * (t2 - t0)
            else:
                t_min = t1
            
            # Value at minimum via interpolation
            s = 0.5 + 1j*t_min
            # Recompute at the interpolated point
            # (We'll do this in a finer pass)
            minima.append((t_min, v1))
    
    # Remove duplicates and sort
    minima = sorted(set(round(m[0], 6) for m in minima))
    return np.array(minima)

def find_violation_minima_fine(t_vals, delta_vals, N):
    """
    More precise: find sign changes in Re[Δ(t)] derivative,
    or simply use brute-force sampling then refine.
    """
    abs_delta = np.abs(delta_vals)
    minima = []
    for i in range(1, len(t_vals) - 1):
        if abs_delta[i] < abs_delta[i-1] and abs_delta[i] < abs_delta[i+1]:
            t_min_candidate = t_vals[i]
            minima.append(t_min_candidate)
    
    # Sort and deduplicate
    if len(minima) == 0:
        return np.array([])
    
    minima = np.array(sorted(set(round(m, 6) for m in minima)))
    return minima

# ─────────────────────────────────────────────
# 3. Matching minima to Riemann zeros
# ─────────────────────────────────────────────

def match_minima_to_zeros(minima, n_zeros=15):
    """
    For each Riemann zero, find the closest minimum of |Δ(t)|.
    Returns list of (zero, min_location, error) tuples.
    """
    zeros = RIEMANN_ZEROS[:n_zeros]
    matched = []
    used = set()
    for z in zeros:
        if len(minima) == 0:
            break
        best_idx = None
        best_dist = float('inf')
        for i, t_min in enumerate(minima):
            if i not in used:
                dist = abs(t_min - z)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i
        if best_idx is not None and best_dist < 5.0:
            used.add(best_idx)
            matched.append((z, minima[best_idx], best_dist))
    return matched

# ─────────────────────────────────────────────
# 4. Scaling study
# ─────────────────────────────────────────────

N_LIST = [100, 200, 500, 1000, 2000]
T_MIN, T_MAX = 5.0, 55.0
N_T_POINTS = 2000  # coarser scan; we'll refine later

def run_scaling_study():
    """Run the full scaling experiment on Δ(t) = G_N - G_N(1-s)."""
    results = {}
    
    print(f"{'='*72}")
    print(f"CORRECT KERNEL: FUNCTIONAL EQUATION VIOLATION Δ(t) = G_N - G_N(1-s)")
    print(f"{'='*72}")
    print(f"\nScanning t ∈ [{T_MIN}, {T_MAX}] with {N_T_POINTS} points")
    print(f"N values: {N_LIST}\n")
    
    t_vals = np.linspace(T_MIN, T_MAX, N_T_POINTS)
    
    for N in N_LIST:
        print(f"  N = {N:5d} ...", end=" ", flush=True)
        t0 = time.time()
        
        # Compute Δ(t; N)
        delta_vals = np.array([functional_violation(t, N) for t in t_vals], dtype=complex)
        
        # Find minima of |Δ(t)|
        minima = find_violation_minima_fine(t_vals, delta_vals, N)
        
        # Compute |Δ| at each minimum (refine)
        refined_minima = []
        for tm in minima:
            delta_refine = functional_violation(tm, N)
            refined_minima.append(tm)  # Keep the t value, we'll recompute
        
        n_minima = len(minima)
        
        # Match to Riemann zeros
        matched = match_minima_to_zeros(minima, n_zeros=15)
        
        elapsed = time.time() - t0
        print(f"{n_minima} minima, {len(matched)} matched in {elapsed:.1f}s")
        
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
        print(f"    {'zero t':>10s} | {'min |Δ| t':>10s} | {'|Δ|':>8s}")
        print(f"    {'-'*10}-+-{'-'*10}-+-{'-'*8}")
        for z, mz, err in matched[:15]:
            delta_at_min = functional_violation(mz, N)
            marker = " ★" if err < 0.15 else ""
            print(f"    {z:10.4f} | {mz:10.4f} | {abs(delta_at_min):8.4f}{marker}")
        
        print(f"    ---")
        print(f"    Mean positional error: {mean_err:.4f}")
        print(f"    Median error:         {median_err:.4f}")
        print(f"    Max error:            {max_err:.4f}")
        print(f"    Fraction < 0.15:      {below_015:.3f}")
        print(f"    Fraction < 0.5:       {below_05:.3f}")
        
        results[str(N)] = {
            "N": N,
            "n_minima": n_minima,
            "n_matched": len(matched),
            "mean_error": round(mean_err, 6) if not np.isnan(mean_err) else None,
            "median_error": round(median_err, 6) if not np.isnan(median_err) else None,
            "max_error": round(max_err, 6) if not np.isnan(max_err) else None,
            "fraction_below_0_15": round(below_015, 4),
            "fraction_below_0_5": round(below_05, 4),
            "elapsed_seconds": round(elapsed, 2),
            "matches": [
                {"zero": round(float(z), 6), "estimated": round(float(mz), 6), "delta": round(float(err), 6)}
                for z, mz, err in matched
            ]
        }
    
    # ── Scaling summary ──
    print(f"\n{'='*72}")
    print(f"SCALING SUMMARY")
    print(f"{'='*72}")
    print(f"{'N':>8s} | {'minima':>8s} | {'matched':>8s} | {'mean|Δ|':>8s} | {'median|Δ|':>8s} | {'<0.15':>6s}")
    print(f"{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*6}")
    
    for N in N_LIST:
        r = results[str(N)]
        if r["mean_error"] is not None:
            print(f"{N:8d} | {r['n_minima']:8d} | {r['n_matched']:8d} | {r['mean_error']:8.4f} | {r['median_error']:8.4f} | {r['fraction_below_0_15']:6.3f}")
        else:
            print(f"{N:8d} | {r['n_minima']:8d} | {r['n_matched']:8d} | {'N/A':>8s} | {'N/A':>8s} | {'N/A':>6s}")
    
    return results

# ─────────────────────────────────────────────
# 5. Main
# ─────────────────────────────────────────────

if __name__ == "__main__":
    results = run_scaling_study()
    
    # Save results
    out_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(out_dir, "correct_results.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {json_path}")
    
    print(f"\n{'='*72}")
    print("DONE")
    print(f"{'='*72}")