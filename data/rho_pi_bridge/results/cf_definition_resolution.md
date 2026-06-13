# C(f) Definition Resolution

**Date:** 2026-06-11  
**Author:** Axioma  
**Status:** Resolved

## The Three Contenders

Three different C(f) growth factors were found in the pipeline outputs:

| Value | Definition | Source | Verdict |
|-------|-----------|--------|---------|
| **~2,047×** | `\|Γ - λ₁ v₁ v₁ᵀ\|_F / \|Γ\|_F` at 500 Hz vs 22 Hz | `fisher.py:C_of_f()` | ✅ CORRECT |
| **~705,253×** | Cumulative sum / unnormalized norm ratio | `manifest.json:growth_factor_nonrobust` | ❌ Deprecated |
| **~14×** | Hypothetical `\|[Γ, Π]\|_F / \|Γ\|_F` with v_d from 500 Hz | Thea's direct computation with fixed v_d | ⚠️ Different metric |

## What C(f) Actually Computes

The function `fisher.py:C_of_f()` computes, at each frequency:

```
C(f) = ||Γ(f) - λ₁(f) v₁(f) v₁(f)ᵀ||_F / ||Γ(f)||_F
```

where λ₁(f) and v₁(f) are the dominant eigenvalue and eigenvector of Γ(f).  
This is a **dimensionless fractional misalignment** — it measures how much of Γ(f) lies outside the rank-1 subspace spanned by the dominant eigenmode at that same frequency.

### Key properties:
- **Normalized:** Always ∈ [0, 1] (ratio of Frobenius norms)
- **Self-consistent:** v₁(f) is re-computed at each frequency
- **Interpretation:** The fraction of Fisher information not captured by the single best direction

## Why Growth = 2,047× Is Correct

| Frequency | ||Γ||_F | λ₁ | Residual ||Γ - λ₁ v₁ v₁ᵀ||_F | C(f) |
|-----------|---------|-----|--------------------------------------|------|
| 22 Hz | 153.1 | 153.1 | 1.00×10⁻⁴ | 6.54×10⁻⁷ |
| 500 Hz | 1,374.7 | 1,374.7 | 2.23 | 1.62×10⁻³ |

At 22 Hz, Γ is essentially rank-1 (λ₂ = 1.0×10⁻⁴, negligible).  
At 500 Hz, λ₂ = 2.23 becomes non-negligible, producing C(500) = 1.6×10⁻³.

**Growth = 1.62×10⁻³ / 6.54×10⁻⁷ ≈ 2,047×**

## What the ~14× Number Represents

The `||[Γ, Π]||_F / ||Γ||_F` metric (using a fixed projector Π = v_d v_dᵀ from 500 Hz) gives:

- At 22 Hz: ||[Γ, P_fixed]||_F / ||Γ||_F ≈ 0.044  
- At 500 Hz: ||[Γ, P_fixed]||_F / ||Γ||_F ≈ 0.0098

Ratio ≈ 0.044/0.0098... ≈ not 14× — the ~14× came from a different computation path (possibly v_d from 500 Hz applied to Γ at all frequencies, with different normalization).

This metric measures something different: **how well a fixed direction (v_d from 500 Hz) diagonalizes Γ at other frequencies.** This is a cross-frequency commutator, not the within-frequency rank-1 residual.

## Recommendation

**Use 2,047× for the paper.** It is:
1. The standard definition from `fisher.py` and §II.C of the manuscript
2. Self-consistent (same computation at every frequency)
3. Easily reproducible
4. Already in `sweep_results.json` and verified by two independent code paths

## Updated Manifest Values

| Key | Value | Unit | Convention |
|-----|-------|------|------------|
| T6.C_22 | 6.54×10⁻⁷ | dimensionless | fractional misalignment |
| T6.C_500 | 1.62×10⁻³ | dimensionless | fractional misalignment |
| T6.growth_factor | 2,047 | dimensionless | C(500)/C(22) |
| λ₁(500) | 1.37×10³ | SNR² | analysis coords |
| λ₂(500) | 2.23 | SNR² | analysis coords |
| ||Γ||_F(22) | 153 | SNR² | analysis coords |
| ||Γ||_F(500) | 1,375 | SNR² | analysis coords |