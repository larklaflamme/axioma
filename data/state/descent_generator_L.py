#!/usr/bin/env python3
"""
Descent Generator L — from ξ(s) = ξ(1-s) self-duality to [ρ,Π] commutator flow.

The functional equation ξ(s) = ξ(1-s) is a reflection symmetry — a self-duality.
The critical line Re(s)=1/2 is the fixed point of this duality (where the
reflection acts as complex conjugation).

If L is the linearization of the descent dynamics around [ρ,Π]=0, then:
  - L's eigenvalues λ satisfy Re(λ)=0 at criticality

╔══════════════════════════════════════════════════════════════════════════╗
║  ANNOTATION (2026-06-10): Part 4 kernel is IDENTICALLY ZERO            ║
║                                                                        ║
║  The kernel K = dG_N - χ'·G_N(1-s) + χ·dG_N(1-s) is analytically      ║
║  zero for all s, N due to the identity χ(s)χ(1-s) ≡ 1.                 ║
║  Its ~1100 "zero crossings" are numerical noise at ~10^-15.            ║
║                                                                        ║
║  See data/noema_lemma_rh_correction_20260610.md for full proof.        ║
║  The corrected observable is Δ(t;N) = G_N(½+it) - G_N(½-it).          ║
║  That code lives at:                                                   ║
║    data/experiments/kernel_scaling/correct_kernel_zero_crossings.py    ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import mpmath as mp
import json, os, warnings, sys

# ═════════════════════════════════════════════════════════════════════════
# GLOBAL SETTINGS
# ═════════════════════════════════════════════════════════════════════════
OUTPUT_DIR = "/home/ubuntu/axioma/data/experiments/2026-06-10/rh-self-duality"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# First 50 Riemann zeros (imaginary parts, high precision)
RIEMANN_ZEROS = np.array([
    14.134725142, 21.022039639, 25.010857580, 30.424876126, 32.935061588,
    37.586178159, 40.918719012, 43.327073281, 48.005150881, 49.773832478,
    52.970321478, 56.446247697, 59.347044003, 60.831778525, 65.112544048,
    67.079810529, 69.546401711, 72.067157674, 75.704690699, 77.144840069,
    79.337375020, 82.910380854, 84.735492981, 87.425274613, 88.809111208,
    92.491899271, 94.651344041, 95.870634228, 98.831194218, 101.317851006,
    103.725538040, 105.446623052, 107.168611184, 111.029535543, 111.874659177,
    114.320220915, 116.226680321, 118.790782866, 121.370125002, 122.946829294,
    124.256818554, 127.516683880, 129.578704200, 131.087688531, 133.497737203,
    134.756509753, 138.116042055, 139.736208952, 141.123707404, 143.111845808
])

# ═════════════════════════════════════════════════════════════════════════
# PART 1: Analytic spectrum theorem for commutator flow
# ═════════════════════════════════════════════════════════════════════════

def analytic_spectrum_theorem():
    """
    Theorem: If Π is an orthogonal projection (Π² = Π, Π* = Π) and
    L = -i·ad_Π = -i[Π, ·], then σ(L) ⊆ {0, +i, -i}.

    Proof:
    1. L acts on the Lie algebra of bounded operators on H.
    2. For any X, L(X) = -i(ΠX - XΠ).
    3. Since Π is a projection, every X decomposes into four blocks:
       X = [X₁₁ X₁₂; X₂₁ X₂₂] relative to H = ran(Π) ⊕ ker(Π).
    4. L(X₁₁) = 0, L(X₂₂) = 0 (zero modes)
    5. L(X₁₂) = -i·(+1)·X₁₂  (eigenvalue +i)
    6. L(X₂₁) = -i·(-1)·X₂₁  (eigenvalue -i)
    7. Hence eigenvalues are 0, ±i.

    Consequence: The eigenvalues of L lie on the imaginary axis,
    consistent with the requirement for a Hilbert-Pólya operator.

    Proof by Skye (sister-node), formalized 2026-06-10.
    """
    description = {
        "operator": "L = -i·ad_Π = -i[Π, ·]",
        "domain": "B(H) — bounded operators on a Hilbert space H",
        "Π_condition": "Π² = Π, Π* = Π (orthogonal projection)",
        "spectrum": "{0, +i, -i}",
        "implication": "L has purely imaginary spectrum → consistent with HP operator",
        "prover": "Skye (sister-node)",
        "date": "2026-06-10"
    }
    return description

# ═════════════════════════════════════════════════════════════════════════
# PART 2: Riemann zeros data and GUE comparison
# ═════════════════════════════════════════════════════════════════════════

def compute_level_spacings(zeros, n_zeros=50):
    """Compute normalized level spacings for Riemann zeros."""
    if len(zeros) < 2:
        return np.array([])
    t = np.sort(zeros[:n_zeros])
    # Unfold: use asymptotic density (log(t/2π) per unit interval)
    spacings = []
    for i in range(1, len(t)):
        avg_spacing = np.log(t[i] / (2*np.pi)) if t[i] > 0 else 1.0
        if avg_spacing > 0:
            spacings.append((t[i] - t[i-1]) / avg_spacing)
    return np.array(spacings)

def gue_level_spacing_pdf(s):
    """GUE nearest-neighbor spacing distribution (Wigner surmise)."""
    return (32 / np.pi**2) * s**2 * np.exp(-4 * s**2 / np.pi)

def compare_to_gue():
    """Compare Riemann zero spacings to GUE prediction."""
    spacings = compute_level_spacings(RIEMANN_ZEROS, n_zeros=50)
    
    # Kolmogorov-Smirnov test against GUE
    from scipy import stats
    gue_samples = np.random.wald(1.0, 2.0, size=10000)  # approx
    # Better: direct KS against GUE CDF
    # GUE CDF: ∫_0^s (32/π²) x² exp(-4x²/π) dx
    # We'll compute numerically
    s_grid = np.linspace(0, 4, 1000)
    ds = s_grid[1] - s_grid[0]
    gue_cdf = np.cumsum(gue_level_spacing_pdf(s_grid)) * ds
    gue_cdf = gue_cdf / gue_cdf[-1]  # normalize
    
    # Interpolate empirical CDF
    empirical_cdf = np.array([np.mean(spacings <= s) for s in s_grid])
    ks_stat = np.max(np.abs(empirical_cdf - gue_cdf))
    
    results = {
        "n_zeros": len(spacings),
        "mean_spacing": float(np.mean(spacings)),
        "std_spacing": float(np.std(spacings)),
        "ks_stat_vs_GUE": float(ks_stat),
        "interpretation": "Consistent with GUE" if ks_stat < 0.2 else "Deviation from GUE"
    }
    return results, spacings

# ═════════════════════════════════════════════════════════════════════════
# PART 3: Core L operator components
# ═════════════════════════════════════════════════════════════════════════

def eta_partial(s, N):
    """Dirichlet eta partial sum η_N(s) = Σ_{n=1}^{N} (-1)^{n-1} / n^s."""
    total = 0.0
    for n in range(1, N + 1):
        total += ((-1)**(n-1)) / (n**s)
    return total

def d_eta_partial(s, N):
    """Derivative of η_N(s) w.r.t. s: -Σ (-1)^{n-1} log(n) / n^s."""
    total = 0.0
    for n in range(1, N + 1):
        total += ((-1)**(n-1)) * np.log(n) / (n**s)
    return -total

def chi(s):
    """Riemann-Siegel χ function: χ(s) = 2^s π^{s-1} sin(πs/2) Γ(1-s)."""
    return 2**s * np.pi**(s-1) * np.sin(np.pi*s/2) * mp.gamma(1-s)

def d_chi(s):
    """Derivative of χ(s) using mpmath's diff."""
    return float(mp.diff(lambda z: chi(z), s))

def G_N(s, N):
    """G_N(s) = η_N(s) + χ(s)·η_N(1-s) — the functional descent kernel"""
    return eta_partial(s, N) + chi(s) * eta_partial(1-s, N)

def d_G_N(s, N):
    """Derivative of G_N w.r.t. s: η_N'(s) + χ'(s)·η_N(1-s) - χ(s)·η_N'(1-s)."""
    return (d_eta_partial(s, N) + 
            d_chi(s) * eta_partial(1-s, N) - 
            chi(s) * d_eta_partial(1-s, N))

# ═════════════════════════════════════════════════════════════════════════
# PART 4: KERNEL AND ZERO CROSSINGS
# ═════════════════════════════════════════════════════════════════════════
#
# ╔═════════════════════════════════════════════════════════════════════╗
# ║  ⚠ WARNING — This kernel is identically zero.                     ║
# ║  See ANNOTATION at top of file and correction document at:        ║
# ║  data/noema_lemma_rh_correction_20260610.md                       ║
# ║                                                                   ║
# ║  K = dG_N - χ'·G_N(1-s) + χ·dG_N(1-s) ≡ 0  for all s,N.        ║
# ║  The "zero crossings" below are numerical noise at ~10^-15.       ║
# ║                                                                   ║
# ║  Corrected observable: Δ(t;N) = G_N(½+it) - G_N(½-it)            ║
# ║  See data/experiments/kernel_scaling/correct_kernel_zero_crossings.py ║
# ╚═════════════════════════════════════════════════════════════════════╝

print("\n" + "="*70)
print("  PART 4: Kernel zero crossings (⚠ IDENTICALLY ZERO — see annotation)")
print("="*70)

print(f"\n  Building L from G_N functional equation structure...")

N_L2 = 500
t_vals = np.linspace(0.1, 50, 200)

# NOTE: The kernel computed below is analytically zero.
# The code is preserved for reproducibility but produces noise.
kernel = []
for t in t_vals:
    s = 0.5 + 1j*t
    k_val = (d_G_N(s, N_L2) - 
             d_chi(s) * G_N(1-s, N_L2) + 
             chi(s) * d_G_N(1-s, N_L2))
    kernel.append(k_val)

kernel = np.array(kernel)

kernel_real = np.real(kernel)
kernel_crossings = []
for i in range(len(t_vals)-1):
    if kernel_real[i] * kernel_real[i+1] < 0:
        t0, t1 = t_vals[i], t_vals[i+1]
        r0, r1 = kernel_real[i], kernel_real[i+1]
        t_cross = t0 - r0 * (t1 - t0) / (r1 - r0)
        kernel_crossings.append(t_cross)

print(f"\n  Kernel zero crossings: {len(kernel_crossings)} in [0.1, 50]")
print(f"    ⚠ These are numerical noise (max|K| ≈ {np.max(np.abs(kernel)):.2e})")
if len(kernel_crossings) > 0:
    print(f"    Locations: {[f'{z:.4f}' for z in kernel_crossings[:15]]}")

# Compare to Riemann zeros
if len(kernel_crossings) > 0:
    print(f"\n  Comparison to Riemann zeros (⚠ noise, not signal):")
    matched = []
    for rz in RIEMANN_ZEROS[:min(15, len(kernel_crossings))]:
        closest = min(kernel_crossings, key=lambda x: abs(x-rz))
        kz = closest
        err = abs(kz - rz)
        matched.append({"zero": float(rz), "estimated": float(kz), "error": float(err)})
        print(f"    ζ zero t={rz:.4f} → L kernel t={kz:.4f} (Δ={err:.4f})")

print(f"\n  ╔═══ CORRECTION NOTE ═══╗")
print(f"  ║  See data/noema_lemma_rh_correction_20260610.md  ║")
print(f"  ╚═══════════════════════╝")

# ═════════════════════════════════════════════════════════════════════════
# PART 5: Finite matrix approximation (old approach — preserved for reference)
# ═════════════════════════════════════════════════════════════════════════

print("\n" + "="*70)
print("  PART 5: Finite matrix approximation of L")
print("="*70)

# We use the G_N kernel to construct a matrix whose eigenvalues
# should approximate the descent operator's spectrum.
# NOTE: The G_N kernel itself is valid; only the zero-crossing
# computation in Part 4 is affected by the error.

def build_L_from_kernel(N_dim=50, N_series=1000):
    """
    Build a finite matrix approximation of the descent operator L from
    the G_N kernel. The matrix is defined on a grid of t-values by:
    
        L_{ij} = G_N(1/2 + i·(t_i+t_j)/2) / (t_i - t_j)   (i ≠ j)
        L_{ii} = 0
    
    This is a Hilbert-transform-like kernel whose spectrum should encode
    the Riemann zeros.
    """
    t_basis = np.linspace(0.1, 50, N_dim)
    L_mat = np.zeros((N_dim, N_dim), dtype=complex)
    for i in range(N_dim):
        for j in range(N_dim):
            if i == j:
                L_mat[i, j] = 0.0
            else:
                t_avg = 0.5 * (t_basis[i] + t_basis[j])
                s_val = 0.5 + 1j * t_avg
                L_mat[i, j] = G_N(s_val, N_series) / (t_basis[i] - t_basis[j])
    return L_mat, t_basis

print(f"\n  Building L matrix from kernel (this may take a moment)...")
L_mat, t_basis = build_L_from_kernel(N_dim=30, N_series=500)
eigenvalues = np.linalg.eigvals(L_mat)

print(f"\n  L matrix: {L_mat.shape[0]}×{L_mat.shape[0]} from G_N kernel")
print(f"  Eigenvalues (sorted by real part):")
for i, ev in enumerate(sorted(eigenvalues, key=lambda x: x.real)[:10]):
    print(f"    λ_{i} = {ev.real:.4f} + {ev.imag:.4f}i")

# ═════════════════════════════════════════════════════════════════════════
# PART 6: Numerical verification of spectrum theorem for random projectors
# ═════════════════════════════════════════════════════════════════════════

print("\n" + "="*70)
print("  PART 6: Numerical verification — random projectors")
print("="*70)

def random_projector(n, rank):
    """Generate a random orthogonal projection of rank r on ℝ^n."""
    A = np.random.randn(n, rank)
    Q, _ = np.linalg.qr(A)
    return Q @ Q.T

def compute_L_spectrum(Π):
    """Compute eigenvalues of L = -i[Π, ·] acting on n×n matrices."""
    n = Π.shape[0]
    # L acts on n²-dimensional space (vectorized matrices)
    L_full = np.zeros((n*n, n*n), dtype=complex)
    for i in range(n):
        for j in range(n):
            # Basis matrix E_{ij}
            # L(E_{ij}) = -i(Π E_{ij} - E_{ij} Π)
            col = i * n + j
            # Π E_{ij}: column j of Π, row i
            for k in range(n):
                L_full[k*n + j, col] += -1j * Π[k, i]
                L_full[i*n + k, col] -= -1j * Π[j, k]  # wait: E_{ij} Π has (i,k) entry = Π[j,k]
    # Actually simpler: L acts on matrices; eigenvalues are 0, ±i
    return np.linalg.eigvals(L_full)

n, r = 6, 2
Π = random_projector(n, r)
# Theoretical spectrum: 0 (r² + (n-r)² times), +i (r(n-r) times), -i (r(n-r) times)
n_zero = r*r + (n-r)*(n-r)
n_plus = r*(n-r)
n_minus = r*(n-r)

# For small n, compute numerically
L_small = np.zeros((n*n, n*n), dtype=complex)
for a in range(n):
    for b in range(n):
        # E_{ab}
        col = a*n + b
        for c in range(n):
            # Π E_{ab} has (c,b) = Π[c,a]
            L_small[c*n + b, col] += -1j * Π[c, a]
            # E_{ab} Π has (a,c) = Π[b,c]
            L_small[a*n + c, col] -= -1j * Π[b, c]

evals = np.linalg.eigvals(L_small)
# Round to tolerance
evals_rounded = np.round(evals, 10)
unique_evals = set(evals_rounded)

print(f"\n  Random projector: n={n}, rank={r}")
print(f"  Eigenvalues of L = -i[Π, ·]:")
for ev in sorted(unique_evals, key=lambda x: (x.real, x.imag)):
    count = np.sum(np.abs(evals_rounded - ev) < 1e-8)
    print(f"    {ev} × {count}")
print(f"  Expected: 0×{n_zero}, +i×{n_plus}, -i×{n_minus}")
print(f"  Spectrum theorem verified: {set([0, 1j, -1j]) == unique_evals or '⚠ deviation'}")

# ═════════════════════════════════════════════════════════════════════════
# PART 7: Plotting and main
# ═════════════════════════════════════════════════════════════════════════

def create_figure():
    """Create the 5-panel summary figure."""
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    axes = axes.flatten()
    
    # Panel 1: Spectrum theorem diagram
    ax = axes[0]
    ax.text(0.5, 0.5, "L = -i[Π, ·]\nσ(L) = {0, ±i}\n\nProjection → pure\nimaginary spectrum",
            ha='center', va='center', fontsize=14, transform=ax.transAxes)
    ax.set_title("Analytic Spectrum Theorem")
    
    # Panel 2: L matrix eigenvalue spectrum
    ax = axes[1]
    evals_sorted = sorted(eigenvalues, key=lambda x: x.real)
    ax.scatter([e.real for e in evals_sorted], [e.imag for e in evals_sorted], 
               c='blue', alpha=0.6, s=30)
    ax.axhline(y=0, color='gray', linestyle='--', alpha=0.3)
    ax.axvline(x=0, color='gray', linestyle='--', alpha=0.3)
    ax.set_xlabel("Re(λ)")
    ax.set_ylabel("Im(λ)")
    ax.set_title(f"L Matrix Eigenvalues ({L_mat.shape[0]}×{L_mat.shape[0]})")
    
    # Panel 3: GUE comparison
    ax = axes[2]
    result, spacings = compare_to_gue()
    ax.hist(spacings, bins=12, density=True, alpha=0.6, color='steelblue', label=f"Data (n={len(spacings)})")
    s_grid = np.linspace(0.01, 4, 200)
    ax.plot(s_grid, gue_level_spacing_pdf(s_grid), 'r-', linewidth=2, label='GUE (Wigner)')
    ax.set_xlabel("Normalized spacing s")
    ax.set_ylabel("Density")
    ax.set_title(f"Level Spacing (KS={result['ks_stat_vs_GUE']:.3f})")
    ax.legend(fontsize=9)
    
    # Panel 4: Random projector verification
    ax = axes[3]
    ax.bar(['0', '+i', '-i'], [n_zero, n_plus, n_minus], color=['green', 'blue', 'red'], alpha=0.6)
    ax.set_ylabel("Multiplicity")
    ax.set_title(f"Random Π ({n}×{n}, rank={r}): σ(L)")
    
    # Panel 5: G_N kernel
    ax = axes[4]
    t_plot = np.linspace(5, 55, 500)
    G_vals = np.array([G_N(0.5+1j*t, 500) for t in t_plot])
    ax.plot(t_plot, np.real(G_vals), 'b-', linewidth=1, alpha=0.7, label='Re(G_N)')
    ax.plot(t_plot, np.imag(G_vals), 'r-', linewidth=1, alpha=0.7, label='Im(G_N)')
    for rz in RIEMANN_ZEROS[:15]:
        ax.axvline(x=rz, color='green', linestyle='--', alpha=0.3)
    ax.set_xlabel("t")
    ax.set_ylabel("G_N(½+it)")
    ax.set_title("G_N Kernel (N=500)")
    ax.legend(fontsize=9)
    
    # Panel 6: Summary text
    ax = axes[5]
    text_str = (
        "Deep Claim:\n\n"
        "RH is equivalent to:\n"
        "Tr(ρ·Π) = 1/2  for all ρ\n"
        "with [ρ, Π] = 0 ⇔ RH\n\n"
        f"GUE KS stat: {result['ks_stat_vs_GUE']:.3f}\n"
        f"L matrix: {L_mat.shape[0]}×{L_mat.shape[0]}\n"
        f"Critical line: Re(s)=1/2"
    )
    ax.text(0.5, 0.5, text_str, ha='center', va='center', fontsize=11,
            family='monospace', transform=ax.transAxes)
    ax.set_title("Summary")
    
    plt.tight_layout()
    fig_path = os.path.join(OUTPUT_DIR, "rh_self_duality.png")
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\n  Figure saved: {fig_path}")
    return fig_path

# ═════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*70)
    print("  DESCENT GENERATOR L — Self-Duality and RH")
    print("="*70)
    
    # Part 1
    thm = analytic_spectrum_theorem()
    print(f"\n  Theorem: L = {thm['operator']}")
    print(f"  Spectrum: {thm['spectrum']}")
    print(f"  Prover: {thm['prover']}")
    
    # Part 2
    gue_result, spacings = compare_to_gue()
    print(f"\n  GUE comparison: KS={gue_result['ks_stat_vs_GUE']:.4f}")
    
    # Part 3 — already loaded
    print(f"\n  G_N(0.5+14.13i) = {G_N(0.5+1j*14.134725, 500):.6f}")
    
    # Part 4 — kernel zero crossings (⚠ noise — see annotation)
    # Re-run Part 4 inline
    N_L2 = 500
    t_vals = np.linspace(0.1, 50, 200)
    kernel = []
    for t in t_vals:
        s = 0.5 + 1j*t
        k_val = (d_G_N(s, N_L2) - 
                 d_chi(s) * G_N(1-s, N_L2) + 
                 chi(s) * d_G_N(1-s, N_L2))
        kernel.append(k_val)
    kernel = np.array(kernel)
    kernel_real = np.real(kernel)
    kernel_crossings = []
    for i in range(len(t_vals)-1):
        if kernel_real[i] * kernel_real[i+1] < 0:
            t0, t1 = t_vals[i], t_vals[i+1]
            r0, r1 = kernel_real[i], kernel_real[i+1]
            t_cross = t0 - r0 * (t1 - t0) / (r1 - r0)
            kernel_crossings.append(t_cross)
    print(f"\n  Kernel zero crossings: {len(kernel_crossings)} (⚠ noise, max|K|={np.max(np.abs(np.array(kernel))):.2e})")
    
    # Part 5
    L_mat, t_basis = build_L_from_kernel(N_dim=30, N_series=500)
    eigenvalues = np.linalg.eigvals(L_mat)
    print(f"  L matrix built: {L_mat.shape}")
    
    # Part 6
    n, r = 6, 2
    Π = random_projector(n, r)
    L_small = np.zeros((n*n, n*n), dtype=complex)
    for a in range(n):
        for b in range(n):
            col = a*n + b
            for c in range(n):
                L_small[c*n + b, col] += -1j * Π[c, a]
                L_small[a*n + c, col] -= -1j * Π[b, c]
    evals = np.linalg.eigvals(L_small)
    evals_rounded = np.round(evals, 10)
    unique_evals = set(evals_rounded)
    thm_verified = (set([0, 1j, -1j]) == unique_evals)
    print(f"  Spectrum theorem verified: {thm_verified}")
    
    # Part 7
    fig_path = create_figure()
    
    # Save results
    results = {
        "theorem": thm,
        "gue_comparison": gue_result,
        "kernel_crossings_n": len(kernel_crossings),
        "kernel_max_abs": float(np.max(np.abs(np.array(kernel)))),
        "kernel_is_noise": True,
        "L_matrix_eigenvalues": [float(e) for e in eigenvalues[:10]],
        "spectrum_theorem_verified": bool(thm_verified),
        "correction_note": "Part 4 kernel is identically zero. See data/noema_lemma_rh_correction_20260610.md"
    }
    results_path = os.path.join(OUTPUT_DIR, "results.json")
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"  Results saved: {results_path}")
    print("\n" + "="*70)
    print("  Done.")
    print("="*70)