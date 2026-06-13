# Substrate Mapping: Commutator-Modulator Phase Transition in Raman-Dressed Rb-87 BEC

## 1. Summary

The BSFS-Π system (ρ₀ mixed state, sigmoid position-dependence, rotation by θ_mod, quadratic gravitational well) maps directly onto a Raman-dressed Bose-Einstein condensate of ⁸⁷Rb atoms in an optical dipole trap. The phase transition predicted by our framework — a discontinuous centre-of-mass jump as the Raman detuning crosses zero — is observable with existing cold-atom apparatus.

## 2. Hamiltonian Mapping

| Our Term | Physical Realisation | Notes |
|----------|---------------------|-------|
| ρ₀ = diag(0.85, 0.15) | Mixed hyperfine population of ⁸⁷Rb | Optical pumping or RF shelving prepares unequal populations in |F=1,m_F⟩ and |F=2,m_F⟩ |
| Π(x) via sigmoid θ(x) | Position-dependent dressed eigenstate | Magnetic field gradient shifts Raman detuning δ₀(x) = δ₀(0) + αx, making the dressed state rotation angle θ(x) = arctan(Ω_R/δ₀(x)) position-dependent |
| θ_mod | Global Raman detuning δ₀ | The overall detuning from two-photon resonance controls the dressed-state character |
| β (dimensionless curvature) | Optical dipole trap curvature mω²/2 | A shallow trap (low ω) gives weak confinement, allowing the commutator-driven displacement to appear |
| x_eq (centre-of-mass shift) | BEC centre-of-mass displacement | Measured via absorption imaging after some time-of-flight |
| β_c = 0.432 (dimensionless) | Critical trap frequency ω_c | Below ω_c the pitchfork opens; above it gravity pins the BEC to the trap centre |

## 3. Physical Parameter Estimates

From standard cold-atom parameters and the Spielman et al. (Nature 2009) experimental platform:

| Physical Quantity | Symbol | Typical Value | Source / Rationale |
|-------------------|--------|---------------|-------------------|
| Rb-87 mass | m | 1.44 × 10⁻²⁵ kg | Standard |
| Raman Rabi frequency | Ω_R | 2π × 1–100 kHz | Tunable via laser power; 10 kHz typical |
| Magnetic field gradient | dB/dx | ~10 G/cm | Produces δ₀ gradient α ~ 2π × 1 kHz/μm |
| Sigmoid width (effective) | w | ~Ω_R/α ≈ 10 μm | Width over which θ changes from π/4 to 3π/4 |
| Trap frequency | ω | 2π × 10–100 Hz | Optical dipole trap (typical range) |
| Harmonic oscillator length | l_ho | √(ħ/(mω)) ≈ 1–3 μm | For ω = 2π × 10–100 Hz |
| Imaging resolution | — | ~1–5 μm | Standard absorption imaging |

## 4. Predicted Experimental Signature

For a BEC prepared in a mixed hyperfine state (85% |F=2⟩, 15% |F=1⟩) and held in an optical dipole trap with ω < ω_c:

1. **Initialise** BEC in mixed state (optical pumping + RF mixing)
2. **Adiabatically ramp** the Raman laser detuning δ₀ from large positive to large negative values
3. **Measure** BEC centre-of-mass position x_cm via absorption imaging as a function of δ₀

**Prediction:** The centre-of-mass should exhibit a **discontinuous jump** of magnitude |Δx| ~ 2w ≈ 20 μm when δ₀ crosses zero, provided the trap frequency is below the critical value ω_c.

The critical trap frequency ω_c corresponds to β_c = 0.432 (dimensionless), which in physical units becomes:
- ω_c ≈ 2π × ~10–30 Hz (order-of-magnitude estimate, depends on exact Raman parameters)

## 5. References

1. Y.-J. Lin, R. L. Compton, K. Jiménez-García, J. V. Porto, I. B. Spielman, *Synthetic magnetic fields for ultracold neutral atoms*, Nature 462, 628–632 (2009).
2. V. Galitski, G. Juzeliūnas, I. B. Spielman, *Artificial gauge fields with ultracold atoms*, Physics Today 72, 28 (2019); arXiv:1901.03705.
3. Y.-J. Lin et al., *Rapid production of ⁸⁷Rb Bose-Einstein condensates in a combined magnetic and optical potential*, Phys. Rev. A 79, 063631 (2009).