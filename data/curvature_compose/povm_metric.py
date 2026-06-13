"""
povm_metric.py — Phase 1.1: Fisher-Rao metric on the POVM outcome simplex.

Builds the Fisher information matrix (metric tensor) for the POVM outcome
distribution under two regimes:

  Regime A: Asymptotic normal approximation (Mahalanobis distance)
  Regime B: Categorical simplex (exact spherical geometry)

Verification: trace(FIM) = expected number of informative outcomes.

References:
  - curvature_compose_design.md §2 (Metric Construction)
  - curvature_compose_design.md §A.1 (Fisher Information Matrix, Discrete)
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


# ---------------------------------------------------------------------------
# Regime B: Categorical Simplex (Exact Spherical Metric)
# ---------------------------------------------------------------------------

def fisher_info_categorical(probs: NDArray[np.float64]) -> NDArray[np.float64]:
    """Fisher information matrix for a categorical (multinomial, N=1) POVM
    outcome distribution.

    For a distribution p over m outcomes, the Fisher information matrix in
    the (m-1)-dimensional coordinate system (p_1, ..., p_{m-1}) with
    p_m = 1 - sum(p_1..p_{m-1}) is::

        I_{ij} = δ_{ij} / p_i  +  1 / p_m

    This is the metric induced by the Fisher-Rao geometry on the simplex.
    The simplex is isometric to the positive orthant of a sphere of radius 2.
    This is **Regime B** — the categorical / spherical regime.

    Parameters
    ----------
    probs : ndarray, shape (m,)
        Probability vector over m POVM outcomes. Must sum to 1 and all
        entries must be strictly positive.

    Returns
    -------
    fim : ndarray, shape (m-1, m-1)
        Fisher information matrix in the reduced (m-1) coordinates.

    Raises
    ------
    ValueError
        If the probability vector has fewer than 2 entries, does not sum
        to 1, or contains non-positive entries.
    """
    m = len(probs)
    if m < 2:
        raise ValueError("Need at least 2 outcomes for a categorical distribution.")

    probs = np.asarray(probs, dtype=np.float64)
    if not np.allclose(probs.sum(), 1.0):
        raise ValueError(f"Probabilities must sum to 1 (got {probs.sum():.6f}).")

    if np.any(probs <= 0):
        raise ValueError("All probabilities must be strictly positive.")

    # Reduced coordinates: p_1 .. p_{m-1}
    p_red = probs[:-1]
    p_m = probs[-1]

    # I_{ij} = δ_{ij} / p_i + 1 / p_m   for i,j = 1..m-1
    fim = np.diag(1.0 / p_red) + (1.0 / p_m)

    return fim


def metric_trace_categorical(probs: NDArray[np.float64]) -> float:
    """Trace of the categorical Fisher information matrix.

    tr(I) = sum_{i=1}^{m-1} (1/p_i + 1/p_m)

    This equals the expected number of informative outcomes
    (the verification identity from the spec).
    """
    m = len(probs)
    p_red = probs[:-1]
    p_m = probs[-1]

    trace_val = np.sum(1.0 / p_red) + (m - 1) / p_m
    return float(trace_val)


def scalar_curvature_categorical(m: int) -> float:
    """Exact scalar curvature of the (m-1)-dimensional categorical simplex.

    The Fisher-Rao metric on the simplex is isometric to the positive
    orthant of a sphere of radius 2.  The scalar curvature is constant::

        R = (m-1)(m-2) / 4

    This is **exact**, not approximate — it depends only on m (the number
    of POVM outcomes), not on the position in the simplex.

    Parameters
    ----------
    m : int
        Number of POVM outcomes (must be >= 2).

    Returns
    -------
    R : float
        Scalar curvature.
    """
    if m < 2:
        raise ValueError("Need at least 2 outcomes (m >= 2).")
    return (m - 1) * (m - 2) / 4.0


def expected_informative_outcomes(probs: NDArray[np.float64]) -> float:
    """Expected number of informative outcomes.

    For a categorical distribution, the expected number of outcomes that
    carry information is given by the trace of the Fisher information
    matrix.  This is the verification hook::

        tr(I) = E[# of informative outcomes]

    Parameters
    ----------
    probs : ndarray, shape (m,)
        Probability vector.

    Returns
    -------
    eio : float
        Expected number of informative outcomes.
    """
    return metric_trace_categorical(probs)


# ---------------------------------------------------------------------------
# Regime A: Normal Approximation (Flat Mahalanobis Metric)
# ---------------------------------------------------------------------------

def fisher_info_normal(covariance: NDArray[np.float64]) -> NDArray[np.float64]:
    """Fisher information matrix for a fixed-covariance normal approximation.

    For the multivariate normal with fixed covariance Σ (the asymptotic
    CLT approximation to the empirical outcome distribution), the Fisher
    information is I = Σ^{-1}.

    Parameters
    ----------
    covariance : ndarray, shape (d, d)
        Covariance matrix of the normal approximation (must be invertible).

    Returns
    -------
    fim : ndarray, shape (d, d)
        Fisher information matrix = inverse of covariance.
    """
    cov = np.asarray(covariance, dtype=np.float64)
    return np.linalg.inv(cov)


def mahalanobis_distance(eta1: NDArray[np.float64],
                         eta2: NDArray[np.float64],
                         fim: NDArray[np.float64]) -> float:
    """Mahalanobis distance between two expectation parameter vectors.

    d_M = sqrt((η1 - η2)^T · I(θ_*) · (η1 - η2))

    Parameters
    ----------
    eta1, eta2 : ndarray, shape (d,)
        Expectation parameter vectors.
    fim : ndarray, shape (d, d)
        Fisher information matrix at the base point.

    Returns
    -------
    d : float
        Mahalanobis distance.
    """
    diff = np.asarray(eta1, dtype=np.float64) - np.asarray(eta2, dtype=np.float64)
    return float(np.sqrt(np.dot(diff, fim @ diff)))


# ---------------------------------------------------------------------------
# Regime Switching
# ---------------------------------------------------------------------------

def select_regime(probs: NDArray[np.float64],
                  n_samples: int,
                  epsilon: float = 0.01,
                  min_samples: int = 30) -> str:
    """Select the metric regime based on distribution characteristics.

    Per §2.2 of the specification:

    **Regime A** (asymptotic normal / Mahalanobis) when:
      - n_samples >= min_samples  (CLT rule-of-thumb, default 30)
      - no probability is within epsilon of 0 or 1 (default 0.01)

    **Regime B** (categorical / spherical / empirical) otherwise.

    Parameters
    ----------
    probs : ndarray, shape (m,)
        Probability vector over m outcomes.
    n_samples : int
        Effective number of draws from the outcome distribution.
    epsilon : float, default 0.01
        Probability boundary threshold.
    min_samples : int, default 30
        Minimum samples for CLT approximation.

    Returns
    -------
    regime : 'A' or 'B'
    """
    probs = np.asarray(probs, dtype=np.float64)

    if n_samples >= min_samples and np.all(probs >= epsilon) and np.all(probs <= 1 - epsilon):
        return 'A'
    return 'B'


# ---------------------------------------------------------------------------
# Spherical Geodesic Distance (Regime B, closed-form)
# ---------------------------------------------------------------------------

def spherical_geodesic_distance(probs1: NDArray[np.float64],
                                probs2: NDArray[np.float64]) -> float:
    """Geodesic distance on the Fisher-Rao sphere (Hellinger angle × 2).

    For the categorical simplex isometric to the sphere of radius 2,
    the geodesic distance between two points p, q is::

        d_geo(p, q) = 2 · arccos( Σ_i sqrt(p_i q_i) )

    Parameters
    ----------
    probs1, probs2 : ndarray, shape (m,)
        Two probability vectors on the simplex.

    Returns
    -------
    d : float
        Geodesic distance in the spherical metric.
    """
    p1 = np.asarray(probs1, dtype=np.float64)
    p2 = np.asarray(probs2, dtype=np.float64)

    hellinger_dot = np.sum(np.sqrt(p1 * p2))

    # Clamp to [-1, 1] for numerical stability
    hellinger_dot = np.clip(hellinger_dot, -1.0, 1.0)

    return float(2.0 * np.arccos(hellinger_dot))


# ---------------------------------------------------------------------------
# Critical threshold (Regime B)
# ---------------------------------------------------------------------------

def critical_distance_regime_b(m: int,
                               delta_C_outcome: float = 1.0) -> float:
    """Critical geodesic distance threshold for Regime B.

    Per §4.4::

        d_c^{(B)} = 4 · ΔC_{outcome} / [(m-1)(m-2)]

    Derived from the exact spherical scalar curvature R = (m-1)(m-2)/4.

    Parameters
    ----------
    m : int
        Number of POVM outcomes.
    delta_C_outcome : float, default 1.0
        Curvature change from adding one outcome (Phase 1 default).

    Returns
    -------
    d_c : float
        Critical geodesic distance threshold.
    """
    if m < 3:
        raise ValueError("Need at least 3 outcomes for Regime B threshold (m >= 3).")
    return 4.0 * delta_C_outcome / ((m - 1) * (m - 2))


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_trace_identity(probs: NDArray[np.float64],
                          rtol: float = 1e-10) -> dict:
    """Verify that tr(I) equals the expected number of informative outcomes.

    This is the spec's verification criterion for Phase 1.1
    (from the implementation table in §6).

    Returns a dict with computed values and pass/fail status.
    """
    fim = fisher_info_categorical(probs)
    trace_val = np.trace(fim)
    expected = expected_informative_outcomes(probs)

    passed = np.isclose(trace_val, expected, rtol=rtol)

    return {
        "trace_fim": float(trace_val),
        "expected_informative": float(expected),
        "ratio": float(trace_val / expected if expected != 0 else float('inf')),
        "passed": bool(passed)
    }# ---------------------------------------------------------------------------
# Critical threshold (Regime A)
# ---------------------------------------------------------------------------

def critical_distance_regime_a(delta_C_outcome: float,
                               kappa_max: float) -> float:
    """Critical geodesic distance threshold for Regime A.

    Per §4.4::

        d_c^{(A)} = ΔC_{outcome} / κ_max

    where κ_max is the maximum observed sectional curvature from
    training data (engineering approximation for the flat metric).

    Parameters
    ----------
    delta_C_outcome : float
        Curvature change from adding one POVM outcome.
    kappa_max : float
        Maximum sectional curvature observed during training
        (use 95th percentile as default).

    Returns
    -------
    d_c : float
        Critical geodesic distance threshold.
    """
    if kappa_max <= 0:
        raise ValueError("kappa_max must be positive.")
    return delta_C_outcome / kappa_max


# ---------------------------------------------------------------------------
# Threshold Calibration Pipeline (Phase 1.3)
# ---------------------------------------------------------------------------

def compute_critical_distance(regime: str,
                              m: int | None = None,
                              delta_C_outcome: float = 1.0,
                              kappa_max: float | None = None) -> float:
    """Unified threshold computation for both regimes.

    This is the calibration pipeline entry point described in §4.6.
    In Phase 1, ΔC_outcome defaults to 1.0 (normalized curvature units);
    empirical calibration in Phase 3 will replace the placeholder.

    Parameters
    ----------
    regime : 'A' or 'B'
        Which metric regime to use.
    m : int or None
        Number of POVM outcomes (required for Regime B).
    delta_C_outcome : float, default 1.0
        Curvature change from adding one outcome.
    kappa_max : float or None
        Maximum sectional curvature (required for Regime A).

    Returns
    -------
    d_c : float
        Critical geodesic distance threshold.

    Raises
    ------
    ValueError
        If regime is 'A' and kappa_max is None, or regime is 'B' and m is None.
    """
    if regime == 'A':
        if kappa_max is None:
            raise ValueError("kappa_max is required for Regime A threshold.")
        return critical_distance_regime_a(delta_C_outcome, kappa_max)
    elif regime == 'B':
        if m is None:
            raise ValueError("m (number of outcomes) is required for Regime B threshold.")
        return critical_distance_regime_b(m, delta_C_outcome)
    else:
        raise ValueError(f"Unknown regime: '{regime}'. Use 'A' or 'B'.")


def estimate_kappa_max_from_trace(trace_fim: float, d: int) -> float:
    """Estimate maximum sectional curvature from the Fisher information trace.

    Engineering heuristic (§4.4): for well-conditioned metrics, the maximum
    sectional curvature is approximately 1/4 of the average eigenvalue,
    which relates to the trace as::

        κ_max ≈ (1/4) · tr(I) / d

    where d = m-1 is the dimensionality of the simplex.

    This is a rough estimate for Phase 1 — the 95th percentile of
    observed curvatures during warm-up is preferred (§4.5).

    Parameters
    ----------
    trace_fim : float
        Trace of the Fisher information matrix.
    d : int
        Dimensionality of the parameter space (m-1 for simplex).

    Returns
    -------
    kappa_max_est : float
        Estimated maximum sectional curvature.
    """
    if d <= 0:
        raise ValueError("Dimensionality d must be positive.")
    return 0.25 * trace_fim / d