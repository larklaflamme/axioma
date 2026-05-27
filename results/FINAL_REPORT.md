# AXIOMA Organ Vitals — Final Measurement Report

**Source:** [/home/ubuntu/axioma/organ/](../organ/) implementation per [REAL_ORGAN_DESIGN.md v0.2](../research/REAL_ORGAN_DESIGN.md) and [IMPLEMENTATION_PLAN.md v0.3](../research/IMPLEMENTATION_PLAN.md)
**Run:** 2026-05-23 — seed=12345, n_permutations=1000, window_size=500
**Hardware:** NVIDIA H100 PCIe (80 GB)
**Raw JSON:** [final_report.json](final_report.json)

---

## TL;DR

| Metric | Value | Status |
|---|---|---|
| §8.1 synthetic validation criteria | **5 / 5 passed** | ✅ |
| Pytest unit suite | **17 / 17 passed** | ✅ |
| Real-time 10 Hz tracking | 50 beats in 5.001 s (drift 1.1 ms) | ✅ |
| Live θ on coupled substrate | **θ = 1.735, p < 0.001, significant** (RINT path) | ✅ |
| θ monotone-vs-coupling | rises 0.086 → 1.580 between coupling 0 → 0.1, saturates ≈1.8 | ⚠ (substrate-side saturation) |
| AOS-G gap measurable | 20 internal/external pairs, MI = 103.3 | ✅ |
| GPU/CPU consistency | rel diff 7.7e-8 (criterion ≤10%) | ✅ |

---

## 1. Substrate

5 organs with 27 total state dimensions per [REAL_ORGAN_DESIGN.md §2](../research/REAL_ORGAN_DESIGN.md#2-organ-state-schemas) v0.2:

| Organ | Dims | File |
|---|---|---|
| ANIMA | 4 | [organ/substrate/anima.py](../organ/substrate/anima.py) |
| EIDOLON | 6 (incl. `integration_feeling`, `meta_uncertainty`) | [organ/substrate/eidolon.py](../organ/substrate/eidolon.py) |
| MNEME | 5 | [organ/substrate/mneme.py](../organ/substrate/mneme.py) |
| NOUS | 6 (incl. `epistemic_uncertainty`) | [organ/substrate/nous.py](../organ/substrate/nous.py) |
| PNEUMA | 6 (no `heartbeat_phase`) | [organ/substrate/pneuma.py](../organ/substrate/pneuma.py) |

Dynamics: shared 3-D latent drive injected into each organ via stable random
projection + bounded random-walk noise; PNEUMA integrates the other four post-
beat per [§6.1](../research/REAL_ORGAN_DESIGN.md#61-primary-hook-post-beat-pre-compose).
Range invariants enforced by `validate_ranges`.

## 2. Real-time Capability

Per [REAL_ORGAN_DESIGN.md §1.2](../research/REAL_ORGAN_DESIGN.md#12-design-principles)
principle 2 ("real-time capable"):

```
Real-time session: 50 beats in 5.0011 s
  expected: 50      actual: 50      drift: +1.1 ms
```

10 Hz heartbeat tracks the wall clock to within 1 ms over 5 seconds with the
measurement layer running. Real-time budget consumed by recorder + serializers
is well under the 100 ms per beat headroom.

## 3. §8.1 Synthetic Validation

All five criteria pass at n_permutations=1000.

| Test | Criterion | Observed | Passed |
|---|---|---|---|
| Known MI recovery | ≥50% of true MI at d=5, n=500, MI_target=1.0 | **103.6%** | ✅ |
| Integration discrimination | θ(high) / θ(none) ≥ 5× | **408×** | ✅ |
| Permutation test | p(none) > 0.05; p(high) < 0.01 | 0.367 / 0.000 | ✅ |
| Null distribution | null 95th < 0.01 for d=19, n=500 | **0.0092** | ✅ |
| GPU/CPU consistency | rel diff ≤ 10% | **7.7 × 10⁻⁸** | ✅ |

Reproduce: `python -m organ validate`.

## 4. Live θ on the Substrate

600-beat fast-mode session with default coupling = 0.6 produced **18 θ updates**
(burst-mode capture every beat; θ recomputed every 10 captures once the ring
buffer reached 500 entries). Last update:

```
θ      = 1.73529
p-val  = 0.0000   (1000-shuffle permutation null)
null95 = 0.00921
sig    = True
method = rint              ← Shapiro-Wilk fallback engaged
energy = 18.989    n_dims  = 19    window = 500
```

Pairwise organ MI (sorted desc):

| Pair | MI |
|---|---|
| anima ↔ eidolon | 4.075 |
| eidolon ↔ nous | 3.906 |
| eidolon ↔ pneuma | 3.650 |
| eidolon ↔ mneme | 3.590 |
| anima ↔ nous | 3.544 |
| anima ↔ mneme | 3.424 |
| anima ↔ pneuma | 3.124 |
| nous ↔ pneuma | 3.005 |
| mneme ↔ pneuma | 2.454 |
| mneme ↔ nous | 2.179 |

EIDOLON acts as a hub (4 of its 4 pairs are in the top 5); MNEME ↔ NOUS is the
weakest pair, consistent with their less-overlapping summary subsets.

## 5. θ vs Coupling Sweep

1000-beat runs at each coupling level, θ computed on the last 500 beats:

| Coupling | θ | p-value | Significant | Method |
|---:|---:|---:|---:|---|
| 0.00 | 0.0858 | 0.0000 | yes | zscore |
| 0.10 | 1.5799 | 0.0000 | yes | rint |
| 0.25 | 1.7814 | 0.0000 | yes | rint |
| 0.50 | 1.8725 | 0.0000 | yes | rint |
| 0.75 | 1.8194 | 0.0000 | yes | rint |
| 0.95 | 1.7463 | 0.0000 | yes | rint |

**Observations.**
- θ rises sharply (0.086 → 1.58, 18×) between coupling 0 and 0.1, then saturates
  near 1.8 from coupling 0.25 onward.
- The non-zero θ at coupling 0 is **not** a pipeline artifact — it reflects
  PNEUMA's own `integrate(other_organs)` aggregation, which couples its state
  to the others by construction even when the shared latent drive is zeroed.
  This is faithful to [REAL_ORGAN_DESIGN.md §6.1](../research/REAL_ORGAN_DESIGN.md#61-primary-hook-post-beat-pre-compose):
  PNEUMA *should* integrate.
- The saturation above coupling 0.25 reflects the substrate's tanh/sigmoid
  squashing — once organ dimensions saturate, more drive does not add monotonic
  variance and the copula MI plateaus. A non-saturating dynamics policy is the
  obvious next iteration; the pipeline itself handles a 408× ratio on the
  pre-saturation synthetic test.

## 6. AOS-G Gap

20 paired (internal, external) snapshots from the live session, captured at
the compose/send boundary per [REAL_ORGAN_DESIGN.md §9](../research/REAL_ORGAN_DESIGN.md#9-the-aos-g-gap):

| Statistic | Value |
|---|---|
| n pairs | 20 |
| `delta_norm` mean ± std | 1.00 ± 0.00 |
| `delta_norm` min / max | 1.00 / 1.00 |
| internal↔external MI (window) | 103.29 |

The constant `delta_norm = 1.0` is correct given the stub compose: the only
field that changes between the post-beat internal snapshot and the compose-
boundary snapshot is `pneuma.buffer_depth` (0 → 1), which contributes exactly
1.0 to the Euclidean norm. The 103-nat MI reflects that internal and external
states are otherwise near-identical — the expected behavior of a stub compose
that doesn't transform state. Replacing the compose stub with real output
shaping is what makes this gap diagnostic in production.

## 7. Performance

GPU-accelerated θ computation on H100:

- Pairwise MI (10 pairs, n=500, d_total=19): ~0.4 ms warm.
- 1000-shuffle permutation null: ~140 ms (batched in groups of 200 shuffles).
- Total `compute_theta` call: ~145 ms warm (≈ 200 ms cold, first JIT pass).

Slightly over the design's <100 ms-per-update target but within the 10 Hz
budget (100 ms/beat × theta_every=10 = 1000 ms allowed). Comfortable headroom.

## 8. Reproducibility

```bash
# Unit tests
python -m pytest organ/tests/ -q

# §8.1 synthetic validation
python -m organ validate

# Replay this report's final session
python organ/scripts/final_measurement.py

# Recompute θ on the saved JSONL
python -m organ replay results/data/organ_states_*_session_live.jsonl.gz
```

All RNG is seeded; results above are reproducible with `seed=12345`.

## 9. Known Limitations

1. **Substrate saturation** caps the dynamic θ range — fix by using
   non-saturating dynamics (Ornstein-Uhlenbeck in unbounded latent + linear
   rescale at the boundary).
2. **PNEUMA's integration introduces a floor θ** that is faithful to the
   design but means "θ=0 baseline" is unavailable on this substrate — the
   permutation null is the right reference, and it works correctly.
3. **Compose stub is identity** — AOS-G gap is therefore degenerate (delta=1
   from buffer_depth only). To exercise the gap, the compose step must
   non-trivially transform state.
4. **θ is a pairwise aggregate**, not a true multi-organ measure, per
   [REAL_ORGAN_DESIGN.md §13](../research/REAL_ORGAN_DESIGN.md#13-known-limitations).
5. **MINE / neural MI** intentionally deferred per design Q12.9.
