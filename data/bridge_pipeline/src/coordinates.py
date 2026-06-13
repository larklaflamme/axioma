"""
Coordinate conventions for the (rho, Pi) bridge pipeline.

Resolves Issue #3 (normalization consistency) by establishing a single
declared convention in which all eigendecompositions are computed,
with two alternatives for robustness testing.
"""

import numpy as np
from typing import Callable

# ---------------------------------------------------------------------------
# Physical parameter order: [Mc_sun, q, chi_eff, Lambdatilde, DL_Mpc]
# ---------------------------------------------------------------------------

def to_primary(theta_phys: np.ndarray) -> np.ndarray:
    """
    Primary convention (declared): x = (ln Mc, q, chi_eff, Lambdatilde/100, ln DL)
    
    Args:
        theta_phys: (..., 5) array of [Mc_sun, q, chi_eff, Lambdatilde, DL_Mpc]
    Returns:
        (..., 5) array in primary coordinates
    """
    Mc, q, chi, lam, Dl = theta_phys[..., 0], theta_phys[..., 1], theta_phys[..., 2], theta_phys[..., 3], theta_phys[..., 4]
    out = np.stack([
        np.log(Mc),
        q,
        chi,
        lam / 100.0,
        np.log(Dl)
    ], axis=-1)
    return out


def from_primary(x: np.ndarray) -> np.ndarray:
    """Inverse of to_primary."""
    lnMc, q, chi, lam_scaled, lnDl = x[..., 0], x[..., 1], x[..., 2], x[..., 3], x[..., 4]
    return np.stack([
        np.exp(lnMc),
        q,
        chi,
        lam_scaled * 100.0,
        np.exp(lnDl)
    ], axis=-1)


def jacobian_primary(theta_phys: np.ndarray) -> np.ndarray:
    """
    Jacobian dx/dtheta_phys for primary convention.
    
    Returns shape (..., 5, 5) where J[i,j] = dx_i / dtheta_j
    """
    Mc = theta_phys[..., 0]
    Dl = theta_phys[..., 4]
    J = np.zeros(theta_phys.shape + (5,))
    # d(ln Mc)/dMc = 1/Mc
    J[..., 0, 0] = 1.0 / Mc
    # d(q)/dq = 1
    J[..., 1, 1] = 1.0
    # d(chi_eff)/dchi_eff = 1
    J[..., 2, 2] = 1.0
    # d(Lambda/100)/dLambda = 1/100
    J[..., 3, 3] = 1.0 / 100.0
    # d(ln DL)/dDL = 1/DL
    J[..., 4, 4] = 1.0 / Dl
    return J


def transport_fisher(G_phys: np.ndarray, J: np.ndarray) -> np.ndarray:
    """
    Transport Fisher matrix from physical to analysis coordinates.
    Gamma_x = J^{-T} Gamma_phys J^{-1}
    """
    # Solve J^T Gamma_x J = Gamma_phys => Gamma_x = J^{-T} Gamma_phys J^{-1}
    # For diagonal J this is simple
    Jinv = np.zeros_like(J)
    for i in range(5):
        Jinv[..., i, i] = 1.0 / J[..., i, i]
    JinvT = np.swapaxes(Jinv, -1, -2)
    G_x = JinvT @ G_phys @ Jinv
    return G_x


def to_alt_a(theta_phys: np.ndarray) -> np.ndarray:
    """
    ALT-A: (ln Mc, eta, chi_eff, ln(Lambdatilde+1), ln DL)
    where eta = q/(1+q)^2 is symmetric mass ratio.
    """
    Mc, q, chi, lam, Dl = theta_phys[..., 0], theta_phys[..., 1], theta_phys[..., 2], theta_phys[..., 3], theta_phys[..., 4]
    eta = q / (1.0 + q) ** 2
    return np.stack([
        np.log(Mc),
        eta,
        chi,
        np.log(lam + 1.0),
        np.log(Dl)
    ], axis=-1)


def jacobian_alt_a(theta_phys: np.ndarray) -> np.ndarray:
    """Jacobian for ALT-A convention."""
    q = theta_phys[..., 1]
    lam = theta_phys[..., 3]
    Mc = theta_phys[..., 0]
    Dl = theta_phys[..., 4]
    J = np.zeros(theta_phys.shape + (5,))
    J[..., 0, 0] = 1.0 / Mc    # d(ln Mc)/dMc
    # d(eta)/dq = (1 - q) / (1 + q)^3
    J[..., 1, 1] = (1.0 - q) / (1.0 + q) ** 3
    J[..., 2, 2] = 1.0          # d(chi_eff)/dchi_eff
    # d(ln(Lambda+1))/dLambda = 1/(Lambda+1)
    J[..., 3, 3] = 1.0 / (lam + 1.0)
    J[..., 4, 4] = 1.0 / Dl     # d(ln DL)/dDL
    return J


def to_alt_b(theta_phys: np.ndarray) -> np.ndarray:
    """
    ALT-B: prior-range whitening.
    Each raw parameter divided by its prior width.
    Prior widths: Mc ~ 0.3 Msun around 1.186, q in [0.1, 1.0],
    chi in [-0.89, 0.89], Lambda in [0, 5000], DL in [1, 100] Mpc.
    """
    Mc, q, chi, lam, Dl = theta_phys[..., 0], theta_phys[..., 1], theta_phys[..., 2], theta_phys[..., 3], theta_phys[..., 4]
    # Rough prior centers/widths for GW170817
    return np.stack([
        (Mc - 1.0) / 0.5,      # Mc ~ [0.7, 1.7]
        (q - 0.55) / 0.45,     # q ~ [0.1, 1.0]
        chi / 0.89,            # chi ~ [-0.89, 0.89]
        lam / 2500.0,          # Lambda ~ [0, 5000]
        (Dl - 40.0) / 30.0     # DL ~ [10, 100] Mpc
    ], axis=-1)


def jacobian_alt_b(theta_phys: np.ndarray) -> np.ndarray:
    """Jacobian for ALT-B convention."""
    J = np.zeros(theta_phys.shape + (5,))
    J[..., 0, 0] = 1.0 / 0.5
    J[..., 1, 1] = 1.0 / 0.45
    J[..., 2, 2] = 1.0 / 0.89
    J[..., 3, 3] = 1.0 / 2500.0
    J[..., 4, 4] = 1.0 / 30.0
    return J


# Registry of conventions
CONVENTIONS = {
    "primary": {
        "to": to_primary,
        "from": from_primary,
        "jacobian": jacobian_primary,
        "label": "Declared (ln Mc, q, chi_eff, Lambda/100, ln DL)"
    },
    "ALT-A": {
        "to": to_alt_a,
        "jacobian": jacobian_alt_a,
        "label": "ALT-A (ln Mc, eta, chi_eff, ln(Lambda+1), ln DL)"
    },
    "ALT-B": {
        "to": to_alt_b,
        "jacobian": jacobian_alt_b,
        "label": "ALT-B (prior-whitened)"
    }
}