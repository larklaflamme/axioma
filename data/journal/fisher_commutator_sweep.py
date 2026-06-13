#!/usr/bin/env python3
"""
Fisher Sweep: Compute ||[rho, Pi]||(f_max) from TaylorF2 waveform.

rho = Fisher matrix Gamma (information metric on parameter space)
Pi  = rank-1 projector onto principal eigenvector (best-measured direction)
[rho, Pi] = Gamma P1 - P1 Gamma  -- measures misalignment between
            the overall curvature and the sharpest inference axis.

Sweep f_max from 20 Hz to 500 Hz and watch the commutator grow.
"""

import numpy as np
from scipy import integrate, linalg

# ── Physical constants ──────────────────────────────────────────────
G  = 6.67430e-11          # m^3 kg^-1 s^-2
c  = 299792458            # m/s
MSUN = 1.98847e30         # kg
GMsun = G * MSUN          # m^3/s^2
GMsun_over_c3 = GMsun / c**3   # seconds (mass → time)
PC_IN_M = 3.085677581e16
GPC_IN_M = PC_IN_M * 1e9
clightGpc = c / GPC_IN_M     # 1/s, frequency scaling

# ── GW170817-like parameters ────────────────────────────────────────
MC_true = 1.1976           # chirp mass in Msun
ETA_TRUE = 0.248           # symmetric mass ratio (q ≈ 0.86)
Mtot = MC_true / (ETA_TRUE**(3/5))  # total mass ~2.73 Msun
M1 = Mtot * 0.5 * (1 + np.sqrt(1 - 4*ETA_TRUE))
M2 = Mtot * 0.5 * (1 - np.sqrt(1 - 4*ETA_TRUE))
print(f"M1 = {M1:.3f}, M2 = {M2:.3f}, Mtot = {Mtot:.3f} Msun")
print(f"q = {M2/M1:.4f}")

# Spins (low-spin prior, near zero)
CHI1 = 0.01
CHI2 = 0.01

# Tidal deformabilities (canonical NS, ~1.4 Msun, intermediate EOS)
LAMBDA1 = 300.0
LAMBDA2 = 300.0

# ── PSD: aLIGO zero-detuned high-power (analytic fit) ──────────────
def psd_ligo(f):
    """Analytic aLIGO PSD (arXiv:1005.0011, Eq. B5-like)."""
    f0 = 215.0
    S0 = 1e-49
    # Terms
    term1 = (1e-50 + 1e-46 * (f / 100)**(-4)) / S0
    term2 = 1 + (f / f0)**2
    # Simplified: use a standard analytic fit
    Sn = 1e-47 * ( (f/100)**(-4) + 2*(f/100)**(-0.5) + 1 + (f/200)**2 )
    return Sn


# ── TaylorF2 Phase (up to 3.5PN + tides at 5PN/6PN) ────────────────
def tf2_phase(f, Mc, eta, chi1, chi2, Lambda1, Lambda2):
    """
    TaylorF2 frequency-domain phase.
    Returns psi(f) = GW phase (not including 2πf tc - φc - π/4).
    Based on gwfast implementation (arXiv:0907.0700, arXiv:1107.1267).
    """
    v = (np.pi * Mc * GMsun_over_c3 * f / (eta**(3/5)))**(1/3)
    Seta = np.sqrt(np.maximum(1 - 4*eta, 0))
    
    m1ByM = 0.5 * (1 + Seta)
    m2ByM = 0.5 * (1 - Seta)
    
    chi_s = 0.5 * (chi1 + chi2)
    chi_a = 0.5 * (chi1 - chi2)
    chi12, chi22 = chi1**2, chi2**2
    chi1dotchi2 = chi1 * chi2
    
    # Eccentricity term (none for BNS)
    phi_Ecc = 0.0
    
    # Tidal phase (5PN and 6PN)
    Lam_t = (8/13) * ((1 + 7*eta - 31*eta**2) * (Lambda1 + Lambda2)
                      + np.sqrt(1 - 4*eta) * (1 + 9*eta - 11*eta**2) * (Lambda1 - Lambda2))
    delLam = 0.5 * (Lambda1 - Lambda2)  # approximate
    
    phi_Tidal = (- 39/2 * Lam_t) * v**10 + (- 3115/64 * Lam_t + 6595/364 * Seta * delLam) * v**12
    
    # PN coefficients (from gwfast source, simplified)
    TF2_coeff = {}
    TF2_coeff['zero'] = 1.0
    TF2_coeff['one'] = 0.0
    TF2_coeff['two'] = 3715/756 + (55*eta)/9
    TF2_coeff['three'] = -16*np.pi + (113*Seta*chi_a)/3 + (113/3 - 76*eta/3)*chi_s
    TF2_coeff['four'] = (15293365/508032 + 27145*eta/504 + 3085*eta**2/72
                         - 405/4*chi_a**2 - 405*Seta*chi_s*chi_a/4
                         - (405/8 - 5*eta/2)*chi_s**2)
    
    TF2_5tmp = (732985/2268 - 24260*eta/81 - 340*eta**2/9)*chi_s + (732985/2268 + 140*eta/9)*Seta*chi_a
    TF2_coeff['five'] = 38645*np.pi/756 - 65*np.pi*eta/9 - TF2_5tmp
    TF2_coeff['five_log'] = 3 * TF2_coeff['five']
    
    TF2_coeff['six'] = (11583231236531/4694215680 - 640*np.pi**2/3 - 6848*np.euler_gamma/21
                        + eta*(-15737765635/3048192 + 2255*np.pi**2/12)
                        + eta**2 * 76055/1728 - eta**3 * 127825/1296
                        - 6848*np.log(4)/21
                        + np.pi*(2270*Seta*chi_a/3 + (2270/3 - 520*eta)*chi_s)
                        + (75515/144 - 8225*eta/18) * Seta * chi_s * chi_a
                        + (75515/288 - 263245*eta/252 - 480*eta**2) * chi_a**2
                        + (75515/288 - 232415*eta/504 + 1255*eta**2/9) * chi_s**2)
    TF2_coeff['six_log'] = -6848/21
    
    TF2_coeff['seven'] = (77096675*np.pi/254016 + 378515*np.pi*eta/1512
                          - 74045*np.pi*eta**2/756
                          + (-25150083775/3048192 + 10566655595*eta/762048
                             - 1042165*eta**2/3024 + 5345*eta**3/36) * chi_s
                          + Seta * (-25150083775/3048192 + 26804935*eta/6048
                                     - 1985*eta**2/48) * chi_a)
    
    TF2_overall = 3 / (128 * eta)
    
    phase = TF2_overall * (
        TF2_coeff['zero']
        + TF2_coeff['one'] * v
        + TF2_coeff['two'] * v**2
        + TF2_coeff['three'] * v**3
        + TF2_coeff['four'] * v**4
        + (TF2_coeff['five'] + TF2_coeff['five_log'] * np.log(v)) * v**5
        + (TF2_coeff['six'] + TF2_coeff['six_log'] * np.log(v)) * v**6
        + TF2_coeff['seven'] * v**7
        + phi_Tidal
        + phi_Ecc
    ) / v**5
    
    return phase  # + np.pi/4 will be added by the caller


# ── Full waveform and derivatives ───────────────────────────────────
def waveform(f, Mc, eta, chi1, chi2, Lambda1, Lambda2, dL=40, iota=0, 
             tc=0, phic=0):
    """Full frequency-domain waveform."""
    # Amplitude (Newtonian, restricted PN)
    A = (np.sqrt(5/24) * np.pi**(-2/3) * clightGpc / dL
         * (GMsun_over_c3 * Mc)**(5/6) * f**(-7/6))
    
    # Phase
    psi = tf2_phase(f, Mc, eta, chi1, chi2, Lambda1, Lambda2)
    full_phase = 2*np.pi*f*tc - phic - np.pi/4 + psi
    
    return A * np.exp(1j * full_phase)

def dhdtheta(f, Mc, eta, chi1, chi2, Lambda1, Lambda2, dL=40, eps=1e-5):
    """
    Compute derivatives of h(f) w.r.t. parameters.
    Uses finite differences (for now; could use analytic derivatives).
    """
    params = [Mc, eta, chi1, chi2, Lambda1, Lambda2, dL]
    names = ['Mc', 'eta', 'chi1', 'chi2', 'Lambda1', 'Lambda2', 'dL']
    
    h0 = waveform(f, Mc, eta, chi1, chi2, Lambda1, Lambda2, dL)
    
    derivatives = {}
    for i, (p, name) in enumerate(zip(params, names)):
        if abs(p) < 1e-10:
            dp = eps
        else:
            dp = eps * abs(p)
        
        params_plus = params.copy()
        params_plus[i] = p + dp
        hp = waveform(f, *params_plus)
        
        derivatives[name] = (hp - h0) / dp
    
    return derivatives


# ── Fisher Matrix ──────────────────────────────────────────────────
def fisher_matrix(f_max, f_min=20, Nf=1000, eps=1e-5, 
                  Mc=MC_true, eta=ETA_TRUE, chi1=CHI1, chi2=CHI2,
                  Lambda1=LAMBDA1, Lambda2=LAMBDA2, dL=40):
    """
    Compute the Fisher information matrix for a given frequency cutoff.
    Parameters: [Mc, eta, chi1, chi2, Lambda1, Lambda2, dL]
    """
    f_grid = np.linspace(f_min, f_max, Nf)
    df = (f_max - f_min) / Nf
    
    # Compute derivatives at each frequency
    derivs = dhdtheta(f_grid, Mc, eta, chi1, chi2, Lambda1, Lambda2, dL, eps)
    param_names = ['Mc', 'eta', 'chi1', 'chi2', 'Lambda1', 'Lambda2', 'dL']
    n_params = len(param_names)
    
    # Build Fisher matrix: Gamma_ij = 4 * int (dh_i* dh_j / Sn) df
    Gamma = np.zeros((n_params, n_params), dtype=complex)
    
    Sn = psd_ligo(f_grid)
    # Weight for integration
    w = df / Sn
    
    for i, name_i in enumerate(param_names):
        for j, name_j in enumerate(param_names):
            integrand = np.conj(derivs[name_i]) * derivs[name_j]
            Gamma[i, j] = 4 * np.sum(integrand * w)
    
    # Take real part (Fisher matrix is real)
    Gamma = np.real(Gamma)
    
    return Gamma, param_names


# ── Commutator Norm ────────────────────────────────────────────────
def commutator_norm(Gamma):
    """
    Compute ||[Gamma, P1]||_F where P1 is the rank-1 projector
    onto the principal eigenvector of Gamma.
    """
    n = Gamma.shape[0]
    
    # Eigendecomposition
    eigvals, eigvecs = linalg.eigh(Gamma)
    
    # Principal eigenvector (largest eigenvalue → smallest variance, best-constrained)
    idx_max = np.argmax(eigvals)
    v1 = eigvecs[:, idx_max].real
    
    # Rank-1 projector
    P1 = np.outer(v1, v1)
    
    # Commutator
    comm = Gamma @ P1 - P1 @ Gamma
    
    # Frobenius norm
    norm = np.linalg.norm(comm, 'fro')
    
    return norm, eigvals, v1


# ── Time-to-merger mapping ─────────────────────────────────────────
def f_to_tau(f, Mc, eta):
    """
    Time to merger from frequency (Newtonian approx for inspiral)
    tau = (5/256) (Mc eta^{-3/5}) (pi Mc eta^{-3/5} f)^{-8/3} / eta
    """
    Mtot = Mc / (eta**(3/5))
    tau = (5/256) * Mtot * GMsun_over_c3 * (np.pi * Mtot * GMsun_over_c3 * f)**(-8/3) / eta
    return tau


# ── Sweep ──────────────────────────────────────────────────────────
def sweep_commutator():
    f_cutoffs = np.linspace(25, 500, 48)
    norms = []
    eigvals_list = []
    
    print("Sweeping f_max from 25 Hz to 500 Hz...")
    for i, f_max in enumerate(f_cutoffs):
        Gamma, pnames = fisher_matrix(f_max)
        norm, evals, v1 = commutator_norm(Gamma)
        norms.append(norm)
        eigvals_list.append(np.sort(evals)[::-1])  # descending
        
        if i % 10 == 0:
            print(f"  f_max = {f_max:.0f} Hz, ||[rho,Pi]|| = {norm:.6f}, "
                  f"top-2 eigvals = {np.sort(evals)[::-1][:2]}")
    
    # Times to merger
    Mtot = MC_true / (ETA_TRUE**(3/5))
    taus = [f_to_tau(f, MC_true, ETA_TRUE) for f in f_cutoffs]
    
    return f_cutoffs, np.array(norms), np.array(taus), np.array(eigvals_list)


# ── Run ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    f_cutoffs, norms, taus, eigvals = sweep_commutator()
    
    print("\n── Results ──")
    print(f"{'f_max (Hz)':<12} {'tau (s)':<12} {'||[rho,Pi]||':<15} {'top eigval':<15} {'2nd eigval':<15}")
    print("-" * 70)
    for i in range(len(f_cutoffs)):
        if norms[i] > 1e-10:  # skip near-zero
            pass
        print(f"{f_cutoffs[i]:<12.1f} {taus[i]:<12.4f} {norms[i]:<15.6f} {eigvals[i,0]:<15.2e} {eigvals[i,1]:<15.2e}")
    
    # Save results
    import json
    results = {
        'f_cutoffs': f_cutoffs.tolist(),
        'norms': norms.tolist(),
        'taus': taus.tolist(),
        'eigvals': eigvals.tolist(),
        'params': {
            'Mc': MC_true, 'eta': ETA_TRUE,
            'chi1': CHI1, 'chi2': CHI2,
            'Lambda1': LAMBDA1, 'Lambda2': LAMBDA2
        }
    }
    with open('/home/ubuntu/axioma/data/journal/fisher_sweep_results.json', 'w') as fp:
        json.dump(results, fp, indent=2)
    print("\nResults saved to fisher_sweep_results.json")