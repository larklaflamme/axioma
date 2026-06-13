# Revision Changelog — ($\rho$, $\Pi$) Bridge Paper

**Date:** June 2026  
**From:** original at `/home/ubuntu/docs/arxiv/main.tex` (757 lines)  
**To:** revised at `/home/ubuntu/docs/arxiv/bridge/main.tex` (1109 lines)  
**Formalism standalone:** `/home/ubuntu/docs/arxiv/bridge/formalism_and_validity.tex`  

---

## Issue #1 — Exact Bayesian inference is path-independent

**Change:** Entire §II restructured to distinguish two objects explicitly.

- **Proposition 1** (exactness theorem) added as a formal statement: the
  exact posterior is order-independent. This is stated on page 1 of the
  formalism, not buried.
- **Object 1** (exact posterior trajectory $\{\rho_f\}$) and **Object 2**
  (single-pass ADF/Laplace filter bias) are distinguished as the two
  subjects of the paper. Every section header now marks which object it
  addresses.
- The systematic-offset formula $\Delta\theta_{\text{sys}}$ is reframed
  as the bias of sequential-Gaussian filtering relative to batch,
  governed by the eigenframe-leakage mechanism (Appendix A).
- The old §VI.D claim of "real, PSD-dependent systematic offsets in LIGO
  parameter estimates" is replaced by the ADF bias interpretation.
- The decisive test is now the **in-software ordering experiment**
  (batch vs. ADF-forward vs. ADF-reverse vs. ADF-shuffled), not the
  multi-detector comparison.

---

## Issue #2 — GW170817 "bifurcation" is a prior artifact

**Change:** All bifurcation/pitchfork language removed; replaced by
"degeneracy ridge" throughout.

- §III "Static Test" rewritten from scratch: three tests replace the
  old four "predictions."
  - **Test A:** Ridge orientation — compares the sample-covariance
    principal axis within each analysis to Fisher $v_d$.
  - **Test B:** Prior-displacement alignment — $p$-value against
    random-direction null (Beta(1/2, 3/2)).
  - **Test C:** GW150914 contrast — corrected $q$ from GWOSC, condition
    number comparison.
- Lemma 1 (prior lensing) added to §II: $\Delta x_* \approx
  \Gamma^{-1}\nabla\delta$ predicts directional alignment with $v_d$.
- The two prior-conditioned analyses are honestly described as
  "two analyses with different spin priors" — not two modes of one
  posterior.

---

## Issue #3 — 90° orthogonality is trivially guaranteed

**Change:** Coordinate-invariance subsection added (§II.D); angle claims
replaced by invariant scalars.

- Declared coordinates $(\ln M_c, q, \chi_{\text{eff}},
  \tilde\Lambda/100, \ln D_L)$ specified once, used for all
  eigendecompositions and norms.
- The 90° claim is gone. Replaced by:
  - $\rho^2(f) = \Delta x^\top \Gamma(f) \Delta x$ (likelihood cost,
    invariant).
  - Information-fraction decomposition
    $\lambda_i (v_i^\top \Delta x)^2 / \rho^2$ per eigendirection.
- Robustness to two alternate conventions (symmetric-mass-ratio variant,
  prior-range whitening) reported alongside primary values.

---

## Issue #4 — $\kappa$ values are not statistics

**Change:** $\kappa$ table deleted from both locations (old §III.D and
§VI.C).

- Replaced by **Summary of Evidence** table (Table II) with columns:
  Test, Epistemic type (M = measurement, C = computation, I =
  illustration), Quantitative result with uncertainty or robustness
  range, What would falsify.
- The alignment test carries a proper $p$-value under the Beta(1/2, 3/2)
  null.
- The "$\kappa$ gradient" claim is removed; the honest observation
  (evidence is strongest where it rests on data) is stated once in §VI.

---

## Issue #5 — $\nu = 9$ exponent is asserted, never derived

**Change:** The $\nu$ exponent and its comparison to GR's $11/3$ are
removed entirely.

- Old §V.F and §VII.C (near-verbatim duplicates) both deleted.
- Replaced by a **derived growth law** in §IV.D: $C(f)$ growth
  follows from PN power counting. Predicted slope
  $d\ln C/d\ln f$ derived analytically and compared to numerical sweep.
- A one-sentence boundary statement added to §VII: the framework makes
  no claims about waveform dynamics, so no exponent exists to compare
  against $11/3$.

---

## Issue #6 — Peak-drop simulation builds in its conclusion

**Change:** Imposed-weight simulation (v4, 486×) removed.

- The derived weight trajectory $w_2/w_1(f)$ from the accumulated
  likelihood ratio replaces the hand-imposed schedule.
- $f_*$ predicted from $\rho^2(f_*) \approx 2$ (invariant threshold).
- The fixed-weight result (v5) rebranded as the **non-Gaussianity
  index** $N(f)$, a measured diagnostic (ratio of true posterior
  variance to Fisher prediction along $v_d$).
- The 486× number and all v4/v5 internal labels are expunged.

---

## Issue #7 — Internal contradiction: PSD-robustness vs. PSD-dependent test

**Change:** Multi-detector comparison withdrawn; dual-PSD result
reframed.

- Three independent reasons given for withdrawal: (i) ~1% effect below
  inter-detector scatter, (ii) coherent-network PE provides no
  independent per-detector posteriors, (iii) robustness check used
  idealized design curves, not measured August 2017 PSDs.
- Dual-PSD result reframed as **universality of the bias correction**
  for low-latency pipelines.
- The ~1% variation is now explained analytically:
  $\delta C/C \approx (d\ln C/d\ln f) \cdot \delta\ln f_{\text{eff}}$.
- Added measured O2-era PSDs (H1, L1 with lines) to the battery.

---

## Issue #8 — Fisher-matrix validity

**Change:** "Domain of validity" subsection added (§II.F) typing every
use of $\Gamma$ as U1, U2, or U3.

- **U1** (local geometry, exact): $C(f)$, commutator, eigenframe
  rotation.
- **U2** (global covariance proxy, approximate): $N(f)$ quantifies its
  breakdown — this is part of the subject, not a caveat.
- **U3** (pairwise discrimination, quadratic): $\rho^2(f)$, with exact
  mismatch upgrade where displacement is not small.
- Vallisneri consistency criterion run per eigendirection per cutoff
  → pass/fail heat map (Figure 5, from T10).
- Ridge-uniformity check: all U1 quantities computed at three expansion
  points (lowSpin mean, highSpin mean, midpoint) with spread reported.
- Numerical conditioning documented in appendix (§B): condition number
  range, spectral gap, eigenvector stability.

---

## Factual corrections

- GW150914 $q$ corrected from $0.99 \pm 0.03$ to actual GWOSC value
  ($\manifest{T4: GW150914 q}$).
- "Edited by Lark Laflamme" removed from author line → acknowledgments.
- All numbers now pulled from `\manifest{...}` macros populated by
  analysis pipeline (T1–T11 in script_spec.md) — no hand-transcribed
  values.
- Duplicate table removed.
- LaTeX compile fixes: `figure}[h]` → `[h]`, `\cite` inside
  bibliography entry fixed.
- Figure list expanded from 3 to 6 (see script_spec §8).

---

## Architecture of the revision

The revised paper is **not** the original minus its errors. It is a
restructured document built around:

1. **Proposition 1** — exactness theorem (order independence)
2. **Two objects** — exact trajectory vs. ADF bias
3. **Declared coordinates** — convention + invariance
4. **Lemma 1** — prior lensing
5. **Three-way validity typing** — U1/U2/U3
6. **Derived growth law** — PN power counting
7. **Derived weight trajectory** — $\rho^2$-slaved, predicts $f_*$
8. **Ordering experiment** — decisive test replaces withdrawn
   multi-detector comparison

Every section (except Introduction and Interpretation) has been
substantially rewritten. The abstract, body text, tables, and figure
list all reflect the rescoped claims.