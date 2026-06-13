"""
TaylorF2 waveform in JAX — automatic differentiation for machine-precision
Fisher matrices.

Resolves Issue #8 (finite-difference corruption) and Issue #3 (normalization
consistency: inner product uses the 4*Re convention consistently).
"""

import jax
import jax.numpy as jnp
import numpy as np
import os

# Enable float64 in JAX
jax.config.update("jax_enable_x64", True)

# Physical constants
G = 6.67430e-11          # m^3 kg^-1 s^-2
C = 299792458            # m/s
M_SUN = 1.98847e30       # kg
PC_TO_M = 3.085677581e16  # m

# Derived constants
G_OVER_C3 = G / (C ** 3)   # s/kg


def taylorf2_htilde(frequencies_hz, Mc_sun, q, chi_eff, Lambdatilde, DL_Mpc):
    """
    TaylorF2 frequency-domain waveform.
    
    Args:
        frequencies_hz: 1D array of frequencies (Hz)
        Mc_sun: chirp mass in solar masses
        q: mass ratio m2/m1 (<= 1)
        chi_eff: effective inspiral spin
        Lambdatilde: effective tidal deformability
        DL_Mpc: luminosity distance in Mpc
        
    Returns:
        complex strain htilde(f) at each frequency
    """
    f = jnp.asarray(frequencies_hz, dtype=jnp.float64)
    
    Mc = Mc_sun * M_SUN  # kg
    M = Mc_sun / (q ** 0.6 / (1 + q) ** 0.2)  # total mass in Msun
    M_kg = M * M_SUN
    
    DL = DL_Mpc * 1e6 * PC_TO_M  # m
    
    # Symmetric mass ratio
    eta = q / (1 + q) ** 2
    
    # Normalized frequency
    pi_M_f = jnp.pi * G_OVER_C3 * M_kg * f
    
    # ---- Amplitude (Newtonian order) ----
    prefactor = (1.0 / DL) * jnp.sqrt(5.0 / 24.0) * (G * Mc) ** (5.0 / 6.0) / (jnp.pi ** (2.0 / 3.0) * C ** 1.5)
    amplitude = prefactor * f ** (-7.0 / 6.0)
    
    # ---- Phase (PN expansion up to 3.5PN + tidal) ----
    # v = (pi G M f / c^3)^(1/3)
    v = pi_M_f ** (1.0 / 3.0)
    
    # TaylorF2 phase coefficients (standard PN)
    # phi_k such that psi = 3/(128*eta) * sum phi_k * v^(k-5)
    phi_0 = 1.0                                        # 0PN: Newtonian
    phi_2 = 0.0                                        # 0.5PN: zero for non-spinning
    phi_3 = 3715.0 / 756.0 + 55.0 / 9.0 * eta          # 1PN
    phi_4 = -16.0 * jnp.pi                             # 1.5PN
    phi_5 = (15293365.0 / 508032.0 + 27145.0 / 504.0 * eta + 3085.0 / 72.0 * eta ** 2)  # 2PN
    
    # 2.5PN (has log term)
    phi_6 = jnp.pi * (38645.0 / 756.0 - 65.0 / 9.0 * eta) * (1.0 + 3.0 * jnp.log(v))
    
    # 3PN
    phi_7 = (11583231236531.0 / 4694215680.0 - 640.0 / 3.0 * jnp.pi ** 2
             - 6848.0 / 21.0 * jnp.euler_gamma
             + eta * (-15737765635.0 / 3048192.0 + 2255.0 / 12.0 * jnp.pi ** 2)
             + 76055.0 / 1728.0 * eta ** 2 - 127825.0 / 1296.0 * eta ** 3
             - 6848.0 / 21.0 * jnp.log(4.0 * v))
    
    # 3.5PN
    phi_8 = jnp.pi * (77096675.0 / 254016.0 + 378515.0 / 1512.0 * eta - 74045.0 / 756.0 * eta ** 2)
    
    # Accumulate phase
    psi = -jnp.pi / 4.0  # stationary phase term
    psi = psi + 3.0 / (128.0 * eta) * phi_0 * v ** (-5)
    psi = psi + 3.0 / (128.0 * eta) * phi_2 * v ** (-3)
    psi = psi + 3.0 / (128.0 * eta) * phi_3 * v ** (-2)
    psi = psi + 3.0 / (128.0 * eta) * phi_4 * v ** (-1)
    psi = psi + 3.0 / (128.0 * eta) * phi_5 * v ** 0
    psi = psi + 3.0 / (128.0 * eta) * phi_6 * v ** 1
    psi = psi + 3.0 / (128.0 * eta) * phi_7 * v ** 2
    psi = psi + 3.0 / (128.0 * eta) * phi_8 * v ** 3
    
    # ---- Spin contribution (effective spin, 1.5PN) ----
    spin_coeff = - (113.0 / 12.0) * chi_eff
    psi = psi + 3.0 / (128.0 * eta) * spin_coeff * v ** 3
    
    # ---- Tidal contribution (5PN relative) ----
    tidal_coeff = - (39.0 / 4.0) * Lambdatilde / eta
    psi = psi + 3.0 / (128.0 * eta) * tidal_coeff * v ** 5
    
    # Complex strain
    htilde = amplitude * jnp.exp(1j * psi)
    
    return htilde


def inner_product(h1, h2, frequencies_hz, psd_values):
    """
    Inner product in waveform space: <a|b> = 4 Re ∫ a(f) b*(f) / S_n(f) df
    
    Uses the 4*Re convention — the standard GW data-analysis inner product.
    Trapezoidal integration.
    """
    integrand = 4.0 * jnp.real(h1 * jnp.conj(h2)) / psd_values
    
    df = jnp.diff(frequencies_hz)
    df_padded = jnp.concatenate([df[:1], df])
    
    return jnp.sum(integrand * df_padded)


def mismatch_exact(theta1, theta2, frequencies_hz, psd_values):
    """
    Exact mismatch between two waveforms: <δh|δh> where δh = h(θ1) - h(θ2).
    """
    Mc1, q1, chi1, lam1, Dl1 = theta1
    Mc2, q2, chi2, lam2, Dl2 = theta2
    
    h1 = taylorf2_htilde(frequencies_hz, Mc1, q1, chi1, lam1, Dl1)
    h2 = taylorf2_htilde(frequencies_hz, Mc2, q2, chi2, lam2, Dl2)
    
    dh = h1 - h2
    return float(inner_product(dh, dh, frequencies_hz, psd_values))


def compute_waveform_and_jacobian(frequencies_hz, theta_phys):
    """
    Compute waveform and its Jacobian using JAX autodiff.
    
    theta_phys = (Mc_sun, q, chi_eff, Lambdatilde, DL_Mpc)
    
    Returns:
        h: complex waveform array (Nf,)
        J: complex Jacobian (Nf, 5) — dh_i / dtheta_j
    """
    f = jnp.asarray(frequencies_hz, dtype=jnp.float64)
    theta = jnp.array(theta_phys, dtype=jnp.float64)
    
    def _hf(theta_vec):
        return taylorf2_htilde(f, theta_vec[0], theta_vec[1], theta_vec[2], theta_vec[3], theta_vec[4])
    
    h = _hf(theta)
    J = jax.jacfwd(_hf)(theta)
    
    return np.array(h), np.array(J)