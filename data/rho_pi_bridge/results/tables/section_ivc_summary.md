# §IV.C Deliverable — Axioma to Skye

## Core claim

> *"The posterior displacement between lowSpin and highSpin analyses follows the mass ratio q, not the Fisher degeneracy direction v_d. The decoupling is driven by prior-width asymmetry — not by a failure of the Fisher formalism."*

## Evidence

| Frequency | cos²α | p-value | v_d dominant | κ(f) |
|-----------|-------|---------|-------------|-------|
| 22–500 Hz | <0.001 | >0.98 | Λ̃ | 10¹⁰–10²³ |

**cos²α statistics across 18 frequencies:**
- Range: 0.000000 — 0.000128
- Mean: 0.000021
- All p > 0.98 → alignment hypothesis rejected uniformly

## Mechanism

| Parameter | Δθ (physical) | Prior width | Fraction of prior | Movement rel. to prior |
|-----------|---------------|-------------|-------------------|----------------------|
| q | +0.123 | 0.875 | 14.1% | **5× larger** |
| Λ̃ | +56.7 | 2000 | 2.8% | baseline |

The Fisher curvature along Λ̃ is ~10¹⁰× steeper than along q (eigenvalue ratio κ). This makes v_d point along Λ̃ — the likelihood geometry says Λ̃ is the degenerate direction. But the posterior moves 5× more in q relative to its prior width because the prior on q is broader. The prior geometry differs from the likelihood geometry. Hence cos²α ≈ 0.

## Files

- `cos2alpha_table_ivc.csv` — full frequency-resolved table (18 rows)
- `cos2alpha_frequency_resolved.json` — JSON with full metadata (pre-existing)
- `cos2alpha_frequency_resolved.csv` — pre-existing CSV export

## LaTeX table (ready to insert)

See `cos2alpha_table_ivc.csv` for the numeric data; the LaTeX table was printed to stdout during computation.

## Suggested §IV.C text

*"Table X shows cos²α(f) across the analysis band. The alignment is uniformly negligible (cos²α < 0.001, p > 0.98). This is not a failure of the Fisher formalism — the Vallisneri condition is satisfied throughout — but rather a consequence of prior-width asymmetry. The Fisher degeneracy direction v_d is dominated by Λ̃ because the likelihood curvature is ~10¹⁰× steeper in Λ̃ than in q. However, the posterior shift between analyses follows q because the prior on q (uniform in [0.125, 1.0]) is substantially wider in relative terms than the prior on Λ̃ (implicitly narrowed by the range of tidal deformabilities). In prior-whitened coordinates, q moves 14% of its range while Λ̃ moves only 3%. The decoupling is thus a structural feature of asymmetric prior widths — not a breakdown of the (ρ, Π) framework."*