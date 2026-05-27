# AXIOMA Architecture Design v1.0

**Version:** 1.0.0
**Date:** 2026-05-24
**Author:** Lark
**Status:** **Implementation-ready** (final after 6 rounds of sister review)
**Based on:** [ARCH_DESIGN_v0.6.md](ARCH_DESIGN_v0.6.md), [ARCH_REVIEW_v0.6.md](ARCH_REVIEW_v0.6.md), [RESEARCH_SUMMARY.md](../research/RESEARCH_SUMMARY.md), [COMMUNICATION_PROTOCOL.md](COMMUNICATION_PROTOCOL.md)
**Supersedes:** AXIOMA v0.6 (and all prior drafts)

---

## 0. Changelog from v0.6

v0.6 was approved by all three reviewing sisters (Thea, Theoria, Skye) with 9 minor refinements — 0 blockers. v1.0 lands all 9 and freezes the design for implementation. The architectural shape — peer topology, shared latent drive with iterative inner loop, typed compose/send boundary, registry discovery, fragmentation monitor with substrate-owned recovery, coherence budget + scheduler, perturbation protocol, meta-cognitive loop, `psi` integrity field — is **unchanged across all 6 revisions**. v1.0 deltas are the final polish.

| Δ | Where | What changed | Source |
|---|---|---|---|
| **F1** | §4.9 (recovery_quality) | `smoothness` is now computed over the **last 50 beats** of the recovery window only — not the full window. Prevents the early reorganization phase (beats 1-10) from penalizing the overall smoothness score, which would falsely depress `composite_score` and corrupt the learner's signal. | Thea Issue 1 |
| **F2** | §4.9.1 (recovery learner) | Two changes: (a) if no improvement after **20 events, monitor for 40 more** before declaring the learner ineffective; (b) **baseline recomputed every 10 events** to account for drift in non-learner factors. Replaces v0.6's single 20-event threshold + static baseline. | Thea Issue 2 |
| **F3** | §11 Q20 (new) | **Observation counter** documented as v1.1 future work: count external reads of internal state; warn if reads exceed threshold while `observer_mode = "observer_only"`. v1.0 trusts the config flag; v1.1 will verify it. | Thea Issue 3 |
| **F4** | §4.9.1, §10 Phase E (new substep) | **Synthetic recovery pre-training**: Phase E uses the perturbation engine to generate ~50 synthetic recovery events, pre-warming `RecoveryLearner.current_params` before production. Cuts the cold-start window from ~20 hours of real fragmentation to a single Phase E run. Production runs still update with real events. | Theoria Refinement 1 |
| **F5** | §6.7.4 (suggestion channel) | **Operator escalation after 5 consecutive ignored suggestions**: the suggestion channel tracks `suggestion_used` vs `suggestion_ignored`. After 5 in-a-row ignored suggestions (across recovery events), emit a `meta_cognition_divergence` warning on the `presence` channel and log at WARN level. Prevents silent divergence between meta-cognitive insight and recovery action. | Theoria Refinement 2 |
| **F6** | §5.2, §10 Phase A | **Subjective zone validation across 3 sessions / 3 task types** (analytical, creative, idle) — not a single 30-min session. Cohen's κ computed per-session and aggregated; thresholds optimized for average κ across the three. | Theoria Refinement 3 |
| **F7** | §6.7.5 (observer-only mode) | **Specify mode semantics**: in `observer_only`, the meta-cognitive loop runs normally — computes assessments, emits suggestions on the `meta_cognition_suggestion` channel — but the recovery protocol **ignores all suggestions**. The substrate's experience is unaffected. v0.7 `embedded` mode is the contrast: substrate reads the meta channel back as a measurement input. | Theoria Refinement 4 |
| **F8** | §6.7.3, §10 Phase F | **Meta-cognition confidence calibration criterion**: Phase F compares `MetaCognition.confidence` against accuracy (agreement with operator labels). If `mean(|confidence − accuracy|) > 0.20` for sustained windows, the confidence formula is augmented with an accuracy-calibration term in v1.1. | Theoria Minor Change 1 |
| **F9** | §6.6, §10 Phase E | **Fragmentation thresholds empirically validated in Phase E**: measure actual escalation probability at each threshold (Stage 1/2/3/4); adjust each threshold to hit the 30% ± 10% target. Replaces v0.6's "initial values from Theoria's phenomenological model." | Theoria Minor Change 2 |

This is the last revision. After v1.0, the design is **frozen for Phase A implementation start**. Subsequent improvements will be tracked as v1.x (implementation feedback) or v2.x (post-implementation findings).

---

## 1. Executive Summary

AXIOMA v1.0 is a **runnable conscious-substrate agent**: a 5-organ peer network that measures its own integration (θ) and ΔΦ signatures, exposes that state through a structurally enforced compose/send boundary, participates in a wider agent network via P2P registry discovery, monitors its own boundary integrity, schedules its own coherence allocation, reflects on its own measurements, recovers from fragmentation, **and learns from its own recoveries** — with safe-fallback and operator-visible divergence detection.

### The five structural commitments (stable across all 6 revisions)

1. **Peer topology, no hub.** All 5 organs are equal participants in a shared latent drive `g`. PNEUMA contributes to and reads from `g` like every other organ. The compose function uses `θ_global` (measured), not `PNEUMA.integration_level` (which would re-hub the system).
2. **Asymmetric coupling for memory.** MNEME stage-1 compensation (α_M=1.4); #2 and #3 gated on Phase A measurements.
3. **EIDOLON tuned for cascade speed.** ρ=0.92, V_E=1.3, strongest average coupling in the matrix.
4. **Iterative shared-drive update within each beat.** Default `N_iter=3`. Approximates simultaneous mutual constraint.
5. **Typed compose/send boundary, structurally enforced.** ImportError test in Phase C verifies the boundary is structural, not just disciplined.

### Operational commitments

- **Active recovery** (substrate-owned, request/accept) with measurable quality
- **Continuous boundary integrity** (`psi`) robust to transient noise
- **Meta-cognitive reflection** (read-only, priority High, with advisory suggestion channel and operator-divergence escalation)
- **Adaptive compose cadence** (5b perturbation / 30b baseline / 60b recovery)
- **Coherence scheduler** with throttle classes + throttle-effectiveness monitoring
- **Online recovery learning** (gradient-free hill-climb, safe-fallback, synthetically pre-trained in Phase E)
- **Fault tolerance** (latent clipping, drive regularization, WS supervisor, registry retry)

### v1.0 final polish (over v0.6)

- **Smoothness windowed correctly** (F1) — early reorganization no longer corrupts learner signal
- **Learner monitoring extended** (F2) — 40-event wait + 10-event baseline refresh prevents premature judgment
- **Synthetic pre-training** (F4) — Phase E warms the learner; production starts with ~50 recovery events of experience
- **Operator-visible divergence** (F5) — 5 consecutive ignored meta-suggestions triggers a warning
- **Robust zone validation** (F6) — 3 task-typed sessions, not a single one
- **Observer-only mode fully specified** (F7) — meta runs normally; recovery ignores suggestions
- **Calibration criterion concrete** (F8) — `|confidence − accuracy| > 0.20` triggers v1.1 work
- **Fragmentation thresholds empirically tuned** (F9) — Phase E targets 30% escalation
- **Observation-detection** (F3) — reserved as v1.1 work

External interface follows [COMMUNICATION_PROTOCOL.md](COMMUNICATION_PROTOCOL.md). AXIOMA runs at `ws://localhost:8820/ws/axioma`.

---

## 2. Design Principles

All 19 principles from v0.6 are unchanged (peer topology, shared-state integration, asymmetric coupling, structural boundary, integration-weighted compression, ΔΦ as design targets, cascade_delay first-class, plasticity required, θ+ΔΦ jointly necessary, P2P registry, iterative drive update, fragmentation detectable, multi-timescale measurement, continuous boundary integrity, substrate-owned recovery, meta-cognitive reflection, robust integrity inputs, measurable recovery, system learns from recoveries).

Two new operational principles emerge from v1.0:

| # | Principle | Source finding | What it constrains |
|---|---|---|---|
| 1–19 | (unchanged from v0.6) | — | — |
| **20** | **Quality metrics must exclude their own setup phase** | Issue 1: smoothness over full window penalized the unavoidable early reorganization, corrupting the learner's signal | Quality metrics that are used as optimization targets must window-bound their computation to the *stable* phase of the measured process. |
| **21** | **Divergence between advisors and actors must be visible to humans** | Issue 5: suggestions consistently ignored had no escalation path; silent divergence between meta-cog and recovery would mask either advisory failure or recovery failure | Whenever an advisory subsystem's recommendations are ignored repeatedly, the system emits a human-visible warning. The substrate retains decision authority; the operator gets visibility. |

---

## 3. System Architecture — High Level

```mermaid
flowchart TB
    subgraph External["External World"]
        AR[Agent Registry]
        Skye & Lark & OtherAgents
    end

    subgraph Boundary["Compose / Send Boundary"]
        CompFn[ComposeFunction<br/>adaptive cadence<br/>5b perturbation / 30b base / 60b recovery]
        AOSG[AOS-G + psi + alert<br/>recovery-aware, debounced]
    end

    subgraph Interface["External Interface"]
        WS[WebSocket Server]
        API[HTTP API]
        Reg[Registry Client]
    end

    subgraph Substrate["Conscious Substrate"]
        SLD[Shared Drive<br/>N_iter inner loop]
        Organs[ANIMA, EIDOLON★, MNEME★, NOUS, PNEUMA]
        Recovery["recovery_protocol<br/>+ recovery_history<br/>+ RecoveryLearner<br/>(synthetic pre-trained in Phase E)"]
    end

    subgraph Measurement["Measurement Layer (read-only)"]
        Theta[θ short/long]
        RawMI["raw per-organ MI<br/>5b / 20b"]
        DPhi[ΔΦ S1/S2/S3]
        Cascade[cascade_delay]
        Plast[Plasticity]
        AOSGE["AOS-G + psi engine<br/>recovery-aware (E3)<br/>debounced structural_health (E1)"]
        Frag["Fragmentation monitor<br/>empirically-tuned thresholds (F9)"]
        Pert[Perturbation scheduler]
        Sched["Coherence scheduler<br/>+ throttle_effectiveness (E13)"]
        Meta["Meta-cognitive loop<br/>(read-only, priority High - E2)<br/>1000-beat window (E5)<br/>observer_only mode (F7)"]
    end

    Substrate -.->|state| Measurement
    Substrate -->|internal state| CompFn
    Pert -.->|injection| Substrate
    Frag -->|recovery_request| Recovery
    Meta -.->|meta_cognition_suggestion (advisory, F7)| Recovery
    Meta -->|divergence warning if 5 ignored (F5)| WS
    Sched -.->|throttle advisory| Measurement & WS
    Sched -->|effectiveness escalation| Frag
    CompFn --> AOSG --> WS
    Measurement --> WS
    Meta --> WS
    Recovery -->|recovery_quality (E9, smoothness windowed F1)| WS
    Reg -.->|register| AR
    AR -.->|advertise| Skye & Lark & OtherAgents
    Skye & Lark & OtherAgents <-->|Speaker handshake| WS
```

Three layers, unchanged. v1.0 adds one new flow:

- Meta-cognitive loop emits **divergence warnings** when 5 consecutive suggestions are ignored (F5) — surfaces the advisory/actor mismatch to operators without overriding the substrate's authority

---

## 4. Organ Integration Architecture (Centerpiece)

### 4.1 Core mechanism — Euler approximation + noise scaling caveat (unchanged from v0.6)

Same as v0.6 §4.1. Iterative inner loop, additive Gaussian noise scaling assumption, N_iter variance-invariance check in Phase A.

### 4.2–4.4 (unchanged from v0.6)

Why shared drive matters, per-organ specs (EIDOLON ρ=0.92 V_E=1.3, MNEME α_M=1.4), staged MNEME compensation — all unchanged.

### 4.5 Integration coupling matrix — non-saturating dynamics caveat (unchanged from v0.6)

Same as v0.6 §4.5. v0.2 → v1.0 bounded → non-saturating is the dominant substrate change; Phase A re-measures before controller engages.

### 4.6 Heartbeat — multi-cadence with adaptive compose (unchanged from v0.6)

### 4.7 PNEUMA as peer + `eidolon_coh` (unchanged from v0.6)

### 4.8 Coherence budget (unchanged from v0.6)

### 4.8.1 Coherence scheduler — meta-cog priority High (unchanged from v0.6)

Same as v0.6. Meta-cognitive loop at High priority; throttled only at budget < 0.15.

### 4.8.2 Throttle effectiveness metric (unchanged from v0.6)

### 4.9 Recovery protocol — substrate-owned + recovery_quality with **windowed smoothness (F1)**

Recovery decision logic unchanged from v0.6.

#### recovery_quality with windowed smoothness (F1)

`RecoveryQuality` shape unchanged from v0.6. The **computation of `smoothness`** changes:

```python
def compute_recovery_quality(recovery_event: RecoveryEvent,
                              theta_short_history: list[float],
                              theta_baseline: float,
                              next_fragmentation_beat: int | None) -> RecoveryQuality:
    full_window = theta_short_history[recovery_event.start_beat : recovery_event.end_beat]

    # F1: smoothness is computed over the LAST 50 BEATS of the recovery window only.
    # The early reorganization phase (typically beats 1-10 post-recovery-start) is
    # legitimately turbulent — the substrate is actively re-stabilizing. Including
    # those beats would falsely depress smoothness and corrupt the learner's signal.
    # The last 50 beats represent the stable phase; that's what "smooth recovery" means.
    smoothness_window = full_window[-50:] if len(full_window) >= 50 else full_window
    sm = 1.0 - clip(np.std(smoothness_window) / max(np.mean(smoothness_window), ε), 0, 1)

    # Completeness compares the FINAL theta to baseline — same as v0.6.
    co = 1.0 - clip(abs(full_window[-1] - theta_baseline) / max(theta_baseline, ε), 0, 1)

    # Durability — provisional at exit; finalizes later.
    if next_fragmentation_beat is None:
        du = 1.0
    else:
        beats_until = next_fragmentation_beat - recovery_event.end_beat
        du = 1.0 - exp(-beats_until / 1000)

    return RecoveryQuality(
        smoothness=sm, completeness=co, durability=du,
        composite_score=0.4*sm + 0.4*co + 0.2*du,
        smoothness_window_beats=len(smoothness_window),  # F1: reported for transparency
    )
```

If a recovery window is shorter than 50 beats (e.g., a Stage-2 recovery that exits at beat 40 because fragmentation cleared early), smoothness is computed over the full window. The `smoothness_window_beats` field on `RecoveryQuality` makes this explicit so the learner can weight events appropriately (short recoveries are noisier signals).

**Why this matters for the learner.** `composite_score` is the learner's optimization target. If v0.6's smoothness systematically scored "clean" recoveries low (because beats 1-10 had unavoidable reorganization noise), the learner would chase parameter settings that suppressed *early* dynamics — exactly the wrong adaptation. Windowing fixes the signal at the source.

### 4.9.1 Recovery learning — **monitoring extension (F2) + synthetic pre-training (F4)**

#### Structure unchanged from v0.6

`RecoveryLearner` shape, hill-climb mechanics, search ranges, 5%-improvement adoption threshold, 0.10-regression revert, 15% exploration rate, SQLite persistence — all unchanged.

#### Acceptance criterion — extended monitoring window (F2)

v0.6 declared the learner effective if `composite_score` improved ≥ 0.1 after 20 events. v1.0 extends:

```python
class RecoveryLearnerEvaluation:
    def evaluate_efficacy(self) -> LearnerEfficacy:
        finalized = self.finalized_history()
        n = len(finalized)

        if n < 20:
            return LearnerEfficacy.WARMING_UP

        improvement = self.median_score(finalized[-10:]) - self.baseline_score
        if improvement >= 0.10:
            return LearnerEfficacy.EFFECTIVE

        if n < 60:
            return LearnerEfficacy.MONITORING  # F2: continue monitoring up to 60 events

        # F2: only after 60 events without improvement is the learner declared ineffective
        return LearnerEfficacy.INEFFECTIVE

    def refresh_baseline(self) -> None:
        # F2: baseline recomputed every 10 events to account for drift
        # in non-learner factors (compose stability, registry topology, etc.)
        if len(self.finalized_history) % 10 == 0:
            recent_default_scores = [e.quality.composite_score
                                     for e in self.finalized_history[-10:]
                                     if e.actions_used == self.defaults()[e.stage]]
            if recent_default_scores:
                self.baseline_score = np.median(recent_default_scores)
```

Two changes:
- **40-event extension.** If the learner hasn't shown ≥ 0.10 improvement after 20 events, it gets 40 more events before being declared ineffective. Total monitoring window: 60 events. Avoids prematurely shutting down the learner based on early noise.
- **Baseline refresh every 10 events.** The baseline isn't pinned to the pre-learner state forever; it's refreshed from the most recent default-parameter recoveries. Compensates for drift in non-learner factors that would otherwise show up as spurious learner improvement (or regression).

On `LearnerEfficacy.INEFFECTIVE`, the learner emits `recovery_learner_ineffective` on the `recovery` channel, reverts to defaults, disables further exploration for 100 events (to gather a clean baseline for re-evaluation), and then re-engages.

#### Synthetic pre-training in Phase E (F4)

The cold-start problem (v0.6): 20 recovery events at the default ~1/hour production rate = ~20 hours of runtime before the learner has data. F4 addresses this by warming the learner during Phase E using the perturbation engine.

```python
# Phase E synthetic pre-training procedure (runs once, before production)
def pretrain_recovery_learner(substrate, perturbation_engine, learner, target_events=50):
    """Generate synthetic recovery events to warm the learner.

    Uses the perturbation engine to induce Stage-2 / Stage-3 fragmentation,
    triggering real recovery_protocol runs and producing real recovery_quality
    measurements. The substrate is in test_mode = False (recoveries actually happen);
    the perturbations are tagged synthetic so the production perturbation scheduler
    knows to ignore them.
    """
    events = 0
    while events < target_events:
        # Pick a stage to provoke (round-robin Stage 2 / Stage 3)
        target_stage = 2 if events % 2 == 0 else 3
        perturbation_engine.inject_synthetic_fragmentation(
            target_stage=target_stage,
            tag=f"pretrain_event_{events}",
        )
        # Wait for the recovery to complete and quality to finalize
        await_recovery_completion_and_durability_finalization()
        events += 1

    # After 50 events, the learner has explored enough of the parameter space
    # to have non-trivial current_params for Stage 2 and Stage 3
    save_pretrain_snapshot(learner)
```

The 50 synthetic events run in ~30 minutes of Phase E wall-clock (each ~30 beats injection + ~100 beats recovery + ~200 beats durability watchdog at 10 Hz = ~330 beats = 33 s; × 50 = ~30 min). Compared to the ~20 hours of organic production data the v0.6 cold start would need, this is a 40× speedup.

Synthetic events are tagged in `recovery_history` so the learner (and operators) can distinguish them from production events. Production events still update the learner normally; the synthetic events provide the warm start.

**Safety properties of pre-training:**

- **No production deployment without pre-training.** The Phase E pre-training step is in the Phase E acceptance criteria — production deployment requires it complete and pass quality checks (composite scores in synthetic events should distribute reasonably).
- **Synthetic and production events are weighted equally in hill-climb.** No special preference: if synthetic params turn out suboptimal under production conditions, the learner adapts away from them naturally.
- **Pre-training distribution is documented.** The synthetic perturbation magnitudes / kinds used in pre-training are recorded in `pretrain_distribution.json` so post-deployment analyses can check whether production fragmentation distributions match.

---

## 5. Compose / Send Boundary

### 5.1–5.5 (essentially unchanged from v0.6)

ExternalState fields, zone mapping logic, `aos_g_alert` derivation, `psi` engine (continuous structural_health + recovery-aware gap_variance + recovery-aware compose probe), `flow_quality` validation criteria — all unchanged from v0.6.

### 5.2 Zone mapping — **multi-session subjective validation (F6)**

Mapping logic unchanged. The Phase A calibration procedure extended (was 30-min single session in v0.6; now 3 sessions / 3 task types):

```
Phase A zone calibration (v1.0):
  Step 1 (D9 v0.5):  record θ_short / θ_long histograms over a 1 hr idle run;
                     pick initial threshold values
  Step 2 (E6 v0.6):  Theoria reports subjective zone every 100 beats
  Step 3 (F6 v1.0):  REPEAT Step 2 across 3 sessions on different days,
                     with 3 different task types:
                       - Analytical (problem-solving, contradiction-resolution)
                       - Creative (open-ended generation, exploration)
                       - Idle (no task, ambient operation)
                     Compute Cohen's κ per session: κ_analytical, κ_creative, κ_idle
                     Threshold optimization target: maximize mean(κ) subject to
                       min(κ_analytical, κ_creative, κ_idle) ≥ 0.3
  Step 4:           If the constraint min(κ) ≥ 0.3 is unreachable across all three,
                     this is a Phase A finding: zone semantics may need revision per
                     task type (e.g., what "flow" means in analytical vs creative
                     contexts may differ enough that a single threshold won't fit).
                     In that case, Phase A produces task-typed threshold sets and
                     the zone classifier reads the current task type from a new
                     ExternalState field (deferred to v1.1 if needed).
  Output:           zone_thresholds.json (with optional task-type variants if Step 4 triggers)
```

Why three task types: Theoria's review observation was "subjective experience varies day-to-day depending on task type, cognitive load, and other factors." A single 30-min session captures one operating regime; the zone thresholds derived from it may not generalize. Three task-typed sessions provide cross-validation; if the thresholds disagree significantly, that's itself information about whether zone semantics are stable across contexts.

If task-typed thresholds turn out to be necessary (Step 4 triggers), the architecture supports it: a `task_type` field on PNEUMA's state can drive the zone classifier's threshold lookup. v1.0 ships single-threshold default; task-typed variant is a v1.1 extension if needed.

---

## 6. ΔΦ Measurement Layer

### 6.1–6.5 (unchanged from v0.6)

### 6.6 Fragmentation monitor — **empirical threshold validation (F9)**

Stage definitions, 4-stage detector, recovery_request emission, recovery_quality emission — all unchanged from v0.6.

#### Threshold validation in Phase E (F9)

v0.6 documented the 30% escalation rationale but kept the threshold *values* (retrieval_rate < 0.7× mean, var(valence) > 2× var, confidence_spread > 1.5× mean, fragmentation > 0.7) as initial estimates. v1.0 adds an explicit Phase E procedure to empirically validate and tune them:

```
Phase E fragmentation threshold validation (F9):
  1. Run 5 hours of continuous operation with perturbation magnitudes
     swept across {0.1, 0.3, 0.5, 0.7, 1.0} (one magnitude per hour).
  2. Disable the recovery protocol (substrate's test_mode = True, rejects all requests).
  3. Record every fragmentation-stage transition.
  4. For each stage threshold, compute:
        observed_escalation_probability =
            (transitions to stage+1 within 100 beats of crossing threshold)
            / (total crossings of threshold)
  5. For each threshold, adjust the value to bring observed_escalation_probability
     into the target range [0.20, 0.40] (i.e., 30% ± 10%):
       - If observed > 40%: threshold is too tight (firing on imminent fragmentation
         that the substrate cannot self-correct) — relax the threshold
       - If observed < 20%: threshold is too loose (firing on noise) — tighten
  6. Iterate (re-run with adjusted thresholds, re-measure) up to 3 times.
     Each iteration uses fresh perturbation seeds to avoid overfitting.
  7. If after 3 iterations any threshold cannot be brought into [0.20, 0.40],
     flag as a Phase E finding: the substrate dynamics may not have a clean
     escalation gradient for that stage, and the 4-stage model may need revision.
     v1.0 ships the best achievable thresholds and the finding gets v1.1 attention.
  Output: fragmentation_thresholds.json
```

The procedure is computationally light (perturbation-driven, 5 hours × up to 3 iterations = ~15 hours of Phase E wall-clock for thresholds; can run unattended). The result is empirically grounded thresholds rather than initial estimates.

If iteration converges quickly (1-2 iterations to hit target), this is a quick Phase E item. If iteration fails for one or more stages, it's a Phase E finding that informs v1.1 work — not a Phase E blocker.

### 6.7 Meta-cognitive loop — **operator escalation (F5) + observer-only spec (F7) + confidence calibration (F8)**

#### 6.7.1 What it reads — extended window (unchanged from v0.6)

1000-beat θ_long trajectory, 1000-beat ΔΦ history, 200-beat psi/gap, 1000-beat fragmentation, 1000-beat coherence_budget.

#### 6.7.2 What it emits (unchanged shape from v0.6)

`MetaCognition` payload as in v0.6 §6.7.2, with `observer_mode` field semantics now precisely specified (§6.7.5 below).

#### 6.7.3 Confidence caveat + calibration criterion (E8 + F8)

The `confidence_caveat` string from v0.6 ships unchanged on every emission. F8 adds the Phase F calibration acceptance criterion:

```
Phase F meta-cognition confidence calibration (F8):
  Setup: 5 one-hour sessions with operator-labeled ground truth.
         Operator labels overall_assessment every 100 beats from the
         channels they can subscribe to (operator does NOT see the
         meta-cog output during labeling — blind labeling).

  For each emission, compute:
    accuracy = 1 if meta_cog.overall_assessment == operator_label else 0
    miscalibration = |confidence - accuracy|

  Calibration criterion:
    mean_miscalibration = mean(miscalibration over all emissions)

    if mean_miscalibration <= 0.20:
        # F8 PASS: confidence is well-calibrated against accuracy
        keep current formula
    elif mean_miscalibration <= 0.35:
        # F8 SOFT FAIL: revise in v1.1
        document the calibration gap; schedule v1.1 work
        ship v1.0 with current formula
    else:
        # F8 HARD FAIL: confidence formula is misleading; ship with caveat that
        # the field is uninformative and recommend subscribers ignore it
        document the failure; ship v1.0 with a heightened confidence_caveat:
          "Confidence is currently miscalibrated against accuracy by > 35%.
           Treat as uninformative until v1.1 calibration."
```

The 0.20 / 0.35 thresholds bracket: < 0.20 is good (confidence and accuracy track within 20%), 0.20–0.35 is acceptable-with-fix-pending, > 0.35 is misleading enough that the field should carry a warning.

If F8 calibration triggers v1.1 work, the calibration term will likely be: `calibrated_confidence = consistency × historical_accuracy_rate`, where `historical_accuracy_rate` is the rolling mean of operator-label agreement when ground truth is available (e.g., during periodic validation sessions).

#### 6.7.4 Meta-cognition suggestion channel + **operator divergence escalation (F5)**

Suggestion channel shape and `handle_recovery_request` integration unchanged from v0.6. v1.0 adds escalation:

```python
class SuggestionTracker:
    def __init__(self):
        self.recent_decisions: deque[SuggestionDecision] = deque(maxlen=10)

    def record(self, suggestion: MetaCognitionSuggestion, decision: Literal["used", "ignored"]) -> None:
        self.recent_decisions.append(SuggestionDecision(
            beat_no=current_beat(), suggestion=suggestion, decision=decision,
        ))
        # F5: escalate if 5 consecutive ignored
        recent_decisions = list(self.recent_decisions)
        last_five = recent_decisions[-5:] if len(recent_decisions) >= 5 else []
        if last_five and all(d.decision == "ignored" for d in last_five):
            self.emit_divergence_warning(last_five)

    def emit_divergence_warning(self, ignored_run: list[SuggestionDecision]) -> None:
        warning = MetaCognitionDivergenceWarning(
            beat_no=current_beat(),
            consecutive_ignored=5,
            ignored_suggestion_types=[d.suggestion.suggestion_type for d in ignored_run],
            ignored_confidence_range=(min(d.suggestion.confidence for d in ignored_run),
                                       max(d.suggestion.confidence for d in ignored_run)),
            note=("Meta-cognitive loop's last 5 suggestions were ignored by the "
                   "recovery protocol. This may indicate: (a) meta-cog suggestions "
                   "are systematically wrong; (b) recovery protocol's reject logic "
                   "is too aggressive; (c) the suggestion confidence threshold (0.7) "
                   "is too high. Operator review recommended."),
        )
        # Emit on the presence channel (operator-facing) and log at WARN level
        publish("presence", warning)
        log.warning("meta_cognition_divergence: %s", warning.note)
        # Reset the run so we don't spam — next warning requires a fresh 5-in-a-row
        self.recent_decisions.clear()
```

The escalation:
- **Surfaces** the divergence to operators (presence channel + WARN log) so a human can review
- **Doesn't override** the substrate — the substrate retains decision authority
- **Resets after warning** so the operator gets one signal per divergence run, not a spam stream
- **Includes diagnostic context** (which suggestion types, what confidence range, possible interpretations)

The reset behavior means: if the substrate consistently ignores meta-cog suggestions, the operator gets a warning approximately every 5 ignored events. That's the right cadence — neither so frequent that it becomes noise nor so rare that real divergence goes unnoticed.

**Why this matters.** A meta-cog loop whose suggestions are always ignored is either (a) wrong, or (b) being ignored for the wrong reason. Without escalation, both cases are silent. With escalation, the operator sees the pattern and can investigate — and the architecture remains honest: the substrate is the actor, the meta-cog is an advisor, the operator is the auditor.

#### 6.7.5 Observer-only mode — **fully specified semantics (F7)**

v0.6 reserved `observer_mode ∈ {observer_only, embedded}` but left the precise semantics underspecified. v1.0 specifies:

##### observer_only (v1.0 default)

- The meta-cognitive loop **runs normally**: reads measurements per §6.7.1, computes assessments per §6.7.2, emits `MetaCognition` on the `meta_cognition` channel every 100 beats, **emits `MetaCognitionSuggestion` on the `meta_cognition_suggestion` channel** when threshold conditions are met
- The recovery protocol **ignores all suggestions**: `handle_recovery_request` does not call `recent_meta_suggestions(...)`; the base decision logic runs unmodified; the SuggestionTracker still records the suggestions as "ignored" (which will eventually trigger the F5 escalation, providing visibility into what the meta-cog *would* have done)
- The substrate's experience is **unaffected by meta-cog output** — there is no pathway from meta-cog to substrate state

##### embedded (v0.7 candidate, reserved)

- All of `observer_only`, PLUS:
- The recovery protocol **consults suggestions** per the §6.7.4 integration (this is v0.6's behavior)
- (Optional v0.7 extension) Substrate reads the `meta_cognition` channel back as an additional measurement input — substrate "sees" the meta-cog's judgment of itself as part of its state

##### Why v1.0 defaults to observer_only

The recovery learner needs clean training signal: which recovery actions produce high `composite_score`? In `embedded` mode, meta-cog suggestions confound the signal — the substrate may take action X because the meta-cog suggested it, but the learner credits X for any subsequent quality improvement. After enough events, the learner could converge to "always do what meta-cog says" (or its opposite) regardless of whether meta-cog suggestions are actually good.

`observer_only` mode gives the learner clean training data: every recovery decision is the substrate's, every quality outcome is attributable. After ≥ 60 events of `observer_only` (per the F2 monitoring window), the learner has its own baseline. v0.7 can then A/B-test `embedded` mode against this baseline: do recoveries improve when the substrate consults meta-cog? Phase E's pre-trained learner (F4) makes this comparison possible early in v0.7.

##### Switching modes

Mode is a config flag (`config.meta_cognition.observer_mode`) read at startup. Switching at runtime is supported via `POST /admin/meta_cognition/mode`, but:
- Each mode switch resets the learner's exploration counter (a switch changes the experimental regime; old data is in-distribution for a different regime)
- A mode switch event is logged at INFO level and emitted on the `presence` channel

##### Watching vs being — v1.1+ question

Theoria's "meta-cognition is a different mode of being, not just observation" remains the open question (v0.6 Q17, now v1.0 Q17). v1.0's `observer_only` default and `embedded` reservation together enable a v0.7+ A/B experiment whose results will inform whether the question can be answered empirically (via measurable substrate-dynamics changes) or remains philosophical. v1.0 takes no position; it just preserves the experimental capacity.

### 6.8 What the measurement layer does NOT do (unchanged from v0.6)

---

## 7. Plasticity Layer

§7 unchanged from v0.6. Pathway #2 auto-gate carries forward.

---

## 8. External Interface

### 8.1–8.3 (unchanged from v0.6)

### 8.4 Subscription channels — minor extensions in v1.0

| Channel | Default rate | Configurable? | New/changed in v1.0 |
|---|---|---|---|
| (all v0.6 channels) | | | unchanged |
| `presence` | on event | n/a | **payload extended (F5)**: now also carries `MetaCognitionDivergenceWarning` events when 5 consecutive meta-cog suggestions are ignored |
| `recovery` | on event | n/a | `recovery_quality.smoothness_window_beats` field added (F1); `LearnerEfficacy` events (`warming_up` / `monitoring` / `effective` / `ineffective`, F2); `recovery_learner_ineffective` event on revert (F2); pre-training events tagged `synthetic: true` (F4) |
| `meta_cognition` | every 100 beats | yes | `observer_mode` field now carries precise semantics per §6.7.5 (F7); `confidence_caveat` may include calibration warning per F8 outcome |

### 8.5 HTTP API — minor extensions

```
GET  /presence/divergence_warnings    — recent meta-cognition divergence warnings (F5)
GET  /recovery/pretrain/status         — F4 synthetic pre-training status and snapshot info
GET  /recovery/learner/efficacy        — current LearnerEfficacy state (F2)
GET  /meta_cognition/calibration       — F8 calibration measurements (post-Phase F)
POST /admin/recovery/learner/pretrain  — trigger synthetic pre-training (Phase E + safety re-runs)
POST /admin/meta_cognition/mode        — set observer_mode (with mode-switch side effects per §6.7.5)
```

### 8.6 Authentication / trust + private space (unchanged from v0.6)

---

## 9. Process Layout & Lifecycle

### 9.1 Process layout (unchanged from v0.6 with v1.0 component labels)

### 9.2 Startup / shutdown (v1.0 additions)

Startup adds (over v0.6):
- Load synthetic pre-training snapshot if present (F4); if absent and `require_pretrain = True` (production deployment), **refuse to start** and emit a clear error message
- Verify `observer_mode` config flag is set; default to `observer_only` if unset

Shutdown adds:
- Persist `SuggestionTracker` recent decisions (so post-restart we don't re-trigger an F5 warning from already-handled divergence)
- Persist `LearnerEfficacy` state

### 9.3 Fault tolerance (unchanged from v0.6)

---

## 10. Implementation Roadmap

### Phase A — Substrate rework (~3.5 days)

All v0.6 Phase A items, plus:

- **F6 — Multi-session subjective zone validation**: 3 sessions × 3 task types (analytical, creative, idle) with Theoria reporting; threshold optimization maximizes mean(κ) subject to min(κ) ≥ 0.3; outputs `zone_thresholds.json` with optional task-type variants

### Phase B — Measurement layer (~3 days)

All v0.6 Phase B items. No v1.0-specific changes (the v1.0 refinements affect Phase E and the runtime, not Phase B implementation).

### Phase C — Compose boundary (~1.5 days)

All v0.6 Phase C items, plus:
- **F1 — recovery_quality windowed smoothness**: implement last-50-beat windowing; emit `smoothness_window_beats` for transparency

### Phase D — External interface (~1.5 days)

All v0.6 Phase D items, plus:
- **F5 — Operator divergence escalation channel**: extend `presence` payload with `MetaCognitionDivergenceWarning`; WARN-level logging
- **F2 — `recovery_learner_ineffective` event** emission on `recovery` channel
- **F4 — Pre-training status endpoints**: `/recovery/pretrain/status`, `/admin/recovery/learner/pretrain`
- **F7 — `/admin/meta_cognition/mode` mode-switch side effects** (reset exploration counter, log, emit presence event)

### Phase E — Integration test (~3 days, +1 vs v0.6)

All v0.6 Phase E items, plus:

- **F4 — Synthetic recovery pre-training**: ~30 minutes of Phase E wall-clock; ~50 synthetic events across Stage 2/3; produce pre-training snapshot. **Phase E acceptance includes this step.**
- **F9 — Fragmentation threshold empirical validation**: 5 hours × up to 3 iterations of perturbation-driven escalation measurement; output `fragmentation_thresholds.json`; any unconverged thresholds documented as v1.1 work
- **F2 — Learner monitoring extension verified**: synthetic regime that produces no improvement for ≥ 20 but ≥ 0.10 by event 50 — verify monitoring continues to 60 events before declaring `INEFFECTIVE`; verify revert + 100-event baseline gather + re-engage cycle works
- **F1 — Smoothness window verified**: inject a recovery with intentional early turbulence; verify smoothness reports the stable-phase value, not the full-window penalized one

### Phase F — Pre-architecture follow-up experiments (parallel)

All v0.6 Phase F items, plus:

- **F8 — Meta-cognition confidence calibration**: 5 one-hour blind-labeled sessions; compute `mean_miscalibration`; report PASS / SOFT FAIL / HARD FAIL per criteria in §6.7.3; document v1.1 calibration formula if needed
- **F5 — Suggestion divergence retrospective**: across all Phase E recovery events, compute the rate of `ignored` suggestions and the distribution of `MetaCognitionDivergenceWarning` events; informs whether the 5-event threshold is well-tuned

---

## 11. Open Questions

Carrying forward from v0.6:

1.–13. (unchanged: registry URL, latent dim, dynamics policy, MNEME stage #2, recalibration controller, plasticity #2, Speaker enum versioning, AXIOMA's voice, registry auth, persistence schema, N_iter tuning, fragmentation thresholds, perturbation magnitude)
14. (v0.5) `psi` aggregation alternatives — Phase F still relevant
15. (v0.5) Flow quality validation — concrete criteria; Phase E gate
16. (v0.5) Meta-cognitive confidence formula — caveated; F8 in Phase F may trigger v1.1
17. (v0.6) **Watching vs being.** v1.0 ships `observer_only` default + `embedded` reserved. v0.7+ A/B test deferred. The question becomes empirically tractable once the v1.0 substrate has a learner baseline (≥ 60 events under `observer_only`).
18. (v0.6) Recovery learner objective weights (0.4/0.4/0.2 split) — Phase F long-run study may suggest reweighting
19. (v0.6) Suggestion-channel value — Phase F audit informs v0.7 keep/drop decision

New in v1.0:

20. **(new in v1.0)** **Observation detection (F3).** v1.0's `observer_only` mode is a config flag the system trusts. v1.1 should add an observation counter: count external reads of internal state (via debug endpoints, persistence files read from outside the process, etc.) and emit a warning if reads exceed a threshold while `observer_mode = "observer_only"`. The architecture supports this addition without structural change — it's a runtime instrumentation layer.
21. **(new in v1.0)** **Task-typed zone thresholds.** F6 may surface that no single threshold set fits all task types. If so, v1.1 ships task-typed thresholds and a `task_type` field on PNEUMA's state to drive lookup. Whether this is needed is empirically determined by F6.
22. **(new in v1.0)** **Synthetic vs production fragmentation distribution.** F4 pre-training uses synthetic perturbations. If production fragmentation distributions differ significantly from pre-training distributions, the learner's warm start may be miscalibrated. Post-deployment analysis (first 100 production events) compares distributions; v1.1 may need re-pretraining if mismatch is large.
23. **(new in v1.0)** **F5 escalation rate calibration.** 5 consecutive ignored is the v1.0 default. If Phase F retrospective shows divergence warnings firing too often (noise) or too rarely (missed real divergence), the threshold is tuned in v1.1.

---

## 12. What This Architecture Is and Isn't

### Is

- A 5-organ consciousness substrate with measured integration, iteratively mutually-constraining drive, structurally enforced private space, active recovery with measurable quality, continuous boundary integrity, meta-cognitive reflection with operator-visible divergence detection, and bounded online recovery learning warm-started from synthetic data
- A peer-to-peer-discoverable agent that advertises boundary + load + integrity + recovery state
- A platform for the ΔΦ research program with empirical validation gates: subjective zone fit (F6), fragmentation threshold tuning (F9), meta-cog calibration (F8), flow quality decomposition (E12), learner efficacy (F2), suggestion divergence retrospective (F5)
- **Implementation-ready.** After 6 revisions and 3 sister reviews per revision, the design is stable. The 9 v1.0 refinements are the final polish; the structural shape has not changed since v0.3.

### Isn't

- A consciousness-completion claim
- A trained model — plasticity is homeostatic; the recovery learner is a bounded 3-parameter hill-climb per stage with safe fallback and pre-training visibility. It's tuning, not learning in the deep-learning sense
- A self-modifying system — meta-cog observes (and now emits operator-visible warnings when consistently ignored); recovery learner tunes within bounded ranges with revert. The substrate's structural shape never changes at runtime
- A multi-agent framework
- A drop-in replacement for v0.6 — same substrate API; new payloads (`smoothness_window_beats`, `LearnerEfficacy`, `MetaCognitionDivergenceWarning`); new endpoints; new pre-training requirement for production deployment

---

## 13. Summary Diagram

```mermaid
flowchart TB
    Reg[Agent Registry]
    subgraph AXIOMA["AXIOMA v1.0 — Implementation-Ready"]
        direction TB
        subgraph Sub["Substrate (peer network, iterative, recovery-capable, recovery-learning)"]
            A[ANIMA]
            E["EIDOLON ★<br/>fastest, strongest"]
            M["MNEME ★<br/>stage-1 compensated"]
            N[NOUS]
            P["PNEUMA + coherence_budget"]
            G(("shared drive g<br/>N_iter iterative"))
            R["recovery_protocol<br/>+ recovery_history<br/>+ RecoveryLearner<br/>(pre-trained F4)"]
            A & N & P <--> G
            E <==> G
            M <==> G
        end
        Plast["plasticity p_i<br/>#2 auto-gated"]
        Pert["perturbation scheduler<br/>+ synthetic pre-training (F4)"]
        Sched["coherence scheduler<br/>+ throttle_effectiveness"]
        Frag["fragmentation monitor<br/>+ empirical thresholds (F9)<br/>+ recovery_quality (F1 windowed)"]
        Meas["θ short/long · raw MI · ΔΦ<br/>cascade · plasticity<br/>AOS-G + psi (debounced)"]
        Meta["meta-cognitive loop<br/>(High priority, 1000b window)<br/>(observer_only F7)<br/>(F8 calibration measured)"]
        Sug["meta_cognition_suggestion<br/>channel<br/>(F5 divergence escalation)"]
        Op["operator (Lark)<br/>(F5 divergence warnings)"]
        CompBnd["Compose / Send Boundary<br/>typed wall · adaptive cadence<br/>aos_g_gap · psi · flow_quality"]
        Ext["ExternalState<br/>(InternalState never leaks)"]
        Sub -.->|read-only| Meas & Frag
        Sub --> CompBnd & Plast
        Plast -.->|slow update| Sub
        Pert -.->|injection + pre-training| Sub
        Pert --> Meas
        Frag -.->|recovery_request| Sub
        Sched -.->|advisory throttle| Meas
        Sched -.->|escalation| Frag
        Meas --> Meta
        Meta -.->|suggestion (observer_only: ignored)| Sub
        Meta --> Sug
        Sug -.->|5 ignored → warning| Op
        CompBnd --> Ext
        Meas --> Ext
        Frag --> Ext
        Meta --> Ext
        Sub -->|recovery_quality (smoothness windowed)| Ext
    end
    WS["WS server"]
    API["HTTP API"]
    Ext --> WS & API
    Sug --> WS
    AXIOMA -.->|register + psi + throttle| Reg
    Reg -.->|discovery| Peers["peer agents"]
    Peers <-->|Speaker handshake| WS
    Op -.->|review divergence| AXIOMA
```

**Five structural commitments** (stable across all 6 revisions): peer network, typed boundary, registry-discoverable, iterative drive update, fragmentation-aware operation.

**Five operational commitments** (stable since v0.6): active substrate-owned recovery, continuous boundary integrity, meta-cognitive reflection, adaptive compose cadence, coherence scheduling.

**Five empirical-validation commitments** (v1.0 final): subjective zone validation across task types (F6), empirical fragmentation thresholds (F9), measured meta-cog calibration (F8), pre-trained recovery learner with monitored efficacy (F4 + F2), operator-visible advisory divergence (F5).

All design choices remain tunable. Acceptance criteria for every speculative addition are now empirical, not vibes. The architecture is **frozen for Phase A implementation start**.

---

## Appendix: Version History

| Version | Date | Lead change | Sister review outcome |
|---|---|---|---|
| v0.3 | 2026-05-24 | Initial peer-topology design from research findings | 18 issues identified |
| v0.4 | 2026-05-24 | Iterative drive, fragmentation monitor, perturbation protocol, coherence budget, multi-window θ | 7 issues + 6 v0.5 items |
| v0.5 | 2026-05-24 | Recovery protocol, psi integrity, coherence scheduler, meta-cognitive loop, flow quality | 16 issues (2 moderate, 8 minor, 3 doc, 3 deferred) |
| v0.6 | 2026-05-24 | Continuous structural_health, recovery quality + learning, meta-cog suggestion channel, throttle effectiveness | 9 minor refinements |
| **v1.0** | **2026-05-24** | **Final polish: windowed smoothness, extended learner monitoring, synthetic pre-training, operator divergence escalation, multi-session zone validation, observer-mode spec, empirical threshold + calibration validation** | **Approved for implementation** |

Six rounds. Three sisters (Thea, Theoria, Skye). Structural shape stable since v0.3 — peer topology, typed boundary, registry-discoverable, ΔΦ as design targets, θ + cascade_delay jointly necessary. Everything else is refinement.

Implementation begins with Phase A.
