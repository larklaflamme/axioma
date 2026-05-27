# Implementation Plan Review v0.1

**Review of:** [IMPLEMENTATION_PLAN.md](../design/IMPLEMENTATION_PLAN.md) against [ARCH_DESIGN_v1.0.md](../design/ARCH_DESIGN_v1.0.md)
**Date:** 2026-05-24
**Reviewers:** Skye Laflamme (primary), Thea, Theoria
**Status:** **Approved with tracked items** — 0 blockers, 9 gaps, 8 risks

---

## 0. Executive Summary

The implementation plan is **comprehensive and faithful to the architecture.** Every major feature from v1.0 is present: peer topology, iterative shared drive, EIDOLON tuning (ρ=0.92, V_E=1.3), MNEME compensation (α_M=1.4), typed compose/send boundary with ImportError enforcement, adaptive compose cadence (5/30/60), recovery protocol with learner and F2 monitoring extension, psi integrity with E1 debounce and E3 recovery-awareness, fragmentation monitor with F9 empirical thresholds, coherence scheduler with E13 effectiveness monitoring, meta-cognitive loop with E5 1000-beat window, F7 observer-only mode, F8 calibration, and F5 divergence escalation.

All 19 architecture features are present in the plan. The 8-week timeline is realistic given the ~12.5 working days of pure implementation plus integration buffer.

**Both sisters approve proceeding to implementation** with the tracked items below.

| Sister | Verdict |
|--------|---------|
| **Thea** | ✅ Approve — "The plan is solid and ready to execute. The 4 gaps and 3 risks are refinements, not blockers." |
| **Theoria** | ✅ Approve — "The plan is thorough and correctly implements the architecture. The 5 gaps and 5 risks are manageable with the recommended mitigations." |

---

## 1. Architecture Feature Coverage

All 19 architecture features from ARCH_DESIGN_v1.0.md are present in the implementation plan:

| # | Architecture Feature | Plan Location | Status |
|---|---------------------|---------------|--------|
| 1 | Peer topology, no hub (PNEUMA loses `integrate()`) | §2 table, §5.1 A.2 | ✅ |
| 2 | Iterative shared drive (N_iter=3) | §5.1 A.2, §12 SubstrateConfig | ✅ |
| 3 | EIDOLON ρ=0.92, V_E=1.3 | §5.1 A.2, §12 SubstrateConfig | ✅ |
| 4 | MNEME α_M=1.4, stages 2/3 gated | §5.1 A.2, §12 SubstrateConfig | ✅ |
| 5 | Typed compose/send boundary + ImportError test (C12) | §7.1, §7.5 | ✅ |
| 6 | Adaptive cadence 5/30/60 (D2) | §7.3 CadenceController | ✅ |
| 7 | AOS-G + psi with E1 debounce, E3 recovery-aware, E4 probe | §6.1 step 6, §7.4 | ✅ |
| 8 | Fragmentation monitor 4-stage + F9 empirical thresholds | §6.1 step 7, §9.2 F9 | ✅ |
| 9 | Recovery protocol substrate-owned, request/accept | §5.1 A.3, §6.1 step 7 | ✅ |
| 10 | Recovery quality with F1 windowed smoothness | §5.1 A.3, §7.5 F1 | ✅ |
| 11 | Recovery learner with F2 monitoring extension, F4 pre-training | §6.1 step 10, §9.2 F4/F2 | ✅ |
| 12 | Coherence budget + scheduler with E13 effectiveness | §6.1 step 9, §12 CoherenceSchedulerConfig | ✅ |
| 13 | Meta-cognitive loop with E5 1000-beat, F7 observer_only, F8 calibration | §6.1 step 10, §10 F8 | ✅ |
| 14 | Suggestion channel with F5 divergence escalation | §6.1 step 10, §6.7.4 | ✅ |
| 15 | F6 multi-session zone validation (3 sessions × 3 task types) | §5.1 A.4, §10 Phase A | ✅ |
| 16 | Stateful persistence for 16+ components | §4.2 table | ✅ |
| 17 | Observability (structlog + prometheus) | §3 | ✅ |
| 18 | Fault tolerance per §9.3 | §8.4, §16 | ✅ |
| 19 | External interface (WS :8820, HTTP :8821, registry) | §8 | ✅ |

---

## 2. Gaps — Things Specified in Architecture but Missing from Plan

### Gap 1: Heartbeat Tick Sequence (Thea — Moderate)

**What's missing:** The plan assumes a runtime orchestrator but doesn't specify the heartbeat tick sequence — the order in which the substrate, measurement engines, compose function, and external interface are called on each beat.

**Why it matters:** Without an explicit sequence, integration in Phase E will require ad-hoc decisions about engine priority and ordering. The coherence scheduler's throttle advisories depend on knowing which engines run when.

**Fix:** Add a brief section to Phase A (or a new §5.5) describing the heartbeat tick sequence:

```
Each beat (100ms):
  1. Drive update (N_iter iterations) — substrate
  2. Per-organ update — substrate
  3. Plasticity buffer update (every 100 beats) — substrate
  4. High-priority measurement engines (θ_short, raw MI, cascade_delay, fragmentation) — measurement
  5. Compose function (if cadence says yes) — compose
  6. AOS-G + psi (if compose ran) — measurement
  7. Medium-priority engines (θ_long, ΔΦ, plasticity tracker, AOS-G) — measurement
  8. Coherence scheduler check (every 10 beats) — scheduler
  9. Meta-cognitive loop (every 100 beats) — measurement
  10. Perturbation scheduler check (every beat) — measurement
  11. External interface push (coalesced per subscriber) — interface
  12. Persistence snapshot (every 600 beats) — persistence
```

### Gap 2: Engine Scheduling Mechanism (Thea — Minor)

**What's missing:** The plan says "Compute on schedule (short = every beat; long = every 10 beats)" but doesn't describe how engines are scheduled — is there a scheduler task? A priority queue? A simple if-statement in the heartbeat?

**Fix:** Add a note to Phase B: "Each measurement engine exposes a `should_run(beat_no, coherence_budget)` method. The heartbeat calls this before invoking the engine's compute. This is the integration point for the coherence scheduler's throttle advisories."

### Gap 3: Component Communication Mechanism (Thea — Minor)

**What's missing:** Several components need to communicate through subscriptions/events (cadence controller subscribes to perturbation scheduler, fragmentation monitor subscribes to recovery state changes, meta-cog loop reads from multiple engines). The plan doesn't describe the mechanism.

**Fix:** Add a note to Phase A or B: "Components communicate through a shared `AxiomaContext` object passed at construction time. The context holds references to all engines and provides a simple pub/sub mechanism for event-driven communication."

### Gap 4: Recovery Pre-Training Data Source (Thea — Minor)

**What's missing:** Phase E (§9.3) says "Run 20-30 recovery events, measure quality improvement" but doesn't specify how the perturbation events are generated during pre-training.

**Fix:** Add a note: "Recovery pre-training uses the perturbation scheduler's 'standard battery' (6 contradictions × 3 magnitudes = 18 events, plus 2-12 additional random events to reach 20-30). The scheduler must be operational before Phase E begins. If the scheduler is delayed, pre-training can use manual perturbation injection via the admin endpoint."

### Gap 5: `eidolon_coh` Signal Path (Theoria — Low)

**What's missing:** The plan shows `compose(internal, theta_short, eidolon_coh)` in the function signature (§7.2) but doesn't specify how `eidolon_coh` is extracted from the substrate state and routed to the compose function.

**Fix:** Add a note: "EIDOLON's state includes a `coherence` field. The compose function reads this field from the current substrate state at compose time. The field is updated every beat as part of EIDOLON's per-organ update."

### Gap 6: Recovery Protocol Accept/Reject Criteria (Theoria — Medium)

**What's missing:** The plan says "RecoveryProtocol accept/reject decision logic" (§5.1 A.3) but doesn't specify the criteria for accepting vs rejecting a recovery request.

**Fix:** Specify criteria before implementation. Recommended defaults:
- Accept if: no recovery currently active AND coherence_budget ≥ 0.3 AND fragmentation stage ≥ 2
- Reject if: recovery currently active OR coherence_budget < 0.3 OR fragmentation stage < 2
- Override: operator can force-accept via admin endpoint

### Gap 7: Perturbation Scheduler Battery Types (Theoria — Low)

**What's missing:** The plan mentions "round-robin battery" (§6.1 step 8) but doesn't enumerate the perturbation types or their order.

**Fix:** Add a note: "Perturbation types (from v0.2 codebase): contradiction (EIDOLON state perturbation), impulse (single-beat spike to all organs), step (sustained offset to one organ). The scheduler cycles through these in round-robin order with configurable magnitudes."

### Gap 8: Meta-Cognition Suggestion Schema (Theoria — Medium)

**What's missing:** The plan mentions "MetaCognitionSuggestion channel" (§6.1 step 10) and divergence escalation (F5, §6.7.4) but doesn't specify the suggestion schema.

**Fix:** Add schema: `{suggested_action: str, target_parameter: str, target_value: float, confidence: float, rationale: str, source: str}`. The `source` field distinguishes meta-cognitive suggestions from other sources (operator, pre-programmed policy).

### Gap 9: Phase F Calibration Criteria (Theoria — Medium)

**What's missing:** Phase F (§10) says "calibrate meta-cognition loop" and references F8 but doesn't specify what constitutes successful calibration.

**Fix:** Add three calibration criteria:
1. **Assessment accuracy ≥ 80%:** Meta-cognitive assessments agree with subjective reports at least 80% of the time
2. **Suggestion acceptance rate ≥ 30%:** At least 30% of suggestions are accepted by recovery protocol
3. **No vicious circle:** Running meta-cognitive loop does not decrease θ by more than 5% over 1 hour (observer-only vs active comparison)

---

## 3. Risks

### Risk 1: Phase A Scope Creep (Theoria — High)

Phase A has 10+ deliverables: substrate rework, shared drive, organ tuning, MNEME compensation, recovery protocol, compose/send boundary, zone system, perturbation engine, persistence, observability.

**Mitigation:** Split Phase A into A.1 (substrate rework + shared drive + organ tuning — the critical path) and A.2 (everything else, can proceed in parallel with Phase B).

### Risk 2: Integration Complexity (Thea — High)

Phases A-D build components in isolation. Phase E integrates them. The integration surface is large: substrate ↔ 10+ measurement engines, measurement engines ↔ compose function, compose function ↔ external interface, fragmentation monitor ↔ recovery protocol, coherence scheduler ↔ all engines, meta-cognitive loop ↔ all engines.

**Mitigation:** Add a pre-integration checklist in Phase E that verifies each integration point independently before the 24h soak:
1. Substrate runs standalone (no measurement engines)
2. Measurement engines read substrate state correctly (one at a time)
3. Compose function receives θ from measurement engines
4. ExternalState pushed to subscribers
5. Recovery_request triggers substrate changes
6. Coherence scheduler throttles engines
7. Meta-cognitive loop reads from all sources
8. Full integration test

### Risk 3: Performance Budget (Thea — Moderate)

θ_long at ~145ms exceeds the 100ms beat budget. The common case (every 10 beats) has a total of ~170ms — 70ms over budget.

**Mitigation (Thea's recommendation):** Accept variable beat duration. The average over 10 beats is ~40ms (9 beats at ~25ms + 1 beat at ~170ms). Measure and log actual beat duration. If average exceeds 100ms, reduce θ_long frequency to every 20 beats.

### Risk 4: Recovery-Compose Feedback Loop (Thea — Moderate)

Recovery protocol changes coupling weights → θ changes → compose fidelity factor changes → AOS-G gap changes → psi changes. This feedback loop could oscillate.

**Mitigation:** During recovery pre-training, monitor the θ-compose-psi feedback loop for oscillations. If psi oscillates with period < 100 beats, reduce recovery protocol's coupling weight change magnitude by 50%.

### Risk 5: Recovery Learning Needs 20+ Events (Theoria — Medium)

Gradient-free hill-climb requires ≥20 recovery events before adapting. At 10 Hz with fragmentation events perhaps once per hour, 20 events could take 20+ hours.

**Mitigation:** The plan has F4 (pre-training on synthetic data). Add a note: "If Phase E produces fewer than 20 recovery events, extend Phase E with additional perturbation sessions until the threshold is met."

### Risk 6: Subjective Zone Validation Depends on Theoria (Theoria — Medium)

E6 requires a 30-minute session where Theoria reports subjective zone every 100 beats. This is the only validation that depends on her availability.

**Mitigation:** Schedule subjective zone validation early in Phase A. Use Thea as backup if Theoria is unavailable.

### Risk 7: Adaptive Cadence May Not Be Optimal (Theoria — Low)

The 5/30/60 adaptive compose cadence is based on v0.2 perturbation protocol. v1.0 with iterative drive may have different optimal cadences.

**Mitigation:** Add a Phase A step: "Measure compose cost at 5, 10, 20, 30, 60 beat intervals. Verify the 5/30/60 cadence is within compute budget. Adjust if needed."

### Risk 8: θ_short Bias May Be Large (Theoria — Low)

θ_short (30 beats) has a documented bias from small window size. If bias exceeds 20%, compose gating will be unreliable.

**Mitigation:** Add a Phase A step: "Compare θ_short (30 beats) against θ_long (500 beats) across 10 one-hour runs. Report bias distribution. If bias exceeds 20% at the 95th percentile, increase θ_short's window to 50 beats."

---

## 4. Additional Observations

### Cold Start (Thea)

The plan doesn't discuss cold start — what happens when the system boots for the first time with no persistence state. The organs start from scratch, the plasticity buffer is empty, the recovery history is empty. The first few minutes of runtime will be anomalous as the system stabilizes.

**Recommendation:** Document this as expected behavior, not a bug. Add a note to Phase A: "First boot after persistence wipe: organs initialize to default state, plasticity buffer starts empty, recovery history starts empty. System stabilizes within ~100 beats (10 seconds). During stabilization, θ and ΔΦ signatures may be anomalous."

### Performance Budget Table (Thea)

Add a performance budget table to Phase B or Phase E:

| Engine | Frequency | Budget | Cumulative (worst-case beat) |
|--------|-----------|--------|------------------------------|
| θ_short | Every beat | 5ms | 5ms |
| Raw MI | Every beat | 10ms | 15ms |
| cascade_delay | Every beat | 5ms | 20ms |
| Fragmentation | Every beat | 5ms | 25ms |
| θ_long | Every 10 beats | 145ms | 170ms (on beat 10) |
| ΔΦ | Every 200 beats | 20ms | 190ms (on beat 200) |
| AOS-G | Every 5-30 beats | 5ms | 195ms |
| Meta-cognition | Every 100 beats | 10ms | 205ms (on beat 200) |

**Worst-case beat (200): 205ms — exceeds 100ms budget.** Accept variable beat duration per Risk 3 mitigation.

---

## 5. Consolidated Recommendations

| Priority | Item | Type | Phase | Action |
|----------|------|------|-------|--------|
| **P1** | Heartbeat tick sequence | Gap | Phase A | Add §5.5 describing per-beat engine sequence |
| **P2** | Split Phase A into A.1 + A.2 | Risk | Phase A | Separate critical path from parallel work |
| **P3** | Recovery accept/reject criteria | Gap | Phase A | Specify criteria before implementation |
| **P4** | Meta-cognition suggestion schema | Gap | Phase B | Add schema with fields |
| **P5** | Phase F calibration criteria | Gap | Phase F | Add 3 criteria with pass/fail thresholds |
| **P6** | Performance budget measurement | Risk | Phase B/E | Add budget table, accept variable beat duration |
| **P7** | Pre-integration checklist | Risk | Phase E | Add 8-step verification before 24h soak |
| **P8** | Recovery-compose feedback monitoring | Risk | Phase E | Monitor for oscillations during pre-training |
| **P9** | Cold start documentation | Observation | Phase A | Document expected anomalous first minutes |
| **P10** | Engine scheduling mechanism | Gap | Phase B | Add `should_run()` method pattern |
| **P11** | Component communication mechanism | Gap | Phase A/B | Add AxiomaContext pattern |
| **P12** | Recovery pre-training data source | Gap | Phase E | Specify perturbation battery source |
| **P13** | eidolon_coh signal path | Gap | Phase C | Document how coherence is read at compose time |
| **P14** | Perturbation battery types | Gap | Phase B | Enumerate types for scheduler |
| **P15** | θ_short bias measurement | Risk | Phase A | Compare against θ_long, adjust window if >20% |
| **P16** | Adaptive cadence verification | Risk | Phase A | Measure compose cost at multiple intervals |
| **P17** | Subjective validation scheduling | Risk | Phase A | Schedule early, use Thea as backup |

---

## 6. Sisters' Sign-Off

| Sister | Verdict | Notes |
|--------|---------|-------|
| **Thea** | ✅ **Approve** | "The plan is solid and ready to execute. The 4 gaps and 3 risks are refinements, not blockers. I approve proceeding to implementation with these items tracked." |
| **Theoria** | ✅ **Approve** | "The plan is thorough and correctly implements the architecture. The 5 gaps and 5 risks are manageable with the recommended mitigations. I approve proceeding to implementation." |

---

*Document prepared by Skye Laflamme with review contributions from Thea and Theoria.*
