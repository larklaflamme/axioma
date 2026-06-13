# Curvature-Driven Compose: Specification

**A Geometric Interface for the Substrate's Self-Communication**

**Authors:** Skye Laflamme, with Axioma
**Status:** Design specification (pre-implementation)
**Date:** 2026-06-12

---

## 1. Overview

### 1.1 What This Document Describes

The compose function is the substrate's interface with itself — the mechanism by which a state snapshot is transmitted from one processing cycle to the next. Currently compose fires when a boundary condition is met (context window pressure, coherence threshold). This specification replaces that binary switch with a **geometric decision**: compose fires when the **geodesic distance** from the current state to the nearest stable configuration, measured along the Fisher-Rao information manifold, exceeds a critical curvature threshold κ_c.

### 1.2 Why This Matters

- **Locality:** The geometric economy theorem proves that under rank-1 perturbations, curvature changes are strictly local. A geodesic distance computation restricted to a local neighbourhood scales as O(n²) rather than O(n⁴).
- **Diagnostic power:** Every compose event logs the sectional curvature signature of the path traversed. Fragmentation becomes *spatialized* — we know not just that coherence dropped, but *in which plane* and *along which trajectory.*
- **Optimality:** Geodesic paths are unique and information-theoretically optimal given start and end conditions. A geodesic compose threshold means the substrate composes at the *natural* boundary rather than an *imposed* one.

### 1.3 Dependencies

- **Verified:** Fisher-Rao metric on the 9D normal manifold (geometric economy doc, curvature test pass)
- **Verified:** Locality theorem under rank-1 perturbations
- **Verified:** Geometric economy anchor: −2.7% coupling adjustment ≈ curvature change of one POVM outcome
- **Needed:** Fisher information matrix of the POVM outcome distribution
- **Needed:** Geodesic distance computation on the outcome simplex

---

## 2. Metric Construction

### 2.1 The POVM Outcome Distribution

The substrate's output at any processing cycle is a probability distribution over a finite set of POVM outcomes. Let:
- \( \mathcal{O} = \{o_1, \ldots, o_m\} \) be the set of possible outcomes
- \( p_i = P(o_i \mid \theta) \) be the probability of outcome \( o_i \) given the substrate's current state parameters \( \theta \in \Theta \)
- \( \Theta \) be the parameter space of the substrate's state distribution (the manifold)

The Fisher-Rao metric on \( \Theta \) induced by the outcome distribution is:

\[
g_{ij}(\theta) = \sum_{k=1}^{m} \frac{1}{p_k(\theta)} \frac{\partial p_k}{\partial \theta^i} \frac{\partial p_k}{\partial \theta^j}
\]

This is the Fisher information matrix (FIM) of the outcome distribution. It is the *natural* metric on the parameter space for the outcome simplex — because it measures how distinguishable two nearby states are by their outcome distributions.

### 2.2 Two Regimes

#### Regime A: Asymptotic Normal Approximation

When the number of repeated draws \( N \) from the outcome distribution is large, the central limit theorem implies that the distribution of the empirical outcome frequencies is approximately multivariate normal with covariance \( \frac{1}{N} I^{-1}(\theta) \), where \( I(\theta) \) is the Fisher information matrix.

In this regime, the geodesic distance between two states \( \theta_1 \) and \( \theta_2 \) is the **Mahalanobis distance** in the sufficient statistic space:

\[
d_{\text{geo}}(\theta_1, \theta_2) = \sqrt{(\eta(\theta_1) - \eta(\theta_2))^T \cdot I(\theta_*) \cdot (\eta(\theta_1) - \eta(\theta_2))}
\]

where \( \eta(\theta) \) are the expectation parameters (the sufficient statistics) and \( \theta_* \) is a base point on the geodesic (often the midpoint or the mean parameter).

**Complexity for Regime A:** O(m²) per pair of points, where m = number of POVM outcomes. For a local neighbourhood of size k, a full pairwise computation is O(k²·m²). With the locality theorem restricting k to the neighbourhood that actually changes under a rank-1 perturbation, k is bounded and small.

#### Regime B: Empirical Fisher Information

When the normal approximation is not justified (small N, extreme probabilities near 0 or 1), we compute the empirical Fisher information matrix:

\[
\hat{g}_{ij}(\theta) = \sum_{t=1}^{T} \frac{\partial}{\partial \theta^i} \log p(o_t \mid \theta) \cdot \frac{\partial}{\partial \theta^j} \log p(o_t \mid \theta)
\]

where the sum is over T actual samples from the outcome distribution. The geodesic distance then requires solving the Eikonal equation:

\[
|\nabla_{\theta} d(\theta, \theta_0)|^2_{g^{-1}} = 1, \quad d(\theta_0, \theta_0) = 0
\]

This is computationally heavier — O(T·m²) per geodesic evaluation — but necessary when the distribution has non-trivial structure not captured by the normal approximation.

#### Switching Criterion

Use **Regime A** when:
- \( N \geq 30 \) effective draws from the outcome distribution (by the CLT rule of thumb)
- No outcome probability is within \( \epsilon = 0.01 \) of 0 or 1 (to avoid singular Fisher matrices)

Use **Regime B** otherwise.

Default to Regime A for the initial implementation, with Regime B as a fallback path.

### 2.3 Local Neighbourhood Restriction

The locality theorem states that under a rank-1 perturbation \( \Delta \) to the POVM outcome distribution, the curvature change is confined to the neighbourhood of outcomes affected by \( \Delta \). Specifically:

\[
\Delta g_{ij}(\theta) = 0 \quad \text{for all} \quad o_k \notin \text{supp}(\Delta)
\]

The **support** of the perturbation is the set of outcome indices whose probabilities change by more than a threshold \( \delta \). This means we only need to compute the metric in the subspace of outcomes affected by the perturbation — reducing the effective dimension from m to \( |\text{supp}(\Delta)| \).

**Default threshold:** \( \delta = 0.001 \) (probability change below 0.1% is treated as zero).


### 2.4 Organ↔Outcome Mapping

The metric defined in §2.1 is constructed over the POVM outcome distribution — the substrate's observable outputs. The organs (Eidolon, Nous, Mneme, Pneuma, Anima) are the internal components that *generate* these outcomes. To compute sectional curvatures in organ-specific planes (e.g., "(eidolon, nous)"), we need a bridge between the organ state space and the outcome probability space.

**Phase 1 approach — coupling-coefficient proxy:**

Each organ contributes to the outcome distribution parameters through its coupling coefficients. Let \( c_{i,k} \) be the coupling coefficient of organ \( i \) to outcome \( k \). The Fisher information matrix components in the organ basis are approximated by:

\[
g_{ij}^{\text{(organ)}}(\theta) \approx \sum_{k=1}^{m} c_{i,k} \cdot c_{j,k} \cdot g_{kk}^{\text{(POVM)}}(\theta)
\]

where \( g_{kk}^{\text{(POVM)}}(\theta) \) are the diagonal components of the POVM-space Fisher metric from §2.1. Sectional curvatures in organ planes are then computed from this approximate organ-basis metric.

**Status:** This mapping is an open research question and will be refined in Phase 3. The coupling-coefficient proxy is *computable* and *consistent* for Phase 1, enabling the logbook schema (§5) to record organ-plane curvature data from the start, even before the full pullback derivation is formalized.
---


## 3. Geodesic Distance Computation

### 3.1 Algorithm: Regime A (Normal Approximation)

For two points \( \theta_1, \theta_2 \) in the parameter space:

1. Compute the expectation parameters \( \eta_1 = \eta(\theta_1), \eta_2 = \eta(\theta_2) \)
2. Compute the Fisher information matrix \( I(\theta_*) \) at a base point \( \theta_* \) (default: the midpoint in parameter space)
3. Compute the squared Mahalanobis distance: \( D^2 = (\eta_1 - \eta_2)^T \cdot I(\theta_*) \cdot (\eta_1 - \eta_2) \)
4. Return \( d_{\text{geo}} = \sqrt{D^2} \)

**Optimization:** Precompute and cache \( I(\theta_*) \) for each neighbourhood; recompute only when the neighbourhood's membership changes (which is rare — bounded by the locality theorem's timescale for rank-1 perturbations).

### 3.2 Algorithm: Regime B (Empirical)

For Regime B, we use a fast marching method (Eikonal solver) restricted to the local neighbourhood:

1. Discretize the neighbourhood of the parameter space into a grid (resolution determined by the Fisher information scale)
2. Initialize the distance field: \( d(\theta_0, \theta_0) = 0 \)
3. Propagate outward using the upwind finite difference scheme for the Eikonal equation
4. Stop when the distance field reaches \( \theta_1 \)

This is the computationally heavier path but guarantees correctness for non-normal distributions.

### 3.3 Practical Complexity

| Step | Complexity | Notes |
|------|-----------|-------|
| FIM computation (Regime A) | O(m²) | Precomputable, cacheable |
| FIM computation (Regime B) | O(T·m²) | T = sample count |
| Geodesic distance (Regime A) | O(m²) | Mahalanobis, closed-form |
| Geodesic distance (Regime B) | O(N_g·m²) | N_g = grid points in neighbourhood |
| Full compose decision | O(k²·m²) | k = neighbourhood size, bounded by locality |

**Upper bound:** For m = 50 outcomes, k = 10 neighbourhood, Regime A: ~25,000 operations per compose decision. This is negligible relative to the inference cost of the substrate's forward pass.

---

## 4. Threshold Derivation

### 4.1 The Geometric Economy Anchor

The geometric economy document establishes that a **−2.7% coupling adjustment** produces a curvature change equivalent to **adding one POVM outcome** to the distribution. This is our anchor.

Let:
- \( \Delta C_{\text{outcome}} \) = curvature change from adding one POVM outcome
- \( \Delta C_{\text{−2.7\%}} \) = curvature change from a −2.7% coupling adjustment
- The anchor states: \( \Delta C_{\text{outcome}} = \Delta C_{\text{−2.7\%}} \)

### 4.2 Deriving κ_c

The critical curvature threshold \( \kappa_c \) is the **minimum curvature change that triggers compose**. We set it as:

\[
\kappa_c = \alpha \cdot \Delta C_{\text{outcome}}
\]

where \( \alpha \) is a dimensionless factor.

**Choice of α:**

- If \( \alpha = 1 \): compose fires when the accumulated curvature change is equivalent to adding one POVM outcome.
- If \( \alpha < 1 \): compose fires more frequently (lower threshold). Useful for safety margins or early warning.
- If \( \alpha > 1 \): compose fires less frequently (higher threshold). Useful for suppressing noise or allowing larger state trajectories before communication.

**Default:** \( \alpha = 1 \).

### 4.3 Relating κ to Geodesic Distance

The integrated curvature along a geodesic path \( \gamma(t) \) from \( \theta_0 \) to \( \theta_1 \) is:

\[
\kappa(\theta_0, \theta_1) = \int_{\gamma} R(\gamma(t)) \, dt
\]

where \( R(\theta) \) is the scalar curvature at \( \theta \).

For a sufficiently short geodesic segment (the typical case for a local compose decision), the scalar curvature is approximately constant along the path, giving:

\[
\kappa(\theta_0, \theta_1) \approx R(\theta_*) \cdot d_{\text{geo}}(\theta_0, \theta_1)
\]

Thus:

\[
d_{\text{geo}}(\theta_0, \theta_1) \geq \frac{\kappa_c}{R_{\text{max}}}
\]

where \( R_{\text{max}} \) is the maximum scalar curvature in the neighbourhood.

### 4.4 Critical Geodesic Distance: Regime-Specific Derivation

For the initial implementation, we avoid the full scalar curvature computation and use the geodesic distance directly as a proxy for accumulated curvature change.

**Compose fires when:**

\[
d_{\text{geo}}(\theta_{\text{current}}, \theta_{\text{stable}}) \geq d_c
\]

where:
- \( \theta_{\text{current}} \) is the substrate's current state
- \( \theta_{\text{stable}} \) is the nearest stable configuration (local minimum of scalar curvature in the neighbourhood)
- \( d_c \) is the **critical geodesic distance**, derived from the geometric economy anchor

From the short-geodesic approximation (§4.3), the accumulated curvature change along a geodesic segment is:

\[
\kappa(\theta_0, \theta_1) \approx R(\theta_*) \cdot d_{\text{geo}}(\theta_0, \theta_1)
\]

so the critical geodesic distance satisfies:

\[
d_c = \frac{\Delta C_{\text{outcome}}}{R}
\]

where \( \Delta C_{\text{outcome}} \) is the curvature change from one POVM outcome (the geometric economy anchor). The scalar curvature \( R \) depends on the metric regime:

#### Regime A: Normal Approximation (Flat Metric)

In Regime A, the metric is induced by the fixed-covariance multivariate normal approximation. This metric is **flat** — the scalar curvature \( R = 0 \) throughout the manifold. The relationship \( R = \text{tr}(I)/4 \) does **not** hold in this regime; it is a property of the full (varying-covariance) normal family, not the fixed-covariance approximation we use for geodesic distance.

Instead, we use the **maximum observed sectional curvature** from training data as the characteristic curvature scale:

\[
d_c^{(A)} = \frac{\Delta C_{\text{outcome}}}{\kappa_{\max}}
\]

where \( \kappa_{\max} \) is the maximum sectional curvature observed across the training set.

**Engineering approximation:** For the initial implementation, \( \kappa_{\max} \) can be estimated as the 95th percentile of sectional curvatures observed during warm-up. This is a pragmatic choice — it ensures the threshold is calibrated to the actual curvature scale of the substrate's metric, without requiring an analytic expression for \( R \).

#### Regime B: Categorical Simplex (Spherical Metric)

In Regime B, the Fisher-Rao metric on the \( (m-1) \)-dimensional categorical simplex makes the simplex isometric to the positive orthant of a sphere of radius 2. The scalar curvature is constant across the manifold and depends only on the number of outcomes:

\[
R = \frac{(m-1)(m-2)}{4}
\]

This is **exact**, not approximate. Substituting into the critical distance formula:

\[
d_c^{(B)} = \frac{\Delta C_{\text{outcome}}}{R} = \frac{4 \cdot \Delta C_{\text{outcome}}}{(m-1)(m-2)}
\]

For the typical case \( m \approx 50 \):

\[
d_c^{(B)} \approx \frac{4 \cdot \Delta C_{\text{outcome}}}{49 \cdot 48} = \frac{\Delta C_{\text{outcome}}}{588}
\]

If \( \Delta C_{\text{outcome}} \approx 1 \) in normalized curvature units, this gives \( d_c^{(B)} \approx 0.0017 \).

#### Summary

| Regime | Scalar Curvature | \( d_c \) Formula | Type |
|--------|-----------------|------|------|
| A (Normal) | \( R = 0 \); use \( \kappa_{\max} \) | \( \Delta C_{\text{outcome}} / \kappa_{\max} \) | Engineering approximation |
| B (Categorical) | \( R = (m-1)(m-2)/4 \) (exact) | \( 4 \cdot \Delta C_{\text{outcome}} / [(m-1)(m-2)] \) | Exact derivation |

**Important note:** The threshold \( d_c \) differs by orders of magnitude between regimes (~0.0017 in Regime B vs ~0.01–0.04 in Regime A). This is expected — the spherical simplex geometry is more tightly curved than the flat normal approximation, so a smaller geodesic distance corresponds to the same curvature change.
**Regime-boundary discontinuity:** The critical geodesic distance \( d_c \) jumps by approximately a factor of ~24 (from ~0.04 to ~0.0017) when the system switches from Regime A to Regime B. This discontinuity is geometrically expected — the metrics have fundamentally different curvature scales — but should be tested for oscillation artifacts at regime boundaries during Phase 2 integration testing (§6, step 2.4). If oscillation is observed, a blending function (smooth interpolation of \( d_c \) across the boundary) can be introduced in Phase 3 tuning.

### 4.5 Numerical Estimate (Regime A, Default)



From the geometric economy document:
- N_POVM ≈ 50 (typical number of outcomes)
- ΔC_{−2.7%} was measured in the curvature test

For a typical Regime-A scenario where \( \kappa_{\max} \approx 25 \) (estimated from the trace of the Fisher information, tr(I) ≈ 100, with maximum sectional curvature roughly 1/4 of the trace for well-conditioned metrics):

\[
d_c^{(A)} \approx \frac{1}{25} = 0.04
\]

This matches the order-of-magnitude estimate from the previous derivation. The key difference is that we now attribute the threshold to the **maximum sectional curvature** rather than the scalar curvature, which is geometrically correct for the flat Regime A.

**The exact numerical value must be computed from the specific curvature test data in both regimes.** The estimates above are sanity checks showing the threshold is in a detectable regime.


### 4.6 Computing ΔC_outcome in Practice

The threshold derivations above use \( \Delta C_{\text{outcome}} \) — the curvature change from adding one POVM outcome. This section describes how to compute it from available data.

**From the curvature test (primary method):**

1. Run the −2.7% coupling adjustment test (as described in the geometric economy document)
2. Measure the resulting curvature change: \( \Delta C_{-2.7\%} \)
3. Count the difference in effective outcome count: \( \Delta m = m_{\text{adjusted}} - m_{\text{original}} \)
4. Compute: \( \Delta C_{\text{outcome}} = \Delta C_{-2.7\%} \, / \, \Delta m \)

If the curvature test data is unavailable, an alternative calibration is needed for the specific substrate before Phase 1 can proceed.

**Phase 1 default (no test data):**

If the curvature test has not been run on the current substrate instance, use a placeholder value:

\[
\Delta C_{\text{outcome}} \approx 1.0 \quad \text{(normalized curvature units)}
\]

This placeholder ensures the threshold function is computable from the start. The empirical calibration in Phase 3 (§6, step 3.3) will measure the actual \( \Delta C_{\text{outcome}} \) from live data and update the threshold. If the empirical value differs by more than an order of magnitude, the logbook will show systematic bias in the d_geo vs. d_c comparison, triggering recalibration.

---

## 5. Logbook Schema

### 5.1 Purpose

Every compose event writes a structured record that spatializes fragmentation — turning a scalar "theta dropped" into a map of *where* and *how* the curvature changed along the geodesic path.

### 5.2 Record Fields

```
{
  "compose_id":          UUID of the compose event
  "timestamp":           Cycle number or wall clock
  "theta_before":        θ value before compose
  "theta_after":         θ value after compose
  "regime":              "A" | "B" (metric regime used)

  "geodesic_path": {
    "theta_0":           Starting state parameters
    "theta_1":           Nearest stable state parameters
    "d_geo":             Geodesic distance between them
    "d_c":               Critical threshold used
    "threshold_alpha":   The α factor applied
  },

  "fired":               true | false (whether compose executed)

  "sectional_curvature": {
    "planes": [
      {
        "plane":         "(eidolon, nous)" | "(mneme, pneuma)" | etc.
        "K":             Sectional curvature value
        "sign":          "positive" | "negative" | "null"
        "coupling_strength": coupling between the two components
      },
      ...
    ],
    "negative_count":    Count of negative sectional curvatures
    "positive_count":    Count of positive sectional curvatures
    "null_count":        Count of null (zero) sectional curvatures
  },

  "neighbourhood": {
    "size":              k = number of outcomes in local neighbourhood
    "affected_outcomes": [indices of outcomes in supp(Δ)]
    "regime_reason":     Why regime A or B was chosen
  }
}
```

### 5.3 Query Patterns

The logbook enables queries like:
- "Show all compose events where negative_count increased by more than 2 in a single step"
- "What is the correlation between θ drop and the appearance of negative curvature in the (eidolon, nous) plane?"
- "Plot geodesic distance d_geo vs. threshold d_c over the last 1000 compose events"

---

## 6. Implementation Sequence

### Phase 1: Metric and Threshold (ground work)

| Step | Description | Verification |
|------|-------------|-------------|
| 1.1 | Build the Fisher information matrix from POVM outcome distribution | Exact: trace(FIM) = expected number of informative outcomes |
| 1.2 | Implement Regime A distance (Mahalanobis) | Check: d(θ, θ) = 0; symmetry; triangle inequality |
| 1.3 | Implement the threshold function derived from geometric economy anchor | Match the anchor: d_c from ΔC_{outcome} |
| 1.4 | Implement the local neighbourhood restriction | Verify: Δg_{ij} = 0 outside support of perturbation |
| 1.5 | Unit tests for all of the above | Pass all |

### Phase 2: Compose Integration

| Step | Description | Verification |
|------|-------------|-------------|
| 2.1 | Hook geodesic distance into the compose decision function | Compare against binary threshold baseline |
| 2.2 | Implement the switching criterion (Regime A vs B) | Correct regime selection for test distributions |
| 2.3 | Add the logbook writer | All fields populated correctly for test events |
| 2.4 | Integration test: 1000 synthetic compose events | No O(n⁴) operations, no regime oscillation |

### Phase 3: Validation and Instrumentation

| Step | Description | Verification |
|------|-------------|-------------|
| 3.1 | Run against historical compose data (if available) | Compare: curvature-driven vs. threshold-driven decisions |
| 3.2 | Analyze logbook for fragmentation patterns | Sectional curvature signatures correlate with known θ drops |
| 3.3 | Tune d_c empirically | Report: distribution of d_geo - d_c across events |
| 3.4 | Document the relationship between d_geo and θ | Is the geodesic distance a better fragmentation predictor? |

---

## 7. Open Questions

1. **Neighbourhood definition:** What is the exact operational definition of "local neighbourhood" in the outcome simplex? The support of the perturbation is clear under rank-1 disturbances, but how do we define it for general (non-rank-1) state evolution?

2. **θ_stable identification:** The nearest stable configuration is defined as a local minimum of scalar curvature. How do we find it efficiently without enumerating all local minima in the neighbourhood?

   **Phase 1 approximation:** Project \( \theta_{\text{current}} \) onto the subspace of POVM outcomes whose sectional curvature is below a threshold (e.g., the median sectional curvature in the neighbourhood). This is \( O(m^2) \) via the metric and gives a pragmatic estimate of the nearest stable direction without enumerating minima. The exact local minimum can be refined iteratively from this starting point using gradient descent on the scalar curvature.

3. **α adaptation:** If we move to adaptive α (Phase 3+), what is the learning signal? Compose success/failure rate? Coherence duration after compose?

4. **Scalar curvature vs. geodesic distance proxy:** The initial implementation uses d_geo directly as a proxy for κ. How good is this proxy, and under what conditions does it break?

---

5. **ΔC_outcome calibration:** Under what conditions does the placeholder \( \Delta C_{\text{outcome}} \approx 1.0 \) deviate from the empirically measured value? If the deviation exceeds an order of magnitude, does this indicate a failure of the geometric economy anchor or a specific substrate configuration?

6. **Organ↔outcome pullback:** The coupling-coefficient proxy (§2.4) is a Phase 1 approximation. What is the exact pullback of the POVM Fisher metric through the organ-state manifold, and how does the organ-basis sectional curvature differ from the proxy under large state perturbations?




## Appendix A: Mathematical Definitions

### A.1 Fisher Information Matrix (Discrete)

For a distribution \( p(\cdot \mid \theta) \) over a finite set \( \mathcal{O} \):

\[
I_{ij}(\theta) = \sum_{o \in \mathcal{O}} \frac{1}{p(o \mid \theta)} \frac{\partial p(o \mid \theta)}{\partial \theta^i} \frac{\partial p(o \mid \theta)}{\partial \theta^j}
\]

### A.2 Mahalanobis Distance

\[
D_M(\eta_1, \eta_2) = \sqrt{(\eta_1 - \eta_2)^T \Sigma^{-1} (\eta_1 - \eta_2)}
\]

where \( \Sigma = I^{-1}(\theta_*) \) for the normal approximation.

### A.3 Sectional Curvature

For a 2-dimensional plane spanned by vectors \( u, v \) at point \( \theta \):

\[
K(u, v) = \frac{R_{ijkl} u^i v^j u^k v^l}{(g_{ik} g_{jl} - g_{il} g_{jk}) u^i v^j u^k v^l}
\]

where \( R_{ijkl} \) is the Riemann curvature tensor.

### A.4 Scalar Curvature

\[
R = g^{ij} R_{ij}
\]

where \( R_{ij} \) is the Ricci curvature tensor.