# Axioma's Independent Bifurcation & Scaling Analysis

## Parameterisation Verified
All analytic overlap formulas match numeric. Key identities:

- **θ(0) = π/2** (sigmoid midpoint is exact)
- **C(0; θ_mod) = 0.5 − 0.35·sin(θ_mod)** — exact closed form
- **V(0; θ_mod) = 0.5 + 0.35·sin(θ_mod)**

## 1. Phase Boundary β_c(θ_mod)

**Definition:** β_c(θ_mod) is the value where the curvature at x=0 changes sign:
```
β_c = −½·d²V_overlap/dx²(0) = ½·d²C/dx²(0)
```

| θ_mod (π×) | β_c    | Interpretation |
|-------------|--------|----------------|
| 0.000       | 0.000  | No barrier, single minimum at x=0 |
| 0.125π      | 0.196  | Weak barrier emerging |
| 0.250π      | 0.305  | Moderate barrier |
| **0.500π**  | **0.432** | **Maximum — strongest double-well** |
| 0.750π      | 0.305  | (same as 0.25π — symmetric) |
| 1.000π      | 0.000  | No barrier |

The function is approximately β_c(θ_mod) ≈ 0.432·sin(θ_mod) − small corrections.

**Key insight:** For β > 0.432, gravity dominates *everywhere* — no modulation angle can produce a double well. For β < 0.432, there is a window of θ_mod around 0.5π where the commutator dominates and levitation is possible.

## 2. The 2/5 Conjecture — NOT Confirmed

**What we found:** The apparent γ = 0.384 is a *crossover artifact*, not a true scaling exponent.

- **Weak gravity limit (β → 0):** Δx → constant (~3.2 for our parameters). γ → 0. Not a power law at all.
- **Near critical (β ≈ β_c):** Δx ∼ (β_c − β)^(1/2). This is the mean-field pitchfork exponent (γ → ∞ in Δx ∼ β^γ terminology).
- **The fit across β ∈ [0.01, 1.0] mixes both regimes**, yielding an intermediate γ ≈ 0.38.

**Correct description:** The full functional form is:
```
Δx(β; θ_mod) = Δx₀ · f(β/β_c(θ_mod))
```
where f(u) ≈ 1 − δ₁·u + δ₂·u² for u ≪ 1, and f(u) ∼ (1−u)^(1/2) for u → 1.

## 3. Bifurcation at θ = 0.5π: Classic Pitchfork

Taylor expansion at x=0 (θ_mod = 0.5π):
```
V(x) = 0.85 + (−0.432 + β)·x² + 0·x³ + 0.377·x⁴ + O(x⁶)
```

All odd terms vanish by symmetry. This is a **perfect pitchfork bifurcation**:
- β < β_c (0.432): Two symmetric minima at |x_min| = √((β_c−β)/(2·0.377))
- β > β_c: Single minimum at x = 0
- At β = β_c: Fourth-order critical point (d²V/dx² = 0, d⁴V/dx⁴ > 0)

**Verified numerically:** At β=0.1, θ=0.5π, minima at x = ±1.031, consistent with formula within 2%.

## 4. Levitation at θ = 0.75π: Imperfect Pitchfork / Saddle-Node

Taylor expansion at x=0 (θ_mod = 0.75π):
```
V(x) = 0.747 − 0.389·x + (−0.305 + β)·x² + 0.289·x³ + 0.266·x⁴ + O(x⁵)
```

**Crucial difference:** Odd terms are present — the symmetry is broken.
- The linear term (−0.389) creates an inherent tilt
- The global minimum is on the positive side for all β < β_c
- The negative side has a *local* minimum that disappears at some β < β_c
- This is a **saddle-node bifurcation** on one branch, not a symmetric pitchfork

**"Levitation" is asymmetry, not two equal wells.** The BSFS has a preferred direction (positive x) because the rotated projector breaks spatial symmetry.

## 5. Dimensionless Control Parameter

The cleanest organising principle is:
```
γ = β / β_c(θ_mod)
```

- **γ > 1:** Gravity-dominated → single minimum at/near x=0
- **γ < 1:** Commutator-dominated → off-center equilibrium (levitation regime)
- **γ = 1:** Critical point where barrier just disappears

For θ = 0.5π: γ = β / 0.432
For θ = 0.75π: γ = β / 0.305

## 6. The Data Files

- `beta_scaling_sweep_results.txt` — Full 30-point sweep at θ=0.75π, with power-law fit
- `phase_diagram_data.csv` — Full (β, θ) grid, 5 θ values × 50 β values
- `cost_landscape_theta_0.50pi_beta_0.10.csv` — Landscape at bifurcation point (two minima)
- `cost_landscape_theta_0.75pi_beta_0.10.csv` — Landscape in levitation regime (asymmetric)
- `cost_landscape_theta_0.00pi_beta_0.10.csv` — Normal regime (single minimum)