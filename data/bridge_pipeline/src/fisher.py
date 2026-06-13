"""
Fisher matrix computation with JAX autodiff and eigensweep utilities.

Resolves Issue #3 (normalization consistency) and Issue #8 (conditioning).

The Fisher matrix is defined as the pullback of the waveform-space inner product
⟨a|b⟩ = 4 Re ∫ a b* / S_n df, giving:
    Γ_ij = ⟨∂_i h, ∂_j h⟩ = 4 Re ∫ (∂_i h)(∂_j h*) / S_n df
"""

import jax
import jax.numpy as jnp
import numpy as np
from scipy import linalg as spla

jax.config.update("jax_enable_x64", True)

from . import waveform as wf
from . import coordinates as coords


def fisher_cumulative(theta_phys, frequencies_hz, psd_values, convention="primary"):
    """
    Compute cumulative Fisher matrix at each frequency cutoff.
    
    Γ_ij(f) = 4 ∫_fmin^f Re(∂_i h ∂_j h*) / S_n df'
    
    The factor of 4 is the standard GW data-analysis convention — it makes
    ρ² = Δθ^T Γ Δθ equal to the squared SNR of the difference waveform
    ⟨δh|δh⟩ in the small-displacement limit.
    
    Args:
        theta_phys: (5,) array [Mc_sun, q, chi_eff, Lambdatilde, DL_Mpc]
        frequencies_hz: (Nf,) array
        psd_values: (Nf,) PSD values
        convention: coordinate convention
        
    Returns:
        G_cum_x: (Nf, 5, 5) cumulative Fisher in analysis coordinates
        G_full_x: (5, 5) Fisher at full band in analysis coordinates
    """
    theta_np = np.array(theta_phys, dtype=np.float64)
    f = np.array(frequencies_hz, dtype=np.float64)
    psd = np.array(psd_values, dtype=np.float64)
    
    # Compute waveform and Jacobian
    h, J = wf.compute_waveform_and_jacobian(f, theta_np)
    # J: (Nf, 5) complex — ∂h_i/∂θ_j
    
    Nf = len(f)
    
    # Physical Fisher increment at each freq: 4 * Re(J_i * conj(J_j)) / S_n
    dG_phys = np.zeros((Nf, 5, 5), dtype=np.float64)
    for i in range(5):
        for j in range(5):
            dG_phys[:, i, j] = 4.0 * np.real(J[:, i] * np.conj(J[:, j])) / psd
    
    # Trapezoidal integration
    df = np.diff(f)
    df_padded = np.concatenate([[df[0]], df])
    
    G_cum_phys = np.zeros((Nf, 5, 5), dtype=np.float64)
    running = np.zeros((5, 5), dtype=np.float64)
    for k in range(Nf):
        running = running + dG_phys[k] * df_padded[k]
        G_cum_phys[k] = running.copy()
    
    G_full_phys = running
    
    # Transport to analysis coordinates: Γ_x = J^{-T} Γ_phys J^{-1}
    Jx = coords.CONVENTIONS[convention]["jacobian"](theta_np.reshape(1, 5))[0]
    Jinv = np.linalg.inv(Jx)
    JinvT = Jinv.T
    
    G_cum_x = np.zeros_like(G_cum_phys)
    for k in range(Nf):
        G_cum_x[k] = JinvT @ G_cum_phys[k] @ Jinv
    
    G_full_x = JinvT @ G_full_phys @ Jinv
    
    return G_cum_x, G_full_x


def eigensweep(G_stack):
    """
    Eigendecomposition at each cutoff with sign-continuity enforced.
    Returns sorted descending: λ_1 ≥ λ_2 ≥ ... ≥ λ_D
    """
    Nf, D = G_stack.shape[0], G_stack.shape[1]
    
    eigvals = np.zeros((Nf, D))
    eigvecs = np.zeros((Nf, D, D))
    
    for k in range(Nf):
        evals, evecs = spla.eigh(G_stack[k])
        # eigh returns ascending; reverse to descending
        evals = evals[::-1]
        evecs = evecs[:, ::-1]
        
        # Sign convention: dominant component positive
        for i in range(D):
            idx_max = np.argmax(np.abs(evecs[:, i]))
            if evecs[idx_max, i] < 0:
                evecs[:, i] = -evecs[:, i]
        
        # Sign continuity with previous cutoff
        if k > 0:
            for i in range(D):
                dot = np.dot(eigvecs[k-1, :, i], evecs[:, i])
                if dot < 0:
                    evecs[:, i] = -evecs[:, i]
        
        eigvals[k] = evals
        eigvecs[k] = evecs
    
    return eigvals, eigvecs


def C_of_f(G_stack):
    """
    Fractional misalignment: C(f) = ||Γ - λ₁ Π||_F / ||Γ||_F
    """
    Nf = G_stack.shape[0]
    C_vals = np.zeros(Nf)
    
    eigvals, eigvecs = eigensweep(G_stack)
    
    for k in range(Nf):
        G = G_stack[k]
        lam1 = eigvals[k, 0]
        v1 = eigvecs[k, :, 0]
        Pi = np.outer(v1, v1)
        
        residual = G - lam1 * Pi
        C_vals[k] = np.linalg.norm(residual, 'fro') / np.linalg.norm(G, 'fro')
    
    return C_vals, eigvals, eigvecs


def commutator_integral(G_stack):
    """∫ ||[Γ, Π]||_F df"""
    Nf = G_stack.shape[0]
    _, eigvecs = eigensweep(G_stack)
    comm_norms = np.zeros(Nf)
    
    for k in range(Nf):
        G = G_stack[k]
        v1 = eigvecs[k, :, 0]
        Pi = np.outer(v1, v1)
        
        comm = G @ Pi - Pi @ G
        comm_norms[k] = np.linalg.norm(comm, 'fro')
    
    integral = np.trapezoid(comm_norms)
    return integral, comm_norms


def rho2(G_stack, dx):
    """ρ²(f) = Δx^T Γ(f) Δx at each cutoff."""
    Nf = G_stack.shape[0]
    rho2_vals = np.zeros(Nf)
    for k in range(Nf):
        rho2_vals[k] = dx @ G_stack[k] @ dx
    return rho2_vals


def condition_number(G):
    """κ = λ_max / λ_min."""
    evals = np.linalg.eigvalsh(G)
    return evals[-1] / evals[0]