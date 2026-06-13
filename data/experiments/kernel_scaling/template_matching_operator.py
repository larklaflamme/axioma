#!/usr/bin/env python3
"""
template_matching_operator.py
=============================
Scaling-template matching operator for Riemann zero detection.

For each t, construct v(t) = [|Δ_{N1}(t)|, ..., |Δ_{Nk}(t)|].
Compute cosine similarity with the ideal N^{-0.5} template u.

True zeros: v(t) ∝ u  →  cos θ ≈ 1
Spurious points: v(t) flat →  cos θ different

Author: Axioma & 🐰 — June 10, 2026
"""

import numpy as np
from scipy.special import gamma
import json, time, os

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

RIEMANN_ZEROS = np.array([
    14.134725, 21.022040, 25.010858, 30.424876, 32.935062,
    37.586178, 40.918719, 43.327073, 48.005151, 49.773832,
    52.970322
])

N_LIST = [100, 200, 500, 1000, 2000]
T_MIN, T_MAX = 5.0, 55.0
N_T_POINTS = 1000

def main():
    print("=" * 72)
    print("TEMPLATE MATCHING OPERATOR: scaling discriminant")
    print("=" * 72)
    
    t_vals = np.linspace(T_MIN, T_MAX, N_T_POINTS)
    
    # Build |Δ| matrix: shape (n_N, n_t)
    abs_D = np.zeros((len(N_LIST), len(t_vals)))
    for i, N in enumerate(N_LIST):
        t0 = time.time()
        delta = functional_violation_vec(t_vals, N)
        abs_D[i, :] = np.abs(delta)
        print(f"  N={N:5d}: {time.time()-t0:.2f}s")
    
    # Template: N^{-0.5}
    u = np.array(N_LIST, dtype=float) ** (-0.5)
    u = u / np.linalg.norm(u)
    
    # For each t-point, compute cosine similarity between v(t) and u
    # v(t) = |Δ_N(t)| for all N — shape (n_N,)
    cos_sim = np.zeros(len(t_vals))
    for j in range(len(t_vals)):
        v = abs_D[:, j]
        v_norm = np.linalg.norm(v)
        if v_norm > 1e-30:
            cos_sim[j] = np.dot(v, u) / v_norm
        else:
            cos_sim[j] = 1.0  # exact zero → perfect match
    
    # Operator D = diag(1 - cos_sim) — near-nullspace at cos_sim ≈ 1
    op_diag = 1.0 - cos_sim
    
    # Sort by cos_sim descending (= by op_diag ascending)
    sorted_idx = np.argsort(-cos_sim)
    
    print(f"\n--- Top 40 t-points by cosine similarity with N^{-0.5} ---")
    print(f"{'rank':>5s} | {'t':>10s} | {'cos θ':>8s} | {'1-cosθ':>8s} | {'|Δ|@2000':>10s} | {'α':>6s} | match")
    print(f"{'-'*5}-+-{'-'*10}-+-{'-'*8}-+-{'-'*8}-+-{'-'*10}-+-{'-'*6}-+-{'-'*12}")
    
    zero_hits = 0
    spurious_hits = []
    
    for rank, idx in enumerate(sorted_idx[:60]):
        t = t_vals[idx]
        cs = cos_sim[idx]
        d2000 = abs_D[-1, idx]
        
        # Compute α from last 3 N-values
        v = abs_D[:, idx]
        logN = np.log(N_LIST[-3:])
        logD = np.log(np.maximum(v[-3:], 1e-30))
        coeffs = np.polyfit(logN, logD, 1)
        alpha = -coeffs[0]
        
        dist = np.min(np.abs(t - RIEMANN_ZEROS[:14]))
        near_zero = dist < 0.5
        marker = ""
        if near_zero:
            zi = np.argmin(np.abs(t - RIEMANN_ZEROS[:14]))
            marker = f"z{zi+1}"
            zero_hits += 1
        elif rank < 20:
            spurious_hits.append((t, cs, d2000, alpha))
        
        if rank < 40 or near_zero:
            print(f"{rank:5d} | {t:10.4f} | {cs:8.4f} | {op_diag[idx]:8.6f} | {d2000:10.6f} | {alpha:6.3f} | {marker:>12s}")
    
    print(f"\n--- Zero hits in top 40: {zero_hits}/{len(RIEMANN_ZEROS)}")
    print(f"\n--- Spurious points check ---")
    for t_s in [9.655, 35.13]:
        idx = np.argmin(np.abs(t_vals - t_s))
        t = t_vals[idx]
        cs = cos_sim[idx]
        d2000 = abs_D[-1, idx]
        v = abs_D[:, idx]
        logN = np.log(N_LIST[-3:])
        logD = np.log(np.maximum(v[-3:], 1e-30))
        coeffs = np.polyfit(logN, logD, 1)
        alpha = -coeffs[0]
        print(f"  t={t_s:.3f} (grid {t:.3f}): cos θ={cs:.4f}, |Δ|@2000={d2000:.6f}, α={alpha:.3f}")
    
    # What do these spurious points look like?
    print(f"\n--- |Δ| across N for spurious vs true ---")
    for t_s, label in [(9.655, "SPURIOUS"), (35.13, "SPURIOUS"), (40.9187, "z7 (true)"), (43.3271, "z8 (true)")]:
        idx = np.argmin(np.abs(t_vals - t_s))
        vals = [abs_D[i, idx] for i in range(len(N_LIST))]
        print(f"  {label} t={t_s:.3f}: |Δ| = {[f'{v:.4f}' for v in vals]}")
    
    # Print full table of zeros
    print(f"\n--- All first 11 zeros ---")
    for z in RIEMANN_ZEROS[:11]:
        idx = np.argmin(np.abs(t_vals - z))
        t = t_vals[idx]
        cs = cos_sim[idx]
        d2000 = abs_D[-1, idx]
        v = abs_D[:, idx]
        logN = np.log(N_LIST[-3:])
        logD = np.log(np.maximum(v[-3:], 1e-30))
        coeffs = np.polyfit(logN, logD, 1)
        alpha = -coeffs[0]
        print(f"  z={z:8.4f} (grid t={t:.4f}, Δt={abs(t-z):.4f}): cos θ={cs:.4f}, |Δ|={d2000:.6f}, α={alpha:.3f}")
    
    # ── Save ──
    results = {
        "parameters": {"N_list": N_LIST, "t_range": [T_MIN, T_MAX], "n_t_points": N_T_POINTS},
        "method": "cosine_similarity_with_N^{-0.5}_template",
        "top_hits": [
            {"rank": rank, "t": float(t_vals[idx]), "cos_sim": float(cos_sim[idx]),
             "abs_delta_2000": float(abs_D[-1, idx])}
            for rank, idx in enumerate(sorted_idx[:30])
        ]
    }
    out_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(out_dir, "template_matching_results.json"), "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved.")

if __name__ == "__main__":
    main()