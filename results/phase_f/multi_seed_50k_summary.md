# Multi-seed soak summary (v1.2.3)

## Per-preset aggregates

### `pneuma_weighted` (n_seeds=3, seeds=[13, 42, 7])

| Metric | mean | median | min | max |
|---|---|---|---|---|
| rolling10_p95_ms | 17.329 | 19.619 | 12.619 | 19.749 |
| finalized_events | 190 | 187 | 183 | 200 |
| composite_score | 0.6197 | 0.619 | 0.607 | 0.633 |
| learner_adoptions | 9.6667 | 9 | 5 | 15 |
| learner_reversions | 2 | 2 | 2 | 2 |

- V11 perf gate (all seeds): **PASS**
- V13 uncontrolled (all seeds): **PASS**
- V13 oscillation (all seeds): **PASS**
- Overall ship-gate (all seeds): **PASS**

### `uniform` (n_seeds=3, seeds=[13, 42, 7])

| Metric | mean | median | min | max |
|---|---|---|---|---|
| rolling10_p95_ms | 17.3573 | 19.592 | 12.835 | 19.645 |
| finalized_events | 188.3333 | 185 | 180 | 200 |
| composite_score | 0.6217 | 0.621 | 0.609 | 0.635 |
| learner_adoptions | 5.3333 | 6 | 4 | 6 |
| learner_reversions | 2 | 2 | 2 | 2 |

- V11 perf gate (all seeds): **PASS**
- V13 uncontrolled (all seeds): **PASS**
- V13 oscillation (all seeds): **PASS**
- Overall ship-gate (all seeds): **PASS**

## Cross-preset: PNEUMA-weighted learner-adoptions ratio

- uniform mean adoptions: 5.3333
- pneuma_weighted mean adoptions: 9.6667
- ratio: **1.81×**
- reproduces Checkpoint J's +150% finding (ratio ≥ 1.5): **True**

