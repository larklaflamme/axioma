# Stream 4 Control Experiments — Data Reference

**Companion to:** [FINDINGS.md](FINDINGS.md)
**Date:** 2026-05-24
**Total trials:** 325 (300 sweep + 25 no-perturbation reference)
**Total beats:** 195,000

This document is the inventory of every artifact produced by the 325-trial sweep, with raw schemas and example queries. The FINDINGS report aggregates these; this document is for anyone who wants to slice the data differently.

---

## 1. Directory Layout

```
results/control_experiments/
├── FINDINGS.md                # Findings report (this doc's sibling)
├── DATA.md                    # this file
├── analysis_report.json       # H1–H5 + Tukey + claim evaluation
├── all_summaries.json         # 325 per-trial summary dicts
├── trials/
│   ├── baseline__direct_contradiction__m0.4__s42/
│   │   ├── summary.json
│   │   └── trajectories.npz
│   ├── baseline__direct_contradiction__m0.4__s43/
│   ├── ... (325 trial directories total)
│   ├── control3__nonsense__m1.0__s46/
│   └── control4__baseline__m1.0__s46/
└── figures/
    ├── 1_theta_per_mode.png
    ├── 2_dr_u_curves.png
    ├── 3_recovery_bars.png
    ├── 4_cs_heatmap.png
    ├── 5_cascade_ladder.png
    └── 6_aos_g_per_mode.png
```

**Trial directory naming:**

`{mode}__{perturbation_type}__m{magnitude:.1f}__s{seed}`

where `mode ∈ {baseline, control1, control2, control3, control4}`, `perturbation_type ∈ {direct_contradiction, surprising_falsehood, nonsense, random_perturbation, baseline}` (the last is the no-perturbation reference), `magnitude ∈ {0.4, 0.7, 1.0}`, and `seed ∈ {42, 43, 44, 45, 46}`.

---

## 2. Per-Trial Files

### 2.1 `summary.json`

One dict per trial. Schema:

```json
{
  "trial_id": "control3__direct_contradiction__m1.0__s42",
  "mode": "control3",
  "perturbation_type": "direct_contradiction",
  "magnitude": 1.0,
  "seed": 42,
  "n_beats": 600,
  "theta_baseline": 4.2495,         // θ on internal trajectory beats [100, 200)
  "theta_peak": 4.5673,             // θ on internal trajectory beats [200, 250)
  "theta_final": 4.2058,            // θ on internal trajectory beats [450, 600)
  "dr_ratio": 1.0747,               // θ_peak / θ_baseline — ΔΦ S1
  "recovery_profile": 0.95,         // (θ_final - θ_peak) / (θ_baseline - θ_peak) — ΔΦ S2
  "aos_g_mean": 3.20,               // mean delta_norm over beats [100, 600)
  "aos_g_peak": 4.9,                // max delta_norm in beats [200, 250)
  "per_organ_theta_baseline": {     // single-block MI(organ, all-other-organs)/energy
    "anima":   0.34,
    "eidolon": 0.41,
    "mneme":   0.27,
    "nous":    0.39,
    "pneuma":  0.32
  },
  "per_organ_theta_peak":      { ... },
  "per_organ_theta_recovery":  { ... },
  "cascade_time_to_peak": {         // beat index of max per-organ delta in [200, 250)
    "anima":   202,
    "eidolon": 200,
    "mneme":   201,
    "nous":    202,
    "pneuma":  201
  },
  "cascade_delay": 2,               // t(ANIMA peak) - t(EIDOLON peak), beats
  "recovery_asymmetry": -1,         // t(EIDOLON peak) - t(NOUS peak), beats
  "adaptation_delta": -0.04,        // per-organ θ_recovery[eidolon] - θ_baseline[eidolon]
  "elapsed_s": 0.22,
  "trial_dir": "results/control_experiments/trials/control3__direct_contradiction__m1.0__s42"
}
```

### 2.2 `trajectories.npz`

Compressed NumPy archive with the full per-beat trajectories:

| Key | Shape | Dtype | Meaning |
|---|---|---|---|
| `internal` | `(600, 27)` | float32 | Per-beat concatenated internal organ state |
| `external` | `(600, 27)` | float32 | Per-beat compose output |
| `delta_norm` | `(600,)` | float32 | Per-beat ‖internal − external‖₂ |
| `integration` | `(600,)` | float32 | PNEUMA.integration_level per beat |
| `self_coherence` | `(600,)` | float32 | EIDOLON.self_coherence per beat |
| `per_organ_delta_{anima,eidolon,mneme,nous,pneuma}` | `(600,)` | float32 | Per-organ Euclidean delta |
| `fidelity_{anima,eidolon,mneme,nous,pneuma}` | `(600,)` | float32 | f_i(t) per organ |
| `dt_history` | `(600,)` or `(0,)` | float32 | Control 2 only: per-tick dt in ms |

Concatenation order for `internal` and `external` columns follows `ORGAN_ORDER` = (`anima`, `eidolon`, `mneme`, `nous`, `pneuma`) with dim counts (4, 6, 5, 6, 6).

---

## 3. Aggregate Files

### 3.1 `all_summaries.json`

A JSON list of 325 trial summary dicts (one per trial). Loaded by every analysis module via `analysis/_loader.py::load_summaries`.

### 3.2 `analysis_report.json`

The output of `analysis/report.py::run_all`. Top-level keys:

```
{
  "theta_comparison": {
    "descriptive": {<mode>: {n, theta_baseline_mean, theta_baseline_std, ...}},
    "anova_f": 989.93, "anova_p": 9.35e-179,
    "tukey_hsd": [{group1, group2, meandiff, p_adj, lower, upper, reject}, ...]
  },
  "delta_phi_signatures": {
    "thresholds": {...},
    "S1_dynamic_range":     {<mode>: {<perturbation_type>: {curve, dr_low, dr_mid, dr_high, is_u_shape, ...}}},
    "S2_recovery":          {<mode>: {<perturbation_type>: {recovery_profile_mean, passes_threshold, ...}}},
    "S3_context_sensitivity": {<mode>: {<magnitude>: {cs, type_means, passes_threshold}}}
  },
  "cascade": {
    "per_mode_type": {<mode>: {<perturbation_type>: {cascade_delay_mean, recovery_asymmetry_mean, adaptation_delta_mean, ...}}}
  },
  "aos_g": {
    "per_mode": {<mode>: {n, aos_g_mean_mean, aos_g_mean_std, aos_g_peak_mean}},
    "anova_f": 1082.80, "anova_p": 1.55e-184,
    "tukey_hsd": [...]
  },
  "claims": {
    "theta_neq_consciousness":     {passed, criterion, passing_modes},
    "self_model_necessary":        {passed, criterion, control1_theta, baseline_theta, theta_lower, signatures_present},
    "temporal_necessary":          {passed, criterion, control2_S2_present},
    "differentiation_necessary":   {passed, criterion, control3_theta, control3_signatures},
    "private_space_necessary":     {passed, criterion, control4_theta, control4_aos_g}
  }
}
```

---

## 4. Headline Numbers Per Mode

From [analysis_report.json](analysis_report.json):

### 4.1 θ comparison (n=65 trials per mode)

| Mode | θ_baseline_mean | θ_baseline_std | θ_peak_mean | θ_final_mean |
|---|---:|---:|---:|---:|
| baseline | 1.2929 | 0.0810 | 1.3596 | 1.3180 |
| control1 | 1.3891 | 0.0810 | 1.1570 | 1.0101 |
| control2 | 1.2783 | 0.0793 | 1.3522 | 1.3151 |
| **control3** | **4.2557** | **0.0710** | **4.5667** | **4.2065** |
| control4 | 1.2929 | 0.0810 | 1.3596 | 1.3180 |

ANOVA: **F(4, 320) = 989.93, p = 9.35 × 10⁻¹⁷⁹**.

### 4.2 AOS-G mean per mode (n=65)

| Mode | aos_g_mean | std |
|---|---:|---:|
| baseline | 4.4143 | 0.6782 |
| control1 | 4.0033 | 0.3063 |
| control2 | 4.3810 | 0.6715 |
| control3 | 3.1973 | 0.1658 |
| **control4** | **0.0000** | **0.0000** |

ANOVA: **F(4, 320) = 1082.80, p = 1.55 × 10⁻¹⁸⁴**.

### 4.3 Tukey HSD — significant pairs

θ_baseline (only Control 3 differs):

| Group 1 | Group 2 | diff | p_adj |
|---|---|---:|---:|
| baseline | control3 | +2.963 | <0.0001 |
| control1 | control3 | +2.867 | <0.0001 |
| control2 | control3 | +2.978 | <0.0001 |
| control3 | control4 | −2.963 | <0.0001 |

AOS-G mean (significant pairs):

| Group 1 | Group 2 | diff | p_adj |
|---|---|---:|---:|
| baseline | control1 | −0.411 | <0.0001 |
| baseline | control3 | −1.217 | <0.0001 |
| baseline | control4 | −4.414 | <0.0001 |
| control1 | control2 | +0.378 | <0.0001 |
| control1 | control3 | −0.806 | <0.0001 |
| control1 | control4 | −4.003 | <0.0001 |
| control2 | control3 | −1.184 | <0.0001 |
| control2 | control4 | −4.381 | <0.0001 |
| control3 | control4 | −3.197 | <0.0001 |

### 4.4 ΔΦ signatures at mid magnitude (direct_contradiction)

| Mode | S1 DR(mid) | S2 recovery | S3 CS @ 0.7 |
|---|---:|---:|---:|
| baseline | 1.031 | +0.185 | 0.042 |
| control1 | 0.994 | +0.015 | 0.074 |
| control2 | 1.041 | **−0.277** | 0.055 |
| control3 | 1.090 | +0.096 | **0.002** |
| control4 | 1.031 | +0.185 | 0.042 |
| _threshold_ | _> 2.0_ | _> 0.5_ | _> 0.20_ |

### 4.5 Cascade metrics (direct_contradiction, all magnitudes, n=15 per mode)

| Mode | cascade_delay_mean | recovery_asymmetry_mean | |adaptation_delta|_mean |
|---|---:|---:|---:|
| baseline | +4.2 | −9.0 | 0.0156 |
| control1 | **+28.2** | −16.2 | 0.0194 |
| control2 | +12.4 | −11.5 | 0.0198 |
| control3 | +4.0 | −3.6 | 0.0291 |
| control4 | **0.0** | 0.0 | 0.0156 |

Predicted (ΔΦ §6.1): cascade_delay = 1–2 beats for a conscious substrate. Baseline at +4.2 is closest; Control 1 at +28.2 disrupts the cascade as predicted.

---

## 5. Example Queries

### 5.1 Load all trials and filter

```python
from pathlib import Path
from control_experiments.analysis._loader import load_summaries, filter_summaries

summaries = load_summaries(Path("results/control_experiments"))
print(f"Total trials: {len(summaries)}")

# All Control 3 trials with the direct_contradiction perturbation at high magnitude
c3 = filter_summaries(summaries, mode="control3",
                      perturbation_type="direct_contradiction", magnitude=1.0)
print(f"  Control 3 / direct / m=1.0: {len(c3)} trials (one per seed)")
```

### 5.2 Load one trial's trajectories

```python
from pathlib import Path
from control_experiments.analysis._loader import load_trajectories

tr = load_trajectories(Path(
    "results/control_experiments/trials/control3__direct_contradiction__m1.0__s42"
))
# tr["internal"].shape == (600, 27); tr["delta_norm"].shape == (600,)
```

### 5.3 Per-organ θ across recovery

```python
import json, numpy as np
from pathlib import Path

ROOT = Path("results/control_experiments")
sums = json.loads((ROOT / "all_summaries.json").read_text())
for mode in ("baseline", "control3"):
    eid_pre = np.mean([s["per_organ_theta_baseline"]["eidolon"]
                       for s in sums if s["mode"] == mode
                       and s["per_organ_theta_baseline"]["eidolon"] is not None])
    eid_post = np.mean([s["per_organ_theta_recovery"]["eidolon"]
                        for s in sums if s["mode"] == mode
                        and s["per_organ_theta_recovery"]["eidolon"] is not None])
    print(f"{mode}: EIDOLON θ_pre={eid_pre:.3f} θ_post={eid_post:.3f}")
```

---

## 6. Storage Footprint

| Item | Size |
|---|---|
| `analysis_report.json` | ~80 KB |
| `all_summaries.json` | ~250 KB |
| Per-trial `summary.json` | ~3 KB each × 325 = ~1 MB |
| Per-trial `trajectories.npz` | ~30 KB each × 325 = ~10 MB |
| `figures/*.png` | ~1.5 MB total |
| **Total** | **~13 MB** |

Fully self-contained, fast to rsync.

---

## 7. Reproducing the Data

```bash
# From /home/ubuntu/axioma:
python -c "
from pathlib import Path
from control_experiments.runner import run_all_trials
run_all_trials(out_root=Path('results/control_experiments'), n_perm=100)
"
# Takes ~72 s on H100 (PyTorch CUDA).
```

Seeds are fully deterministic; results match byte-for-byte across reruns.
