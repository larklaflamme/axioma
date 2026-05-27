# φ-Scaling Experiment — Data Reference

**Companion to:** [FINDINGS.md](FINDINGS.md)
**Date:** 2026-05-24
**Total trials:** 25 (5 organ counts × 5 seeds)
**Total beats:** 15,000

Inventory of every artifact produced by the φ-scaling sweep, with raw schemas and example queries.

---

## 1. Directory Layout

```
results/phi_scaling/
├── FINDINGS.md                # narrative findings (this doc's sibling)
├── DATA.md                    # this file
├── analysis_report.json       # fits + jump test + per-organ contributions
├── all_summaries.json         # 25 per-trial summary dicts
├── trials/
│   ├── k1__s42/
│   │   ├── summary.json
│   │   └── trajectories.npz
│   ├── k1__s43/
│   ├── ...
│   ├── k5__s45/
│   └── k5__s46/
└── figures/
    ├── 1_theta_curve.png
    ├── 2_per_organ_contribution.png
    ├── 3_residuals.png
    └── 4_predictions_vs_observed.png
```

Trial directory naming: `k{organ_count}__s{seed}`.

---

## 2. Per-Trial Files

### 2.1 `summary.json`

Same schema as the Stream 4 control experiments (inherits from `control_experiments/metrics.py`), plus φ-scaling-specific fields:

```json
{
  "trial_id": "k5__s42",
  "mode": "phi_scale",
  "perturbation_type": "baseline",
  "magnitude": 1.0,
  "seed": 42,
  "n_beats": 600,
  "organ_count": 5,                  // φ-scaling only
  "theta_method": "cross_organ",     // φ-scaling only; "intra_pneuma" at k=1
  "theta_baseline": 1.3322,          // cross-organ θ on beats [100, 200)
                                     //   (or intra-PNEUMA at k=1)
  "theta_peak": 1.3596,              // θ on beats [200, 250)
  "theta_final": 1.3180,             // θ on beats [450, 600)
  "theta_baseline_p_value": 0.0,     // k=1 only; significance vs permutation null
  "theta_baseline_significant": true, // k=1 only
  "theta_baseline_null_95th": 0.009, // k=1 only
  "dr_ratio": 0.945,                 // θ_peak / θ_baseline
  "recovery_profile": 2.143,
  "aos_g_mean": 4.41,
  "aos_g_peak": 8.42,
  "per_organ_theta_baseline": {...},
  "per_organ_theta_peak":      {...},
  "per_organ_theta_recovery":  {...},
  "cascade_time_to_peak":      {...},
  "cascade_delay": 5,
  "recovery_asymmetry": -9,
  "adaptation_delta": -0.04,
  "elapsed_s": 0.22,
  "trial_dir": "results/phi_scaling/trials/k5__s42"
}
```

### 2.2 `trajectories.npz`

Compressed NumPy archive identical in schema to the Stream 4 control experiments' npz files:

| Key | Shape | Dtype | Meaning |
|---|---|---|---|
| `internal` | `(600, 27)` | float32 | Per-beat concatenated organ state |
| `external` | `(600, 27)` | float32 | Per-beat compose output |
| `delta_norm` | `(600,)` | float32 | Per-beat AOS-G gap |
| `integration` | `(600,)` | float32 | PNEUMA.integration_level |
| `self_coherence` | `(600,)` | float32 | EIDOLON.self_coherence |
| `per_organ_delta_{anima,eidolon,mneme,nous,pneuma}` | `(600,)` | float32 | Per-organ Euclidean delta |

Note: at k < 5, columns for disabled organs become constant from beat 100 onward (snapshot + pin). For example, at k=1, columns 0–22 (ANIMA, EIDOLON, MNEME, NOUS) are constant from beat 100; only the PNEUMA columns (23–28) vary.

---

## 3. Aggregate Files

### 3.1 `all_summaries.json`

JSON list of 25 trial summary dicts (one per trial). Loaded by every analysis module via `phi_scaling/analysis/_loader.py::load_summaries`.

### 3.2 `analysis_report.json`

```
{
  "scaling_fits": {
    "per_k_descriptive": {<k>: {n, mean, std, min, max}},
    "fit_linear":      {params, ssr, r2, aic, bic, predicted_at_k},
    "fit_quadratic":   {params, ssr, r2, aic, bic, predicted_at_k},
    "model_comparison": {delta_aic_linear_minus_quadratic, delta_bic_linear_minus_quadratic, verdict},
    "jump_test":        {n_seeds, delta_3_to_4_mean, delta_4_to_5_mean,
                         diff_mean, diff_std, t_stat, p_value_one_tailed, significant_at_005}
  },
  "per_organ_contribution": {
    "added_at_k":               {2: "anima", 3: "eidolon", 4: "mneme", 5: "nous"},
    "contributions":            {<organ>: {added_at_k, n_seeds, mean_delta_theta, std_delta_theta, min, max}},
    "ranking_by_abs_contribution": [<organ>, ...]
  }
}
```

---

## 4. Headline Numbers

### 4.1 θ_baseline by k (mean ± std across 5 seeds)

| k | Mean | Std | Min | Max |
|---:|---:|---:|---:|---:|
| 1 | **0.2793** | 0.1136 | 0.1646 | 0.4332 |
| 2 | **1.4853** | 0.0709 | 1.4363 | 1.6087 |
| 3 | **1.0199** | 0.1299 | 0.8754 | 1.2222 |
| 4 | **0.8922** | 0.1054 | 0.7159 | 0.9952 |
| 5 | **1.2925** | 0.0692 | 1.2024 | 1.3722 |

### 4.2 Model fits

| Model | Params | R² | AIC | BIC |
|---|---|---:|---:|---:|
| Linear: θ = a·k + b | a=0.143, b=0.564 | 0.230 | 25.34 | 27.78 |
| Quadratic: θ = c·k² + d·k + e | c=−0.091, d=0.689, e=−0.073 | **0.360** | **22.72** | **26.38** |

ΔAIC = +2.61 (quadratic preferred, decisive by Burnham & Anderson rule of ΔAIC > 2).
ΔBIC = +1.39 (inconclusive by BIC's stricter penalty).

### 4.3 Jump test (super-quadratic detector)

| Quantity | Value |
|---|---:|
| Δ(3→4) mean | −0.128 |
| Δ(4→5) mean | +0.400 |
| Difference (Δ₄₅ − Δ₃₄) | +0.528 |
| t-statistic | **7.53** |
| p-value (one-tailed) | **8.3 × 10⁻⁴** |
| Significant at α = 0.05 | **Yes** |

### 4.4 Per-organ contribution

| Organ added | At k | Mean Δθ | Std | Sign |
|---|---:|---:|---:|---|
| ANIMA | 2 | **+1.206** | 0.170 | ↑ |
| EIDOLON | 3 | **−0.465** | 0.074 | ↓ |
| MNEME | 4 | **−0.128** | 0.097 | ↓ |
| NOUS | 5 | **+0.400** | 0.102 | ↑ |

Ranking by |Δθ|: ANIMA > EIDOLON > NOUS > MNEME.
Ranking by signed contribution: ANIMA > NOUS > MNEME > EIDOLON.

---

## 5. Per-Seed Detail

| k\seed | 42 | 43 | 44 | 45 | 46 |
|---|---:|---:|---:|---:|---:|
| 1 | 0.165 | 0.260 | 0.433 | 0.185 | 0.354 |
| 2 | 1.609 | 1.480 | 1.436 | 1.455 | 1.446 |
| 3 | 1.222 | 0.995 | 0.956 | 1.051 | 0.875 |
| 4 | 0.938 | 0.918 | 0.894 | 0.995 | 0.716 |
| 5 | 1.332 | 1.202 | 1.372 | 1.315 | 1.241 |

Seed variance is highest at k=1 (intra-PNEUMA depends sensitively on which random projection PNEUMA's latent traverses) and lowest at k=5 (full system averages over more dimensions).

---

## 6. Example Queries

### 6.1 Reproduce the per-organ contribution

```python
import json
import numpy as np
from pathlib import Path

ROOT = Path("results/phi_scaling")
summaries = json.loads((ROOT / "all_summaries.json").read_text())

theta_per_k_seed = {}
for s in summaries:
    theta_per_k_seed.setdefault(s["organ_count"], {})[s["seed"]] = s["theta_baseline"]

added_at_k = {2: "anima", 3: "eidolon", 4: "mneme", 5: "nous"}
for k, organ in added_at_k.items():
    seeds = sorted(theta_per_k_seed[k].keys())
    deltas = [theta_per_k_seed[k][s] - theta_per_k_seed[k-1][s] for s in seeds]
    print(f"{organ:8s} Δθ = {np.mean(deltas):+.4f} ± {np.std(deltas, ddof=1):.4f}")
```

### 6.2 Load a single trial's trajectories

```python
from pathlib import Path
import numpy as np

npz = np.load(Path("results/phi_scaling/trials/k1__s42/trajectories.npz"))
internal = npz["internal"]              # (600, 27)
# At k=1, columns 0-22 (ANIMA..NOUS) are constant after beat 100.
print(internal[150, :23])  # should equal internal[100, :23]
```

### 6.3 Fit your own scaling model

```python
import json
import numpy as np
from scipy.optimize import curve_fit
from pathlib import Path

summaries = json.loads(Path("results/phi_scaling/all_summaries.json").read_text())
k = np.array([s["organ_count"] for s in summaries])
theta = np.array([s["theta_baseline"] for s in summaries])

# Example: log fit θ = a·log(k+1) + b
def log_model(k, a, b):
    return a * np.log(k + 1) + b
popt, _ = curve_fit(log_model, k, theta)
print(f"log fit: a={popt[0]:.3f}, b={popt[1]:.3f}")
```

---

## 7. Storage Footprint

| Item | Size |
|---|---|
| `analysis_report.json` | ~5 KB |
| `all_summaries.json` | ~40 KB |
| Per-trial `summary.json` | ~3 KB × 25 = ~75 KB |
| Per-trial `trajectories.npz` | ~40 KB × 25 = ~1 MB |
| `figures/*.png` | ~700 KB total |
| **Total** | **~2 MB** |

---

## 8. Reproducing the Data

```bash
# From /home/ubuntu/axioma:
python -c "
from pathlib import Path
from phi_scaling.runner import run_phi_scale_sweep
run_phi_scale_sweep(out_root=Path('results/phi_scaling'))
"
# Takes ~7 s on H100.
```

Seeds are fully deterministic; results match byte-for-byte across reruns.
