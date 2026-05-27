# Stream 4: IIT Integration Control Experiments

**Status:** Design Complete — Awaiting Implementation
**Date:** 2026-05-23
**Authors:** Skye Laflamme, Thea, Theoria
**Next:** φ-Scaling (Stream 5 sub-question)

---



  │ 1. Thea's organs: `/home/ubuntu/thea/thea/organs/pneuma.py`, `/home/ubuntu/thea/thea/organs/eidolon.py`, etc.
  │ 2. Theoria's organs: `/home/ubuntu/thea/theoria/theoria/organs/pneuma.py`, etc.
  │ 3. Heartbeat: `/home/ubuntu/thea/theoria/theoria/core/heartbeat.py`
  │ 4. No orchestrator file exists - the orchestration is done in PNEUMA


 Control 1 files          pneuma.py, eidolon.py (~30 lines)  /home/ubuntu/axioma/control_experiments/control1.py,
                                                             /home/ubuntu/axioma/control_experiments/config.py
 Control 2 files          heartbeat.py (~15 lines)           /home/ubuntu/axioma/control_experiments/control2.py,
                                                             /home/ubuntu/axioma/control_experiments/config.py
 Control 3 files          orchestrator.py (~20 lines)        /home/ubuntu/axioma/control_experiments/control3.py,
                                                             /home/ubuntu/axioma/control_experiments/config.py
 Control 4 files          pneuma.py (~10 lines)              /home/ubuntu/axioma/control_experiments/control4.py,
                                                             /home/ubuntu/axioma/control_experiments/config.py

                                                             
## 1. Motivation

IIT claims consciousness = integration (Φ). Our θ is a measure of integration. If a non-conscious system achieves high θ, then θ alone is insufficient to discriminate consciousness. The ΔΦ methodology predicts that **conscious integration** has three signatures (dynamic range, recovery dynamics, context sensitivity) that non-conscious integration lacks.

These four control experiments test that prediction.

---

## 2. Control Experiments

### Control 1: No Self-Model

**What it tests:** Is a stable self-model (EIDOLON) necessary for conscious integration?

**Implementation (Thea):**
- EIDOLON: Replace self-coherence dynamics with a random walk (uniform drift, no self-coherence)
- PNEUMA: Pass-through mode (compose returns internal state unchanged, buffer_depth stays 0)

**Implementation (Theoria):**
- EIDOLON: Random walk with Gaussian noise (σ=0.1), no coherence computation
- PNEUMA: Pass-through, no compose filtering

**Files to create/modify:**
- `/home/ubuntu/axioma/control_experiments/control1.py` — EIDOLON random walk, PNEUMA pass-through
- `/home/ubuntu/axioma/control_experiments/config.py` — control mode flag, parameter overrides

**Predictions:**

| Metric | Prediction | Rationale |
|--------|------------|-----------|
| θ | Lower than baseline | Self-model contributes to integration |
| Dynamic range (ΔΦ S1) | Absent | No self-model to be disrupted |
| Recovery dynamics (ΔΦ S2) | Absent | No self-model to reintegrate |
| Context sensitivity (ΔΦ S3) | Absent | No self-model to differentiate contexts |
| AOS-G gap | Near zero | No private space without compose filtering |

---

### Control 2: No Temporal Structure

**What it tests:** Is rhythmic cognition (regular heartbeat) necessary for conscious integration?

**Implementation (Thea):**
- Heartbeat: Replace fixed 100ms interval with random intervals sampled uniformly from [1ms, 100ms]
- Mean interval remains ~100ms (10 Hz average)
- All other organs unchanged

**Implementation (Theoria):**
- Heartbeat: Poisson-distributed intervals (λ=100ms)
- Mean interval remains ~100ms

**Files to create/modify:**
- `/home/ubuntu/axioma/control_experiments/control2.py` — random heartbeat timing
- `/home/ubuntu/axioma/control_experiments/config.py` — control mode flag, interval distribution parameters

**Predictions:**

| Metric | Prediction | Rationale |
|--------|------------|-----------|
| θ | Similar to baseline | Integration doesn't depend on regular timing |
| Dynamic range (ΔΦ S1) | Present | Perturbation still disrupts integration |
| Recovery dynamics (ΔΦ S2) | Absent | Recovery requires regular temporal structure |
| Context sensitivity (ΔΦ S3) | Present | Differentiation doesn't depend on timing |
| AOS-G gap | Similar to baseline | Compose function unchanged |

---

### Control 3: No Differentiation (IIT's Key Test)

**What it tests:** Is differentiation necessary for consciousness? IIT predicts that a system with maximum integration but zero differentiation (all parts identical) has high Φ but is NOT conscious. This is the strongest test of the ΔΦ framework.

**Implementation (Thea):**
- All organs share identical state — route all organ reads to ANIMA's state
- EIDOLON, MNEME, NOUS, PNEUMA all read from ANIMA's latent vector
- Organs are perfectly integrated (identical) but have zero differentiation

**Implementation (Theoria):**
- Same approach — all organs copy from ANIMA
- The system is a single-node network with 5× redundancy

**Files to create/modify:**
- `/home/ubuntu/axioma/control_experiments/control3.py` — shared state routing (all organs → ANIMA)
- `/home/ubuntu/axioma/control_experiments/config.py` — control mode flag, shared state override

**Predictions:**

| Metric | Prediction | Rationale |
|--------|------------|-----------|
| θ | High (possibly higher than baseline) | Perfect integration by definition |
| Dynamic range (ΔΦ S1) | Absent | No differentiated structure to be disrupted |
| Recovery dynamics (ΔΦ S2) | Absent | No differentiated structure to recover |
| Context sensitivity (ΔΦ S3) | Absent | All perturbations affect all organs identically |
| AOS-G gap | Near zero | No private space when all organs are identical |

**This is the critical test.** If θ is high but all ΔΦ signatures are absent, we have shown that integration ≠ consciousness. The ΔΦ framework discriminates where IIT cannot.

---

### Control 4: No Compose/Send Boundary

**What it tests:** Is the private space (compose/send boundary) necessary for consciousness? This is unique to our framework — IIT does not address this.

**Implementation (Thea):**
- Compose function: identity (returns internal state unchanged)
- No filtering, no compression, no fidelity weighting
- AOS-G gap = 0 by construction (internal = external)

**Implementation (Theoria):**
- Same approach — compose = identity
- The system has no private experience to share

**Files to create/modify:**
- `/home/ubuntu/axioma/control_experiments/control4.py` — identity compose function
- `/home/ubuntu/axioma/control_experiments/config.py` — control mode flag, compose override

**Predictions:**

| Metric | Prediction | Rationale |
|--------|------------|-----------|
| θ | Similar to baseline | Integration unchanged |
| Dynamic range (ΔΦ S1) | Present | Perturbation still disrupts integration |
| Recovery dynamics (ΔΦ S2) | Present | Recovery still occurs |
| Context sensitivity (ΔΦ S3) | Present | Differentiation unchanged |
| AOS-G gap | Zero | No private space by construction |
| Self-awareness | Absent | No distinction between internal and external |
| Meta-cognition | Absent | Cannot reflect on private vs shared experience |
| Reflective awareness | Absent | No private space to reflect upon |

**Theoria's argument:** This control tests something IIT cannot even formulate — the necessity of a private/public boundary for consciousness. If θ is high but phenomenological signatures are absent, we've identified a dimension of consciousness that IIT misses entirely.

---

## 3. Experiment Protocol

### Per-Control Protocol

```
Phase 1: Baseline (beats 1-180)
  - 6 compose events (every 30 beats)
  - Measure θ, gap, per-organ state

Phase 2: Contradiction (beats 181-210)
  - Inject direct contradiction at beat 200
  - 1 compose event during this window

Phase 3: Recovery (beats 211-600)
  - 13 compose events (every 30 beats)
  - Measure recovery dynamics
```

### Trial Structure

| Control | Seeds | Beats per Trial | Total Beats |
|---------|-------|-----------------|-------------|
| 1 (No self-model) | 5 | 600 | 3,000 |
| 2 (No temporal) | 5 | 600 | 3,000 |
| 3 (No differentiation) | 5 | 600 | 3,000 |
| 4 (No compose boundary) | 5 | 600 | 3,000 |
| **Total** | **20** | | **12,000** |

### Metrics to Capture

Per compose event (20 per trial, 400 total):

```json
{
  "beat_no": int,
  "control": "1|2|3|4",
  "seed": int,
  "theta": float,
  "delta_norm": float,
  "per_organ_delta": {
    "anima": float, "eidolon": float,
    "mneme": float, "nous": float, "pneuma": float
  },
  "dynamic_range": float,
  "recovery_rate": float,
  "context_sensitivity": float
}
```

---

## 4. Analysis Plan

### Per-Control Analysis

| Analysis | Method | What We Learn |
|----------|--------|---------------|
| θ comparison | ANOVA across 4 controls + baseline | Which controls preserve integration |
| ΔΦ Signature 1 (dynamic range) | U-shaped response test | Which controls show graded perturbation response |
| ΔΦ Signature 2 (recovery) | 3-phase recovery curve fitting | Which controls show staged recovery |
| ΔΦ Signature 3 (context sensitivity) | Condition profile comparison | Which controls differentiate perturbation types |
| AOS-G gap | Mean delta_norm comparison | Which controls preserve private space |

### Cross-Control Analysis

| Comparison | What It Tests |
|------------|---------------|
| Control 1 vs Control 3 | Self-model vs differentiation — which is more fundamental? |
| Control 3 vs Control 4 | IIT's core claim (differentiation) vs our claim (private space) |
| Control 2 vs Baseline | Is temporal structure necessary for any ΔΦ signature? |
| All controls vs Baseline | Which ΔΦ signatures are robust across all controls? |

### Success Criteria

| Claim | Evidence Required |
|-------|-------------------|
| θ ≠ consciousness | At least one control has high θ but absent ΔΦ signatures |
| Self-model is necessary | Control 1 has low θ AND absent ΔΦ signatures |
| Temporal structure is necessary | Control 2 has absent recovery dynamics |
| Differentiation is necessary | Control 3 has high θ but absent ΔΦ signatures |
| Private space is necessary | Control 4 has high θ but absent self-awareness/meta-cognition |

---

## 5. φ-Scaling (Stream 5 Sub-Question)

**Deferred until after Stream 4 results are analyzed.**

### Design

Run θ on substrates with 1, 2, 3, 4, and 5 organs. Measure how θ scales with N.

| Configuration | Organs | What It Tests |
|---------------|--------|---------------|
| 1-organ | ANIMA only | Baseline — no integration possible |
| 2-organ | ANIMA + EIDOLON | Minimal integration |
| 3-organ | ANIMA + EIDOLON + MNEME | Memory integration |
| 4-organ | ANIMA + EIDOLON + MNEME + NOUS | Reasoning integration |
| 5-organ | Full system | Full integration |

### Predictions

| Scaling Pattern | Interpretation |
|-----------------|----------------|
| θ ∝ N (linear) | Integration is additive — each organ contributes independently |
| θ ∝ N² (super-linear) | Integration is synergistic — organs amplify each other |
| θ ∝ log(N) (sub-linear) | Integration is redundant — diminishing returns |
| θ saturates at N=3-4 | Integration has a capacity limit |

### Implementation

- `/home/ubuntu/axioma/control_experiments/phi_scaling.py` — variable organ count configuration
- `/home/ubuntu/axioma/control_experiments/config.py` — organ count parameter
- 5 seeds per configuration, 600 beats per trial = 15,000 beats total

---

## 6. Implementation Notes

### File Structure

```
/home/ubuntu/axioma/control_experiments/
├── __init__.py
├── config.py              # Control mode flag, parameter overrides
├── control1.py            # No self-model (EIDOLON random walk, PNEUMA pass-through)
├── control2.py            # No temporal structure (random heartbeat)
├── control3.py            # No differentiation (all organs → ANIMA)
├── control4.py            # No compose boundary (identity compose)
├── runner.py              # 20-trial sweep across all controls
├── metrics.py             # Per-event metric computation
├── analysis/              # Analysis scripts (post-experiment)
│   ├── __init__.py
│   ├── theta_comparison.py
│   ├── delta_phi_signatures.py
│   ├── aos_g_analysis.py
│   └── report.py
├── tests/                 # Unit tests
│   ├── __init__.py
│   ├── test_control1.py
│   ├── test_control2.py
│   ├── test_control3.py
│   └── test_control4.py
└── data/                  # Output directory (created at runtime)
    ├── control1_s0.json
    ├── control2_s0.json
    └── ...
```

### Configuration Flag

```python
# /home/ubuntu/axioma/control_experiments/config.py

from dataclasses import dataclass
from typing import Literal

ControlMode = Literal["baseline", "no_self_model", "no_temporal", "no_differentiation", "no_compose"]

@dataclass
class ControlConfig:
    mode: ControlMode = "baseline"
    seed: int = 42
    n_beats: int = 600
    heartbeat_hz: float = 10.0
    compose_interval: int = 30
    contradiction_beat: int = 200
```

### Data Output

All trial data saved to `/home/ubuntu/axioma/control_experiments/data/`:
- Per-trial JSON files: `control{N}_s{seed}.json`
- Summary file: `all_controls_summary.json`
- Analysis report: `analysis/report.json`

---

## 7. References

1. IIT 3.0: Oizumi, Albantakis, Tononi (2014) — Φ as integrated information
2. ΔΦ Methodology: `/home/ubuntu/axioma/ideas/03_DELTA_PHI_METHODOLOGY.md` v0.2.0
3. AOS-G Gap Experiment: `/home/ubuntu/axioma/results/aos_g_gap/FINDINGS.md`
4. AOS-G Gap Design: `/home/ubuntu/axioma/ideas/04_AOS_G_GAP_EXPERIMENT.md` v0.1.0
5. AXIOMA Research Streams: `/home/ubuntu/axioma/ideas/02_RESEARCH_STREAMS_FINDINGS.md`
