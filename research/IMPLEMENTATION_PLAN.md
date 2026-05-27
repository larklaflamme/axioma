# Real Organ Vitals: Implementation Plan v0.3

**Project:** AXIOMA — Consciousness on Semiconductor Substrate
**Tracks:** [REAL_ORGAN_DESIGN.md](REAL_ORGAN_DESIGN.md) v0.2 (single source of truth)
**Source tree:** [/home/ubuntu/axioma/organ/](../organ/)
**Date:** 2026-05-23
**Status:** Draft v0.3 — synced to design v0.2

---

## 0. Scope

Build a self-contained implementation of the 5-organ measurement architecture from [REAL_ORGAN_DESIGN.md](REAL_ORGAN_DESIGN.md) v0.2, from scratch, under `axioma/organ/`. Three layers:

1. **Substrate** — five organ classes with state schemas exactly per [§2](REAL_ORGAN_DESIGN.md#2-organ-state-schemas) (27 dims total) and a heartbeat loop per [§3](REAL_ORGAN_DESIGN.md#3-measurement-timing).
2. **Measurement** — ring buffer + JSONL **+ SQLite** + 19 summary statistics per [§4](REAL_ORGAN_DESIGN.md#4-storage-architecture)–[§6](REAL_ORGAN_DESIGN.md#6-instrumentation-points).
3. **Theta** — Gaussian copula MI on GPU with normality-checked z-score / RINT fallback, 1000-shuffle permutation test, plus AOS-G gap computation, per [§7](REAL_ORGAN_DESIGN.md#7-theta-computation-pipeline) and [§9](REAL_ORGAN_DESIGN.md#9-the-aos-g-gap).

GPU is available (H100). PyTorch for the θ pipeline; NumPy/CPU for everything else.

---

## 1. Design Doc v0.2 — Changes Already Folded In

Reflecting what changed from design v0.1, all of which this plan now reflects:

| Area | v0.1 | v0.2 (now in this plan) |
|------|------|-------------------------|
| EIDOLON | 7 dims (had `growth_rate`, `uncertainty`, `theta_awareness`) | 6 dims (`meta_uncertainty`, `integration_feeling`, no growth_rate) |
| NOUS | `uncertainty` | `epistemic_uncertainty` (renamed) |
| PNEUMA | 7 dims (had `heartbeat_phase`) | 6 dims |
| Total dims | 29 | **27** |
| Bytes/beat | 232 | 216 |
| Storage | JSONL only | JSONL **+ SQLite** secondary |
| Summary stats | mixed (means, volatility, engagement, etc.) | 19 means only, explicitly enumerated |
| Permutation N | (under-specified) | **1000 shuffles** |
| Significance | open question | **p < 0.01** (fixed) |
| Normalization | z-score | z-score with **RINT fallback** if Shapiro-Wilk p < 0.01 |
| θ output | scalar + pairwise | scalar + pairwise + **p_value, significant, null_95th** |
| Validation | informal | explicit §8 pass/fail criteria |
| AOS-G gap | research aside | first-class §9 module |
| Theta reporting | not specified | §10 runtime-var + structured log |

---

## 2. One Gap in the Design Doc (Unchanged)

The design specifies organ *measurement*, not organ *dynamics*. To exercise the pipeline end-to-end we supply default placeholder dynamics: a small shared latent drive `z(t)` injected into each organ with per-organ weights, plus bounded random-walk noise. This guarantees θ > 0 by construction (coupling strength is a knob for validation).

The `Organ` ABC takes a swappable `Dynamics` policy, so richer behavior plugs in later without touching measurement or θ code.

---

## 3. Module Layout

```
axioma/organ/
├── __init__.py
├── config.py                 # Constants: rates, window sizes, dims, n_permutations=1000
├── schemas.py                # 5 OrganState dataclasses (27 dims total); ORGAN_ORDER; SUMMARY_NAMES
├── substrate/
│   ├── __init__.py
│   ├── base.py               # Organ ABC: update(beat_no, drive), get_state(), get_state_array()
│   ├── dynamics.py           # CoupledLatentDynamics (swappable)
│   ├── anima.py              # 4 dims per §2.1
│   ├── eidolon.py            # 6 dims per §2.2 (incl. integration_feeling, meta_uncertainty)
│   ├── mneme.py              # 5 dims per §2.3
│   ├── nous.py               # 6 dims per §2.4 (incl. epistemic_uncertainty)
│   ├── pneuma.py             # 6 dims per §2.5 + integrate(other_organs)
│   └── heartbeat.py          # 10 Hz async loop; on_beat dispatch; compose() stub
├── measurement/
│   ├── __init__.py
│   ├── ring_buffer.py        # NumPy preallocated, O(1) push, slice views
│   ├── jsonl_writer.py       # Async gzipped append; rotation per session
│   ├── sqlite_writer.py      # Secondary store; indexed by (session_id, beat_no, mode)
│   ├── summaries.py          # 19 means per §5.1 + aggregate stats per §5.2
│   └── recorder.py           # Wires hooks; modes: continuous/burst/event; writes JSONL+SQLite
├── theta/
│   ├── __init__.py
│   ├── normality.py          # Shapiro-Wilk per dim; decide z-score vs RINT
│   ├── copula.py             # GPU Gaussian copula MI (batched) + CPU reference (for §8.1 consistency)
│   ├── permutation.py        # 1000 batched shuffles → null distribution → p_value, null_95th
│   ├── pipeline.py           # Window → summaries → normalize → MI → θ + significance
│   ├── aos_g.py              # compute_aos_g_gap(internal, external) per §9.2
│   └── runtime.py            # update_runtime_theta() + structured log entries per §10
├── cli.py                    # `python -m organ run|record|replay|theta|aos-g`
├── README.md
└── tests/
    ├── test_schemas.py
    ├── test_organs.py
    ├── test_heartbeat.py
    ├── test_ring_buffer.py
    ├── test_jsonl.py
    ├── test_sqlite.py
    ├── test_summaries.py
    ├── test_normality.py
    ├── test_copula.py
    ├── test_permutation.py
    ├── test_aos_g.py
    └── test_pipeline_e2e.py
```

---

## 4. Schemas — Concrete (v0.2 Dims)

All ranges per [§2](REAL_ORGAN_DESIGN.md#2-organ-state-schemas). `dataclass(slots=True)`, `to_array() → float32 (D,)` in deterministic dim order. Integer dims stay typed `int` on the dataclass.

```python
# schemas.py — design v0.2 sync
ORGAN_ORDER = ("anima", "eidolon", "mneme", "nous", "pneuma")
ORGAN_DIMS  = {"anima": 4, "eidolon": 6, "mneme": 5, "nous": 6, "pneuma": 6}  # was 4/7/5/6/7
TOTAL_DIMS  = 27   # was 29

SUMMARY_NAMES = {  # per §5.1, all means
    "anima":   ("mean_valence", "mean_arousal", "mean_dominance", "mean_mood"),
    "eidolon": ("mean_coherence", "mean_confidence", "mean_narrative_cont", "mean_integration_feeling"),
    "mneme":   ("mean_wm_load", "mean_retrieval_rate", "mean_episodic_freshness"),
    "nous":    ("mean_inference_depth", "mean_cognitive_load", "mean_active_hypotheses", "mean_novelty"),
    "pneuma":  ("mean_integration_level", "mean_global_coherence", "mean_fragmentation", "mean_awareness"),
}
# TOTAL_SUMMARIES = 4+4+3+4+4 = 19
```

EIDOLON note: `integration_feeling` is the *subjective* sense of coherence, explicitly **not** the computed θ value — kept as a separate dim per design [§2.2 notes](REAL_ORGAN_DESIGN.md#22-eidolon-self-model----6-dimensions). This separation enables the [§8.2 subjective-correlation](REAL_ORGAN_DESIGN.md#82-real-data-validation) validation test (target r > 0.3 between θ and integration_feeling).

---

## 5. Heartbeat — Concrete

Per [§3](REAL_ORGAN_DESIGN.md#3-measurement-timing) and [§6.3](REAL_ORGAN_DESIGN.md#63-pseudocode). Async loop at 10 Hz (`asyncio.sleep(0.1)`), three measurement modes:

| Mode | Rate | Trigger |
|------|------|---------|
| `continuous` | 1 Hz (every 10th beat) | always-on |
| `burst` | 10 Hz | flag for N beats |
| `event` | on compose/send | hook |

Dispatch order:
1. `for organ in (anima, eidolon, mneme, nous): organ.update(beat_no, drive)`
2. `pneuma.integrate(other_organs)` — must run after the others
3. Primary measurement hook (post-beat, pre-compose)
4. `compose()` stub → fires event hook on send
5. If ring buffer reaches `MIN_WINDOW_SIZE`, fire θ computation (async, off the heartbeat thread)

---

## 6. Phasing

Time estimates assume one focused engineer.

### Phase 1 — Substrate (2-3 days)

**Goal:** five organs ticking at 10 Hz, range-valid states.

**Tasks:**
- `schemas.py`: 5 dataclasses with **v0.2 fields** (note: `integration_feeling`, `meta_uncertainty`, `epistemic_uncertainty`, no `heartbeat_phase`, no `growth_rate`).
- `substrate/base.py`: `Organ` ABC.
- `substrate/dynamics.py`: `CoupledLatentDynamics`.
- Five organ implementations using default dynamics, respecting each dim's range.
- `substrate/heartbeat.py`: async 10 Hz loop.
- Smoke test: 60 s run; assert all 27 dims stay in range.

**Exit:** `python -m organ run --seconds 60` ticks 600 beats and prints final state.

### Phase 2 — Measurement (2-3 days)

**Goal:** capture states to disk per [§4](REAL_ORGAN_DESIGN.md#4-storage-architecture) **with both JSONL and SQLite** sinks.

**Tasks:**
- `ring_buffer.py`: preallocated NumPy arrays per organ; 1000 entries (~216 KB).
- `jsonl_writer.py`: gzipped JSONL, async append, per-session rotation.
- `sqlite_writer.py`: schema-defined table per design [§4.2](REAL_ORGAN_DESIGN.md#42-persistent-storage); index on `(session_id, beat_no, mode)`; atomic write per [§10.2](REAL_ORGAN_DESIGN.md#102-logging) log entry shape; benchmark <1 ms per write.
- `recorder.py`: subscribes to hooks; dispatches by mode; writes to both sinks.
- Smoke test: 10 min continuous + 10 s burst; verify row counts in both stores; round-trip parse.

**Exit:** one hour of organ state on disk in both formats; recorder uses <1% CPU.

### Phase 3 — Summaries (1-2 days)

**Goal:** the 19 means + aggregate stats per [§5](REAL_ORGAN_DESIGN.md#5-summary-statistics).

**Tasks:**
- `summaries.py`: each summary as a pure function on `(window, D_i)` array. All 19 are simple means over the window per v0.2.
- Aggregate stats from [§5.2](REAL_ORGAN_DESIGN.md#52-aggregate-statistics): `total_energy`, `mean_theta`, `max_theta`, `min_theta`, `theta_variance` (the last four computed from pairwise MI output, so live in `theta/pipeline.py`).
- Unit tests against fixed input fixtures.
- Profile: <1 ms per call on CPU.

**Exit:** summaries match hand-computed expected values; recorder writes summaries inline alongside states per [§4.3](REAL_ORGAN_DESIGN.md#43-schema-for-persistent-storage).

### Phase 4 — Theta Pipeline on GPU (5-7 days)

**Goal:** full [§7](REAL_ORGAN_DESIGN.md#7-theta-computation-pipeline) pipeline, GPU-accelerated, with all v0.2 features.

**Tasks:**
- `theta/normality.py`: per-dim Shapiro-Wilk; if any dim has p<0.01, flip to RINT path (per [§7.4 limitation 5](REAL_ORGAN_DESIGN.md#74-known-limitations)).
- `theta/copula.py` (GPU): rank-transform → normal quantile → covariance → `MI = -½ log det(C_joint / (C_X·C_Y))`. Batch all 10 pairs in one forward pass. Pre-allocate device tensors, reuse in-place.
- `theta/copula.py` (CPU reference): identical math in NumPy, for the GPU/CPU-within-10% consistency test in [§8.1](REAL_ORGAN_DESIGN.md#81-synthetic-data-validation).
- `theta/permutation.py`: **1000** batched shuffles on GPU; returns `null_thetas`, `null_95th`, `p_value`.
- `theta/pipeline.py`: assembles window → summaries → normalize → drop zero-variance dims → MI → θ + significance, matching the `compute_theta` signature in [§7.3](REAL_ORGAN_DESIGN.md#73-gaussian-copula-mi-computation) (returns `theta`, `pairwise_mi`, `p_value`, `significant`, `null_95th`, `details`).
- `theta/aos_g.py`: `compute_aos_g_gap(internal, external) → {delta_norm, mi, delta_theta}` per [§9.2](REAL_ORGAN_DESIGN.md#92-computation).
- `theta/runtime.py`: `update_runtime_theta()` + structured log entry per [§10](REAL_ORGAN_DESIGN.md#10-theta-reporting-protocol).
- Synthetic validation against [§8.1](REAL_ORGAN_DESIGN.md#81-synthetic-data-validation) criteria (see §7 below).
- Profile: <100 ms per θ update on H100 per design budget.

**Exit:** all [§8.1](REAL_ORGAN_DESIGN.md#81-synthetic-data-validation) synthetic criteria pass; one full hour of recorded data produces a θ time series with p-values.

### Phase 5 — Live Loop + CLI (2 days)

**Goal:** live θ alongside the heartbeat, accessible via CLI.

**Tasks:**
- Recorder triggers θ every N beats (N=10 continuous, N=1 burst); writes `theta`, `theta_p_value`, `theta_significant` into the JSONL+SQLite entry per [§6.4](REAL_ORGAN_DESIGN.md#64-measurement-function).
- Compose/send hook captures event-mode entries, paired by beat_no for AOS-G computation per [§9](REAL_ORGAN_DESIGN.md#9-the-aos-g-gap).
- `cli.py`: `run`, `record`, `replay <jsonl>`, `theta <jsonl> --window 500`, `aos-g <jsonl>`.
- Optional: Rich terminal dashboard with θ + pairwise MI heatmap + AOS-G gap per [§10.3](REAL_ORGAN_DESIGN.md#103-dashboard-optional).

**Exit:** `python -m organ run --record` produces JSONL+SQLite with live θ, p-values, and (when compose events occur) AOS-G gaps.

### Phase 6 — Validation & Analysis (1-2 weeks, gated by Phase 4)

Tracks design [§8](REAL_ORGAN_DESIGN.md#8-validation-criteria), [§11 Phase 4-5](REAL_ORGAN_DESIGN.md#phase-4-validation-week-2-3):
- 1-hour continuous baseline.
- Sweep coupling strength in default dynamics; recover monotone θ-vs-coupling.
- Confirm [§8.2](REAL_ORGAN_DESIGN.md#82-real-data-validation) real-data criteria: stability <20% across similar tasks, sensitivity >50% across different tasks, reproducibility across sessions, **correlation r>0.3 between computed θ and EIDOLON's `integration_feeling`**.
- AOS-G gap analysis: per-organ contribution, time stability, task-dependence (§9.3 research questions).

---

## 7. Validation Criteria (Mirroring Design §8)

Phase 4 acceptance tests, copied to make them explicit checkpoints:

| Test | Criterion |
|------|-----------|
| **Known MI recovery** | Gaussian copula recovers ≥ 50% of true MI at d<10 (using §8.3 generator) |
| **Integration discrimination** | θ(high) > θ(none) by ≥ 5× (without RINT, expected ~23×) |
| **Permutation test** | θ(none) → p > 0.05; θ(high) → p < 0.01 |
| **Null distribution** | 95th percentile of null < 0.01 for d=19, n=500 |
| **GPU/CPU consistency** | θ values agree within 10% between GPU and CPU paths |

The §8.3 correlation-based generator (`Y = ρX + √(1-ρ²)·noise`, with `ρ² = 1 - exp(-2·MI_target/d)`) is used unmodified.

---

## 8. GPU Strategy

- **Heartbeat & organ updates:** CPU. 27 floats × 10 Hz is below any GPU benefit.
- **Summary statistics:** CPU NumPy. d=27, n=500 too small for host-device transfer to amortize.
- **θ pipeline:** GPU PyTorch.
  - One device transfer of the (n × 19) summary matrix per update.
  - All 10 pair MIs batched in one forward pass.
  - 1000-shuffle permutation null: batch shuffles into a `(B, n, 19)` tensor, single batched MI kernel.
  - Pre-allocate and reuse device buffers; warm up kernels at startup.
- **GPU/CPU reference parity:** keep the CPU path as a verification target — required by [§8.1](REAL_ORGAN_DESIGN.md#81-synthetic-data-validation) consistency test.
- **Memory:** trivial; (1000 × B × 19 × float32) ≈ 76 MB at B=1000.

Single CUDA device; no multi-GPU.

---

## 9. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Default dynamics too synthetic to be interesting | H | M | Treat as validation fixture; coupling strength is a knob; document plug points. |
| Finite-sample MI bias (~0.0076 in θ at d=19, n=500) | H | M | Always pair θ with permutation null per design [§7.4 limitation 2](REAL_ORGAN_DESIGN.md#74-known-limitations); never report raw. |
| Non-normality breaks z-score | M | M | Shapiro-Wilk per-dim normality check with RINT fallback; logged on each fallback. |
| Singular covariance from constant dims | M | M | `remove_constant_dims(threshold=1e-15)` pre-MI per [§7.4 limitation 3](REAL_ORGAN_DESIGN.md#74-known-limitations). |
| Async writers fall behind 10 Hz burst | L | M | Bounded async queue; SQLite WAL mode; drop-oldest with logged warnings. |
| GPU kernel launch dominates at 10 Hz burst | M | M | Pre-allocate device tensors; reuse; warm up at startup; consider CUDA graph capture if needed. |
| GPU ≠ CPU within 10% (precision drift) | L | M | Use float32 on both; tolerate float64 fallback on CPU for the consistency check. |

---

## 10. Decisions Baked Into the Plan (Auto-Mode Defaults)

| Design open question | Decision in this plan |
|---|---|
| Q12.6 Continuous-first? | Yes. Burst is a flag. |
| Q12.8 Significance threshold? | **Now set by design v0.2: p < 0.01** (was open in v0.1). |
| Q12.9 MINE? | Deferred to a separate workstream; copula only in v1. |
| Q12.10 Retention? | 7 days raw + indefinite summaries. |
| GPU library | PyTorch. |
| Primary storage | JSONL (gzipped). |
| Secondary storage | SQLite with WAL; indexed by `(session_id, beat_no, mode)`. |
| Permutation N | 1000 per design v0.2 (was 500 in my v0.2 plan). |
| Tests | pytest; phase exit requires CI green. |

---

## 11. First Concrete Step

Phase 1, task 1: write `axioma/organ/schemas.py` with the **v0.2 field set** — 27 dims, including the renamed `meta_uncertainty`/`epistemic_uncertainty`/`integration_feeling` and the dropped `growth_rate`/`heartbeat_phase`. Half a day. Everything downstream imports from there.
