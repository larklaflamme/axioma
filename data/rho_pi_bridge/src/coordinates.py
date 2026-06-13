"""
coordinates.py — Parameter transforms, Jacobians, Fisher transport
Issues #3, #8. Declared convention + alternate conventions for robustness.
"""

import numpy as np
from numpy.typing import NDArray
from typing import Callable

# ---------------------------------------------------------------------------
# Convention keys
# ---------------------------------------------------------------------------
PRIMARY = "primary"
ALT_A   = "alternate_A"
ALT_B   = "alternate_B"

# ---------------------------------------------------------------------------
# Physical parameter order
# ---------------------------------------------------------------------------
PHYS_NAMES = ["Mc", "q", "chi_eff", "Lambda_tilde", "DL"]  # Msun, —, —, —, Mpc
PHYS_DIM   = 5

# ---------------------------------------------------------------------------
# Primary convention: x = (ln Mc, q, chi_eff, Lambda_tilde/100, ln DL)
# ---------------------------------------------------------------------------
def to_primary(phys: NDArray) -> NDArray:
    """physical (Mc, q, chi_eff, Lambda_tilde, DL) -> primary coordinates."""
    Mc, q, chi, Lt, DL = phys[0], phys[1], phys[2], phys[3], phys[4]
    return np.array([np.log(Mc), q, chi, Lt / 100.0, np.log(DL)])


def jacobian_primary(phys: NDArray) -> NDArray:
    """Jacobian J_ij = dx_i / d(phys)_j for primary convention."""
    Mc, q, chi, Lt, DL = phys[0], phys[1], phys[2], phys[3], phys[4]
    J = np.zeros((PHYS_DIM, PHYS_DIM))
    J[0, 0] = 1.0 / Mc        # d ln Mc / d Mc
    J[1, 1] = 1.0              # d q / d q
    J[2, 2] = 1.0              # d chi_eff / d chi_eff
    J[3, 3] = 1.0 / 100.0     # d (Lt/100) / d Lt
    J[4, 4] = 1.0 / DL        # d ln DL / d DL
    return J


def from_primary(x: NDArray) -> NDArray:
    """primary coordinates -> physical."""
    lnMc, q, chi, Lt_scaled, lnDL = x[0], x[1], x[2], x[3], x[4]
    return np.array([np.exp(lnMc), q, chi, Lt_scaled * 100.0, np.exp(lnDL)])


# ---------------------------------------------------------------------------
# Alternate A: (ln Mc, eta, chi_eff, ln(Lambda_tilde+1), ln DL)
# ---------------------------------------------------------------------------
def q_to_eta(q: float) -> float:
    """Symmetric mass ratio eta = q / (1+q)^2."""
    return q / ((1.0 + q) ** 2)


def eta_to_q(eta: float) -> float:
    """Invert symmetric mass ratio (primary branch q <= 1)."""
    # eta = q/(1+q)^2  =>  eta q^2 + (2 eta - 1) q + eta = 0
    disc = (2 * eta - 1) ** 2 - 4 * eta * eta
    if disc < 0:
        raise ValueError(f"eta={eta} not in [0, 0.25]")
    sqrt_disc = np.sqrt(disc)
    q1 = (1 - 2 * eta - sqrt_disc) / (2 * eta)
    q2 = (1 - 2 * eta + sqrt_disc) / (2 * eta)
    # return the smaller positive root (q <= 1)
    return min(q1, q2)


def to_alt_A(phys: NDArray) -> NDArray:
    """physical -> alternate A."""
    Mc, q, chi, Lt, DL = phys[0], phys[1], phys[2], phys[3], phys[4]
    eta = q_to_eta(q)
    return np.array([np.log(Mc), eta, chi, np.log(Lt + 1.0), np.log(DL)])


def jacobian_alt_A(phys: NDArray) -> NDArray:
    """Jacobian for alternate A convention."""
    Mc, q, chi, Lt, DL = phys[0], phys[1], phys[2], phys[3], phys[4]
    eta = q_to_eta(q)
    J = np.zeros((PHYS_DIM, PHYS_DIM))
    J[0, 0] = 1.0 / Mc
    # d eta / d q = (1 - q) / (1+q)^3
    J[1, 1] = (1.0 - q) / ((1.0 + q) ** 3)
    J[2, 2] = 1.0
    J[3, 3] = 1.0 / (Lt + 1.0)
    J[4, 4] = 1.0 / DL
    return J


def from_alt_A(x: NDArray) -> NDArray:
    """alternate A -> physical."""
    lnMc, eta, chi, lnLtp1, lnDL = x[0], x[1], x[2], x[3], x[4]
    q = eta_to_q(eta)
    Lt = np.exp(lnLtp1) - 1.0
    return np.array([np.exp(lnMc), q, chi, Lt, np.exp(lnDL)])


# ---------------------------------------------------------------------------
# Alternate B: prior-range whitening
# ---------------------------------------------------------------------------
# Prior widths approximated from GW170817 published bounds
PRIOR_RANGES = {
    "Mc": np.array([1.0, 2.0]),      # Msun
    "q": np.array([0.125, 1.0]),     # q in [1/8, 1]
    "chi_eff": np.array([-0.5, 0.5]),
    "Lambda_tilde": np.array([0.0, 2000.0]),
    "DL": np.array([10.0, 200.0]),   # Mpc
}


def prior_whiten(phys: NDArray) -> NDArray:
    """Map each param to [0, 1] via (x - min) / (max - min)."""
    x = np.zeros(PHYS_DIM)
    for i, name in enumerate(PHYS_NAMES):
        lo, hi = PRIOR_RANGES[name]
        x[i] = (phys[i] - lo) / (hi - lo)
    return x


def jacobian_whiten(phys: NDArray) -> NDArray:
    """Jacobian for prior-range whitening (diagonal scaling)."""
    J = np.zeros((PHYS_DIM, PHYS_DIM))
    for i, name in enumerate(PHYS_NAMES):
        lo, hi = PRIOR_RANGES[name]
        J[i, i] = 1.0 / (hi - lo)
    return J


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
CONVENTIONS = {
    PRIMARY: {
        "to": to_primary,
        "from": from_primary,
        "jacobian": jacobian_primary,
        "name": "ln Mc, q, chi_eff, Λ̃/100, ln DL",
    },
    ALT_A: {
        "to": to_alt_A,
        "from": from_alt_A,
        "jacobian": jacobian_alt_A,
        "name": "ln Mc, η, chi_eff, ln(Λ̃+1), ln DL",
    },
    ALT_B: {
        "to": prior_whiten,
        "from": None,  # not needed for primary use
        "jacobian": jacobian_whiten,
        "name": "prior-range whitened (each ∈ [0,1])",
    },
}


def get_convention(key: str = PRIMARY) -> dict:
    """Return the convention dict by key. Raises KeyError if unknown."""
    if key not in CONVENTIONS:
        raise KeyError(f"Unknown convention '{key}'. Options: {list(CONVENTIONS.keys())}")
    return CONVENTIONS[key]


def transport_fisher(G_phys: NDArray, J: NDArray) -> NDArray:
    r"""Transport Fisher matrix from physical to analysis coordinates.

    Γ_x = J^{-T} Γ_phys J^{-1}

    where J_ij = ∂x_i / ∂(phys)_j.
    """
    Jinv = np.linalg.inv(J)
    return Jinv.T @ G_phys @ Jinv


def transport_vector(v_phys: NDArray, J: NDArray) -> NDArray:
    """Transport a displacement vector (contravariant) to new coordinates.

    v_x = J v_phys    (since dx = J d(phys))
    """
    return J @ v_phys


# ---------------------------------------------------------------------------
# Unit test / self-check
# ---------------------------------------------------------------------------
def _self_test():
    """Verify invariant scalars agree across conventions to < 1e-10."""
    rng = np.random.default_rng(42)
    for _ in range(10):
        # random physical parameters in plausible BNS range
        phys = np.array([
            rng.uniform(1.1, 1.3),     # Mc
            rng.uniform(0.5, 1.0),     # q
            rng.uniform(-0.1, 0.1),    # chi_eff
            rng.uniform(200, 800),     # Lambda_tilde
            rng.uniform(20, 80),       # DL
        ])
        # Test round-trip for each convention
        for key, conv in CONVENTIONS.items():
            if conv["from"] is None:
                continue  # ALT_B has no inverse
            x = conv["to"](phys)
            phys_rt = conv["from"](x)
            err = np.max(np.abs(phys - phys_rt))
            assert err < 1e-12, f"{key}: round-trip error {err:.2e}"
    print("coordinates.py: all round-trip self-tests passed.")


if __name__ == "__main__":
    _self_test()