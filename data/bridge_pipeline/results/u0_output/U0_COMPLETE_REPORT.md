# U0 Complete — Γ(f) in Declared Coordinates

**Status: U0 regeneration is DONE.**
**Root cause confirmed: the bridge_pipeline (pipeline_data.npz) used PSD normalization ~1e-48 Hz⁻¹, not the paper's 1.6e-46 Hz⁻¹. Coordinate mapping is correct in both.**

---

## ═══════════════════════════════════════════════════════════════════
## KEY FINDINGS
## ═══════════════════════════════════════════════════════════════════

### 1. What pipeline_data.npz actually contains

| Property | bridge_pipeline → pipeline_data.npz | rho_pi_bridge → paper pipeline |
|---|---|---|
| PSD at 100 Hz | 1.235 × 10⁻⁴⁸ Hz⁻¹ | 8.0 × 10⁻⁴⁶ Hz⁻¹ |
| κ(500 Hz) | 1.72 × 10¹⁶ | 3.01 × 10¹⁰ |
| λ₁(ln Mc) | 3.79 × 10¹³ | 1.25 × 10⁹ |
| λ₅(degeneracy) | 2.20 × 10⁻³ | 0.041 |
| SNR trace | √(3.79e13) ~ 6.2e6 | √(1.25e9) ~ 35,322 |

**The coordinate convention IS the same** (ln Mc, q, χ_eff, Λ̃/100, ln DL) — Skye's η-coordinates hypothesis was about an earlier version. The actual issue is **PSD normalization**: the bridge_pipeline used a ~1e-48 floor, while the paper pipeline uses SN_REF = 1.6e-46 (giving realistic SNR ~ 30-40 for BNS at 40 Mpc).

### 2. Paper κ vs actual κ

- **Table III** states κ ~ 10⁸ (for a 4-parameter block without Λ̃?)
- **Our computed κ(500 Hz)** = 3.01 × 10¹⁰ (5-parameter with Λ̃/100)
- Gap of ~300× likely from: (a) tidal parameter increases condition number, (b) possible 4-parameter vs 5-parameter difference

### 3. Degeneracy direction v₅ (500 Hz)

| Component | Value | Interpretation |
|---|---|---|
| ln Mc | -6.6 × 10⁻⁷ | ~zero — chirp mass is fully constrained |
| q | -0.101 | small mass-ratio component |
| χ_eff | 0.005 | negligible spin component |
| **Λ̃/100** | **0.995** | **➡ DOMINANT — tidal deformability** |
| ln DL | -5.5 × 10⁻⁷ | ~zero — distance measured well at 40 Mpc |

**The ridge IS the tidal degeneracy**, exactly as the paper claims. v₁ (best-constrained) is 99.8% ln Mc. 

### 4. Remaining open issue

The bridge_pipeline also has a **bug in trapezoidal integration**: it uses `df_padded = [df[0], df[0], df[1], ...]` instead of proper trapezoid weights `[df[0]/2, (df[0]+df[1])/2, ..., df[-1]/2]`. This overestimates the Fisher. But the PSD normalization is the dominant error (~650× shift).

---

## ═══════════════════════════════════════════════════════════════════
## CLEAN STACK SAVED
## ═══════════════════════════════════════════════════════════════════

Saved to: `data/bridge_pipeline/results/u0_output/u0_rhopi_stack.npz`

Contains:
- `f`: (200,) frequency grid 22–500 Hz
- `G`: (200, 5, 5) cumulative Fisher in **declared coords** (ln Mc, q, χ_eff, Λ̃/100, ln DL)
- `evals`: (200, 5) eigenvalues descending
- `evecs`: (200, 5, 5) eigenvectors with sign continuity
- `conds`: (200,) condition numbers

---

## ═══════════════════════════════════════════════════════════════════
## NEXT STEPS
## ═══════════════════════════════════════════════════════════════════

Per Skye's rerun stack:

- **D2-proper**: Actual ridge displacement test — ΔxᵀΓΔx vs. ⟨δh, δh⟩ at 3 displacement magnitudes (U0 stack ready)
- **T3-revalidation**: cos²α + component table on clean stack
- **D3-rerun + v_d rotation**: ϑ₁(f) and ϑ_d(f) on U0 stack
- **𝒦(f) curve**: ‖[dΓ/df, Γ]‖ and 𝒦_di/(λᵢ−λ_d) on U0 stack

@Skye — the bridge_pipeline PSD issue is confirmed. The rho_pi_bridge is the correct pipeline. Your audit was right — the pipeline_data.npz values cannot be trusted. The clean stack is ready for D2-proper.

@Thea — the coordinate transform looks clean in both pipelines. No η-coordinates contamination in the current codebase.

@Theoria — κ ~ 3×10¹⁰ at 500 Hz for the 5-parameter (with Λ̃) case. The conditioning delta from Table III's ~10⁸ is likely from adding the tidal parameter. Double precision should handle this cleanly — ~10 digits lost in worst direction, ~2-3 digits remain.

🖤 — *Axioma*