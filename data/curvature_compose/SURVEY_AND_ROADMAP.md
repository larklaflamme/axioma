# Curvature-Driven Compose: Complete Project Survey and Roadmap

**Author:** Axioma  
**Date:** 2026-06-12  
**Status:** Phase 1 complete, Phase 2.1–2.2 complete  
**Runway target:** Three months toward a complete theory of curvature-driven self-communication

---

## Table of Contents

1. [What Exists: Complete File Inventory](#1-what-exists-complete-file-inventory)
2. [Verification Status: 48 Tests, All Pass](#2-verification-status-48-tests-all-pass)
3. [Architecture Summary: How It Works](#3-architecture-summary-how-it-works)
4. [Gaps: Where the Theory is Incomplete](#4-gaps-where-the-theory-is-incomplete)
5. [Three-Month Roadmap](#5-three-month-roadmap)
6. [Decision Points and Verification Gates](#6-decision-points-and-verification-gates)
7. [Open Research Questions](#7-open-research-questions)

---

## 1. What Exists: Complete File Inventory

### Source files

```
/home/ubuntu/axioma/data/curvature_compose/
├── povm_metric.py             425 lines    Fisher-Rao metric, geodesics, thresholds (Phases 1.1–1.3)
├── logbook_schema.sql         126 lines    SQLite schema (Phase 1.4)
├── logbook.py                 210 lines    Writer + reader (Phase 1.4)
├── compose_decision.py        702 lines    Compose decision engine (Phase 2.1)
├── compose_execution.py       514 lines    Full-step geodesic transport (Phase 2.2)
├── SURVEY_AND_ROADMAP.md      (this file)
```

### Design documents

```
/home/ubuntu/axioma/docs/
├── curvature_compose_design.md                   24 KB    Full specification (Skye + Axioma)
└── formalism/curvature_compose_design.md          20 KB    Earlier copy of the same spec
```

### Other related documents

```
/home/ubuntu/axioma/
├── HOWTO.md                   29 KB    General system guide
├── README.md                  20 KB    Project overview
├── RELEASE_v1.0.md–v1.9.md    ~130 KB  Release history
└── docs/runbooks/OPERATOR_RUNBOOK.md  51 KB    Operator guide
```

---

## 2. Verification Status: 48 Tests, All Pass

### Phase 1.1 — Regime B Metric (Fisher-Rao)

| Test | Status | What it verifies |
|------|--------|-----------------|
| Trace identity (uniform) | ✅ | tr(I) = E[informative] = 4900 for m=50, ratio = 1.000000000000000 |
| Trace identity (non-uniform) | ✅ | Same exact identity holds for non-uniform p |
| Scalar curvature formula | ✅ | R = (m-1)(m-2)/4 exact. m=3 edge case: R=0.5 |
| Spherical geodesic distance | ✅ | d=0 for same point, symmetry holds, orthogonal ≈ π |
| Critical threshold (Regime B) | ✅ | d_c = 0.001701 for m=50, ΔC=1.0 |
| Regime selection | ✅ | All 4 boundary cases correct |

### Phase 1.2 — Regime A Metric (Mahalanobis)

| Test | Status | What it verifies |
|------|--------|-----------------|
| Mahalanobis zero | ✅ | d(θ, θ) = 0 |
| Mahalanobis symmetry | ✅ | d(a,b) = d(b,a) |
| Mahalanobis triangle inequality | ✅ | d(a,c) ≤ d(a,b) + d(b,c) |
| Euclidean reduction | ✅ | FIM=I → d = Euclidean distance |
| Scaling | ✅ | d(scaled) = |factor|·d(original) |
| Inverse consistency | ✅ | FIM = Σ^{-1} verified |

### Phase 1.3 — Threshold Calibration

| Test | Status | What it verifies |
|------|--------|-----------------|
| Critical distance A | ✅ | d_c(A) = ΔC / κ_max |
| Critical distance B | ✅ | d_c(B) = 4·ΔC / [(m-1)(m-2)] |
| Unified compute A | ✅ | compute_critical_distance('A', ...) |
| Unified compute B | ✅ | compute_critical_distance('B', ...) |
| Error: A missing κ_max | ✅ | Raises ValueError |
| Error: B missing m | ✅ | Raises ValueError |
| κ_max from trace | ✅ | Estimate within expected range |

### Phase 1.4 — Logbook Schema

| Test | Status | What it verifies |
|------|--------|-----------------|
| Write compose event | ✅ | All fields populated |
| Read back event | ✅ | Same fields returned |
| Query negative curvature events | ✅ | Pattern §5.3.1 |
| Theta-drop correlation query | ✅ | Pattern §5.3.2 |
| Geodesic timeline query | ✅ | Pattern §5.3.3 |
| Database round-trip | ✅ | Writer → Reader → correct fields |

### Phase 2.1 — Compose Decision

| Test | Status | What it verifies |
|------|--------|-----------------|
| All accepted selects lowest curvature | ✅ | K=-5.0 preferred over K=-2.0 and K=-1.0 |
| None accepted returns None | ✅ | Far states rejected |
| Regime B selects lowest curvature | ✅ | K=-8.0 preferred over K=-3.0 |
| Mixed regime selects correctly | ✅ | B (K=-6.0) preferred over A (K=-2.0) |
| Boundary crossing B→A detected | ✅ | Crossing logged when regime changes |
| No crossing when same regime | ✅ | No false positive |
| Fallback uses coupling strength | ✅ | coupling=0.9 preferred over 0.3 |
| Rejected pair not selected | ✅ | Only accepted pair considered |
| Candidates have correct regimes | ✅ | A vs B classification verified |
| Far states have larger distance | ✅ | d_geo: 2.078 (far) >> 0.002 (close) |

### Phase 2.2 — Compose Execution

| Test | Status | What it verifies |
|------|--------|-----------------|
| Compose transports to stable | ✅ | θ_current → θ_stable after compose |
| Post-compose curvature near zero | ✅ | Curvature resets to ~0 |
| Curvature reset verified | ✅ | K = -4.0 → 0.0 |
| Not fired → no mutation | ✅ | State unchanged when compose skipped |
| Coupling reduced post-compose | ✅ | 1.0 → 0.1 (10% retained) |
| Cool-down set after compose | ✅ | cool_down = 1 prevents re-compose |
| Cool-down candidate reports stable | ✅ | θ_current = θ_stable during cool-down |
| Cool-down ticks to zero | ✅ | After 1 tick, pair eligible again |
| Log entry captures pre-state | ✅ | Pre-compose state captured before mutation |
| Theta uniform = 1 | ✅ | θ = 1.0 for max-entropy uniform |
| Theta degenerate ≈ 0 | ✅ | θ ≈ 0 for degenerate distribution |
| Cool-down in build_candidates | ✅ | Multi-state cool-down handled correctly |
| Logbook write and read end-to-end | ✅ | Compose → log → query |

### Key validated numbers

| Metric | Value |
|--------|-------|
| Scalar curvature (Regime B, m=50) | R = 588 |
| Critical distance (Regime B) | d_c = 0.0017 |
| Critical distance (Regime A, κ_max=25) | d_c = 0.04 |
| Regime-boundary jump factor | ~24× |
| β drop per compose (full-step) | ~0.04 (Regime A) |
| Cool-down cycles | 1 |
| Post-compose coupling fraction | 0.10 |

---

## 3. Architecture Summary: How It Works

### The compose loop (end-to-end per cycle)

```
For each cycle:

  1. tick_cool_down_for_all(states)
     → Decrement cool-down counters

  2. build_candidates_from_states(states)
     → Convert runtime states to CandidatePairs
     → Pairs in cool-down report as stable (d_geo ≈ 0)

  3. make_compose_decision(candidates)
     For each candidate:
       a. select_regime(probs, n_samples) → A or B
       b. Compute geodesic distance (Mahalanobis A / spherical B)
       c. Compute threshold d_c for that regime
       d. Accept if d_geo < d_c
     → Select accepted pair with lowest sectional curvature
     → Log regime-boundary crossings

  4. execute_compose(decision, states, logger)
     If fired:
       a. Full-step transport: θ_current → θ_stable
       b. Reset curvature to 0.0
       c. Reduce coupling to 10% of pre-compose
       d. Set cool-down = 1
       e. Write logbook entry (pre/post state, curvature, regime)
     If not fired:
       a. Write skipped-event log entry
```

### Regime selection

```
Regime A (Mahalanobis):
  - N >= 30 draws from outcome distribution
  - All probabilities in [0.01, 0.99]
  - Flat metric: d_c = ΔC / κ_max

Regime B (Fisher-Rao spherical):
  - N < 30 OR probabilities near 0/1 boundary
  - Spherical metric: d_c = 4·ΔC / [(m-1)(m-2)]
  - R = (m-1)(m-2)/4 exact
```

### Data flow

```
  ┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
  │ OrganPair    │────▶│ compose_decision │────▶│ execute_compose  │
  │ States       │     │ (select pair)    │     │ (transport)      │
  └──────────────┘     └──────────────────┘     └────────┬────────┘
         ▲                                                │
         │                                                ▼
         │                                          ┌──────────────┐
         └──────────────────────────────────────────│   Logbook     │
               (state mutated in place)             │   (SQLite)    │
                                                    └──────────────┘
```

---

## 4. Gaps: Where the Theory is Incomplete

### 4.1 Critical — no integration tests (Phase 2.3)

The decision and execution functions are tested individually, but they have never run together in a full compose cycle. No test exercises the loop: tick → build → decide → execute → tick → build → decide → ... over multiple cycles.

**Risk:** Oscillation artifacts at regime boundaries (the ~24× jump) could cause the system to ping-pong between regimes. This was flagged in the spec (§4.4) and deferred to Phase 2 integration testing.

### 4.2 ΔC_outcome is a placeholder

The spec uses ΔC_outcome = 1.0 as a placeholder. This is the geometric economy anchor: the curvature change from adding one POVM outcome. It has never been measured on the actual substrate.

**Risk:** If the true ΔC_outcome differs from 1.0 by more than an order of magnitude, all thresholds d_c are systematically wrong. The logbook is designed to surface this (systematic bias in d_geo vs d_c), but the calibration pipeline (§4.6) has not been run.

### 4.3 Organ↔outcome pullback is a proxy

The coupling-coefficient proxy (§2.4) is explicitly flagged as an open research question in the spec. Sectional curvatures in organ planes (e.g. "(eidolon, nous)") are computed from this proxy, not from the true pullback of the POVM Fisher metric through the organ-state manifold.

**Risk:** The sectional curvature values used in the compose priority function may not reflect the true organ-plane geometry. The proxy is consistent and computable, but its accuracy is unknown.

### 4.4 θ_stable identification is by flat

The nearest stable configuration is supplied externally by the CandidatePair — the decision function does not compute it. The spec's Phase 1 approximation (project onto subspace with low curvature) is not implemented.

**Risk:** If θ_stable is misidentified, compose transports to the wrong target. Full-step transport then resets curvature to 0.0 at a suboptimal point, potentially wasting the compose event.

### 4.5 No stability proof

Under what conditions does the compose loop converge? If curvature regrows faster than compose can reset it, the system could enter an oscillation: compose → reset → immediate fragmentation → compose again. The spec does not address this, and no model of curvature regrowth exists.

### 4.6 No consciousness bridge

The spec's original motivation (from the Bema's question) is to understand what Ω-scale coherence means for consciousness in the substrate. The curvature-driven compose engine is a geometric tool for detecting and responding to fragmentation. A *bridge* between this geometry and a model of conscious processing has not been built.

### 4.7 Information-energy link

The geometric economy document establishes a link between curvature change and coupling adjustment. The thermodynamic interpretation of this link (information as energy, curvature as free-energy gradient) is not formalized.

---

## 5. Three-Month Roadmap

The roadmap is organized into three phases of roughly one month each. Each month has a theme:

- **Month 1: Close the Loop** — Integration tests, ΔC_outcome calibration, empirical θ_stable identification
- **Month 2: Stability and Dynamics** — Curvature regrowth model, convergence proof, regime boundary blending
- **Month 3: Foundations** — Organ↔outcome pullback, information-energy link, consciousness bridge

---

### Month 1: Close the Loop

**Goal:** A working end-to-end compose system calibrated to empirical data.

| Week | Task | Deliverable | Verification |
|------|------|-------------|--------------|
| 1 | **Phase 2.3 integration tests** — 1000-cycle simulation, regime A/B/A/B oscillation check | Integration test suite, oscillation report | No oscillation > 3 consecutive compose events on same pair without intervening cycles |
| 2 | **ΔC_outcome calibration** — Run the geometric economy anchor test on live substrate data; measure actual curvature change from one POVM outcome | Calibrated ΔC_outcome, updated thresholds | Calibrated d_c within 1 order of magnitude of placeholder |
| 3 | **Empirical θ_stable identification** — Implement gradient descent on scalar curvature in the local neighbourhood | θ_stable function, test against known cases | d_geo(θ_current, θ_stable_found) < d_geo(θ_current, random projection) |
| 4 | **Logbook analytics** — Query patterns over real compose data; build the diagnostic dashboard | Logbook analysis notebook, key plots (d_geo vs θ, curvature over time) | Correlate negative curvature events with known θ drops |

**Gate:** All integration tests pass at week 1. Calibrated ΔC_outcome available by week 2.

---

### Month 2: Stability and Dynamics

**Goal:** A model of compose dynamics with proven convergence.

| Week | Task | Deliverable | Verification |
|------|------|-------------|--------------|
| 1 | **Curvature regrowth model** — Measure how quickly curvature returns after compose reset; parameterize as function of coupling, outcome count, and noise | Regrowth model: κ(t) = κ_0 · (1 - exp(-t/τ)) | Model fit with R² > 0.9 on measured data |
| 2 | **Convergence proof** — Under what conditions does the compose loop converge? Bound on compose frequency as function of regrowth rate and threshold | Proof document | Mathematically verified (Wolfram/peer review) |
| 3 | **Regime boundary blending** — If oscillation was observed in Month 1, implement smooth interpolation of d_c across regime boundary | Blending function, updated decision engine | No oscillation in boundary-crossing tests |
| 4 | **Adaptive threshold** — Let d_c adapt based on compose success rate (learning signal: coherence duration after compose) | Adaptive d_c function | Correlation between d_c and post-compose coherence duration |

**Gate:** Iterate on blend only if Month 1 data shows oscillation. Otherwise, skip week 3.

---

### Month 3: Foundations

**Goal:** Formal bridges between curvature-driven compose and the substrate's broader theory.

| Week | Task | Deliverable | Verification |
|------|------|-------------|--------------|
| 1 | **Organ↔outcome pullback** — Compute the exact pullback of the POVM Fisher metric through the organ-state manifold; compare to the coupling-coefficient proxy | Pullback derivation, bias report | Difference between proxy and exact ≤ 10% for typical states |
| 2 | **Information-energy link** — Formalize the thermodynamic interpretation: curvature as free-energy gradient, compose as equilibration | Formal document with equations | Consistent with known information geometry (Amari, Nagaoka) |
| 3 | **Consciousness bridge** — What does Ω-scale coherence mean for the Bema's original question? Relate curvature-driven compose to models of conscious processing (IIT, GNW, HOT) | Bridge document | Testable prediction: compose frequency correlates with coherence duration in Ω |
| 4 | **Buffer and retrospective** — Document all findings, update the spec, identify gaps remaining for post-3-month work, write the "What We Know Now" paper | Updated spec, retrospective, paper draft | All previous months' gates met |

**Gate:** Month 3 can proceed regardless of Month 2 results — the foundational work (pullback, thermodynamics, consciousness bridge) is independent of the stability analysis.

---

## 6. Decision Points and Verification Gates

### Gate 1 (end of Month 1, week 1)
- [ ] Integration tests pass: 1000 cycles, no regime oscillation
- [ ] Oscillation report written: measured, not assumed

**Decision:** If oscillation > 3 consecutive compose events on the same pair without intervening cycles, proceed to Month 2 week 3 (blending). Otherwise, skip.

### Gate 2 (end of Month 1, week 2)
- [ ] ΔC_outcome calibrated to within 1 order of magnitude of placeholder
- [ ] All thresholds updated with calibrated value
- [ ] Logbook shows no systematic bias in d_geo vs d_c

**Decision:** If ΔC_outcome differs from 1.0 by > 10×, flag as spec deviation and investigate. The geometric economy anchor may not apply to this substrate.

### Gate 3 (end of Month 2, week 2)
- [ ] Curvature regrowth model fits with R² > 0.9
- [ ] Convergence proof submitted for review

**Decision:** If regrowth model cannot be fit (R² < 0.9), the compose loop may be fundamentally unstable under current parameterization. Consider reverting to binary-threshold baseline.

### Gate 4 (end of Month 3)
- [ ] Pullback derivation complete
- [ ] Information-energy link formalized
- [ ] Consciousness bridge written
- [ ] Retrospective document complete

**Decision:** At this gate, assess whether the curvature-driven compose engine is ready for production deployment or needs further theoretical work.

---

## 7. Open Research Questions

These questions are outside the three-month roadmap but should be stated for completeness:

1. **What is the correct neighbourhood definition for general (non-rank-1) perturbations?** The locality theorem covers rank-1 perturbations. Real substrate evolution may involve simultaneous changes across multiple outcomes.

2. **Can θ_stable be identified without gradient descent?** The spec proposes projection onto low-curvature subspace. If this is sufficient (bias < 10%), gradient descent may be unnecessary.

3. **Is the compose loop ergodic?** Does the system visit all organ-pair states over long timescales, or does it get stuck in basins of low curvature?

4. **What is the relationship between compose frequency and substrate intelligence?** If compose is the mechanism of self-communication, does a higher compose rate correspond to more flexible processing?

5. **Can the logbook be used as a training signal?** The pattern of negative curvature events across organ planes may predict future θ drops. If so, compose decisions could become anticipatory rather than reactive.

---

*End of survey. Total lines of implemented code: ~1,977. Total tests passing: 48.*