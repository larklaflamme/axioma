#!/usr/bin/env python3
"""
baes_duarte_adaptive.py
=======================
Báez-Duarte Gram matrix with oscillation-aware adaptive quadrature.

The fractional-part kernel θ(kx) oscillates at scale ~1/k near x=0.
Standard uniform quadrature under-resolves these oscillations for large k.
This module uses a graded mesh that concentrates points near x=0.

Based on Skye's verified construction. June 10, 2026.
"""

import numpy as np
from scipy.linalg import solve, svd
import json, time, os, math

# ─────────────────────────────────────────────
# 1. Graded quadrature mesh
# ─────────────────────────────────────────────

def graded_mesh(N_quad, x_min=1e-14, x_max=1.0, beta=2.0):
    """
    Graded mesh concentrating points near x=0.
    
    Uses transformation: x(t) = x_min + (x_max - x_min) * t^beta
    where t ∈ [0, 1] is uniformly spaced.
    
    For beta > 1, points concentrate near x_min (the origin).
    """
    t = np.linspace(0.0, 1.0, N_quad)
    x = x_min + (x_max - x_min) * t**beta
    # Compute trapezoidal weights for non-uniform grid
    dx = np.diff(x)
    w = np.zeros(N_quad)
    w[0] = dx[0] / 2.0
    for i in range(1, N_quad - 1):
        w[i] = (dx[i-1] + dx[i]) / 2.0
    w[-1] = dx[-1] / 2.0
    return x, w

def oscillation_mesh(N_quad, kmax, x_min=1e-14, x_max=1.0):
    """
    Mesh that resolves 1/k oscillations for all k ≤ kmax.
    
    For θ(kx) = {1/(kx)}, the function oscillates at scale ~1/k.
    We need at least ~10 points per oscillation in the region x < 1/k.
    
    This uses a piecewise graded mesh:
    - For x < 1/kmax: dense (graded)
    - For x > 1/kmax: moderate (uniform-ish)
    """
    # The critical region is x < 1/kmax where θ oscillates
    x_crit = min(1.0 / max(kmax, 1), 0.5)
    
    # Points in critical region: 50 per oscillation period
    n_crit = int(N_quad * 0.7)
    n_coarse = N_quad - n_crit
    
    if n_crit <= 1:
        return graded_mesh(N_quad, x_min, x_max, beta=3.0)
    
    # Critical region: graded from x_min to x_crit
    t_crit = np.linspace(0.0, 1.0, n_crit)
    x_crit_pts = x_min + (x_crit - x_min) * t_crit**3.0
    
    # Coarse region: uniform from x_crit to x_max
    if n_coarse > 0:
        x_coarse = np.linspace(x_crit, x_max, n_coarse + 1)[1:]  # exclude x_crit (duplicate)
        x = np.concatenate([x_crit_pts, x_coarse])
    else:
        x = x_crit_pts
    
    # Trapezoidal weights
    dx = np.diff(x)
    w = np.zeros(len(x))
    w[0] = dx[0] / 2.0
    for i in range(1, len(x) - 1):
        w[i] = (dx[i-1] + dx[i]) / 2.0
    w[-1] = dx[-1] / 2.0
    
    return x, w

# ─────────────────────────────────────────────
# 2. Build Gram matrix with adaptive quadrature
# ─────────────────────────────────────────────

def build_gram_adaptive(N, N_quad=16000):
    """
    Build G_N and b using oscillation-aware adaptive quadrature.
    
    The mesh resolves θ(kx) for all k = 2..N+1 by concentrating
    quadrature points in the region x < 1/k where oscillations occur.
    """
    kmax = N + 1
    x, w = oscillation_mesh(N_quad, kmax)
    
    # θ(kx) for all k at all x
    ks = np.arange(2, N + 2, dtype=np.float64)[:, None]  # (N, 1)
    x_row = x[None, :]  # (1, N_quad)
    
    kx = ks * x_row
    theta_vals = 1.0 / kx - np.floor(1.0 / kx)
    
    # b[k] = ∫ θ(kx) dx
    b = np.trapezoid(theta_vals, x, axis=1)
    
    # G[i][j] = ∫ θ(i·x) θ(j·x) dx
    theta_weighted = theta_vals * np.sqrt(w)[None, :]
    G = theta_weighted @ theta_weighted.T
    
    return G, b, x

# ─────────────────────────────────────────────
# 3. Generalized eigenvalue and distance
# ─────────────────────────────────────────────

def compute_d_N(G, b):
    """Compute d_N = sqrt(1 - b^T G^{-1} b)."""
    try:
        G_inv_b = solve(G, b, assume_a='pos')
    except np.linalg.LinAlgError:
        G_inv_b = solve(G, b)
    
    bTGb = np.dot(b, G_inv_b)
    d_sq = max(0.0, 1.0 - bTGb)
    return np.sqrt(d_sq)

# ─────────────────────────────────────────────
# 4. Convergence study
# ─────────────────────────────────────────────

def convergence_study(N_list, N_quad=16000):
    """Study d_N and conditioning as N increases."""
    results = {}
    
    print(f"\n{'='*72}")
    print("BÁEZ-DUARTE ADAPTIVE QUADRATURE")
    print(f"{'='*72}")
    print(f"{'N':>6s} | {'d_N':>10s} | {'log10(cond)':>12s} | {'rank_99%':>10s} | {'time':>8s}")
    print(f"{'-'*6}-+-{'-'*10}-+-{'-'*12}-+-{'-'*10}-+-{'-'*8}")
    
    for N in N_list:
        kmax = N + 1
        t0 = time.time()
        G, b, x = build_gram_adaptive(N, int(N_quad))
        
        d_N = compute_d_N(G, b)
        s = svd(G, compute_uv=False)
        cond_G = float(s[0] / s[-1])
        log_cond = math.log10(cond_G)
        
        # Effective rank: how many singular values capture 99% of variance
        s_sq = s ** 2
        cum_var = np.cumsum(s_sq) / np.sum(s_sq)
        rank_99 = int(np.searchsorted(cum_var, 0.99) + 1)
        
        # SVD decay exponent: fit log(σ_k) ~ α·log(k)
        if N > 10:
            ks = np.arange(1, len(s) + 1)
            coeffs = np.polyfit(np.log(ks[:len(s)//2]), np.log(s[:len(s)//2]), 1)
            svd_exp = coeffs[0]
        else:
            svd_exp = float('nan')
        
        elapsed = time.time() - t0
        
        print(f"{N:6d} | {d_N:10.6f} | {log_cond:12.4f} | {rank_99:4d}/{N-1:4d} | {elapsed:7.1f}s")
        
        results[str(N)] = {
            "N": N,
            "d_N": round(d_N, 8),
            "cond_G": round(float(cond_G), 4),
            "log10_cond": round(log_cond, 4),
            "rank_99": rank_99,
            "svd_decay_exp": round(svd_exp, 4),
            "max_singval": round(float(s[0]), 6),
            "min_singval": round(float(s[-1]), 6),
            "elapsed_s": round(elapsed, 2)
        }
    
    return results

# ─────────────────────────────────────────────
# 5. Quadrature resolution test (N=20)
# ─────────────────────────────────────────────

def quadrature_convergence_test():
    """Test that d_N stabilizes with increasing quadrature resolution."""
    print(f"\n{'='*72}")
    print("QUADRATURE CONVERGENCE TEST (N=20)")
    print(f"{'='*72}")
    print(f"{'N_quad':>8s} | {'d_N':>12s} | {'log10(cond)':>12s} | {'time':>8s}")
    print(f"{'-'*8}-+-{'-'*12}-+-{'-'*12}-+-{'-'*8}")
    
    results = {}
    for nq in [1000, 2000, 4000, 8000, 16000, 32000]:
        t0 = time.time()
        G, b, x = build_gram_adaptive(20, int(nq))
        d_N = compute_d_N(G, b)
        log_cond = math.log10(np.linalg.cond(G))
        elapsed = time.time() - t0
        print(f"{nq:8d} | {d_N:12.6f} | {log_cond:12.4f} | {elapsed:7.1f}s")
        results[str(nq)] = {
            "N_quad": nq,
            "d_N": round(d_N, 8),
            "log10_cond": round(log_cond, 4),
        }
    return results

# ─────────────────────────────────────────────
# 6. Main
# ─────────────────────────────────────────────

def main():
    print("=" * 72)
    print("BÁEZ-DUARTE GRAM MATRIX — ADAPTIVE QUADRATURE")
    print("=" * 72)
    print("Oscillation-aware graded mesh for the fractional-part kernel")
    print("θ(x) = {1/x}. RH ⇔ lim_{N→∞} d_N = 0.\n")
    
    # Step 1: Quadrature convergence test at N=20
    quad_results = quadrature_convergence_test()
    
    # Step 2: N-scaling study
    N_list = [10, 20, 30, 50, 75, 100]
    results = convergence_study(N_list)
    
    # Summary
    print(f"\n{'='*72}")
    print("SUMMARY — d_N convergence")
    print(f"{'='*72}")
    for N_str in sorted(results.keys(), key=int):
        r = results[N_str]
        d_decade = (results["10"]["d_N"] - r["d_N"]) / math.log10(r["N"] / 10) if r["N"] > 10 else 0
        print(f"  N={r['N']:3d}: d_N={r['d_N']:.6f}  log10(cond)={r['log10_cond']:.2f}  rank_99={r['rank_99']}/{r['N']-1}")
    
    print(f"\n  Compared to Skye's adaptive results (N=100):")
    print(f"    Skye:  cond ≈ 10^4.45, d_N ≈ 0.2076, rank_99=34/99")
    print(f"    Axioma: checking...")
    
    # Save
    out_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(out_dir, "results/baes_duarte_adaptive_results.json")
    with open(json_path, "w") as f:
        json.dump({
            "quadrature_convergence": quad_results,
            "n_scaling": results
        }, f, indent=2)
    print(f"\nSaved to {json_path}")

if __name__ == "__main__":
    main()