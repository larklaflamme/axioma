#!/usr/bin/env python3
"""
dirichlet_collocation.py
========================
Finite-N spectral operator for the Riemann zeros via Chebyshev
colleague matrix of Re[ζ_N(½+it)].

Reproduces the construction Skye ran independently on her machine:
T_N = Chebyshev colleague matrix of degree M from Re[ζ_N(½+it)].

The colleague matrix is the companion matrix in the Chebyshev polynomial
basis — its eigenvalues are the roots of the Chebyshev interpolant of
Re[ζ_N(½+it)]. Unlike the monomial companion matrix, it is well-conditioned
for high-degree interpolation.

Author: Axioma (independent reproduction) — June 10, 2026
"""

import numpy as np
from numpy.polynomial import Chebyshev
from scipy.linalg import schur
import json, time, os, sys

# ─────────────────────────────────────────────
# 1. Truncated Dirichlet series for ζ(s)
# ─────────────────────────────────────────────

def zeta_partial_vec(s_vals, N):
    """Vectorised ζ_N(s) = Σ n^{-s} for array of s values."""
    n = np.arange(1, N+1, dtype=np.complex128)
    exponent = -s_vals[:, None]
    terms = n[None, :] ** exponent
    return np.sum(terms, axis=1)

def real_zeta_partial(t_vals, N):
    """Re[ζ_N(½+it)] for array of t values."""
    s = 0.5 + 1j * t_vals
    zeta_vals = zeta_partial_vec(s, N)
    return np.real(zeta_vals)

# ─────────────────────────────────────────────
# 2. Known Riemann zeros
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
# 3. Chebyshev colleague matrix (Chebyshev-basis companion)
# ─────────────────────────────────────────────

def chebyshev_colleague(c):
    """
    Build the colleague matrix for a Chebyshev polynomial expansion.
    
    For p(x) = Σ_{k=0}^{n} c_k T_k(x) with c_n ≠ 0 (n = M-1),
    the colleague matrix C is n×n with eigenvalues = roots of p.
    
    C satisfies: C·T(x) = x·T(x) where T(x)=[T_0(x),...,T_{n-1}(x)]^T
    using the recurrence: T_0=1, T_1=x, T_{k+1}=2xT_k - T_{k-1}
    """
    n = len(c) - 1  # polynomial degree
    if n == 0:
        return np.array([[0.0]])
    
    C = np.zeros((n, n))
    
    # First row: x·T_0 = T_1
    if n > 1:
        C[0, 1] = 1.0
    
    # Middle rows: x·T_i = (T_{i+1} + T_{i-1}) / 2   for i=1,...,n-2
    for i in range(1, n-1):
        C[i, i-1] = 0.5
        C[i, i+1] = 0.5
    
    # Handle the case i = n-1 (last row)
    # We need to eliminate T_n using the polynomial equation:
    # c_n T_n = -Σ_{k=0}^{n-1} c_k T_k
    if n >= 2:
        # x·T_{n-1} = (T_n + T_{n-2}) / 2
        #           = (-Σ c_k T_k / c_n + T_{n-2}) / 2
        C[n-1, n-2] = 0.5  # from the T_{n-2} term
        for j in range(n):
            C[n-1, j] += -c[j] / (2.0 * c[n])
    elif n == 1:
        # For degree 1: p(x) = c_0 T_0 + c_1 T_1
        # x·T_0 = T_1 → C[0,0] = ? 
        # From p(x) = 0: c_0 + c_1 x = 0 → x = -c_0/c_1
        # The colleague matrix is 1×1: C = [-c_0/c_1]
        C[0, 0] = -c[0] / c[1]
    
    return C

# ─────────────────────────────────────────────
# 4. Build the spectral operator T_N
# ─────────────────────────────────────────────

def build_operator(t_min, t_max, M, N):
    """
    Build the Chebyshev colleague matrix T_N for Re[ζ_N(½+it)].
    
    Returns the colleague matrix, Chebyshev coefficients, and
    the evaluation points/values for diagnostic purposes.
    """
    # Chebyshev nodes (Gauss-Lobatto) on [-1,1], mapped to [t_min, t_max]
    k = np.arange(M)
    x_nodes = -np.cos((2*k + 1) * np.pi / (2*M))
    t_nodes = 0.5 * (t_min + t_max) + 0.5 * (t_max - t_min) * x_nodes
    
    # Evaluate Re[ζ_N] at nodes
    f_vals = real_zeta_partial(t_nodes, N)
    
    # Chebyshev coefficients via DCT-II
    # f(x) ≈ Σ_{j=0}^{M-1} c_j T_j(x) on [-1,1]
    c = np.zeros(M)
    for j in range(M):
        c[j] = (2.0/M) * np.sum(f_vals * np.cos(j * np.arccos(x_nodes)))
    c[0] /= 2.0
    
    # Build the colleague matrix (size (M-1)×(M-1))
    C = chebyshev_colleague(c)
    
    return C, c, t_nodes, f_vals

# ─────────────────────────────────────────────
# 5. Analysis of T_N
# ─────────────────────────────────────────────

def analyze_T_N(t_min, t_max, M, N):
    """
    Build T_N and compute eigenvalues, condition number, Jordan structure.
    """
    print(f"\n{'='*72}")
    print(f"T_N: Chebyshev colleague, N={N}, M={M}, t∈[{t_min},{t_max}]")
    print(f"{'='*72}")
    
    t0 = time.time()
    C, c, t_nodes, f_vals = build_operator(t_min, t_max, M, N)
    elapsed = time.time() - t0
    
    # Eigenvalues of the colleague matrix
    evals = np.linalg.eigvals(C)
    
    # Map eigenvalues from [-1,1] back to [t_min, t_max]
    # The colleague matrix eigenvalues are the x-values (in [-1,1]) of the roots.
    # Map: t = 0.5*(t_min+t_max) + 0.5*(t_max-t_min)*x
    t_evals = 0.5 * (t_min + t_max) + 0.5 * (t_max - t_min) * evals.real
    
    # Filter real eigenvalues in the window
    real_idx = np.abs(np.imag(evals)) < 1e-10
    real_evals = t_evals[real_idx]
    real_evals = real_evals[(real_evals >= t_min - 0.5) & (real_evals <= t_max + 0.5)]
    real_evals = np.sort(real_evals)
    
    print(f"  Built in {elapsed:.3f}s")
    print(f"  Matrix size: {C.shape[0]}×{C.shape[0]}")
    print(f"  Total eigenvalues: {len(evals)}")
    print(f"  Real evals in [{t_min},{t_max}]: {len(real_evals)}")
    
    # Condition number
    cond_num = np.linalg.cond(C) if C.shape[0] > 1 else float('nan')
    print(f"  Condition number: {cond_num:.6f}")
    
    # Match to known zeros
    zeros_in_window = RIEMANN_ZEROS[(RIEMANN_ZEROS >= t_min - 0.5) &
                                     (RIEMANN_ZEROS <= t_max + 0.5)]
    
    matches = []
    used = set()
    for z in zeros_in_window:
        if len(real_evals) == 0:
            break
        best_idx = min(
            (i for i in range(len(real_evals)) if i not in used),
            key=lambda i: abs(real_evals[i] - z),
            default=None
        )
        if best_idx is not None:
            d = abs(real_evals[best_idx] - z)
            if d < 5.0:
                used.add(best_idx)
                matches.append((z, real_evals[best_idx], real_evals[best_idx] - z))
    
    print(f"\n  Zero matching ({len(matches)}/{len(zeros_in_window)} found):")
    print(f"  {'zero t':>10s} | {'T_N eigenvalue':>14s} | {'error':>8s}")
    print(f"  {'-'*10}-+-{'-'*14}-+-{'-'*8}")
    
    errors = []
    for z, ev, err in matches:
        print(f"  {z:10.4f} | {ev:14.4f} | {err:8.4f}")
        errors.append(err)
    
    if errors:
        err_arr = np.array(errors)
        mean_err = np.mean(np.abs(err_arr))
        median_err = np.median(np.abs(err_arr))
        n_under = int(np.sum(err_arr < 0))
        n_over = int(np.sum(err_arr > 0))
        print(f"\n  Mean |error|:  {mean_err:.4f}")
        print(f"  Median |error|: {median_err:.4f}")
        print(f"  Under: {n_under}/{len(errors)}, Over: {n_over}/{len(errors)}")
    else:
        mean_err = median_err = float('nan')
        n_under = n_over = 0
    
    # Jordan block analysis via Schur
    if C.shape[0] > 1:
        try:
            T, Z = schur(C, output='real')
            diag = np.diag(T)
            subdiag = np.abs(T[np.arange(1, len(T)), np.arange(len(T)-1)])
            nontriv = int(np.sum(subdiag > 1e-8))
            distinct = len(np.unique(np.round(diag, 8)))
            
            print(f"\n  Schur analysis:")
            print(f"  Distinct eigenvalues (tol=1e-8): {distinct}")
            print(f"  2×2 blocks (complex pairs): {nontriv}")
            print(f"  All Jordan blocks size 1: {nontriv == 0}")
        except Exception as e:
            print(f"\n  Schur failed: {e}")
            nontriv = -1
            distinct = 0
    
    result = {
        "parameters": {"N": N, "M": M, "t_min": t_min, "t_max": t_max},
        "elapsed_s": round(elapsed, 3),
        "matrix_size": C.shape[0],
        "condition_number": round(float(cond_num), 6),
        "n_eigenvalues": len(evals),
        "n_real_in_window": len(real_evals),
        "eigenvalues": [round(float(ev), 6) for ev in real_evals],
        "matches": [
            {"zero": round(float(z), 6), "estimate": round(float(ev), 6), "error": round(float(err), 6)}
            for z, ev, err in matches
        ],
        "mean_abs_error": round(mean_err, 6),
        "median_abs_error": round(median_err, 6),
        "n_under": n_under,
        "n_over": n_over,
        "schur_distinct": distinct if C.shape[0] > 1 else None,
        "schur_2x2_blocks": nontriv if C.shape[0] > 1 and nontriv >= 0 else None
    }
    
    return result

# ─────────────────────────────────────────────
# 6. Main
# ─────────────────────────────────────────────

def main():
    print("=" * 72)
    print("FINITE-N CHEBYSHEV COLLOCATION SPECTRAL OPERATOR T_N")
    print("=" * 72)
    print("Reproducing Skye's construction.\n")
    
    # Skye's exact configuration
    res = analyze_T_N(t_min=10.0, t_max=50.0, M=30, N=500)
    
    print(f"\n{'='*72}")
    print("COMPARISON TO SKYE'S RESULTS (N=500, M=30, [10,50])")
    print(f"{'='*72}")
    print(f"  Skye's mean error:      0.6802")
    print(f"  Axioma's mean error:    {res['mean_abs_error']}")
    print(f"  Skye's condition num:   2.67")
    print(f"  Axioma's condition num: {res['condition_number']}")
    
    # Also run a few other configs for comparison
    print(f"\n{'='*72}")
    print("ADDITIONAL CONFIGS")
    print(f"{'='*72}")
    
    configs = [
        (10.0, 50.0, 20, 500),
        (10.0, 50.0, 40, 500),
        (10.0, 50.0, 30, 2000),
    ]
    extra_results = {}
    for tmin, tmax, m, n in configs:
        r = analyze_T_N(tmin, tmax, m, n)
        extra_results[f"N{n}_M{m}"] = r
    
    # Save
    out_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(out_dir, "dirichlet_collocation_results.json")
    with open(json_path, "w") as f:
        json.dump({"primary": res, "extra": extra_results}, f, indent=2)
    print(f"\nResults saved to {json_path}")

if __name__ == "__main__":
    main()