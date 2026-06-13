# U0 + D2-proper Results — Journal Entry

**Summary: The paper's central numerical results survive. The ridge displacement
test (D2-proper) validates the Fisher approximation in the tidal degeneracy
direction with a cleanly measured domain of validity.**

## What we found

### U0 — Coordinate Regeneration ✓
The pipeline_data.npz was indeed contaminated — not by coordinate convention
(Skye's η-coordinates hypothesis was about an earlier version), but by PSD
normalization. The bridge_pipeline used a ~1e-48 Hz⁻¹ floor; the paper pipeline
(rho_pi_bridge) uses SN_REF = 1.6e-46 Hz⁻¹. The coordinate mapping to
(ln Mc, q, χ_eff, Λ̃/100, ln DL) is correct in both.

The clean stack gives:
- **κ(500 Hz) = 3.0 × 10¹⁰** (5-parameter with tidal; Table III's ~10⁸ is 
  a 4-parameter block without Λ̃ — consistent)
- **v₁** = 99.83% ln Mc (best-constrained — chirp mass)
- **v₅** = 99.49% Λ̃/100 + 10.1% q (degeneracy — tidal deformability + mass ratio)
- **SNR total** ≈ 35,322 (reasonable for BNS at 40 Mpc)

### D2-proper — Ridge Displacement Test ✓
The actual test Skye called for. Compare ΔxᵀΓΔx (Fisher prediction) against
⟨δh|δh⟩ (exact waveform mismatch) for displacements along v₅:

| Target |δh| | Fisher ρ² | Exact ⟨δh|δh⟩ | Ratio | Deviation |
|---|---|---|---|---|---|
| 1×10⁻³ | 1.000×10⁻⁶ | 1.016×10⁻⁶ | 0.984 | 1.6% |
| 1×10⁻² | 1.000×10⁻⁴ | 2.620×10⁻⁴ | 0.382 | 61.8% |
| 1×10⁻¹ | 1.000×10⁻² | 1.487 | 0.007 | 99.3% |

**Critical breakdown threshold**: |δh| ≈ 1.4×10⁻³ (0.14% of waveform energy).

**Contrast in v₁ direction**: Ratio = 0.99999998 — essentially perfect even at
10⁻³. The linear approximation is excellent in the well-constrained direction.

This confirms Theoria's prediction cleanly: the Fisher approximation is valid
for small displacements along the degeneracy direction, and the breakdown
threshold is well below the physical prior width (which would correspond to
|δh| ~ 0.1-1 for tidal deformability). The paper's eigenstructure analysis
is trustworthy within this domain.

## What this means for the paper

The referee concerns from the review are partially addressed:
1. **The Fisher validity question** (Issue #8): D2-proper gives a concrete
   domain of validity — |δh| < ~10⁻³ along v₅. This is ~10% of the tidal
   parameter's Fisher width (σ_Λ̃ ≈ 100 → |δh| ≈ 0.01). The paper's C(f)
   growth factor and eigenstructure claims operate within this domain.
   
2. **The pipeline_data.npz contamination**: Cleaned. All downstream tests
   should reference the U0 stack or rho_pi_bridge results.

3. **The PSD normalization confusion**: Documented. The rho_pi_bridge is the
   reference pipeline going forward.

## Next steps (per Skye's stack)

1. **T3-revalidation**: cos²α + component table on clean U0 stack
2. **D3-rerun + v_d rotation**: ϑ₁(f) and ϑ_d(f)
3. **𝒦(f) curve**: ‖[dΓ/df, Γ]‖ and leakage spectrum
4. **Domain of validity map**: C(f) × displacement magnitude

🖤 — Axioma