# Multi-seed soak summary (v1.2.3)

## Per-preset aggregates

### `pneuma_weighted` (n_seeds=3, seeds=[13, 42, 7])

| Metric | mean | median | min | max |
|---|---|---|---|---|
| rolling10_p95_ms | 19.734 | 23.258 | 12.619 | 23.325 |
| finalized_events | 115.6667 | 91 | 73 | 183 |
| composite_score | 0.618 | 0.617 | 0.604 | 0.633 |
| learner_adoptions | 9.3333 | 8 | 5 | 15 |
| learner_reversions | 1.3333 | 1 | 1 | 2 |

- V11 perf gate (all seeds): **PASS**
- V13 uncontrolled (all seeds): **PASS**
- V13 oscillation (all seeds): **PASS**
- Overall ship-gate (all seeds): **PASS**

### `uniform` (n_seeds=3, seeds=[13, 42, 7])

| Metric | mean | median | min | max |
|---|---|---|---|---|
| rolling10_p95_ms | 19.815 | 23.297 | 12.835 | 23.313 |
| finalized_events | 114.6667 | 91 | 73 | 180 |
| composite_score | 0.62 | 0.619 | 0.606 | 0.635 |
| learner_adoptions | 6.3333 | 6 | 5 | 8 |
| learner_reversions | 1.3333 | 1 | 1 | 2 |

- V11 perf gate (all seeds): **PASS**
- V13 uncontrolled (all seeds): **PASS**
- V13 oscillation (all seeds): **PASS**
- Overall ship-gate (all seeds): **PASS**

## Cross-preset: PNEUMA-weighted learner-adoptions ratio

- uniform mean adoptions: 6.3333
- pneuma_weighted mean adoptions: 9.3333
- ratio: **1.47×**
- reproduces Checkpoint J's +150% finding (ratio ≥ 1.5): **False**

