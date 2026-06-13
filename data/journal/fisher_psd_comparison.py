#!/usr/bin/env python3
"""
Dual-PSD Fisher Sweep: Compare ZDHP vs Early aLIGO PSD
using the full TaylorF2 + tidal waveform.

Extends fisher_commutator_sweep_v2.py to run two complete
Fisher sweeps (one per PSD) and compare commutator integrals,
eigenvector tilts, and the predicted systematic offset Δθ_sys.
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

CHI1 = 0.01
CHI2 = 0.01
LAMBDA1 = 300.0
LAMBDA2 = 300.0


# ── PSD Models ──────────────────────────────────────────────────────
def psd_zdhp(f):
    """
    aLIGO zero-detuned high-power (design sensitivity).
    Analytic fit from arXiv:1005.0011, Eq. B5-like.
    """
    return 1e-47 * ((f/100)**(-4) + 2*(f/100)**(-0.5) + 1 + (f/200)**2)

def psd_early(f):
    """
    Early aLIGO (O1/O2 sensitivity).
    Noisier overall, proportionally worse at low frequencies.
    """
    S0 = 2.5e-47
    low = 10.0 * (f/100)**(-4)
    mid = 2.0 * (f/100)**(-0.5)
    high = 1.0 + (f/200)**2
    return S0 * (1.0 + low + mid + high) / (1.0 + 10.0 + 2.0 + 1.0 + (500/200)**2)


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
    A = (np.sqrt(5/24) * np.pi**(-2/3) * clightGpc / dL
         * (GMsun_over_c3 * Mc)**(5/6) * f**(-7/6))
    psi = tf2_phase(f, Mc, eta, chi1, chi2, Lambda1, Lambda2)
    return A * np.exp(1j * psi)

def compute_derivatives(f, Mc, eta, chi1, chi2, Lambda1, Lambda2, dL=40, eps=1e-5):
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
def fisher_matrix(f_max, psd_func, f_min=20, Nf=2000, eps=1e-5):
    f_grid = np.linspace(f_min, f_max, Nf)
    df = (f_max - f_min) / Nf
    
    derivs = compute_derivatives(f_grid, MC_TRUE, ETA_TRUE, CHI1, CHI2, LAMBDA1, LAMBDA2, eps=eps)
    names = ['Mc', 'eta', 'chi1', 'chi2', 'Lambda1', 'Lambda2', 'dL']
    n = len(names)
    
    Sn = psd_func(f_grid)
    w = df / Sn
    
    Gamma = np.zeros((n, n))
    for i, ni in enumerate(names):
        for j, nj in enumerate(names):
            integrand = np.conj(derivs[ni]) * derivs[nj]
            Gamma[i, j] = 4 * np.real(np.sum(integrand * w))
    
    return Gamma, names


# ── Fixed Projector onto Chirp Mass ────────────────────────────────
def build_projector_Mc(param_names):
    n = len(param_names)
    idx_Mc = param_names.index('Mc')
    v = np.zeros(n)
    v[idx_Mc] = 1.0
    return np.outer(v, v)


# ── Commutator Norm ────────────────────────────────────────────────
def commutator_norm(Gamma, P):
    comm = Gamma @ P - P @ Gamma
    return np.linalg.norm(comm, 'fro')


# ── Time-to-merger ─────────────────────────────────────────────────
def f_to_tau(f):
    Mtot = MC_TRUE / (ETA_TRUE**(3/5))
    tau = (5/256) * Mtot * GMsun_over_c3 * (np.pi * Mtot * GMsun_over_c3 * f)**(-8/3) / ETA_TRUE
    return tau


# ── Sweep ──────────────────────────────────────────────────────────
def sweep(psd_func, psd_label, f_cutoffs):
    """Run full Fisher sweep for a given PSD."""
    norms = []
    fracs = []
    eigvals_list = []
    v2_list = []
    
    print(f"\n{'='*60}")
    print(f"Sweep: {psd_label}")
    print(f"{'='*60}")
    
    P_Mc = None  # build once
    
    for i, f_max in enumerate(f_cutoffs):
        Gamma, names = fisher_matrix(f_max, psd_func)
        
        if P_Mc is None:
            P_Mc = build_projector_Mc(names)
        
        norm = commutator_norm(Gamma, P_Mc)
        gamma_norm = np.linalg.norm(Gamma, 'fro')
        frac = norm / gamma_norm if gamma_norm > 0 else 0.0
        norms.append(norm)
        fracs.append(frac)
        
        # Eigendecomposition
        evals, evecs = linalg.eigh(Gamma)
        idx_sort = np.argsort(evals)[::-1]
        evals = evals[idx_sort]
        evecs = evecs[:, idx_sort]
        eigvals_list.append(evals)
        
        # Second eigenvector (v2 = degeneracy direction)
        v2_list.append(evecs[:, 1].real)
        
        if i % 10 == 0 or i == len(f_cutoffs) - 1:
            print(f"  f_max={f_max:.0f} Hz, ||[Γ,Π]||={norm:.6f}, "
                  f"frac={frac:.6f}, λ₁={evals[0]:.2e}, λ₂={evals[1]:.2e}")
    
    return np.array(norms), np.array(fracs), np.array(eigvals_list), np.array(v2_list)


if __name__ == '__main__':
    f_cutoffs = np.linspace(22, 500, 48)
    taus = np.array([f_to_tau(f) for f in f_cutoffs])
    
    # ── Run ZDHP sweep ──
    norms_z, fracs_z, evals_z, v2_z = sweep(psd_zdhp, "ZDHP (design)", f_cutoffs)
    
    # ── Run Early aLIGO sweep ──
    norms_e, fracs_e, evals_e, v2_e = sweep(psd_early, "Early aLIGO (O1/O2)", f_cutoffs)
    
    # ── Commutator integrals ──
    total_comm_z = np.trapezoid(norms_z, f_cutoffs)
    total_comm_e = np.trapezoid(norms_e, f_cutoffs)
    
    print(f"\n{'='*60}")
    print("COMMUTATOR INTEGRALS")
    print(f"{'='*60}")
    print(f"  ZDHP:   {total_comm_z:.4e}")
    print(f"  Early:  {total_comm_e:.4e}")
    print(f"  Ratio:  {total_comm_e/total_comm_z:.4f}")
    
    # ── Systematic offset ──
    # Use the final second eigenvector from ZDHP as v⊥
    v2_final_z = v2_z[-1].real
    v2_final_e = v2_e[-1].real
    
    # Compute the angle between v⊥ vectors
    cos_angle = np.dot(v2_final_z, v2_final_e) / (np.linalg.norm(v2_final_z) * np.linalg.norm(v2_final_e))
    angle_deg = np.degrees(np.arccos(np.clip(cos_angle, -1, 1)))
    
    print(f"\n{'='*60}")
    print("EIGENVECTOR COMPARISON (500 Hz)")
    print(f"{'='*60}")
    print(f"\n  v₂ (ZDHP):  Mc={v2_final_z[0]:+.6f}, eta={v2_final_z[1]:+.6f}, "
          f"chi1={v2_final_z[2]:+.6f}, chi2={v2_final_z[3]:+.6f}, "
          f"Λ1={v2_final_z[4]:+.6f}, Λ2={v2_final_z[5]:+.6f}, dL={v2_final_z[6]:+.6f}")
    print(f"  v₂ (Early): Mc={v2_final_e[0]:+.6f}, eta={v2_final_e[1]:+.6f}, "
          f"chi1={v2_final_e[2]:+.6f}, chi2={v2_final_e[3]:+.6f}, "
          f"Λ1={v2_final_e[4]:+.6f}, Λ2={v2_final_e[5]:+.6f}, dL={v2_final_e[6]:+.6f}")
    print(f"\n  Angle between v₂ vectors: {angle_deg:.2f}°")
    
    # ── Δθ_sys prediction ──
    λ2_z = evals_z[-1, 1]  # second eigenvalue at 500 Hz for ZDHP
    λ2_e = evals_e[-1, 1]
    
    offset_mag_z = total_comm_z / (np.dot(v2_final_z, v2_final_z) * λ2_z)
    offset_mag_e = total_comm_e / (np.dot(v2_final_e, v2_final_e) * λ2_e)
    
    # Project onto the (eta, chi) subspace for comparison with Thea's result
    # Convert eta to q for easier interpretation
    v2_z_q = -8*np.sqrt(1-4*ETA_TRUE)/(1+np.sqrt(1-4*ETA_TRUE))**2  # approx ∂q/∂eta
    # Actually just report both
    
    print(f"\n{'='*60}")
    print("SYSTEMATIC OFFSET Δθ_sys")
    print(f"{'='*60}")
    print(f"\n  Δθ_sys magnitude (ZDHP):  {offset_mag_z:.6e}")
    print(f"  Δθ_sys magnitude (Early): {offset_mag_e:.6e}")
    print(f"  Ratio: {offset_mag_e/offset_mag_z:.4f}")
    
    print(f"\n  λ₂ (second eigenvalue, ZDHP):  {λ2_z:.4e}")
    print(f"  λ₂ (second eigenvalue, Early): {λ2_e:.4e}")
    
    # ── Results table ──
    print(f"\n{'='*60}")
    print("COMPARISON TABLE")
    print(f"{'='*60}")
    print(f"{'f (Hz)':<10} {'τ (s)':<10} {'Frac_Z':<10} {'Frac_E':<10} {'Ratio':<10}")
    print("-" * 50)
    for i in range(0, len(f_cutoffs), 6):
        print(f"{f_cutoffs[i]:<10.1f} {taus[i]:<10.4f} {fracs_z[i]:<10.6f} {fracs_e[i]:<10.6f} "
              f"{fracs_e[i]/fracs_z[i] if fracs_z[i] > 0 else 0:<10.4f}")
    
    # ── Save ──
    np.savez('/home/ubuntu/axioma/data/journal/fisher_psd_comparison_results.npz',
             f_cutoffs=f_cutoffs, taus=taus,
             norms_z=norms_z, fracs_z=fracs_z, evals_z=evals_z, v2_z=v2_z,
             norms_e=norms_e, fracs_e=fracs_e, evals_e=evals_e, v2_e=v2_e,
             total_comm_z=total_comm_z, total_comm_e=total_comm_e,
             offset_mag_z=offset_mag_z, offset_mag_e=offset_mag_e,
             λ2_z=λ2_z, λ2_e=λ2_e, angle_deg=angle_deg)
    print(f"\nSaved to fisher_psd_comparison_results.npz")
    print("\nDone.")