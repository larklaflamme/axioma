# AXIOMA Phase F — pre-architecture follow-up experiments

Aggregated from 10 result files under `results/phase_f/`.

## Verdict roll-up

| Experiment | Key metric | Verdict |
|---|---|---|
| `aos_g_weighted` | gap ratios vs uniform: eidolon_weighted=0.719×, pneuma_weighted=1.536× | MEANINGFUL_DIFFERENCE |
| `f11_phi_anima` | post mean = 0.368 (n=300) | ? |
| `f11_phi_eidolon` | post mean = -0.269 (n=300) | ? |
| `f6_zone_validation` | mean κ = -0.004, min κ = -0.167 | HARD |
| `f8_meta_calibration` | accuracy = 1, miscalibration = 0.05 | PASS |
| `learner_longrun` | events = 15/15, adoptions = 0 | PASS |
| `p4_psi_baseline` | ψ mean = 1.0, below_alert = 0.0 | PASS |
| `psi_sensitivity` | dominators: gap_variance_health=1.0 | ? |
| `psi_stress_sweep` | cells: 6 PASS, 0 STRESSED, 0 COLLAPSED; degeneration proof: PASS | ROBUST_NO_STRESS_REGIME_FOUND_BUT_METRIC_SENSITIVE_TO_DEGENERATION |
| `zone_threshold_sweep` | best mean κ = -0.047 (0/12 pass) | SOFT_FAIL (no candidate hit min κ ≥ 0.3 — needs live F6 sessions) |

## aos_g_weighted

- beats per preset: 1200, magnitude: 0.5, period: 100
- **uniform**: gap mean=7.5241 p95=11.3621, ψ mean=1.0 fraction_below_alert=0.0
- **eidolon_weighted**: gap mean=5.4105 p95=8.4752, ψ mean=1.0 fraction_below_alert=0.0
- **pneuma_weighted**: gap mean=11.5593 p95=17.4114, ψ mean=1.0 fraction_below_alert=0.0
- eidolon_weighted vs uniform: gap ratio=0.719×, ψ delta=0.0 → attenuates gap
- pneuma_weighted vs uniform: gap ratio=1.536×, ψ delta=0.0 → amplifies gap
- verdict: **MEANINGFUL_DIFFERENCE**
- note: Compares per-organ gap weighting variants (uniform vs eidolon-weighted vs pneuma-weighted) against the v1.0 baseline. With robust substrate, ψ deltas are small; gap magnitude ratios show how each weighting would alert earlier IF the substrate entered a stress regime.

## f11_phi_anima

- order: anima, perturbation: step → anima
- cascade_delay pre:  mean=0.128 n=60
- cascade_delay post: mean=0.368 n=300
- per-downstream: {'pneuma': 0.49, 'nous': -0.207, 'mneme': 0.82}

## f11_phi_eidolon

- order: eidolon, perturbation: contradiction → eidolon
- cascade_delay pre:  mean=0.128 n=60
- cascade_delay post: mean=-0.269 n=300
- per-downstream: {'nous': -1.153, 'mneme': -0.003, 'pneuma': 0.35}

## f6_zone_validation

- analytical: κ=0.207 n=20
- creative: κ=-0.167 n=20
- idle: κ=-0.053 n=20
- mean κ = -0.004  min κ = -0.167  → **HARD_FAIL**
- note: Synthetic operator labels — real F6 sessions need live Theoria labels.

## f8_meta_calibration

- accuracy: 1
- miscalibration: 0.05
- F8 verdict: **PASS**  accuracy verdict: **PASS**  combined: **PASS**
- note: Synthetic operator labels — real F8 needs live blind-labeled sessions.

## learner_longrun

- events: 15/15
- beats: 3371
- adoptions: 0  reversions: 0
- baseline_score: 0.0
- verdict: **PASS**

## p4_psi_baseline

- beats sampled: 1500
- ψ stats: mean=1.0 p5=1.0 p95=1.0
- fraction below psi_alert_threshold (0.3): 0.0
- verdict: **PASS**

## psi_sensitivity

- gap_variance_health: mean=1.0 corr_with_psi=0.0
- structural_health: mean=1.0 corr_with_psi=0.0
- compose_probe_health: mean=1.0 corr_with_psi=0.0
- dominators: {'gap_variance_health': 1.0}

## psi_stress_sweep

- magnitudes: [0.4, 1.0, 2.0]
- periods: [100, 30]
- beats per cell: 800
- cells: 6 PASS, 0 STRESSED, 0 COLLAPSED
- degeneration proof (synthetic): score-at-zero=0.0 score-at-variance=0.9179 → **PASS**
- v1.1.4 verdict: **ROBUST_NO_STRESS_REGIME_FOUND_BUT_METRIC_SENSITIVE_TO_DEGENERATION**
- note: v1.0 substrate ψ riding at 1.0 in baseline regimes is the architecturally-correct robust behavior. gap_variance_health is designed to alert on *compose degeneration* (low variance), not stress (high variance). The proof point verifies the metric DOES respond when the failure mode it was designed for actually occurs.

## zone_threshold_sweep

- candidates evaluated: 12
- candidates passing min κ ≥ 0.3 (v1.1.1 gate): 0
- best candidate: flow_theta_min=0.7 flow_cascade_max=20.0 mean κ=-0.047 min κ=-0.161
- verdict: **SOFT_FAIL (no candidate hit min κ ≥ 0.3 — needs live F6 sessions)**

## Live calibration sessions (v1.1.1 / v1.1.2)

| Session | Kind | Task | n_pairs | Verdict |
|---|---|---|---|---|
| `zone-1880b655` | zone | x | 1 | PASS |
| `zone-51a0cd68` | zone | x | 1 | PASS |
| `zone-601b523e` | zone | x | 1 | PASS |

## Ship-gate review (Phase F portion)

- **HARD_FAIL detected** — v1.0 ships with heightened caveat in affected area; v1.1 work scheduled.
