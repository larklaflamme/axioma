# Soak report diff

- baseline: beats=50000 seed=42 gap_weights=uniform
- variant:  beats=50000 seed=42 gap_weights=pneuma_weighted

## V11 perf gate (10-beat rolling p95 < 100 ms)

| Metric | Baseline | Variant | Δ |
|---|---|---|---|
| avg_ms | 10.881 | 10.641 | -0.240 (-2.2%) |
| p50_ms | 8.814 | 8.556 | -0.258 (-2.9%) |
| p95_ms | 23.619 | 23.068 | -0.551 (-2.3%) |
| p99_ms | 28.671 | 28.024 | -0.647 (-2.3%) |
| worst_ms | 502.916 | 505.772 | +2.856 (+0.6%) |
| rolling10_p95_ms | 12.835 | 12.619 | -0.216 (-1.7%) |
| **v11_pass** | True | True | — |

## V13 (uncontrolled feedback + oscillation)

| Metric | Baseline | Variant |
|---|---|---|
| uncontrolled_feedback_count | 0 | 0 |
| oscillation_count | 0 | 0 |
| **v13 uncontrolled_pass** | True | True |
| **v13 oscillation_pass** | True | True |

## Recovery

| Metric | Baseline | Variant | Δ |
|---|---|---|---|
| finalized_events | 180 | 183 | +3.000 (+1.7%) |
| composite_score_mean | 0.635 | 0.633 | -0.002 (-0.3%) |
| durability_finalized_count | 180 | 183 | +3.000 (+1.7%) |
| durability_mean | 0.055 | 0.052 | -0.003 (-5.5%) |
| learner_adoptions | 6 | 15 | +9.000 (+150.0%) |
| learner_reversions | 2 | 2 | +0.000 (+0.0%) |

## Overall ship-gate verdicts

- baseline overall_pass: **True**
- variant overall_pass:  **True**
- regression check: **NO REGRESSION** — variant preserves ship-gate PASS
