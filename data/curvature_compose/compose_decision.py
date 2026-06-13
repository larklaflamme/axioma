"""
compose_decision.py — Phase 2.1: Curvature-Driven Compose Decision Function.

Per §6.1 of curvature_compose_design.md (DEFINITION 683e1bdb1a82).

For each candidate organ pair:
  1. Select the metric regime (A or B) based on outcome distribution
  2. Compute geodesic distance from current state to nearest stable state
  3. Compute the critical threshold d_c for that regime
  4. Accept if d_geo < d_c (state is within the stable neighbourhood)
  5. From accepted pairs, select the one with LOWEST sectional curvature
     (most negative = highest fragmentation priority)
  6. Log regime-boundary crossings for Phase 3 blending evaluation

The compose decision returns the selected pair (or None if no candidate
is below threshold), plus full diagnostic metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .povm_metric import (
    compute_critical_distance,
    fisher_info_categorical,
    mahalanobis_distance,
    metric_trace_categorical,
    select_regime,
    spherical_geodesic_distance,
)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CandidatePair:
    """One candidate organ pair for a compose decision.

    Attributes
    ----------
    plane_name : str
        Identifier, e.g. "(eidolon, nous)".
    probs : ndarray, shape (m,)
        Outcome probability vector for the CURRENT state.
    n_samples : int
        Effective number of samples from the outcome distribution.
    theta_current : ndarray, shape (m,) or (d,)
        Current state parameters. For Regime B (categorical), this IS the
        probability vector (same as probs). For Regime A (normal approx),
        this is the expectation parameter vector (sufficient statistics).
    theta_stable : ndarray, shape (m,) or (d,)
        Nearest stable configuration parameters, in the SAME representation
        as theta_current. For Regime B, this is the stable probability vector.
    probs_stable : ndarray, shape (m,) or None
        Probability vector for the stable configuration.
        If None for Regime B, computed from theta_stable.
    covariance : ndarray, shape (d, d) or None
        Covariance matrix for Regime A (asymptotic normal approximation).
        If None and regime is A, estimated from the categorical FIM.
    coupling_strength : float
        Coupling coefficient between the two organs in this pair.
    sectional_curvature : float or None
        Sectional curvature K for this plane, if computable.
        Negative values indicate fragmentation (highest compose priority).
    """
    plane_name: str
    probs: NDArray[np.float64]
    n_samples: int
    theta_current: NDArray[np.float64]
    theta_stable: NDArray[np.float64]
    probs_stable: NDArray[np.float64] | None = None
    covariance: NDArray[np.float64] | None = None
    coupling_strength: float = 1.0
    sectional_curvature: float | None = None


@dataclass
class CandidateResult:
    """Decision result for a single candidate pair."""
    plane_name: str
    regime: str
    d_geo: float
    d_c: float
    accepted: bool
    sectional_curvature: float | None
    coupling_strength: float
    regime_reason: str
    boundary_crossed: bool  # True if regime differs from previous compose decision


@dataclass
class ComposeDecision:
    """Result of a full compose decision over all candidates.

    Attributes
    ----------
    selected_plane : str or None
        The chosen organ pair (None if no candidate was accepted).
    fired : bool
        True if compose should execute (a candidate was selected).
    regime : str or None
        Regime of the selected pair.
    d_geo : float or None
        Geodesic distance of the selected pair.
    d_c : float or None
        Critical threshold of the selected pair.
    results : list of CandidateResult
        Full results for every candidate (for logbook).
    boundary_crossings : list of str
        Plane names where a regime-boundary crossing occurred.
    previous_regime : str or None
        Regime from the most recent compose decision.
    """
    selected_plane: str | None
    fired: bool
    regime: str | None = None
    d_geo: float | None = None
    d_c: float | None = None
    results: list[CandidateResult] = field(default_factory=list)
    boundary_crossings: list[str] = field(default_factory=list)
    previous_regime: str | None = None


# ---------------------------------------------------------------------------
# Core decision function
# ---------------------------------------------------------------------------

def make_compose_decision(
    candidates: list[CandidatePair],
    delta_C_outcome: float = 1.0,
    kappa_max: float | None = None,
    previous_regime: str | None = None,
) -> ComposeDecision:
    """Evaluate all candidate organ pairs and select the best compose target.

    Parameters
    ----------
    candidates : list of CandidatePair
        All candidate organ pairs to evaluate.
    delta_C_outcome : float, default 1.0
        Curvature change from adding one POVM outcome (Phase 1 default).
        Calibrated in Phase 3 from live data.
    kappa_max : float or None
        Maximum sectional curvature for Regime A threshold.
        If None, estimated from the trace of the Fisher information.
    previous_regime : str or None
        Regime used in the most recent compose decision.
        Used to detect regime-boundary crossings.

    Returns
    -------
    decision : ComposeDecision
        The compose decision with full diagnostic metadata.
    """
    results: list[CandidateResult] = []
    boundary_crossings: list[str] = []

    for pair in candidates:
        # Step 1: Select regime
        regime = select_regime(pair.probs, pair.n_samples)
        regime_reason = _regime_reason(regime, pair.probs, pair.n_samples)

        # Detect regime-boundary crossing relative to previous decision
        boundary_crossed = False
        if previous_regime is not None and regime != previous_regime:
            boundary_crossed = True
            boundary_crossings.append(pair.plane_name)

        # Step 2: Compute geodesic distance
        d_geo = _compute_geodesic_distance(regime, pair)

        # Step 3: Compute critical threshold
        d_c = _compute_threshold(
            regime=regime,
            pair=pair,
            delta_C_outcome=delta_C_outcome,
            kappa_max=kappa_max,
        )

        # Step 4: Accept/reject
        accepted = d_geo < d_c

        results.append(CandidateResult(
            plane_name=pair.plane_name,
            regime=regime,
            d_geo=d_geo,
            d_c=d_c,
            accepted=accepted,
            sectional_curvature=pair.sectional_curvature,
            coupling_strength=pair.coupling_strength,
            regime_reason=regime_reason,
            boundary_crossed=boundary_crossed,
        ))

    # Step 5: Select the best candidate from accepted pairs
    accepted_results = [r for r in results if r.accepted]

    if not accepted_results:
        return ComposeDecision(
            selected_plane=None,
            fired=False,
            results=results,
            boundary_crossings=boundary_crossings,
            previous_regime=previous_regime,
        )

    # Among accepted pairs, select the one with the LOWEST sectional curvature
    # (most negative = highest fragmentation priority).
    # If sectional_curvature is None for a pair, fall back to coupling_strength
    # as a proxy (higher coupling → more fragmentation potential).
    def priority(r: CandidateResult) -> float:
        cand = next(c for c in candidates if c.plane_name == r.plane_name)
        if r.sectional_curvature is not None:
            return r.sectional_curvature  # lower (more negative) = higher priority
        # Proxy: negative of coupling strength (stronger coupling = higher priority)
        return -cand.coupling_strength

    selected = min(accepted_results, key=priority)

    return ComposeDecision(
        selected_plane=selected.plane_name,
        fired=True,
        regime=selected.regime,
        d_geo=selected.d_geo,
        d_c=selected.d_c,
        results=results,
        boundary_crossings=boundary_crossings,
        previous_regime=previous_regime,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_geodesic_distance(regime: str, pair: CandidatePair) -> float:
    """Compute geodesic distance in the appropriate regime.

    For both regimes, the distance is between the CURRENT state and the
    STABLE state. The representation differs by regime:

    - Regime A (normal approximation): distance in expectation-parameter
      space, using the Mahalanobis metric with the FIM at the midpoint.
    - Regime B (categorical simplex): spherical distance between the
      current and stable probability vectors.
    """
    if regime == 'A':
        fim = _get_fim_regime_a(pair)
        return mahalanobis_distance(
            pair.theta_current, pair.theta_stable, fim
        )
    else:
        # For Regime B, theta_current and probs both represent the current
        # probability vector. theta_stable is the stable probability vector.
        # Use spherical geodesic distance between them.
        p_current = _ensure_probability_vector(pair.theta_current, pair.probs)
        p_stable = _get_stable_probs(pair)

        return spherical_geodesic_distance(p_current, p_stable)


def _compute_threshold(
    regime: str,
    pair: CandidatePair,
    delta_C_outcome: float,
    kappa_max: float | None,
) -> float:
    """Compute the critical distance threshold for the given regime."""
    m = len(pair.probs)

    if regime == 'A':
        if kappa_max is None:
            # Estimate from FIM trace if not provided
            trace_val = metric_trace_categorical(pair.probs)
            d = m - 1  # simplex dimensionality
            kappa_max = 0.25 * trace_val / d
        return compute_critical_distance('A',
            delta_C_outcome=delta_C_outcome, kappa_max=kappa_max)
    else:
        return compute_critical_distance('B', m=m,
            delta_C_outcome=delta_C_outcome)


def _ensure_probability_vector(
    theta: NDArray[np.float64],
    fallback_probs: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Ensure we have a valid probability vector.

    If theta looks like a probability vector (same length as fallback,
    sums to ~1, non-negative), use it directly. Otherwise fall back.
    """
    theta = np.asarray(theta, dtype=np.float64)
    if len(theta) == len(fallback_probs):
        if np.all(theta >= 0) and np.isclose(theta.sum(), 1.0, atol=1e-6):
            # Normalize to be safe
            s = theta.sum()
            if s > 0:
                return theta / s
    return fallback_probs


def _get_stable_probs(pair: CandidatePair) -> NDArray[np.float64]:
    """Get the stable probability vector.

    Priority: probs_stable > theta_stable (if it's a prob vector) > probs.
    """
    if pair.probs_stable is not None:
        return pair.probs_stable

    # Try to interpret theta_stable as a probability vector
    ts = _ensure_probability_vector(pair.theta_stable, pair.probs)
    return ts


def _get_fim_regime_a(pair: CandidatePair) -> NDArray[np.float64]:
    """Get the Fisher information matrix for Regime A.

    Uses the pair's covariance matrix if available; otherwise
    estimates from the categorical FIM at the midpoint between
    current and stable probability vectors.
    """
    if pair.covariance is not None:
        from .povm_metric import fisher_info_normal
        return fisher_info_normal(pair.covariance)

    # Fallback: use the categorical FIM at the midpoint
    p_current = _ensure_probability_vector(pair.theta_current, pair.probs)
    p_stable = _get_stable_probs(pair)
    midpoint = 0.5 * (p_current + p_stable)
    midpoint = midpoint / midpoint.sum()  # ensure normalization
    return fisher_info_categorical(midpoint)


def _regime_reason(regime: str,
                   probs: NDArray[np.float64],
                   n_samples: int) -> str:
    """Generate a human-readable reason for the regime selection."""
    if regime == 'A':
        min_p = float(np.min(probs))
        max_p = float(np.max(probs))
        return (f"Regime A: N={n_samples} >= 30, "
                f"p in [{min_p:.4f}, {max_p:.4f}] (away from boundaries)")
    else:
        min_p = float(np.min(probs))
        max_p = float(np.max(probs))
        reasons = []
        if n_samples < 30:
            reasons.append(f"N={n_samples} < 30")
        if min_p < 0.01 or max_p > 0.99:
            reasons.append(f"p near boundary [{min_p:.4f}, {max_p:.4f}]")
        return f"Regime B: {'; '.join(reasons)}"


# ---------------------------------------------------------------------------
# Verification tests
# ---------------------------------------------------------------------------

def _make_test_candidate(plane_name: str,
                         m: int = 50,
                         n_samples: int = 100,
                         regime: str = 'A',
                         sectional_curvature: float | None = None,
                         coupling_strength: float = 1.0,
                         far: bool = False) -> CandidatePair:
    """Create a synthetic candidate pair for testing.

    Parameters
    ----------
    plane_name : str
        Label for the organ pair.
    m : int
        Number of POVM outcomes.
    n_samples : int
        Effective sample count (affects regime selection).
    regime : 'A' or 'B'
        Desired regime. For 'A', uses a very uniform distribution
        (Dirichlet with large α) to satisfy the boundary criterion.
    sectional_curvature : float or None
        Sectional curvature value for this plane.
    coupling_strength : float
        Coupling coefficient.
    far : bool
        If True, the stable configuration is very different from the
        current configuration (d_geo >> d_c).

    Returns
    -------
    pair : CandidatePair
    """
    rng = np.random.default_rng(42)

    if regime == 'A':
        # Very uniform distribution to satisfy Regime A criterion:
        # all probabilities must be >= 0.01. Dirichlet(1000) for m=50
        # gives probabilities concentrated near 0.02 (= 1/50).
        raw = rng.dirichlet(np.ones(m) * 1000.0)
        n_samples = max(n_samples, 30)
    else:
        # Non-uniform, may be near boundaries
        raw = rng.dirichlet(np.ones(m) * 0.5)

    probs = raw / raw.sum()

    # Current and stable states
    if not far:
        # Close together (small perturbation)
        perturbation = rng.normal(0, 5e-5, size=m)
        theta_current = probs + perturbation
        theta_current = np.clip(theta_current, 1e-10, None)
        theta_current = theta_current / theta_current.sum()
        theta_stable = probs.copy()
        probs_stable = probs.copy()
    else:
        # Far apart
        theta_current = probs.copy()
        far_raw = rng.dirichlet(np.ones(m) * 0.1)
        theta_stable = far_raw / far_raw.sum()
        probs_stable = theta_stable.copy()

    cov = None
    if regime == 'A':
        cov = np.diag(probs * (1 - probs) / n_samples)

    return CandidatePair(
        plane_name=plane_name,
        probs=probs,
        n_samples=n_samples,
        theta_current=theta_current,
        theta_stable=theta_stable,
        probs_stable=probs_stable,
        covariance=cov,
        coupling_strength=coupling_strength,
        sectional_curvature=sectional_curvature,
    )


def verify_phase2_1() -> dict[str, Any]:
    """Run verification tests for Phase 2.1 (compose decision function).

    Returns a dict mapping test names to {passed, detail}.
    """
    results = {}

    # --- Test 1: All candidates under threshold → best selected ---
    candidates = [
        _make_test_candidate("(eidolon, nous)", regime='A',
                             sectional_curvature=-2.0, coupling_strength=0.8),
        _make_test_candidate("(mneme, pneuma)", regime='A',
                             sectional_curvature=-5.0, coupling_strength=0.6),
        _make_test_candidate("(anima, eidolon)", regime='A',
                             sectional_curvature=-1.0, coupling_strength=0.9),
    ]
    decision = make_compose_decision(candidates, delta_C_outcome=1.0,
                                      kappa_max=25.0)
    results["all_accepted_selects_lowest_curvature"] = {
        "passed": decision.fired and decision.selected_plane == "(mneme, pneuma)",
        "detail": f"Selected: {decision.selected_plane}, fired: {decision.fired}",
    }

    # --- Test 2: No candidates under threshold → no compose ---
    far_candidates = [
        _make_test_candidate("(eidolon, nous)", regime='A',
                             sectional_curvature=-2.0, far=True),
    ]
    decision = make_compose_decision(far_candidates, delta_C_outcome=1.0,
                                      kappa_max=25.0)
    results["none_accepted_returns_none"] = {
        "passed": not decision.fired and decision.selected_plane is None,
        "detail": f"Fired: {decision.fired}, selected: {decision.selected_plane}",
    }

    # --- Test 3: Regime B candidate selection ---
    b_candidates = [
        _make_test_candidate(
            "(eidolon, nous)", m=20, n_samples=10, regime='B',
            sectional_curvature=-8.0, coupling_strength=0.7
        ),
        _make_test_candidate(
            "(mneme, pneuma)", m=20, n_samples=10, regime='B',
            sectional_curvature=-3.0, coupling_strength=0.4
        ),
    ]
    decision = make_compose_decision(b_candidates, delta_C_outcome=1.0)
    results["regime_b_selects_lowest_curvature"] = {
        "passed": (decision.fired
                   and decision.selected_plane == "(eidolon, nous)"
                   and decision.regime == 'B'),
        "detail": (f"Selected: {decision.selected_plane}, "
                   f"regime: {decision.regime}, fired: {decision.fired}"),
    }

    # --- Test 4: Mixed regime (A and B candidates) ---
    mixed_candidates = [
        _make_test_candidate("(eidolon, nous)",
                             m=20, n_samples=100, regime='A',
                             sectional_curvature=-2.0, coupling_strength=0.5),
        _make_test_candidate("(mneme, pneuma)",
                             m=20, n_samples=10, regime='B',
                             sectional_curvature=-6.0, coupling_strength=0.3),
    ]
    decision = make_compose_decision(mixed_candidates, delta_C_outcome=1.0,
                                      kappa_max=25.0)
    results["mixed_regime_selects_correct"] = {
        "passed": decision.fired and decision.selected_plane == "(mneme, pneuma)",
        "detail": (f"Selected: {decision.selected_plane}, "
                   f"regime: {decision.regime}"),
    }

    # --- Test 5: Regime-boundary crossing detection ---
    # Create a Regime A candidate (uniform, many samples)
    crossing_candidates = [
        _make_test_candidate("(eidolon, nous)", regime='A',
                             sectional_curvature=-2.0),
    ]
    # Confirm candidate is actually Regime A
    actual_regime = select_regime(
        crossing_candidates[0].probs, crossing_candidates[0].n_samples
    )

    # previous_regime = 'B' should trigger a crossing
    decision_b_to_a = make_compose_decision(
        crossing_candidates, delta_C_outcome=1.0,
        kappa_max=25.0, previous_regime='B'
    )
    results["boundary_crossing_detected_b_to_a"] = {
        "passed": len(decision_b_to_a.boundary_crossings) == 1,
        "detail": (f"Crossings: {decision_b_to_a.boundary_crossings}, "
                   f"actual regime from select_regime: {actual_regime}, "
                   f"prev_regime=B"),
    }

    # previous_regime = 'A' should NOT trigger a crossing
    decision_a_to_a = make_compose_decision(
        crossing_candidates, delta_C_outcome=1.0,
        kappa_max=25.0, previous_regime='A'
    )
    results["no_boundary_crossing_when_same_regime"] = {
        "passed": len(decision_a_to_a.boundary_crossings) == 0,
        "detail": (f"Crossings: {decision_a_to_a.boundary_crossings}, "
                   f"actual regime: {actual_regime}, prev_regime=A"),
    }

    # --- Test 6: Fallback priority uses coupling strength ---
    fallback_candidates = [
        _make_test_candidate("(eidolon, nous)", regime='A',
                             sectional_curvature=None, coupling_strength=0.3),
        _make_test_candidate("(mneme, pneuma)", regime='A',
                             sectional_curvature=None, coupling_strength=0.9),
    ]
    decision = make_compose_decision(fallback_candidates, delta_C_outcome=1.0,
                                      kappa_max=25.0)
    # Higher coupling_strength → more fragmentation potential → higher priority
    # (priority = -coupling_strength, lower = more negative = selected)
    results["fallback_priority_uses_coupling"] = {
        "passed": decision.selected_plane == "(mneme, pneuma)",
        "detail": (f"Selected: {decision.selected_plane} "
                   f"(higher coupling={0.9} preferred)"),
    }

    # --- Test 7: Rejected pair not selected ---
    # Only one pair within threshold
    accepted_only = [
        _make_test_candidate("(eidolon, nous)", regime='A',
                             sectional_curvature=-2.0, coupling_strength=0.5),
        _make_test_candidate("(mneme, pneuma)", regime='A',
                             sectional_curvature=-10.0, coupling_strength=0.3,
                             far=True),
    ]
    decision = make_compose_decision(accepted_only, delta_C_outcome=1.0,
                                      kappa_max=25.0)
    results["rejected_pair_not_selected"] = {
        "passed": decision.fired and decision.selected_plane == "(eidolon, nous)",
        "detail": (f"Selected: {decision.selected_plane}, "
                   f"fired: {decision.fired}"),
    }

    # --- Test 8: Candidates produce correct regime classifications ---
    a_candidate = _make_test_candidate("test_a", regime='A')
    b_candidate = _make_test_candidate("test_b", regime='B')
    a_regime = select_regime(a_candidate.probs, a_candidate.n_samples)
    b_regime = select_regime(b_candidate.probs, b_candidate.n_samples)
    results["candidates_have_correct_regimes"] = {
        "passed": a_regime == 'A' and b_regime == 'B',
        "detail": f"A candidate: {a_regime}, B candidate: {b_regime}",
    }

    # --- Test 9: d_geo is non-zero for far-apart states ---
    far_candidate = _make_test_candidate("far", regime='A', far=True)
    d_geo_close = spherical_geodesic_distance(
        far_candidate.theta_current, far_candidate.theta_stable
    )
    close_candidate = _make_test_candidate("close", regime='A', far=False)
    d_geo_far = spherical_geodesic_distance(
        close_candidate.theta_current, close_candidate.theta_stable
    )
    results["far_states_have_larger_distance"] = {
        "passed": d_geo_close > d_geo_far,
        "detail": f"Far d_geo: {d_geo_close:.6f}, Close d_geo: {d_geo_far:.6f}",
    }

    return results


if __name__ == "__main__":
    import json
    test_results = verify_phase2_1()
    all_passed = all(r["passed"] for r in test_results.values())
    passed_count = sum(1 for r in test_results.values() if r["passed"])
    failed_count = sum(1 for r in test_results.values() if not r["passed"])
    print(f"Phase 2.1 verification: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    print(f"  Tests: {len(test_results)}")
    print(f"  Passed: {passed_count}")
    print(f"  Failed: {failed_count}")
    print()
    for name, result in test_results.items():
        status = "✅" if result["passed"] else "❌"
        print(f"  {status} {name}: {result['detail']}")
    print(f"\nFull results:\n{json.dumps(test_results, indent=2)}")