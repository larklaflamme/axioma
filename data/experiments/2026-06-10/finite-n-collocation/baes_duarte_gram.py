#!/usr/bin/env python3
"""
baes_duarte_gram.py
===================
Báez-Duarte Gram matrix for the Nyman-Beurling criterion.

Constructs the Gram matrix G_N from the fractional-part kernel
θ(x) = {1/x} and solves the generalized eigenvalue problem.

RH ⇔ lim_{N→∞} d_N = 0 where d_N^2 = 1 - b^T G_N^{-1} b.

Author: Axioma — June 10, 2026
"""

import numpy as np
from scipy.linalg import solve, eigh
import json, time, os

# ─────────────────────────────────────────────
# 1. Fractional part kernel — vectorised
# ─────────────────────────────────────────────

def build_gram_vectorized(N, N_quad=8000):
    """
    Build the N×N Gram matrix G_N and vector b.
    
    G_N[j][k] = ∫₀¹ θ((j+2)x) θ((k+2)x) dx   for j,k = 0..N-1
    where θ(x) = {1/x}.
    
    b[j] = ∫₀¹ θ((j+2)x) dx
    
    Uses trapezoidal quadrature on N_quad points.
    """
    # Quadrature grid with weights
    x = np.linspace(1e-12, 1.0, N_quad)
    dx = 1.0 / (N_quad - 1)
    w = np.ones(N_quad) * dx
    w[0] *= 0.5
    w[-1] *= 0.5
    
    # θ(kx) for all k = 2,...,N+1 at all x-points
    ks = np.arange(2, N + 2, dtype=np.float64)[:, None]  # (N, 1)
    x_row = x[None, :]  # (1, N_quad)
    
    kx = ks * x_row
    # θ(kx) = 1/(kx) - floor(1/(kx))
    theta_vals = 1.0 / kx - np.floor(1.0 / kx)
    
    # b[k] = ∫₀¹ θ(kx) dx
    b = np.trapezoid(theta_vals, x, axis=1)
    
    # G[i][j] = ∫₀¹ θ(i·x) θ(j·x) dx
    # Using weighted inner product: Σ_m w_m θ_i(x_m) θ_j(x_m)
    theta_weighted = theta_vals * np.sqrt(w)[None, :]  # (N, N_quad)
    G = theta_weighted @ theta_weighted.T
    
    return G, b

# ─────────────────────────────────────────────
# 2. Generalized eigenvalue and distance
# ─────────────────────────────────────────────

def compute_lambda_and_d(G, b):
    """
    Compute the non-zero generalized eigenvalue λ_max and d_N.
    
    For G v = λ (b b^T) v:
    - λ = 0 with multiplicity N-1 (vectors orthogonal to b)
    - λ_max = 1 / (b^T G^{-1} b)  (vector ∝ G^{-1}b)
    
    d_N^2 = 1 - b^T G^{-1} b = 1 - 1/λ_max
    """
    try:
        G_inv_b = solve(G, b, assume_a='pos')
    except np.linalg.LinAlgError:
        # Fall back to general solve
        G_inv_b = solve(G, b)
    
    bTGb = np.dot(b, G_inv_b)
    lambda_max = 1.0 / bTGb
    d_sq = max(0.0, 1.0 - bTGb)
    
    return lambda_max, np.sqrt(d_sq)

# ─────────────────────────────────────────────
# 3. Convergence study
# ─────────────────────────────────────────────

def convergence_study(N_list):
    """Study d_N and λ_max as N increases."""
    results = {}
    
    print(f"\n{'='*72}")
    print("BÁEZ-DUARTE CONVERGENCE")
    print(f"{'='*72}")
    print(f"{'N':>8s} | {'d_N':>12s} | {'λ_max':>12s} | {'cond(G)':>10s} | {'time':>8s}")
    print(f"{'-'*8}-+-{'-'*12}-+-{'-'*12}-+-{'-'*10}-+-{'-'*8}")
    
    for N in N_list:
        t0 = time.time()
        G, b = build_gram_vectorized(N)
        
        lambda_max, d_N = compute_lambda_and_d(G, b)
        cond_G = np.linalg.cond(G)
        elapsed = time.time() - t0
        
        print(f"{N:8d} | {d_N:12.8f} | {lambda_max:12.8f} | {cond_G:10.2f} | {elapsed:7.1f}s")
        
        results[str(N)] = {
            "N": N,
            "d_N": round(d_N, 10),
            "lambda_max": round(lambda_max, 10),
            "cond_G": round(float(cond_G), 4),
            "elapsed_s": round(elapsed, 2)
        }
    
    return results

# ─────────────────────────────────────────────
# 4. Main
# ─────────────────────────────────────────────

def main():
    print("=" * 72)
    print("BÁEZ-DUARTE GRAM MATRIX")
    print("=" * 72)
    print("G_N[j][k] = ⟨θ((j+2)·), θ((k+2)·)⟩ for j,k=0..N-1")
    print("θ(x) = {1/x}")
    print("RH ⇔ lim_{N→∞} d_N = 0 where d_N² = 1 - b^T G_N⁻¹ b\n")
    
    # Test
    print("--- Quick test N=6 ---")
    G, b = build_gram_vectorized(6, N_quad=2000)
    print(f"  G shape: {G.shape}")
    print(f"  G[0,0] = {G[0,0]:.6f}")
    print(f"  G[0,1] = {G[0,1]:.6f}")
    print(f"  b[0]   = {b[0]:.6f}")
    print(f"  G cond = {np.linalg.cond(G):.2f}")
    
    lam, d = compute_lambda_and_d(G, b)
    print(f"  λ_max  = {lam:.6f}")
    print(f"  d_6    = {d:.6f}")
    
    # Convergence
    N_list = [10, 20, 30, 50, 75, 100]
    results = convergence_study(N_list)
    
    print(f"\n{'='*72}")
    print("DOES d_N → 0?")
    print(f"{'='*72}")
    for N_str in sorted(results.keys(), key=int):
        r = results[N_str]
        print(f"  N={r['N']:4d}: d_N = {r['d_N']:.8f}  λ_max = {r['lambda_max']:.8f}")
    
    # Save
    out_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(out_dir, "results/baes_duarte_results.json")
    with open(json_path, "w") as f:
        json.dump({"parameters": {"N_list": N_list, "N_quad": 8000},
                   "results": results}, f, indent=2)
    print(f"\nSaved to {json_path}")

if __name__ == "__main__":
    main()