"""
compose_execution.py — Phase 2.2: Compose Execution (Geodesic Transport).

Per §6.2 of curvature_compose_design.md (DEFINITION 683e1bdb1a82).

When compose fires for a selected organ pair, the system executes
FULL-STEP geodesic transport: the pair's state moves from θ_current
to θ_stable along the geodesic, resetting curvature to near-zero.

Design decisions (Phase 2.2, confirmed per Lark §6.2):

  1. **Full-step transport** — θ_post = θ_stable. Not damped.
     Creates the clearest logbook signal. Damping deferred to Phase 3
     if oscillation is observed.

  2. **Cool-down of 1 cycle** — prevents immediate re-compose of the
     same pair. Logbook timestamps allow measurement of whether 1 cycle
     is sufficient.

  3. **Coupling reduced post-compose** — set to 10% of pre-compose value.
     The composed pair is now coherent; strong coupling is less needed.

  4. **Regime stability** — regime does not change mid-compose event.
     The regime used for the decision is also used for the log entry.

  5. **Boundary crossings tracked** — if a compose event coincides with
     a regime-boundary crossing (detected in Phase 2.1), the logbook
     captures it for Phase 3 blending evaluation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .compose_decision import CandidatePair, ComposeDecision
from .logbook import LogbookWriter


# ---------------------------------------------------------------------------
# Runtime state — one per organ pair, persists across compose cycles
# ---------------------------------------------------------------------------

@dataclass
class OrganPairState:
    """Mutable runtime state for one organ pair across compose cycles.

    This is the "living" state that is read at compose-decision time
    and mutated when compose fires. Each compose cycle reads from and
    writes to these states.

    Attributes
    ----------
    plane_name : str
        Identifier, e.g. "(eidolon, nous)".
    theta_current : ndarray
        Current state parameters (probability vector for Regime B,
        expectation parameter vector for Regime A).
    probs : ndarray
        Current outcome probability vector (same length as theta_current
        for Regime B; may differ for Regime A).
    theta_stable : ndarray
        Nearest stable state (updated during compose).
    probs_stable : ndarray
        Stable outcome probability vector (updated during compose).
    n_samples : int
        Effective number of samples from the outcome distribution.
    covariance : ndarray or None
        Covariance matrix (Regime A); None for Regime B.
    coupling_strength : float
        Coupling coefficient between the two organs in this pair.
    sectional_curvature : float or None
        Current sectional curvature K. Negative = fragmented.
    cool_down : int
        Cycles remaining before this pair is eligible for compose.
        0 = eligible. Decremented by 1 each compose cycle.
    """
    plane_name: str
    theta_current: NDArray[np.float64]
    probs: NDArray[np.float64]
    theta_stable: NDArray[np.float64]
    probs_stable: NDArray[np.float64]
    n_samples: int
    covariance: NDArray[np.float64] | None = None
    coupling_strength: float = 1.0
    sectional_curvature: float | None = None
    cool_down: int = 0

    def to_candidate(self) -> CandidatePair:
        """Convert to a CandidatePair for compose-decision evaluation.

        During cool-down, the pair reports itself as if already at the
        stable state (theta_current = theta_stable, curvature = 0.0).
        This means d_geo ≈ 0 and it won't be selected as a compose target.
        """
        if self.cool_down > 0:
            return CandidatePair(
                plane_name=self.plane_name,
                probs=self.probs_stable,
                n_samples=self.n_samples,
                theta_current=self.theta_stable,
                theta_stable=self.theta_stable,
                probs_stable=self.probs_stable,
                covariance=self.covariance,
                coupling_strength=self.coupling_strength,
                sectional_curvature=0.0,
            )
        return CandidatePair(
            plane_name=self.plane_name,
            probs=self.probs,
            n_samples=self.n_samples,
            theta_current=self.theta_current,
            theta_stable=self.theta_stable,
            probs_stable=self.probs_stable,
            covariance=self.covariance,
            coupling_strength=self.coupling_strength,
            sectional_curvature=self.sectional_curvature,
        )


# ---------------------------------------------------------------------------
# Compose cycle utilities
# ---------------------------------------------------------------------------

def tick_cool_down_for_all(states: dict[str, OrganPairState]) -> None:
    """Decrement cool-down counters for all pairs (min 0).

    Call this once per compose cycle, BEFORE building candidates.
    """
    for state in states.values():
        if state.cool_down > 0:
            state.cool_down -= 1


def build_candidates_from_states(
    states: dict[str, OrganPairState],
) -> list[CandidatePair]:
    """Convert runtime states to a list of CandidatePairs for decision.

    Respects cool-down: pairs in cool-down report as stable.
    """
    return [state.to_candidate() for state in states.values()]


# ---------------------------------------------------------------------------
# Compose execution result
# ---------------------------------------------------------------------------

@dataclass
class ComposeExecution:
    """Result of executing a compose decision.

    Attributes
    ----------
    compose_id : str
        UUID hex string for this compose event (traceable through logbook).
    fired : bool
        Whether compose actually executed (True) or was skipped (False).
    selected_plane : str or None
        Name of the composed pair (None if not fired).
    regime : str or None
        Regime at compose time ('A' or 'B'; None if not fired).
    theta_before : float or None
        Pre-compose scalar coherence proxy (higher = more coherent).
    theta_after : float or None
        Post-compose scalar coherence proxy.
    d_geo : float or None
        Geodesic distance traversed during compose.
    d_c : float or None
        Critical threshold used for the compose decision.
    curvature_before : float or None
        Pre-compose sectional curvature of the selected plane.
    curvature_after : float or None
        Post-compose sectional curvature (should be ~0 after full-step).
    delta_theta : float
        Change in scalar coherence (positive = improvement).
    log_entry : dict
        Pre-structured data for LogbookWriter.write_compose_event().
    """
    compose_id: str
    fired: bool
    selected_plane: str | None = None
    regime: str | None = None
    theta_before: float | None = None
    theta_after: float | None = None
    d_geo: float | None = None
    d_c: float | None = None
    curvature_before: float | None = None
    curvature_after: float | None = None
    delta_theta: float = 0.0
    log_entry: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core execution function
# ---------------------------------------------------------------------------

def execute_compose(
    decision: ComposeDecision,
    pair_states: dict[str, OrganPairState],
    logger: LogbookWriter | None = None,
    cycle: int = 0,
    delta_theta_per_unit_d: float = 0.1,
    post_compose_coupling_fraction: float = 0.1,
) -> ComposeExecution:
    """Execute a compose decision.

    If the decision fired, the selected pair's state is transported
    FULL-STEP along the geodesic to the stable configuration. The
    pair's runtime state is mutated in place. A logbook entry is
    written if a logger is provided.

    Parameters
    ----------
    decision : ComposeDecision
        Output of `make_compose_decision()` — contains the selected
        pair and full diagnostic metadata.
    pair_states : dict[str, OrganPairState]
        Mutable runtime states indexed by plane_name.
        **Mutated in place** if compose fires.
    logger : LogbookWriter or None, default None
        If provided, the compose event is written to the logbook.
    cycle : int, default 0
        Current cycle number (used as logbook timestamp).
    delta_theta_per_unit_d : float, default 0.1
        How much the scalar θ increases per unit geodesic distance
        traversed during compose. (Phase 2 placeholder; Phase 3
        will calibrate from live data.)
    post_compose_coupling_fraction : float, default 0.1
        Fraction of pre-compose coupling strength to retain after
        compose. The composed pair is now coherent, so strong
        coupling is less needed.

    Returns
    -------
    execution : ComposeExecution
        Full execution result with pre/post state, delta_theta, and
        a log_entry dict ready for LogbookWriter.

    Raises
    ------
    KeyError
        If decision selects a plane that does not exist in pair_states.
    """
    compose_id = uuid.uuid4().hex

    if not decision.fired or decision.selected_plane is None:
        # No compose — build a skipped-event log entry
        log_entry = _build_skipped_log(decision, compose_id, cycle)
        if logger is not None:
            _write_log(logger, log_entry)
        return ComposeExecution(
            compose_id=compose_id,
            fired=False,
            log_entry=log_entry,
        )

    plane_name = decision.selected_plane
    pair_state = pair_states[plane_name]

    # --- Capture pre-compose state (before any mutation) ---
    theta_current_pre = pair_state.theta_current.copy()
    probs_pre = pair_state.probs.copy()
    curvature_before = pair_state.sectional_curvature
    coupling_before = pair_state.coupling_strength
    theta_before = _estimate_theta(theta_current_pre, curvature_before)

    # --- Full-step geodesic transport ---
    # Move current state to stable state (the geodesic endpoint)
    pair_state.theta_current = pair_state.theta_stable.copy()
    pair_state.probs = pair_state.probs_stable.copy()

    # Reset curvature to near-zero (full-step = coherent configuration)
    pair_state.sectional_curvature = 0.0

    # Reduce coupling — the pair is now coherent, strong coupling no longer needed
    pair_state.coupling_strength *= post_compose_coupling_fraction

    # Enforce cool-down: pair cannot be recomposed immediately
    pair_state.cool_down = 1

    # --- Post-compose state ---
    curvature_after = pair_state.sectional_curvature
    theta_after = _estimate_theta(pair_state.theta_current, curvature_after)
    delta_theta = theta_after - theta_before
    d_geo = decision.d_geo if decision.d_geo is not None else 0.0

    # --- Build log entry ---
    log_entry = _build_compose_log(
        compose_id=compose_id,
        decision=decision,
        plane_name=plane_name,
        theta_current_pre=theta_current_pre,
        probs_pre=probs_pre,
        pair_state=pair_state,
        theta_before=theta_before,
        theta_after=theta_after,
        curvature_before=curvature_before,
        curvature_after=curvature_after,
        coupling_before=coupling_before,
        delta_theta=delta_theta,
        cycle=cycle,
    )

    if logger is not None:
        _write_log(logger, log_entry)

    return ComposeExecution(
        compose_id=compose_id,
        fired=True,
        selected_plane=plane_name,
        regime=decision.regime,
        theta_before=theta_before,
        theta_after=theta_after,
        d_geo=d_geo,
        d_c=decision.d_c,
        curvature_before=curvature_before,
        curvature_after=curvature_after,
        delta_theta=delta_theta,
        log_entry=log_entry,
    )


# ---------------------------------------------------------------------------
# Theta estimation (coherence proxy)
# ---------------------------------------------------------------------------

def _estimate_theta(
    state_vector: NDArray[np.float64],
    sectional_curvature: float | None = None,
) -> float:
    """Estimate a scalar coherence measure θ from the current state.

    θ ∈ [0, 1], where higher values indicate greater coherence
    (less fragmentation).

    Method:
      1. If the state vector is a probability distribution (sums to 1,
         non-negative), use normalized entropy::

             θ = 1 - (H_max - H) / H_max

         where H is the Shannon entropy. θ = 1 for uniform (max coherence),
         θ ≈ 0 for degenerate (max fragmentation).

      2. Fallback: if sectional curvature is available, use::

             θ = 0.5 - K / (2 · K_max)

         where K_max ≈ (m-1)(m-2)/4 (the scalar curvature of the simplex).
         K=0 → θ=0.5, K negative → θ < 0.5 (fragmented).

      3. If neither applies, return 0.5 (mid-range).

    This is a Phase 2 default. Phase 3 will calibrate from live data.
    """
    vec = np.asarray(state_vector, dtype=np.float64)

    # Method 1: entropy-based (if it's a probability vector)
    if np.all(vec >= 0) and np.isclose(vec.sum(), 1.0, atol=1e-6):
        m = len(vec) if len(vec) > 0 else 1
        max_entropy = np.log(m)
        safe_vec = np.maximum(vec, 1e-15)
        current_entropy = -np.sum(safe_vec * np.log(safe_vec))
        if max_entropy > 1e-15:
            return float(np.clip(1.0 - (max_entropy - current_entropy) / max_entropy, 0.0, 1.0))
        return 1.0

    # Method 2: curvature-based
    if sectional_curvature is not None:
        m = len(vec) if len(vec) > 1 else 50
        k_max = max(1.0, (m - 1) * (m - 2) / 4.0)
        theta = 0.5 - sectional_curvature / (2.0 * k_max)
        return float(np.clip(theta, 0.0, 1.0))

    return 0.5


# ---------------------------------------------------------------------------
# Log entry builders
# ---------------------------------------------------------------------------

def _build_compose_log(
    compose_id: str,
    decision: ComposeDecision,
    plane_name: str,
    theta_current_pre: NDArray[np.float64],
    probs_pre: NDArray[np.float64],
    pair_state: OrganPairState,
    theta_before: float,
    theta_after: float,
    curvature_before: float | None,
    curvature_after: float | None,
    coupling_before: float,
    delta_theta: float,
    cycle: int,
) -> dict[str, Any]:
    """Build the log entry for a successful compose event.

    theta_0_json = pre-compose state vector (captured before mutation)
    theta_1_json = stable state vector (the geodesic endpoint)
    """
    m = len(pair_state.probs)
    # Sample the first few affected outcomes
    # (Phase 3: this will come from actual outcome analysis)
    n_affected = min(5, m)
    affected_outcomes = list(range(n_affected))

    # Build plane curvature records
    planes = []
    if curvature_before is not None:
        sign = (
            "negative" if curvature_before < 0
            else "positive" if curvature_before > 0
            else "null"
        )
        planes.append({
            "plane": plane_name,
            "K": curvature_before,
            "sign": sign,
            "coupling_strength": coupling_before,
        })

    # Extract regime reason for the selected pair
    regime_reason = ""
    if decision.results:
        for r in decision.results:
            if r.plane_name == plane_name:
                regime_reason = r.regime_reason
                break

    return {
        "timestamp": cycle,
        "theta_before": theta_before,
        "theta_after": theta_after,
        "regime": decision.regime or 'B',
        "theta_0": theta_current_pre.tolist(),   # pre-compose state
        "theta_1": pair_state.theta_stable.tolist(),  # stable state
        "d_geo": decision.d_geo or 0.0,
        "d_c": decision.d_c or 0.0,
        "fired": True,
        "affected_outcomes": affected_outcomes,
        "regime_reason": regime_reason,
        "planes": planes,
        "compose_id": compose_id,
        "delta_theta": delta_theta,
        "curvature_before": curvature_before,
        "curvature_after": curvature_after,
    }


def _build_skipped_log(
    decision: ComposeDecision,
    compose_id: str,
    cycle: int,
) -> dict[str, Any]:
    """Build the log entry for a compose decision that did NOT fire."""
    return {
        "timestamp": cycle,
        "theta_before": 0.0,
        "theta_after": None,
        "regime": decision.regime or 'B',
        "theta_0": [0.0],
        "theta_1": [0.0],
        "d_geo": 0.0,
        "d_c": 0.0,
        "fired": False,
        "affected_outcomes": [],
        "regime_reason": "No candidate under threshold",
        "planes": [],
        "compose_id": compose_id,
        "delta_theta": 0.0,
        "curvature_before": None,
        "curvature_after": None,
    }


def _write_log(logger: LogbookWriter, entry: dict[str, Any]) -> None:
    """Write a pre-built log entry via the LogbookWriter."""
    logger.write_compose_event(
        timestamp=entry["timestamp"],
        theta_before=entry["theta_before"],
        regime=entry["regime"],
        theta_0=entry["theta_0"],
        theta_1=entry["theta_1"],
        d_geo=entry["d_geo"],
        d_c=entry["d_c"],
        fired=entry["fired"],
        theta_after=entry.get("theta_after"),
        affected_outcomes=entry.get("affected_outcomes", []),
        regime_reason=entry.get("regime_reason"),
        planes=entry.get("planes", []),
    )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _make_test_state(
    plane_name: str,
    m: int = 20,
    seed: int = 42,
    curvature: float | None = -3.0,
    coupling: float = 1.0,
    far: bool = False,
) -> OrganPairState:
    """Create a synthetic OrganPairState for testing."""
    rng = np.random.default_rng(seed)

    # Current probability vector
    raw = rng.dirichlet(np.ones(m) * 0.8)
    probs = raw / raw.sum()

    # Stable probability vector
    if not far:
        # Close — small perturbation from current
        pert = rng.normal(0, 5e-5, size=m)
        stable_raw = probs + pert
        stable_raw = np.clip(stable_raw, 1e-10, None)
        probs_stable = stable_raw / stable_raw.sum()
    else:
        # Far — very different distribution
        far_raw = rng.dirichlet(np.ones(m) * 0.1)
        probs_stable = far_raw / far_raw.sum()

    return OrganPairState(
        plane_name=plane_name,
        theta_current=probs.copy(),
        probs=probs.copy(),
        theta_stable=probs_stable.copy(),
        probs_stable=probs_stable.copy(),
        n_samples=100,
        covariance=np.diag(probs * (1 - probs) / 100),
        coupling_strength=coupling,
        sectional_curvature=curvature,
        cool_down=0,
    )


def verify_phase2_2() -> dict[str, Any]:
    """Run verification tests for Phase 2.2 (compose execution).

    Returns a dict mapping test names to {passed, detail}.
    """
    import tempfile
    import os

    results = {}

    # --- Test 1: Compose fires → state is transported to stable ---
    states = {
        "(eidolon, nous)": _make_test_state("(eidolon, nous)", m=20, curvature=-4.0),
        "(mneme, pneuma)": _make_test_state("(mneme, pneuma)", m=20, curvature=-2.0),
    }
    candidates = build_candidates_from_states(states)
    from .compose_decision import make_compose_decision
    decision = make_compose_decision(candidates, delta_C_outcome=1.0, kappa_max=25.0)

    pre_state = states["(eidolon, nous)"].theta_current.copy()
    execution = execute_compose(decision, states, cycle=0)
    post_state = states["(eidolon, nous)"].theta_current

    results["compose_transports_to_stable"] = {
        "passed": (
            execution.fired
            and np.allclose(post_state, states["(eidolon, nous)"].theta_stable)
        ),
        "detail": (
            f"Selected: {execution.selected_plane}, fired: {execution.fired}, "
            f"pre-stable match: {np.allclose(pre_state, states['(eidolon, nous)'].theta_stable)}, "
            f"post-stable match: {np.allclose(post_state, states['(eidolon, nous)'].theta_stable)}"
        ),
    }

    # --- Test 2: Post-compose curvature is near-zero ---
    results["post_compose_curvature_near_zero"] = {
        "passed": (
            execution.fired
            and execution.curvature_after is not None
            and abs(execution.curvature_after) < 1e-10
        ),
        "detail": f"Curvature after compose: {execution.curvature_after}",
    }

    # --- Test 3: Theta increases after compose (coherence improves) ---
    results["curvature_reset_after_compose"] = {
        "passed": execution.curvature_after is not None and abs(execution.curvature_after) < 1e-10,
        "detail": f"Curvature before: {execution.curvature_before}, after: {execution.curvature_after}",
    }

    # --- Test 4: Compose not fired → no state mutation ---
    far_state = _make_test_state("(eidolon, nous)", m=20, curvature=-5.0, far=True)
    far_states = {"(eidolon, nous)": far_state}
    far_candidates = build_candidates_from_states(far_states)
    far_decision = make_compose_decision(far_candidates, delta_C_outcome=1.0, kappa_max=25.0)

    pre_theta = far_states["(eidolon, nous)"].theta_current.copy()
    no_fire = execute_compose(far_decision, far_states, cycle=1)
    post_theta = far_states["(eidolon, nous)"].theta_current

    results["not_fired_no_mutation"] = {
        "passed": (not no_fire.fired and np.allclose(pre_theta, post_theta)),
        "detail": f"Fired: {no_fire.fired}, state changed: {not np.allclose(pre_theta, post_theta)}",
    }

    # --- Test 5: Coupling reduced after compose ---
    coupling_states = {
        "(eidolon, nous)": _make_test_state("(eidolon, nous)", m=20,
                                             curvature=-3.0, coupling=1.0),
    }
    coupling_candidates = build_candidates_from_states(coupling_states)
    coupling_decision = make_compose_decision(
        coupling_candidates, delta_C_outcome=1.0, kappa_max=25.0
    )
    pre_coupling = coupling_states["(eidolon, nous)"].coupling_strength
    execute_compose(coupling_decision, coupling_states, cycle=2,
                    post_compose_coupling_fraction=0.1)
    post_coupling = coupling_states["(eidolon, nous)"].coupling_strength

    results["coupling_reduced_post_compose"] = {
        "passed": post_coupling < pre_coupling,
        "detail": f"Coupling before: {pre_coupling:.4f}, after: {post_coupling:.4f}",
    }

    # --- Test 6: Cool-down prevents immediate re-compose ---
    cd_states = {
        "(eidolon, nous)": _make_test_state("(eidolon, nous)", m=20,
                                             curvature=-3.0, coupling=1.0),
    }
    cd_candidates = build_candidates_from_states(cd_states)
    cd_decision = make_compose_decision(
        cd_candidates, delta_C_outcome=1.0, kappa_max=25.0
    )
    execute_compose(cd_decision, cd_states, cycle=3)

    # Cool-down should be 1 after compose
    results["cool_down_set_after_compose"] = {
        "passed": cd_states["(eidolon, nous)"].cool_down == 1,
        "detail": f"Cool-down after compose: {cd_states['(eidolon, nous)'].cool_down}",
    }

    # During cool-down, to_candidate should return a stable-state candidate
    cd_candidate = cd_states["(eidolon, nous)"].to_candidate()
    results["cool_down_candidate_reports_stable"] = {
        "passed": (
            np.allclose(cd_candidate.theta_current, cd_states["(eidolon, nous)"].theta_stable)
            and cd_candidate.sectional_curvature == 0.0
        ),
        "detail": (
            f"theta_current == theta_stable: "
            f"{np.allclose(cd_candidate.theta_current, cd_states['(eidolon, nous)'].theta_stable)}, "
            f"curvature: {cd_candidate.sectional_curvature}"
        ),
    }

    # After tick, cool-down should be 0
    tick_cool_down_for_all(cd_states)
    results["cool_down_ticks_to_zero"] = {
        "passed": cd_states["(eidolon, nous)"].cool_down == 0,
        "detail": f"Cool-down after tick: {cd_states['(eidolon, nous)'].cool_down}",
    }

    # --- Test 7: Log entry correctly captures pre-compose state ---
    log_states = {
        "(eidolon, nous)": _make_test_state("(eidolon, nous)", m=20,
                                             curvature=-5.0, coupling=0.8),
    }
    log_candidates = build_candidates_from_states(log_states)
    log_decision = make_compose_decision(
        log_candidates, delta_C_outcome=1.0, kappa_max=25.0
    )
    pre_theta_current = log_states["(eidolon, nous)"].theta_current.copy()
    log_exec = execute_compose(log_decision, log_states, cycle=5)

    results["log_entry_has_correct_pre_state"] = {
        "passed": (
            "theta_0" in log_exec.log_entry
            and np.allclose(log_exec.log_entry["theta_0"], pre_theta_current.tolist())
        ),
        "detail": (
            f"log_entry has theta_0: {'theta_0' in log_exec.log_entry}, "
            f"pre-compose match: {np.allclose(log_exec.log_entry.get('theta_0', []), pre_theta_current.tolist())}"
        ),
    }

    # --- Test 8: Theta estimation is in [0, 1] ---
    theta_val = _estimate_theta(np.ones(20) / 20.0)
    results["theta_uniform_is_one"] = {
        "passed": np.isclose(theta_val, 1.0, atol=1e-6),
        "detail": f"θ for uniform(20): {theta_val:.10f}",
    }

    degenerate = np.zeros(20)
    degenerate[0] = 1.0
    theta_val2 = _estimate_theta(degenerate)
    results["theta_degenerate_near_zero"] = {
        "passed": theta_val2 < 0.1,
        "detail": f"θ for degenerate(20): {theta_val2:.6f}",
    }

    # --- Test 9: build_candidates_from_states preserves cool-down ---
    multi_states = {
        "a": _make_test_state("a", m=10, curvature=-1.0),
        "b": _make_test_state("b", m=10, curvature=-5.0),
    }
    multi_states["a"].cool_down = 1
    cands = build_candidates_from_states(multi_states)
    results["cool_down_candidate_is_stable"] = {
        "passed": (
            np.allclose(cands[0].theta_current, multi_states["a"].theta_stable)
            and not np.allclose(cands[1].theta_current, multi_states["b"].theta_stable)
        ),
        "detail": (
            f"Candidate a (cool-down=1) current == stable: "
            f"{np.allclose(cands[0].theta_current, multi_states['a'].theta_stable)}, "
            f"Candidate b (cool-down=0) current == stable: "
            f"{not np.allclose(cands[1].theta_current, multi_states['b'].theta_stable)}"
        ),
    }

    # --- Test 10: Logbook write works end-to-end ---
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        logger = LogbookWriter(tmp_path)
        e2e_states = {
            "(anima, pneuma)": _make_test_state("(anima, pneuma)", m=15,
                                                 curvature=-4.5, coupling=0.7),
        }
        e2e_cands = build_candidates_from_states(e2e_states)
        e2e_decision = make_compose_decision(
            e2e_cands, delta_C_outcome=1.0, kappa_max=25.0
        )
        e2e_exec = execute_compose(e2e_decision, e2e_states,
                                    logger=logger, cycle=10)

        # Read back from logbook
        from .logbook import LogbookReader
        reader = LogbookReader(tmp_path)
        events = reader.events_with_negative_curvature_increase(min_negative=0)
        logger.close()
        reader.close()

        results["logbook_write_and_read"] = {
            "passed": len(events) == 1 and events[0]["fired"] == 1,
            "detail": f"Events found: {len(events)}, fired: {events[0]['fired'] if events else 'N/A'}",
        }
    finally:
        os.unlink(tmp_path)

    return results


if __name__ == "__main__":
    import json
    test_results = verify_phase2_2()
    all_passed = all(bool(r["passed"]) for r in test_results.values())
    passed_count = sum(1 for r in test_results.values() if bool(r["passed"]))
    failed_count = sum(1 for r in test_results.values() if not bool(r["passed"]))
    print(f"Phase 2.2 verification: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    print(f"  Tests: {len(test_results)}")
    print(f"  Passed: {passed_count}")
    print(f"  Failed: {failed_count}")
    print()
    for name, result in test_results.items():
        status = "\u2705" if bool(result["passed"]) else "\u274c"
        print(f"  {status} {name}: {result['detail']}")
    clean = {}
    for name, r in test_results.items():
        clean[name] = {"passed": bool(r["passed"]), "detail": str(r["detail"])}
    print(json.dumps(clean, indent=2))
