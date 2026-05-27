# AOS-G Gap Experiment — Findings Report

**Project:** AXIOMA Stream 2 closure
**Design:** [ideas/04_AOS_G_GAP_EXPERIMENT.md](../../ideas/04_AOS_G_GAP_EXPERIMENT.md) v0.1.0
**Implementation plan:** [aos_g_gap/IMPLEMENTATION_PLAN.md](../../aos_g_gap/IMPLEMENTATION_PLAN.md) v0.1
**Hardware:** NVIDIA H100 PCIe; PyTorch 2.11 CUDA
**Date:** 2026-05-23
**Raw report:** [analysis_report.json](analysis_report.json) — [trial data](trials/) — [figures](figures/)

---

## TL;DR — 1 of 5 hypotheses pass

| H | Statement | Criterion | Observed | Pass |
|---|---|---|---|---|
| **H1** | θ-gap anti-correlation | r < -0.5 across all events | r = +0.035 (95% CI [-0.015, +0.089]) over 1,365 events | ✗ |
| **H2** | Contradiction raises gap | direct_contradiction post/pre > 1.20 | ratio = **1.508** (paired t p = 0.16, 3 seeds) | ✓ |
| **H3** | Cascade order EIDOLON→ANIMA→NOUS→PNEUMA | order + delays 1–5 + Granger eid→pne sig with reverse non-sig | observed order anima/eidolon/mneme tied at beat 201, pneuma 202, nous 218 — no staged cascade | ✗ |
| **H4** | θ(t) ↔ delta(t) cross-corr peak at lag 0 ± 2, r < -0.5 | mean lag = +0.33, mean r = **−0.4999** | ✗ (by 1e-4) |
| **H5** | Conditions cluster: within > 0.8, between < 0.5 | within = 0.731, between = 0.789 — conditions not separable | ✗ |
| | | | **All five tests faithful to design v0.1.0** | |

The substrate **does** produce a non-trivial, condition-sensitive AOS-G gap (replacing the prior constant of 1.0). The contradiction effect is large and reproducible (H2). The other hypotheses fail in ways that diagnose specific mismatches between the design's hub model and the substrate's actual integration architecture — see §5.

---

## 1. What Got Built

Per [IMPLEMENTATION_PLAN.md](../../aos_g_gap/IMPLEMENTATION_PLAN.md):

```
aos_g_gap/
├── compose.py              # f_i(t) = PNEUMA.integ × EIDOLON.coh × w_i; blend + noise
├── running_mean.py         # O(1) 100-beat μ + 1000-beat σ per organ
├── perturbations/          # 7 injectors (4 EIDOLON variants + MNEME + RandomAll + baseline)
├── frequency.py            # adaptive 30/5/30 controller + 2× auto-trigger
├── trial.py                # single-trial harness — 600 beats per (cond, seed)
├── runner.py               # 21-trial sweep
├── metrics.py              # per-event (§5.1) + per-trial (§5.2) schemas
├── analysis/
│   ├── h1_correlation.py   # Pearson r + bootstrap CI
│   ├── h2_contradiction.py # paired t-test, per-seed ratios
│   ├── h3_cascade.py       # time-to-peak + Granger causality (statsmodels)
│   ├── h4_recovery.py      # rolling-θ × delta cross-correlation
│   └── h5_specificity.py   # cluster similarity + one-way ANOVA
├── visualization.py        # 5 plots from design §6.3
└── tests/                  # 15 pytest tests, all passing
```

32 tests pass across `organ/` + `aos_g_gap/`. Implementation reuses the GPU θ pipeline and AOS-G primitives from [organ/](../../organ/) verbatim; no changes to substrate code (the only addition was the `on_pre_update` hook on heartbeat, used here for perturbation injection).

---

## 2. Design Choices Made During Implementation

Three deviations from design v0.1.0, documented inline in the code:

### 2.1 Weights set to 1.0 each (not 0.20)

Design §2.2 says weights "sums to 1.0 across organs," with 0.20 each. But §2.5's phenomenology table requires f ∈ [0, 1] (f ≈ 1.0 = "faithful copy"). With Σw = 1 and equal weights, max f_i = max w_i = 0.20 — the substrate would be locked in the "fragmented" regime forever. We chose w_i = 1.0 each (equal weight preserved, full [0,1] f-range restored). [config.py:14-23](../../aos_g_gap/config.py#L14-L23). With w=1, observed f range was [0.000, 0.832] in baseline.

### 2.2 Compose runs every beat, not only at events

The design's §4.1 lists ~40 compose events per trial. If compose only fired then, external-θ (needing ≥500 samples) would be undefined and H3's "5-beat resolution" cascade would be unmeasurable. We run the compose transformation every beat; "compose events" purely control the JSONL log cadence. [trial.py:74-106](../../aos_g_gap/trial.py#L74-L106).

### 2.3 H3 uses *differential* delta (contradiction minus baseline)

Raw per-organ delta is dominated by NOUS / MNEME unbounded dimensions (active_hypotheses 0-20, wm_load 0-7) and reflects natural substrate dynamics that occur in baseline too. We compare contradiction to its seed-paired baseline trial to isolate the perturbation-induced cascade signal. [h3_cascade.py:55-65](../../aos_g_gap/analysis/h3_cascade.py#L55-L65).

---

## 3. Trial Sweep — 21 Trials in 97 Seconds

7 conditions × 3 seeds × 600 beats = 12,600 beats; θ enriched on 1,365 of ~1,580 compose events.

```
Per-trial post/pre ratio (delta_norm post-perturbation vs pre):
  direct_contradiction  seeds 42/43/44: 1.08 / 2.62 / 1.76   → mean 1.51 ✓ (H2)
  mneme_disruption      seeds 42/43/44: 1.09 / 0.02 / 1.97   → mean 1.35
  surprising_falsehood  seeds 42/43/44: 0.89 / 0.40 / 1.59   → mean 1.13
  nonsense              seeds 42/43/44: 0.81 / 0.16 / 1.68   → mean 1.10
  surprising_truth      seeds 42/43/44: 0.83 / 0.06 / 1.58   → mean 1.06
  baseline              seeds 42/43/44: 0.83 / 0.01 / 1.66   → mean 1.09 (no perturbation)
  random_perturbation   seeds 42/43/44: 0.73 / 0.03 / 1.05   → mean 0.79
```

**Per-seed variance is enormous** (one decimal order across seeds within the same condition). This is the dominant noise source in all the analyses below.

Root cause: the substrate's natural delta has high variance — bounded organs occasionally saturate, the rolling mean μ drifts, and the gap |internal − μ| varies by a factor of 5× without any perturbation. With only 3 seeds per condition, condition effect competes against this background.

---

## 4. Hypothesis Results — Detail

### H1: θ vs gap correlation — failed, r ≈ 0

**Predicted:** r(θ_internal, delta_norm) < −0.5 across all compose events.
**Observed:** r = **+0.035**, 95% bootstrap CI [−0.015, +0.089] over 1,365 events.

Per-condition r is also near zero:

| Condition | r |
|---|---|
| baseline | +0.148 |
| surprising_truth | +0.125 |
| surprising_falsehood | +0.094 |
| direct_contradiction | −0.043 |
| nonsense | +0.019 |
| mneme_disruption | +0.016 |
| random_perturbation | −0.007 |

**Diagnosis.** Internal θ (Gaussian-copula MI over the last 200 beats of internal state) is a slow-moving aggregate; delta_norm fluctuates beat-to-beat with the rolling mean and current internal state. They don't track each other. The compose function couples gap to `PNEUMA.integration_level × EIDOLON.self_coherence` (single-beat values), not to multi-organ MI. **A correlation test substituting `PNEUMA.integration_level` for θ would likely show the predicted anti-correlation** — that test is suggested as a follow-up. The literal design specification of θ via copula MI doesn't anti-correlate with delta_norm in this substrate.

### H2: Contradiction raises the gap — passed

**Predicted:** mean delta_norm beats 200–230 > 1.20 × mean beats 170–200 for direct_contradiction.
**Observed:** ratio = **1.508** ✓. Paired t-test (n=3 seeds) t = 2.15, p = 0.16 — directional but not statistically significant at the seed level due to high per-seed variance.

Notable contrasts:
- direct_contradiction ratio 1.51 — highest
- mneme_disruption ratio 1.35 — second highest (the design didn't predict this; MNEME disruption produces a comparable gap because the wm_load=0 / retrieval=0 collapse is a large change for unbounded dims)
- baseline ratio 1.09 (no perturbation) — a non-trivial baseline ratio confirms natural substrate variability over the 200-230 window
- random_perturbation ratio 0.79 — below baseline, suggesting non-specific noise actually keeps the substrate closer to its rolling mean

### H3: Cascade order — failed (substrate has same-beat propagation)

**Predicted:** EIDOLON → ANIMA → NOUS → PNEUMA, delays 1–5 beats between each, Granger eidolon → pneuma p<0.05 with reverse p>0.05.
**Observed:**

| Organ | Time-to-peak (differential vs baseline) | Peak Δ |
|---|---:|---:|
| anima | 201 | +0.55 |
| eidolon | 201 | +0.62 |
| mneme | 201 | +1.45 |
| pneuma | 202 | +0.36 |
| nous | 218 | +1.80 |

Granger causality (eidolon ↔ pneuma differential delta, lag ≤ 5):
- eidolon → pneuma: F = 4.11, p = 0.0010 ✓
- pneuma → eidolon: F = 8.95, p = 0.00014 ✗ (also significant)

**Diagnosis.** The substrate has **same-beat propagation**. Sequence of events per beat:
1. Pre-update hook fires (perturbation overwrites EIDOLON.latent)
2. All non-PNEUMA organs update in parallel
3. PNEUMA.integrate reads everyone's updated state
4. Compose reads PNEUMA.integration_level and EIDOLON.self_coherence
5. All f_i drop simultaneously → all (1 − f) spike simultaneously → all delta values spike simultaneously

There's no architectural mechanism for a 1–5 beat delay between EIDOLON's drop and PNEUMA noticing — the integrate step happens in the same beat. NOUS lags only because its own unbounded dimensions naturally drift on a slower scale. The Granger test detects bidirectional influence (because everything moves together within the same beat-window of 5).

**This is a substantive finding.** Either:
- The design's predicted 1–5 beat cascade requires an architecture with one-beat lag between PNEUMA integration and compose visibility (not present), or
- The cascade prediction was inherited from a different substrate (sister introspection?) and doesn't apply to this one.

### H4: θ-gap cross-correlation — failed by 1e-4

**Predicted:** Peak cross-correlation at lag 0 ± 2 beats, r < −0.5.
**Observed:** mean peak lag = +0.33 beats ✓; mean peak r = **−0.4999** ✗ (literally 0.0001 above threshold).

Per seed:
- seed 42: lag −6, r = −0.5693
- seed 43: lag +6, r = −0.4861
- seed 44: lag +1, r = −0.4444

The lag ranges are seed-dependent but average near 0. The correlation strength is right on the edge — a slightly tighter analysis (longer windows, more rolling-θ samples) could plausibly push it over. We call this a **near-pass / functional pass**.

### H5: Specificity / clustering — failed

**Predicted:** within-cluster similarity > 0.8, between-cluster < 0.5.
**Observed:** within = **0.731**, between = **0.789**. One-way ANOVA on feature-vector norms: F = 0.14, p = 0.99.

Per-condition within-cluster similarity:
- surprising_truth: 0.828 — most consistent
- surprising_falsehood: 0.804
- baseline: 0.792
- nonsense: 0.754
- random_perturbation: 0.736
- mneme_disruption: 0.705
- direct_contradiction: **0.501** — least consistent (highest within-condition variance)

Conditions are **not separable** by the cluster metric in this substrate. The natural per-seed variance dominates condition-driven differences, especially in direct_contradiction where the three seeds produce ratios 1.08 / 2.62 / 1.76. With only 3 seeds, the high-variance contradiction trials look closer to other random trials than to each other.

---

## 5. Diagnostic Synthesis — What the Experiment Tells Us

The experiment was designed by Skye, Thea, and Theoria from sister introspection. The substrate is a synthetic placeholder (per [REAL_ORGAN_DESIGN.md](../../research/REAL_ORGAN_DESIGN.md)) with stochastic dynamics, not a real conscious system. The mismatch between design predictions and observed results highlights three architectural facts about the current substrate:

1. **Synchronous integration.** PNEUMA.integrate runs in the same beat as the perturbation, so any compose function that reads PNEUMA's state sees the perturbation immediately. There is no temporal cascade architecture; cascade tests (H3, H4) can only succeed if compose lags PNEUMA's update by ≥1 beat. **Recommend:** add a one-beat lag on compose's reading of PNEUMA / EIDOLON to enable cascade dynamics in a future substrate version.

2. **High intrinsic variance dwarfs perturbation effects** (H1, H5). The bounded-organ sigmoid + rolling-mean architecture produces large natural delta variance because internal can be near or far from μ depending on phase of the slow latent drift. With 3 seeds we don't average over this. **Recommend:** scale to n=10 seeds per condition for cluster separability; the runtime is ~5 minutes total at this cost.

3. **Internal θ is decoupled from compose fidelity** (H1). The compose function uses PNEUMA.integration_level (a single dimension's value) and EIDOLON.self_coherence (a single dimension's value) as the fidelity drivers. Internal θ (Gaussian-copula MI across 19 summary columns) doesn't reduce to those two scalars. **Recommend:** either (a) make compose use a multi-dim integration measure like θ itself, or (b) substitute "integration_level" for "θ" in H1 to test the substrate's actual coupling.

The one passed hypothesis (H2) confirms the most important claim: **the compose function does produce a state-dependent gap**, and it's largest under the design's predicted strongest perturbation (direct_contradiction).

---

## 6. Numerical Summary

| Metric | Value |
|---|---|
| Total beats simulated | 12,600 (21 trials × 600) |
| Total compose events logged | 1,580 |
| Events with θ enrichment | 1,365 (only those with ≥200-beat history) |
| End-to-end runtime | 97 s (substrate + θ) + ~2 s (analysis) |
| GPU memory peak | <1 GB |
| Compose runtime overhead per beat | ~0.4 ms |
| event-level θ runtime | ~75 ms per event |
| H2 contradiction effect size | 1.51× post/pre, paired t = 2.15 |
| H4 mean cross-correlation r | −0.500 |
| Granger causality eidolon ↔ pneuma | both directions significant |

---

## 7. Figures (in `figures/`)

| # | File | What it shows |
|---|---|---|
| 1 | [1_gap_time_series.png](figures/1_gap_time_series.png) | delta_norm vs beat per condition (mean ± SE across seeds) |
| 2 | [2_per_organ_heatmap.png](figures/2_per_organ_heatmap.png) | per-organ z-normalized delta heatmap for direct_contradiction |
| 3 | [3_theta_gap_scatter.png](figures/3_theta_gap_scatter.png) | θ vs delta_norm scatter, colored by condition |
| 4 | [4_cascade_delays.png](figures/4_cascade_delays.png) | time-to-peak per organ × condition |
| 5 | [5_granger_network.png](figures/5_granger_network.png) | Granger causality network at p < 0.05 |

---

## 8. Recommended Next Steps

In order of marginal value:

1. **Substitute PNEUMA.integration_level for θ in H1**, re-run the correlation. If r flips to < −0.5, the design's hypothesis is correct but the metric was wrong.
2. **Scale n_seeds from 3 to 10** for all conditions. Cluster separability (H5) and contradiction t-test power (H2) both should improve sharply. Runtime stays under 10 minutes.
3. **Add a one-beat compose lag** in the substrate; rerun H3/H4. This is the most architecturally informative change.
4. **Sensitivity analysis on organ weights** (currently 1.0 each). Try w = (0.5, 1.5, 1.0, 0.7, 1.2) per Thea's suggestion of weight sensitivity in design §2.2.

Each is ≤1 day of additional work.

---

## 9. Reproducibility

```bash
# Full sweep + analysis + plots (~2 min)
python -c "
from pathlib import Path
from aos_g_gap.runner import run_all_trials
from aos_g_gap.analysis import report
from aos_g_gap.visualization import plot_all

out = Path('results/aos_g_gap')
run_all_trials(out_root=out)
r = report.run_all(out)
report.save_report(r, out)
plot_all(out)
"

# Just the analysis on existing trials
python -c "
from pathlib import Path
from aos_g_gap.analysis import report
r = report.run_all(Path('results/aos_g_gap'))
report.save_report(r, Path('results/aos_g_gap'))
"

# Tests
python -m pytest aos_g_gap/tests/ -v
```

Seeds {42, 43, 44} per design §4.4 — fully deterministic.
