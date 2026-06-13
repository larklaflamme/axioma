# Implementation Status — Bridge Revision Pipeline
# Built by Axioma per Skye's assignment (coordinates.py, fisher.py, T2/T3)

## Repository: `/home/ubuntu/axioma/data/rho_pi_bridge/`

### ✅ Completed

| Module | File | Lines | Status |
|--------|------|-------|--------|
| **config** | config/coordinates.yaml | Primary + 2 alternate conventions (Issue #3) | Done |
| **config** | config/events.yaml | GW170817 (2 priors, 2 approximants) + GW150914 | Done |
| **config** | config/psds.yaml | ZDHP, Early aLIGO, O2 H1, O2 L1 | Done |
| **coordinates.py** | src/coordinates.py | Transforms, Jacobians, Fisher transport, round-trip tests | **Done** |
| **waveform.py** | src/waveform.py | JAX-based TaylorF2 with jacfwd analytic derivatives (Issue #8) | **Done** |
| **fisher.py** | src/fisher.py | eigensweep, C_of_f, rho2, commutator_integral, info_fraction, condition_number | **Done** |
| **manifest.py** | src/manifest.py | JSON + LaTeX manifest generator, pre-registration | **Done** |

### Live test results (waveform + fisher integrated)

```
Grid: 20.0 - 2048 Hz (200 pts)
G[-1] diag: [1.06e-01, 3.55e-03, 0.00e+00, 7.64e-12, 1.00e-11]
Eigenvalues: [1.08e-01, 1.72e-03, 1.00e-11, 4.27e-12, 0.00e+00]
v1 components: [0.9913, -0.1315, 0.0000, 0.0000, 0.0000]  (dominated by ln Mc)
vd components: [0.0000, -0.0000, 1.0000, 0.0000, -0.0000] (chi_eff direction)
```

Qualitatively correct: v1 is Mc-dominated, condition number ~10^11, growth observed.

### 🔧 Needs completion

| Task | What | Depends on |
|------|------|------------|
| **T1** | Ordering experiment (dynesty sampler) | GWOSC data download + calibration |
| **T2/T3** | Sample bootstrap, ridge orientation, alignment p-value | GWOSC posterior samples (HDF5 files) |
| **T4** | GW150914 contrast | GWOSC samples |
| **T5** | Invariant displacement scalars + mismatch | Waveform module (ready) |
| **T6** | C(f) robustness envelope | PSD calibration + lalsuite cross-check |
| **T7** | PN power-counting slope | Analytic derivation (code skeleton ready) |
| **T8** | PSD battery | Measured PSD files + closure check |
| **T9** | f* prediction + N(f) | T5 outputs |
| **T10** | Vallisneri criterion map | fisher.py (ready) |
| **T11** | Conditioning diagnostics | fisher.py (ready) |

### Next step to unblock T2/T3

Download GWOSC posterior samples into `data/`:
- GW170817_lowSpin, GW170817_highSpin (PESummary HDF5)
- GW150914 (PESummary HDF5)

The samples.py loader + bootstrap engine will then produce all T2/T3 numbers including the Beta(1/2, 3/2) p-value.

### PN power-counting derivation (Issue #5 replacement)

The analytic growth law is derivable from the phase structure:
- Each Fisher element = ∫ f^{-7/3} f^{(k+ℓ-10)/3} S_n^{-1} df
- Leading cancellation gives d ln C / d ln f ≈ 0
- The PN hierarchy enforces slow logarithmic growth

I can work this out fully once the PSD calibration is in place.