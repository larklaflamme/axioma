# Analysis Script Specification — (ρ, Π) Bridge Revision

**Purpose:** Single pipeline producing every number, table, and figure required by the revised
manuscript. Each analysis task (T1–T11) is keyed to the review issue it resolves and the
manuscript section it populates. All paper-bound numbers are emitted to a versioned JSON
manifest so no value is ever transcribed by hand into LaTeX.

**Target runtime:** Phase 1 ≈ minutes (laptop). Phase 2 ≈ 1–2 hours. Phase 3 ≈ overnight
(sampler-dominated).

---

## 1. Repository layout

```
rho_pi_bridge/
├── config/
│   ├── coordinates.yaml        # declared convention + alternates (Issue #3)
│   ├── events.yaml             # GWOSC file paths, GPS times, injection params
│   └── psds.yaml               # PSD registry: analytic + measured
├── src/
│   ├── coordinates.py          # parameter transforms, Jacobians
│   ├── waveform.py             # TaylorF2 (JAX), inner products, mismatch
│   ├── fisher.py               # autodiff derivatives, cumulative Γ(f), eigensweep
│   ├── samples.py              # GWOSC/PESummary loaders, bootstrap engine
│   ├── adf.py                  # sequential-Laplace recursion (Issue #1)
│   └── manifest.py             # result registry → results/manifest.json
├── analyses/
│   ├── t01_ordering.py … t11_conditioning.py
├── results/                    # manifest.json, figures/, tables/
└── data/                       # user-downloaded GWOSC files (gitignored)
```

**Dependencies:** `numpy`, `scipy`, `jax` (CPU is sufficient), `h5py`, `pesummary`,
`matplotlib`, `dynesty` (T1 only), `lalsuite` (optional — cross-check only, see §3).
Pin versions in `requirements.txt`; record `jax` version in the manifest (eigensolver
reproducibility).

---

## 2. Coordinate module (`coordinates.py`) — Issue #3

**Declared convention (primary), used for every eigendecomposition, norm, and angle:**

```
x = ( ln Mc,  q,  χeff,  Λ̃/100,  ln DL )
```

Rationale: `ln Mc`, `ln DL` are scale-free; `q`, `χeff` are already dimensionless and
O(1); `Λ̃` is rescaled to O(1) rather than logged because the lowSpin analysis allows
values approaching the boundary of support.

**Alternate conventions (robustness battery, used by T6/T8):**

- `ALT-A`: ( ln Mc, η, χeff, ln(Λ̃+ε), ln DL ), ε = 1
- `ALT-B`: prior-range whitening — each raw parameter divided by its prior width

**API:**

```python
to_coords(theta_phys, convention)      # physical → analysis coordinates
jacobian(theta_phys, convention)       # ∂x/∂θ_phys, used to transport Γ and vectors
transport_fisher(G_phys, J)            # Γ_x = J⁻ᵀ Γ_phys J⁻¹
```

**Acceptance check:** invariant scalars (ρ², ΔlogL, mismatch) must agree across all three
conventions to < 1e-10 relative; this is a unit test, not a result.

---

## 3. Waveform module (`waveform.py`)

TaylorF2, 3.5PN point-particle phase + leading-order (5PN-relative) tidal term, amplitude
to Newtonian order — i.e., exactly the model in the current draft, reimplemented in JAX.

```python
htilde(f_array, theta)          # complex strain; pure jax.numpy, jittable
inner(a, b, f_array, psd)       # 4 Re ∫ a b* / S_n df   (trapezoid on the f grid)
mismatch_exact(theta1, theta2, f_array, psd)   # ⟨δh|δh⟩, δh = h(θ1) − h(θ2)
```

**Why JAX (not finite differences, not lalsuite-first):** Issue #8 identified
finite-difference corruption of the degenerate eigenvector v₂ in an ill-conditioned Γ as a
threat to C(f) itself. `jax.jacfwd(htilde)` gives machine-precision derivatives and removes
the step-size question from the error budget entirely. TaylorF2 is closed-form, so the port
is mechanical. **lalsuite role:** cross-check only — T6 includes one comparison run of Γ at
full band against lalsuite finite-difference values (agreement to ~1e-6 expected; record in
manifest).

**Approximant robustness (T6):** one IMRPhenomD_NRTidal run via lalsuite at 5 cutoffs to
bound waveform-systematic sensitivity of the C(f) growth factor. This path may use finite
differences (it is a robustness bound, not a primary result).

**Frequency grid:** N = 500 log-spaced bins, f ∈ [20, 2048] Hz, with cutoff sweep evaluated
at the 18 manuscript cutoffs plus a dense 200-point grid for slope fitting (T7).

---

## 4. Fisher module (`fisher.py`)

```python
fisher_cumulative(theta, f_array, psd, convention)
    # returns Γ(f_k) for all k in one pass: outer products of jacfwd rows,
    # cumulative trapezoid along f. Shape (Nf, 5, 5).
eigensweep(G_stack)             # λ_i(f), v_i(f) with sign-continuity enforced
C_of_f(G_stack)                 # ‖Γ − λ1 Π‖_F / ‖Γ‖_F per cutoff
commutator_integral(G_stack)    # ∫ ‖[Γ, Π]‖_F df  (for T8 ratios)
rho2(G_stack, dtheta)           # Δθᵀ Γ(f) Δθ per cutoff (quadratic form)
```

**Sign continuity:** eigenvectors flipped to maximize ⟨v_i(f_k), v_i(f_{k−1})⟩ — required
for angle tracking and for T11 convergence plots.

**Expansion points:** every Fisher quantity is computed at **three** points (Issue #8
ridge-uniformity): the lowSpin posterior mean, the highSpin posterior mean, and their
midpoint. Primary numbers quote the midpoint; the spread across the three enters the
manifest as the ridge-uniformity band.

---

## 5. Samples module (`samples.py`)

**Inputs (user downloads; GWOSC is outside this sandbox's network allowlist):**

| Key                 | File                                                  | Notes                   |
| ------------------- | ----------------------------------------------------- | ----------------------- |
| `GW170817_lowspin`  | GWTC-1 PESummary HDF5, IMRPhenomPv2NRT_lowSpin        | χ < 0.05 prior          |
| `GW170817_highspin` | GWTC-1 PESummary HDF5, IMRPhenomPv2NRT_highSpin       | χ < 0.89 prior          |
| `GW170817_tf2`      | TaylorF2 posterior release (both priors if available) | cross-approximant check |
| `GW150914`          | GWTC-1 PESummary HDF5                                 | T4                      |

Loader extracts (Mc, q, χeff, Λ̃, DL) per sample, converts via `coordinates.py`, and
records the file SHA-256 in the manifest (provenance — fixes the "numbers quoted from
memory" class of error wholesale).

**Bootstrap engine:** N_boot = 1000 resamples, fixed seed (`config`), used by T2/T3/T9.
All sample-derived quantities are reported as median with 5–95% bootstrap interval.

---

## 6. Analysis tasks

### Phase 1 — samples only (no waveform code required)

**T2 — Ridge orientation (Issue #2 Test A → revised §III).**
For each prior analysis separately: sample covariance in declared coordinates restricted to
(q, χeff) and to the full 4D Mc-orthogonal subspace; principal axis vs Fisher v₂ at full
band. *Outputs:* alignment angle + bootstrap CI, per analysis, per subspace.
*Falsification threshold (pre-registered in manifest):* misalignment > 20° at 95%.

**T3 — Prior-displacement alignment (Issue #2 Test B, Issue #4 statistic → §III, evidence
table).** Δx = mean(highspin) − mean(lowspin) in declared coordinates. Report: (a) raw
ΔMc with bootstrap CI — replaces the "exactly 0" claim; (b) restriction of Δx to the 4D
Mc-orthogonal subspace; (c) cos²α against v₂ within that subspace; (d) p-value under the
random-direction null, cos²α ~ Beta(1/2, 3/2): `p = 1 − scipy.stats.beta.cdf(cos2a, 0.5, 1.5)`;
(e) bootstrap CI on α. Repeat for the TaylorF2 release pair (cross-approximant
persistence of the *direction*, the honest descendant of the old "persists across
approximants" claim).

**T4 — GW150914 contrast + corrected numbers (Issue #2 Test C, factual fixes → §III).**
Recompute q, χeff (median, 90% CI) from actual samples — replaces q = 0.99 ± 0.03.
Compute Γ for GW150914 parameters (no tidal sector; 4D space), report condition number vs
GW170817's at matched cutoffs, and the ratio of λ_min⁻¹ lensing gains. *Prediction on
record:* GW170817 gain exceeds GW150914's by ≳ an order of magnitude.

### Phase 2 — Fisher sweep infrastructure

**T5 — Invariant displacement scalars (Issues #3, #8 → §III).**
ρ²(f) = ΔxᵀΓ(f)Δx at all 18 cutoffs (quadratic), and `mismatch_exact` between the two
prior-conditioned mean waveforms at the same cutoffs (exact). Report both curves and their
ratio (the linear-signal validity factor — feeds T10). Information-fraction decomposition
λᵢ(vᵢᵀΔx)²/ρ² at full band, with bootstrap CI. *Pre-registered prediction:* fraction on
the smallest-λ direction > 0.9.

**T6 — C(f) sweep + robustness battery (Issues #3, #4, #5 → §IV, evidence table).**
C(f) on the dense grid, declared convention, midpoint expansion. Growth factor
C(500)/C(22) under: {primary, ALT-A, ALT-B} × {3 expansion points} × {TaylorF2,
IMRPhenomD_NRTidal at 5 cutoffs}. *Output:* central value + min/max envelope — this
envelope *is* the evidence-table robustness entry. Includes the lalsuite cross-check run.

**T7 — Growth-law slope (Issue #5 → §V derivation check).**
Fit d ln C / d ln f on the dense grid, piecewise over [22, 75], [75, 200], [200, 500] Hz
(the PN-order transition bands), with fit residuals. Analytic power-counting values are
entered in `config` as constants once the derivation is done; the script emits
predicted-vs-measured per band. *Pre-registered tolerance:* agreement within 25% per band.

**T8 — PSD battery (Issue #7 → §IV).**
PSD registry: ZDHP (analytic), Early aLIGO (analytic), measured O2 H1 and L1 PSDs
(GWOSC strain-derived, spectral lines retained). For each: commutator integral, C(22),
C(500) — recomputed in declared coordinates (the printed 0.989 is superseded). Additionally:
δC/C predicted from δ ln f_eff (PSD-weighted log-mean frequency shift) × measured slope
(T7) vs actual δC/C — the closed-loop check. Line-artifact scan: flag any |ΔC| between
adjacent grid points > 5× the local median step (steps at line frequencies).

**T9 — Derived weight trajectory, f*, and N(f) (Issue #6 → §V forward model).**
w₂/w₁(f) = exp(−½ρ²_exact(f) + ρ_exact(f)·z), z ~ N(0,1), 10⁴ draws. Between/within
ratio curve using σ²(f) = (Γ(f)⁻¹) projected on v₂. *Outputs:* f* solving ρ²_exact = 2
(report also for thresholds 1 and 4 — sensitivity band), peak magnitude, and the f*
scatter distribution across noise draws (the population-survey prediction).
N(f) = Var_samples(v₂ᵀx) / (Γ(f)⁻¹)_{v₂v₂}, full band, both prior analyses — the
non-Gaussianity index; manifest records N(500 Hz).

### Phase 3 — sampler-dependent

**T1 — Ordering experiment (Issue #1 → rewritten §VI.B; the paper's decisive test).**
Synthetic injection, GW170817-midpoint parameters, ZDHP PSD, f ∈ [22, 500] Hz split into
B = 18 bands. Three data conditions: zero-noise, plus 2 fixed noise realizations (seeded).
Inference arms per condition:
  (a) **batch** — `dynesty` on the full-band likelihood (ground truth; 5D, cheap);
  (b) **ADF-forward** — `adf.py`: per-band Laplace update, linearize at current mean,
      re-Gaussianize, ascending bands;
  (c) **ADF-reverse** — descending bands;
  (d) **ADF-shuffled** — 20 random permutations (seeded).
*Outputs:* offset vectors (b,c,d)−(a) in declared coordinates; projection onto v₂;
predicted offset from the commutator-integral bias formula per ordering; predicted-vs-
measured scatter plot across the 23 ADF runs. *Pre-registered success criterion:*
rank correlation (Spearman) between predicted and measured v₂-offsets > 0.7 across
orderings; zero-noise arm offsets within a factor of 2 of prediction.
*This figure replaces the deleted multi-detector test and becomes the §VI.B centerpiece.*

**T10 — Vallisneri criterion map (Issue #8 → validity subsection).**
At each of the 18 cutoffs, for each eigendirection i: displace by ±1σ_i = ±λ_i^{−1/2} v_i,
compute exact mismatch, form r_i(f) = mismatch_exact / (½·1²) (quadratic prediction = ½).
Pass if |r − 1| < 0.1 (tolerance in config). *Output:* pass/fail heat map over
(f, eigendirection) — the figure that demonstrates the approximation's domain was mapped.
*Expected:* v₁ passes everywhere; v₂ fails at low f with onset tracking N(f).

**T11 — Conditioning diagnostics (Issue #8 → appendix).**
κ(Γ(f)) across the sweep (all three conventions); v₂ stability under perturbation
(eigenvector condition via spectral gap λ₄ − λ₅); autodiff-vs-finite-difference v₂ angle
at 5 step sizes (quantifies the error the JAX port eliminates — one panel, ends the
discussion).

---

## 7. Manifest contract (`manifest.py`)

Every paper-bound value is registered:

```python
record("T3.alignment_angle_deg", value, ci=(lo, hi), section="III.C", table="II")
```

`results/manifest.json` carries: value, uncertainty, units, convention, expansion point,
input-file hashes, git commit, seed. The LaTeX revision pulls from a generated
`manifest.tex` of `\newcommand` macros — no hand-transcribed numbers anywhere in the
manuscript. Pre-registered thresholds (T1, T2, T5, T7) live in `config` and are echoed
into the manifest *before* results, so the falsifiability column of the evidence table
cites commitments made ahead of the numbers.

## 8. Figure list (1:1 with revised manuscript)

| Fig | Source                                              | Replaces                  |
| --- | --------------------------------------------------- | ------------------------- |
| 1   | T6 C(f) + robustness envelope; T7 slope inset       | current Fig. 1            |
| 2   | T8 four-PSD comparison + closed-loop δC/C check     | current Fig. 2            |
| 3   | T9 between/within curve, f* band, f* scatter        | current Fig. 3 (v4/v5)    |
| 4   | T1 predicted-vs-measured ADF offsets                | — (new centerpiece)       |
| 5   | T10 validity heat map                               | — (new)                   |
| 6   | T2/T3 ridge + displacement corner plot, both priors | — (new, replaces Table I) |

## 9. Execution order and gates

1. **Phase 1** (T2, T3, T4): runs the day the GWOSC files are downloaded; fixes every
   factual error in §III and produces the headline p-value. **Gate:** if T3's alignment
   p-value is not small (say > 0.05), the static section's claim does not survive — know
   this before writing any §III text.
2. **Phase 2** (T5–T9): the Fisher rebuild. **Gate:** T6's robustness envelope must not
   include 1.0× (i.e., growth must survive convention changes) before §IV is rewritten.
3. **Phase 3** (T1, T10, T11): T1 is the long pole (dynesty × 3 conditions). Start it
   while drafting; its figure is the last one in.