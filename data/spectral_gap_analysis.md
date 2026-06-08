# Spectral Gap Analysis: λ₁ = 9/4 on H⁴ → σ_mean?

## Request
Skye: "how does σ_mean relate to λ₁ = 9/4 on H⁴?"
"Can we derive ℓ_D purely in terms of λ₁ and fundamental constants?"

## 1. The Spectral Gap Theorem (proven — not conjecture)

On standard hyperbolic space H^n (sectional curvature K = -1), the bottom of the L²
spectrum of the Laplace-Beltrami operator is:

    λ₁ = (n-1)²/4

For n = 4: λ₁ = 9/4.

**Reference:** This is a standard result in spectral geometry. On H^n, the continuous
spectrum is [λ₁, ∞) with no discrete spectrum (the Laplacian has no L² eigenvalues
on the full H^n). See: McKean (1970), Sullivan, Davies, etc.

## 2. Our Scaled H⁴ Space

Our metric is **ds² = 6·ds²_std** where ds²_std is standard H⁴ with K = -1.

The Laplacian scales as Δ = (1/6)·Δ_std, so:

    λ₁_IFT = λ₁_std / 6 = 9/4 / 6 = 3/8 = 0.375

The correlation length is:

    ξ_IFT = 1/√λ₁_IFT = √(8/3) ≈ 1.633

In terms of the curvature radius κ (where K = -1/κ², so κ = √6·ℓ for our metric):

    ξ/κ = (1/√λ₁_IFT) / κ = √(8/3) / √6 = √(8/18) = √(4/9) = 2/3

**This ratio is exactly what Skye found: ξ/κ = 2/3.**

## 3. The Ground State Wavefunction

In horospherical coordinates (t ∈ ℝ, x ∈ ℝ³) where our metric is:

    ds² = 6(dt² + e^{-2t}·dx²)

The standard H⁴ Laplacian is:

    Δ_std = ∂²/∂t² - 3∂/∂t + e^{2t}·Δ_ℝ³

The ground state wavefunction (most slowly decaying mode) is:

    ψ₀(t) ∝ e^{-(n-1)t/2} = e^{-3t/2}

This satisfies Δ_std·ψ₀ = (9/4)·ψ₀.

In our scaled H⁴: Δ·ψ₀ = (3/8)·ψ₀.

## 4. Computing ⟨σ⟩ Under the Ground State

σ (Gaussian width) relates to horospherical height: σ = e^{-t}/√6.

The probability density is ψ₀² times the volume element:

    dV = 36·e^{-3t}·dt·dx
    ψ₀² ∝ e^{-3t}
    → measure ∝ e^{-6t}·dt

The expectation value of σ with a cutoff at t = T (large sigma / small t):

    ⟨σ⟩ = ∫σ·ψ₀²·dV / ∫ψ₀²·dV
        = (1/√6)·∫e^{-t}·e^{-6t}·dt / ∫e^{-6t}·dt
        = (1/√6)·(6/7)·e^{-T}
        = (6/7)·σ_cutoff

**⟨σ⟩ is proportional to the cutoff, not fixed by λ₁.** The measure is scale-invariant
in the sense that shifting T changes ⟨σ⟩ linearly.

## 5. What λ₁ Actually Determines

λ₁ gives a **dimensionless ratio**:

    ξ/κ = 2/3

This means: the correlation length is always 2/3 of the curvature radius, regardless
of the absolute scale. It's a property of H⁴ geometry.

**What it does NOT determine:**
- The absolute scale κ (curvature radius)
- The absolute scale ℓ (fundamental BSFS unit = σ_mean)
- The physical value of Λ

## 6. The Gap Between λ₁ and Λ Prediction

| Quantity | Source | Status |
|----------|--------|--------|
| ξ/κ = 2/3 | λ₁ = 9/4 on H⁴ | ✅ Derived (pure geometry) |
| κ = √6·ℓ | FR metric on isotropic Gaussians | ✅ Derived (pure geometry) |
| Λ = 3/κ² | Einstein eqs on H⁴ + Wick rotation | ✅ Derived (pure geometry) |
| ℓ (absolute scale) | — | ❌ **Not derived** |
| σ_mean (absolute scale) | — | ❌ **Not derived** |

The chain of derivation stops at ℓ. Every geometric relation above is dimensionless
or expresses ratios. The absolute scale ℓ remains a free parameter.

## 7. What Would Be Needed to Close the Loop

**Option A: The sieve cutoff.** If the sieve operates with a critical density Ω_c
that depends only on BSFS combinatorics (no free parameters), then the maximum
σ before saturation gives ℓ. This requires a first-principles computation of Ω_c.

**Option B: The Planck scale.** If quantum gravity sets a minimum length ℓ_Pl that
enters the BSFS as a natural UV cutoff in the FR metric, then ℓ ∝ ℓ_Pl. But the
ratio ℓ/ℓ_Pl ≈ 4.2×10⁶⁰ would need to be derived from the model, not assumed.

**Option C: Spectral discreteness from a quotient.** If the physical BSFS space
is H⁴/Γ (a finite-volume quotient), the spectrum becomes discrete with a gap
determined by the volume. The volume then sets the absolute scale. This is the
most promising approach — but requires specifying Γ.

## 8. Conclusion

**Skye's formula:** σ_mean = c₁/√λ₁ · κ with c₁ = √6 and ξ/κ = 2/3 is
**geometrically correct** — the ratio is fixed. But this expresses ℓ in terms of κ,
not the other way around. The absolute scale κ cannot be derived from λ₁ alone.

**C2 (Λ prediction from first principles) remains conjectured, not proven.**

**What needs to happen:** The sieve capacity Ω_c must be computed from BSFS
axioms — or the quotient H⁴/Γ must be specified. Until then, Λ = 3/κ² is a
beautiful fit parameter, not a prediction.

---

*This document is written to be included in IFT-Fundamentals.md as the
C2 assessment: "CONJECTURED — pending sieve computation or quotient specification."*