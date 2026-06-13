"""Mellin Gram matrix test: G_N(t) = <θ_j, θ_k>_{x^{-1/2+it}}"""

import numpy as np
from scipy import integrate, linalg
import time
import sys

def G_entry(j, k, t, max_break=5000, epsabs=1e-10, epsrel=1e-10):
    bps = set()
    bps.add(1.0)
    for n in range(1, int(np.ceil(max_break / j)) + 1):
        bp = n * j
        if 1 < bp < max_break:
            bps.add(bp)
    for n in range(1, int(np.ceil(max_break / k)) + 1):
        bp = n * k
        if 1 < bp < max_break:
            bps.add(bp)
    bps.add(max_break)
    bps = sorted(bps)
    n_seg = len(bps) - 1
    if n_seg == 0:
        return 0.0 + 0.0j
    total = 0.0 + 0.0j
    for idx in range(n_seg):
        a = bps[idx]
        b = bps[idx + 1]
        if b - a < 1e-14:
            continue
        n_j = int(np.floor(a / j))
        n_k = int(np.floor(a / k))
        def integrand(u):
            return ((u/j - n_j) * (u/k - n_k)) * u**(-1.5 - 1j*t)
        res_re, _ = integrate.quad(lambda u: np.real(integrand(u)), a, b,
                                   epsabs=epsabs/n_seg, epsrel=epsrel, limit=200)
        res_im, _ = integrate.quad(lambda u: np.imag(integrand(u)), a, b,
                                   epsabs=epsabs/n_seg, epsrel=epsrel, limit=200)
        total += res_re + 1j*res_im
    U = max_break
    total += (1/4) * U**(-0.5 - 1j*t) / (0.5 + 1j*t)
    return total

def G_N(N, t, max_break=5000):
    G = np.zeros((N, N), dtype=complex)
    for j in range(1, N+1):
        for k in range(j, N+1):
            val = G_entry(j, k, t, max_break=max_break)
            G[j-1, k-1] = val
            G[k-1, j-1] = val
    return G

# Run tests
N_val = int(sys.argv[1]) if len(sys.argv) > 1 else 15

t_focus = [13.8, 14.0, 14.05, 14.08, 14.1, 14.12, 14.1347, 14.15, 14.2, 14.3, 14.5]
print(f"N={N_val} around first zero")
for t in t_focus:
    t0 = time.time()
    G = G_N(N_val, t, max_break=5000)
    U, s, Vh = np.linalg.svd(G)
    dt = time.time() - t0
    marker = " <<< ζ₁" if abs(t - 14.1347) < 0.01 else ""
    print(f"t={t:8.4f}  σ_min={s[-1]:10.6f}  σ[0]={s[0]:.4f}  cond={s[0]/s[-1]:.0f}  ({dt:.0f}s){marker}")

# Second scan at N=N_val with broader range
print(f"\nN={N_val} broader range")
t_broad = [13.0, 13.5, 14.5, 15.0, 21.022, 25.0, 30.0]
for t in t_broad:
    t0 = time.time()
    G = G_N(N_val, t, max_break=5000)
    U, s, Vh = np.linalg.svd(G)
    dt = time.time() - t0
    marker = " <<< ζ₂" if abs(t - 21.022) < 0.01 else ""
    print(f"t={t:8.4f}  σ_min={s[-1]:10.6f}  σ[0]={s[0]:.4f}  cond={s[0]/s[-1]:.0f}  ({dt:.0f}s){marker}")