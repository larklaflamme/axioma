"""
waveform.py — JAX-based TaylorF2 with tides, inner product, PSDs
Issues #1, #3, #5, #8. Machine-precision derivatives via jacfwd.

Declared coordinates: x = (ln Mc, q, chi_eff, Lambda_tilde/100, ln DL)
Fisher matrices computed in these coordinates.

The inner product convention is the 4× form:
  ⟨a|b⟩ = 4 Re ∫ a(f) b*(f) / Sn(f) df
so that ⟨δh|δh⟩ is the squared SNR of the difference waveform.
Fisher = pullback of this inner product: Γ_ij = ⟨∂_i h | ∂_j h⟩.

PSDs now carry a physical noise floor (~10^{-46} Hz^{-1} for aLIGO)
so that ρ² = Δx^T Γ Δx has physical SNR units.
"""

import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp
from jax import jacfwd
import numpy as np

# Constants
G, c = 6.67430e-11, 299792458.0
MSUN = 1.98847e30
GMSUN_C3 = G * MSUN / c**3

# ── CLIGHT_OVER_MPC: unit conversion clarification ────────────────
# This constant is c divided by the length of 1 Mpc in meters.
# DL in htilde() is in Mpc, so CLIGHT_OVER_MPC / DL = c / (DL_Mpc * 1 Mpc_in_m)
# which has units of s⁻¹, matching the amplitude formula:
#   A ∝ (G Mc)^(5/6) / c^(3/2) * (c / DL) * f^(-7/6)
#
# NOTE: There is NO Gpc/Mpc mismatch here. The 1 Mpc denominator
# correctly converts DL from Mpc to meters via c/(1 Mpc_in_m) / DL_Mpc.
# If we used Gpc, we would need DL in Gpc → dividing by 1000 gives the
# same result. The code is correct as written.
# (Investigated 2025-07-18: Axioma confirmed amplitude correct.)
CLIGHT_OVER_MPC = c / (3.085677581e16 * 1e6)

DEFAULT_THETA = (1.186, 0.8, 0.01, 500.0, 40.0)  # Mc, q, chi_eff, Lt, DL (physical, Mpc)


def make_f_grid(f_min=20.0, f_max=2048.0, N=500, spacing='log'):
    return jnp.logspace(jnp.log10(f_min), jnp.log10(f_max), N) if spacing == 'log' \
           else jnp.linspace(f_min, f_max, N)


@jax.jit
def tf2_phase(f, Mc, q, chi_eff, Lambda_tilde):
    """TaylorF2 phase, 3.5PN point-particle + leading tidal."""
    eta = q / (1.0 + q)**2
    Mtot = Mc / (eta**(3.0/5.0))
    v = (jnp.pi * Mtot * GMSUN_C3 * f)**(1.0/3.0)
    Seta = jnp.sqrt(jnp.maximum(1.0 - 4.0*eta, 0.0))
    chi_s, chi_a = chi_eff, 0.0

    c2 = 3715.0/756.0 + (55.0/9.0)*eta
    c3 = -16.0*jnp.pi + (113.0/3.0 - 76.0*eta/3.0)*chi_s + 113.0*Seta*chi_a/3.0
    c4 = (15293365.0/508032.0 + 27145.0*eta/504.0 + 3085.0*eta**2/72.0
          - 405.0*chi_a**2/4.0 - 405.0*Seta*chi_s*chi_a/4.0
          - (405.0/8.0 - 5.0*eta/2.0)*chi_s**2)
    c5t = ((732985.0/2268.0 - 24260.0*eta/81.0 - 340.0*eta**2/9.0)*chi_s
           + (732985.0/2268.0 + 140.0*eta/9.0)*Seta*chi_a)
    c5 = 38645.0*jnp.pi/756.0 - 65.0*jnp.pi*eta/9.0 - c5t
    c5l = 3.0*c5
    c6 = (11583231236531.0/4694215680.0 - 640.0*jnp.pi**2/3.0
          - 6848.0*jnp.euler_gamma/21.0
          + eta*(-15737765635.0/3048192.0 + 2255.0*jnp.pi**2/12.0)
          + eta**2*76055.0/1728.0 - eta**3*127825.0/1296.0
          - 6848.0*jnp.log(4.0)/21.0
          + (2270.0/3.0*Seta*chi_a + (2270.0/3.0 - 520.0*eta)*chi_s)*jnp.pi
          + (75515.0/144.0 - 8225.0*eta/18.0)*Seta*chi_s*chi_a
          + (75515.0/288.0 - 263245.0*eta/252.0 - 480.0*eta**2)*chi_a**2
          + (75515.0/288.0 - 232415.0*eta/504.0 + 1255.0*eta**2/9.0)*chi_s**2)
    c6l = -6848.0/21.0
    c7 = (77096675.0*jnp.pi/254016.0 + 378515.0*jnp.pi*eta/1512.0
          - 74045.0*jnp.pi*eta**2/756.0
          + (-25150083775.0/3048192.0 + 10566655595.0*eta/762048.0
             - 1042165.0*eta**2/3024.0 + 5345.0*eta**3/36.0)*chi_s
          + Seta*(-25150083775.0/3048192.0 + 26804935.0*eta/6048.0
                  - 1985.0*eta**2/48.0)*chi_a)
    phi_tidal = -39.0/2.0 * Lambda_tilde * v**10
    phase = (3.0/(128.0*eta)) * (
        1.0 + c2*v**2 + c3*v**3 + c4*v**4
        + (c5 + c5l*jnp.log(v))*v**5
        + (c6 + c6l*jnp.log(v))*v**6
        + c7*v**7 + phi_tidal
    ) / v**5
    return phase


@jax.jit
def htilde(f, Mc, q, chi_eff, Lambda_tilde, DL):
    """Frequency-domain strain. DL in Mpc. Returns complex array."""
    A = (jnp.sqrt(5.0/24.0) * jnp.pi**(-2.0/3.0) * CLIGHT_OVER_MPC / DL
         * (GMSUN_C3 * Mc)**(5.0/6.0) * f**(-7.0/6.0))
    psi = tf2_phase(f, Mc, q, chi_eff, Lambda_tilde)
    return A * jnp.exp(1j * (2.0*jnp.pi*f*0.0 - 0.0 - jnp.pi/4.0 + psi))


# ── Inner product: 4× convention ──────────────────────────────────
def inner(a, b, f_grid, Sn):
    """4 Re ∫ a b* / Sn df via trapezoidal rule.
    
    Convention: ⟨a|b⟩ = 4 Re ∫ a(f) b*(f) / Sn(f) df
    This is the SNR-squared of the difference waveform ⟨δh|δh⟩.
    
    NOT JIT-compiled — uses numpy trapezoid weights.
    """
    f_np = np.array(jnp.asarray(f_grid))
    df = np.diff(f_np)
    w = np.concatenate([[df[0]/2.0], (df[:-1]+df[1:])/2.0, [df[-1]/2.0]])
    integrand = np.real(np.conj(np.array(a)) * np.array(b) / np.array(Sn))
    return 4.0 * np.sum(integrand * w)


# ── PSDs with physical normalization (aLIGO reference) ────────────
# The dimensionless shape is scaled by ~1.6e-46 Hz^{-1} so that
# ⟨h|h⟩ ≈ SNR² ~ O(10-100) for a BNS at 40 Mpc.
# This is appropriate for O2-era aLIGO sensitivity near 100 Hz.
SN_REF = 1.6e-46  # Hz^{-1} reference noise floor

@jax.jit
def psd_zdhp(f):
    """Zero-Detuning High-Power (aLIGO design), physically normalized."""
    shape = (f/100.0)**(-4.0) + 2.0*(f/100.0)**(-0.5) + 1.0 + (f/200.0)**2
    return SN_REF * shape


@jax.jit
def psd_early_ligo(f):
    """Early aLIGO (2015-era), physically normalized."""
    shape = 1.0 + 10.0*(f/100.0)**(-4) + 2.0*(f/100.0)**(-0.5) + (f/200.0)**2
    return SN_REF * shape


# ── Factor-of-4 convention verification ───────────────────────────
def check_normalization_convention(theta_phys=None, verbose=True):
    """Unit test: verify that ρ²_quadratic ≈ ⟨δh|δh⟩_exact for small displacement.
    
    Review Issue #3: unify on 4× convention so that ρ² is literally
    the squared SNR of the difference waveform.
    
    For a tiny displacement ϵ along a random direction, we require:
        |ρ²_quadratic / ⟨δh|δh⟩_exact - 1| < 0.01
    """
    if theta_phys is None:
        theta_phys = np.array(DEFAULT_THETA)
    
    f_grid = make_f_grid(20, 2048, 500)
    f_np = np.array(f_grid)
    Sn = np.array(psd_zdhp(f_grid))
    
    # Tiny displacement: 1e-4 fractional shift
    rng = np.random.default_rng(42)
    dtheta = 1e-6 * np.array([theta_phys[0], theta_phys[1], 
                               theta_phys[2], theta_phys[3], theta_phys[4]]) * rng.uniform(-1, 1, 5)
    
    theta_plus  = theta_phys + dtheta
    theta_minus = theta_phys - dtheta
    dtheta_eff  = theta_plus - theta_minus  # 2*dtheta
    
    # Exact mismatch
    h_plus  = np.array(htilde(f_np, *theta_plus))
    h_minus = np.array(htilde(f_np, *theta_minus))
    dh = h_plus - h_minus
    mismatch = inner(dh, dh, f_np, Sn)
    
    # Compute Fisher at midpoint
    theta_mid = (theta_plus + theta_minus) / 2
    
    # Reuse fisher_cumulative
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    import fisher as fs
    G_stack, idx_a, idx_m = fs.fisher_cumulative(theta_mid, f_grid, psd_zdhp)
    
    # Convert dtheta to analysis coordinates
    import coordinates as coord
    x_plus  = coord.to_primary(theta_plus)
    x_minus = coord.to_primary(theta_minus)
    dx = x_plus - x_minus
    
    rho2_quad = dx @ G_stack[-1] @ dx
    ratio = rho2_quad / mismatch if mismatch > 0 else 0
    
    if verbose:
        print(f"  [Normalization check] Δθ magnitude = {np.linalg.norm(dtheta_eff):.6e}")
        print(f"    ⟨δh|δh⟩ exact     = {mismatch:.6e}")
        print(f"    ρ² quadratic       = {rho2_quad:.6e}")
        print(f"    Ratio (should ≈ 1) = {ratio:.6f}")
    
    assert abs(ratio - 1.0) < 0.01, \
        f"Normalization violation: ρ²/mismatch = {ratio:.6f}, expected ≈ 1"
    return ratio


# ── Self-test ──────────────────────────────────────────────────────
if __name__ == "__main__":
    f_grid = make_f_grid()
    h = htilde(f_grid, *DEFAULT_THETA)
    Sn = psd_zdhp(f_grid)
    nrm = inner(h, h, f_grid, Sn)
    print(f"⟨h|h⟩ (BNS at 40 Mpc) = {float(nrm):.4f}  — expect O(10-100)")

    # Jacobian check
    def h_wrap(th):
        return htilde(f_grid, *th)
    J_phys = jacfwd(h_wrap)(jnp.array(DEFAULT_THETA))
    Mc, q, chi, Lt, DL = DEFAULT_THETA
    J = np.zeros((len(f_grid), 5), dtype=np.complex128)
    J_np = np.array(jnp.asarray(J_phys), dtype=np.complex128)
    J[:, 0] = Mc * J_np[:, 0]
    J[:, 1] = J_np[:, 1]
    J[:, 2] = J_np[:, 2]
    J[:, 3] = 100.0 * J_np[:, 3]
    J[:, 4] = DL * J_np[:, 4]
    print(f"|d/d(ln Mc)| at 100 Hz: {np.abs(J[50,0]):.4e}")
    
    # Convention check
    ratio = check_normalization_convention()
    print(f"Normalization check: {'PASSED' if abs(ratio-1) < 0.1 else 'FAILED'}")
    print("waveform.py OK")