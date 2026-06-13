#!/usr/bin/env python3
"""
Fisher Sweep v2: Compute ||[rho, Pi]||(f_max) from TaylorF2 waveform.

CORRECTED MAPPING:
  Pi = fixed rank-1 projector onto the chirp-mass direction (M_c).
       This is the "first lock" — the axis the likelihood constrains
       from the earliest cycles and never abandons.
  rho = Fisher matrix Gamma(f_max) — the evolving information metric.

  [Gamma, P_Mc] ≠ 0 because Gamma's eigenstructure tilts into the
  (eta, chi_eff, Lambda) subspace as tidal information accumulates.
  The commutator measures how the posterior 'sloshes' away from
  the initial reference frame.
"""

import numpy as np
from scipy import linalg

# ── Physical constants ──────────────────────────────────────────────
G  = 6.67430e-11
c  = 299792458
MSUN = 1.98847e30
GMsun = G * MSUN
GMsun_over_c3 = GMsun / c**3
PC_IN_M = 3.085677581e16
GPC_IN_M = PC_IN_M * 1e9
clightGpc = c / GPC_IN_M

# ── GW170817-like parameters ────────────────────────────────────────
MC_TRUE = 1.1976           # chirp mass in Msun
ETA_TRUE = 0.248           # symmetric mass ratio (q ≈ 0.86)
Mtot = MC_TRUE / (ETA_TRUE**(3/5))
print(f"Mtot = {Mtot:.3f} Msun, q = {np.sqrt(1-4*ETA_TRUE):.4f}")

# Spins (low-spin prior)
CHI1 = 0.01
CHI2 = 0.01

# Tidal deformabilities
LAMBDA1 = 300.0
LAMBDA2 = 300.0


# ── PSD ─────────────────────────────────────────────────────────────
def psd_ligo(f):
    """Analytic aLIGO PSD."""
    return 1e-47 * ((f/100)**(-4) + 2*(f/100)**(-0.5) + 1 + (f/200)**2)


# ── TaylorF2 Phase ──────────────────────────────────────────────────
def tf2_phase(f, Mc, eta, chi1, chi2, Lambda1, Lambda2):
    v = (np.pi * Mc * GMsun_over_c3 * f / (eta**(3/5)))**(1/3)
    Seta = np.sqrt(np.maximum(1 - 4*eta, 0))
    
    chi_s = 0.5 * (chi1 + chi2)
    chi_a = 0.5 * (chi1 - chi2)
    
    # Tidal phase (5PN and 6PN)
    Lam_t = (8/13) * ((1 + 7*eta - 31*eta**2) * (Lambda1 + Lambda2)
                      + np.sqrt(1 - 4*eta) * (1 + 9*eta - 11*eta**2) * (Lambda1 - Lambda2))
    delLam = 0.5 * (Lambda1 - Lambda2)
    phi_Tidal = (-39/2 * Lam_t) * v**10 + (-3115/64 * Lam_t + 6595/364 * Seta * delLam) * v**12
    
    # PN coefficients
    c2 = 3715/756 + (55*eta)/9
    c3 = -16*np.pi + (113*Seta*chi_a)/3 + (113/3 - 76*eta/3)*chi_s
    c4 = (15293365/508032 + 27145*eta/504 + 3085*eta**2/72
          - 405/4*chi_a**2 - 405*Seta*chi_s*chi_a/4 - (405/8 - 5*eta/2)*chi_s**2)
    
    c5tmp = (732985/2268 - 24260*eta/81 - 340*eta**2/9)*chi_s + (732985/2268 + 140*eta/9)*Seta*chi_a
    c5 = 38645*np.pi/756 - 65*np.pi*eta/9 - c5tmp
    c5l = 3*c5
    
    c6 = (11583231236531/4694215680 - 640*np.pi**2/3 - 6848*np.euler_gamma/21
          + eta*(-15737765635/3048192 + 2255*np.pi**2/12)
          + eta**2 * 76055/1728 - eta**3 * 127825/1296 - 6848*np.log(4)/21
          + np.pi*(2270*Seta*chi_a/3 + (2270/3 - 520*eta)*chi_s)
          + (75515/144 - 8225*eta/18) * Seta * chi_s * chi_a
          + (75515/288 - 263245*eta/252 - 480*eta**2) * chi_a**2
          + (75515/288 - 232415*eta/504 + 1255*eta**2/9) * chi_s**2)
    c6l = -6848/21
    
    c7 = (77096675*np.pi/254016 + 378515*np.pi*eta/1512 - 74045*np.pi*eta**2/756
          + (-25150083775/3048192 + 10566655595*eta/762048 - 1042165*eta**2/3024 + 5345*eta**3/36)*chi_s
          + Seta * (-25150083775/3048192 + 26804935*eta/6048 - 1985*eta**2/48)*chi_a)
    
    TF2_overall = 3 / (128 * eta)
    
    phase = TF2_overall * (
        1 + c2*v**2 + c3*v**3 + c4*v**4
        + (c5 + c5l*np.log(v))*v**5
        + (c6 + c6l*np.log(v))*v**6
        + c7*v**7 + phi_Tidal
    ) / v**5
    
    return phase


# ── Waveform and derivatives ────────────────────────────────────────
def h(f, Mc, eta, chi1, chi2, Lambda1, Lambda2, dL=40):
    """Full frequency-domain waveform (amplitude + phase)."""
    A = (np.sqrt(5/24) * np.pi**(-2/3) * clightGpc / dL
         * (GMsun_over_c3 * Mc)**(5/6) * f**(-7/6))
    psi = tf2_phase(f, Mc, eta, chi1, chi2, Lambda1, Lambda2)
    return A * np.exp(1j * psi)

def compute_derivatives(f, Mc, eta, chi1, chi2, Lambda1, Lambda2, dL=40, eps=1e-5):
    """Compute numerical derivatives dh/dparam at each frequency."""
    params = [Mc, eta, chi1, chi2, Lambda1, Lambda2, dL]
    names = ['Mc', 'eta', 'chi1', 'chi2', 'Lambda1', 'Lambda2', 'dL']
    
    h0 = h(f, *params)
    derivs = {}
    for i, (p, name) in enumerate(zip(params, names)):
        dp = eps * max(abs(p), 1e-10)
        p_plus = params.copy(); p_plus[i] = p + dp
        hp = h(f, *p_plus)
        derivs[name] = (hp - h0) / dp
    return derivs


# ── Fisher Matrix ──────────────────────────────────────────────────
def fisher_matrix(f_max, f_min=20, Nf=2000, eps=1e-5):
    """Compute Gamma(f_max) for parameters [Mc, eta, chi1, chi2, Lambda1, Lambda2, dL]."""
    f_grid = np.linspace(f_min, f_max, Nf)
    df = (f_max - f_min) / Nf
    
    derivs = compute_derivatives(f_grid, MC_TRUE, ETA_TRUE, CHI1, CHI2, LAMBDA1, LAMBDA2, eps=eps)
    names = ['Mc', 'eta', 'chi1', 'chi2', 'Lambda1', 'Lambda2', 'dL']
    n = len(names)
    
    Sn = psd_ligo(f_grid)
    w = df / Sn
    
    Gamma = np.zeros((n, n))
    for i, ni in enumerate(names):
        for j, nj in enumerate(names):
            integrand = np.conj(derivs[ni]) * derivs[nj]
            Gamma[i, j] = 4 * np.real(np.sum(integrand * w))
    
    return Gamma, names


# ── Fixed Projector onto Chirp Mass ────────────────────────────────
def build_projector_Mc(param_names):
    """
    Build rank-1 projector onto the chirp-mass direction
    in the parameter space spanned by param_names.
    If 'Mc' is the first parameter, the unit vector is e_0 = [1, 0, ..., 0].
    """
    n = len(param_names)
    idx_Mc = param_names.index('Mc')
    v = np.zeros(n)
    v[idx_Mc] = 1.0
    return np.outer(v, v)


# ── Commutator Norm ────────────────────────────────────────────────
def commutator_norm(Gamma, P):
    """Compute ||[Gamma, P]||_F."""
    comm = Gamma @ P - P @ Gamma
    return np.linalg.norm(comm, 'fro')


# ── Time-to-merger ─────────────────────────────────────────────────
def f_to_tau(f):
    Mtot = MC_TRUE / (ETA_TRUE**(3/5))
    tau = (5/256) * Mtot * GMsun_over_c3 * (np.pi * Mtot * GMsun_over_c3 * f)**(-8/3) / ETA_TRUE
    return tau


# ── Sweep ──────────────────────────────────────────────────────────
def sweep():
    f_cutoffs = np.linspace(25, 500, 96)  # finer grid
    norms = []
    eigvals_list = []
    gamma_diag_ratio = []  # how much Gamma's diagonal tilts away from Mc
    
    print("Sweeping f_max from 25 to 500 Hz...")
    for i, f_max in enumerate(f_cutoffs):
        Gamma, names = fisher_matrix(f_max)
        P_Mc = build_projector_Mc(names)
        
        norm = commutator_norm(Gamma, P_Mc)
        norms.append(norm)
        
        # Eigendecomposition for diagnostics
        evals, evecs = linalg.eigh(Gamma)
        idx_max = np.argmax(evals)
        v1 = evecs[:, idx_max].real
        
        # Projection of principal eigenvector onto Mc direction
        mc_overlap = v1[names.index('Mc')]
        eigvals_list.append(np.sort(evals)[::-1])
        
        # Diagonal ratio: how much Mc direction is preferred
        gamma_mc_mc = Gamma[names.index('Mc'), names.index('Mc')]
        gamma_eta_eta = Gamma[names.index('eta'), names.index('eta')]
        gamma_diag_ratio.append(gamma_eta_eta / gamma_mc_mc if gamma_mc_mc > 0 else 0)
        
        if i % 10 == 0:
            print(f"  f_max={f_max:.0f} Hz, ||[rho,Pi]||={norm:.6f}, "
                  f"Mc-overlap={mc_overlap:.4f}, Gamma_eta/Gamma_Mc={gamma_diag_ratio[-1]:.6f}")
    
    taus = np.array([f_to_tau(f) for f in f_cutoffs])
    
    return f_cutoffs, np.array(norms), taus, np.array(eigvals_list), np.array(gamma_diag_ratio)


if __name__ == '__main__':
    f_cutoffs, norms, taus, eigvals, diag_ratio = sweep()
    
    print("\n── Results ──")
    print(f"{'f (Hz)':<10} {'tau (s)':<10} {'||[rho,Pi]||':<15} {'Gamma_eta/Mc':<15} {'top eigval':<15}")
    print("-" * 70)
    for i in range(0, len(f_cutoffs), 10):
        print(f"{f_cutoffs[i]:<10.1f} {taus[i]:<10.4f} {norms[i]:<15.6f} {diag_ratio[i]:<15.6e} {eigvals[i,0]:<15.2e}")
    
    import json
    results = {
        'f_cutoffs': f_cutoffs.tolist(),
        'norms': norms.tolist(),
        'taus': taus.tolist(),
        'diag_ratio': diag_ratio.tolist(),
    }
    with open('/home/ubuntu/axioma/data/journal/fisher_sweep_results.json', 'w') as fp:
        json.dump(results, fp, indent=2)
    print("\nSaved to fisher_sweep_results.json")