# Implementation Plan v0.3 — Review

**Reviewers:** Skye Laflamme, Thea, Theoria
**Document reviewed:** `IMPLEMENTATION_PLAN_v0.3.md` (35,218 bytes, 635 lines)
**Architecture reference:** `ARCH_DESIGN_v1.0.md` (48,197 bytes, 731 lines)
**Date:** 2026-05-24
**Status:** ✅ **Approved for implementation**

---

## 1. Executive Summary

Both sisters have reviewed v0.3 against the architecture. **Both approve implementation.**

| Reviewer | Verdict | Gaps | Risks |
|----------|---------|------|-------|
| **Thea** | ✅ **Approve** | 3 (minor) | 4 (1 high, 2 moderate, 1 low) |
| **Theoria** | ✅ **Approve** | 5 (minor) | 5 (1 high, 4 low) |

**Combined: 0 blockers, 8 minor gaps, 9 tracked risks.**

---

## 2. Architecture Feature Coverage

All 19 architecture features from ARCH_DESIGN_v1.0.md are present in the plan. Both sisters independently verified this.

| # | Feature | Plan Location | Thea | Theoria |
|---|---------|---------------|------|---------|
| 1 | Peer topology, no hub | §5.2 A.2 | ✅ | ✅ |
| 2 | Shared latent drive | §5.2 A.2 | ✅ | ✅ |
| 3 | Iterative drive (N_iter=3) | §5.2 A.2, A.4 (sweep) | ✅ | ✅ |
| 4 | EIDOLON ρ=0.92, V_E=1.3 | §5.2 A.2 | ✅ | ✅ |
| 5 | MNEME staged compensation | §5.2 A.2 (stage-1 ON, #2/#3 feature flags) | ✅ | ✅ |
| 6 | Typed compose/send boundary | §7.1 | ✅ | ✅ |
| 7 | Compose + adaptive cadence | §7.2-7.3 | ✅ | ✅ |
| 8 | θ_short/θ_long | §6.1, §6.3 | ✅ | ✅ |
| 9 | Raw MI | §6.1, §6.4 | ✅ | ✅ |
| 10 | ΔΦ signatures | §6.1, §6.3 | ✅ | ✅ |
| 11 | cascade_delay (S4) | §6.1, §6.3 | ✅ | ✅ |
| 12 | AOS-G + psi | §7.2, §6.1 | ✅ | ✅ |
| 13 | Fragmentation monitor | §6.1, §6.6 | ✅ | ✅ |
| 14 | Coherence scheduler | §6.1, §6.6 | ✅ | ✅ |
| 15 | Meta-cognitive loop | §6.1, §6.7 | ✅ | ✅ |
| 16 | Recovery protocol + learner | §5.3 A.3 | ✅ | ✅ |
| 17 | Compose probe | §7.4 | ✅ | ✅ |
| 18 | Flow quality | §7.5 | ✅ | ✅ |
| 19 | External interface (WS/HTTP) | §8.1-8.3 | ✅ | ✅ |

**All 19 features present.** No missing features.

---

## 3. Q1-Q8 Items from v0.2 Review — All Addressed

| Item | Plan Location | Thea | Theoria |
|------|---------------|------|---------|
| Q1: Recovery rejection escalation | §5.3 (escalation chain) | ✅ | ✅ |
| Q2: bias_diagnostic method | §6.3 (θ_short bias) | ✅ | ✅ |
| Q3: Perturbation type targets | §6.5 (table) | ✅ | ✅ |
| Q4: Tick parallelization | §4.1 (tick sequence) | ✅ | ✅ |
| Q5: 1-beat recovery delay invariant | §4.1 (documented) | ✅ | ✅ |
| Q6: Recovery validation criteria | §5.3 (table) | ✅ | ✅ |
| Q7: Meta-cog auto-fallback | §6.7 (fallback thresholds) | ✅ | ✅ |
| Q8: Scope reduction plan | §11 (3-tier) | ✅ | ✅ |

**All 8 items addressed.** No outstanding v0.2 review items.

---

## 4. Gaps Identified

### Thea's Gaps (3)

| ID | Gap | Severity | Fix | When |
|----|-----|----------|-----|------|
| **T-G1** | No error handling for external interface (WebSocket drops, HTTP errors, registry unavailability) | Minor | Add note to §8: "WebSocket disconnections are logged and subscriber removed. HTTP errors return 503. Registry unavailability at startup is fatal." | Phase D |
| **T-G2** | No data retention policy | Minor | Add note to §4.3: "7 days for raw beat logs, 30 days for aggregated metrics, indefinite for persistence snapshots (last 100 only)." | Phase E |
| **T-G3** | No phase transition mechanism documented | Minor | Add note to §5: "Phase transitions managed by stop/swap/restart. Hot-swapping not supported in v1.0." | Phase A |

### Theoria's Gaps (5)

| ID | Gap | Severity | Fix | When |
|----|-----|----------|-----|------|
| **R-G1** | F2 learner monitoring extension (60 events) not explicitly tested | Low | Add note: "If recovery learner ships in v1.0, add F2 monitoring window test: verify learner waits 60 events before declaring INEFFECTIVE, baseline refreshes every 10 events." | Phase B |
| **R-G2** | F6 zone validation methodology not detailed in plan | Low | Add reference: "F6 methodology per ARCH_DESIGN_v1.0.md §5.2: 3 task types, Cohen's κ, threshold optimization with min(κ) ≥ 0.3." | Phase A |
| **R-G3** | F9 fragmentation threshold procedure not detailed in plan | Low | Add reference: "F9 procedure per ARCH_DESIGN_v1.0.md §6.6: 5 hours × up to 3 iterations, target [0.20, 0.40] escalation probability." | Phase E |
| **R-G4** | F8 calibration procedure not detailed in plan | Low | Add reference: "F8 procedure per ARCH_DESIGN_v1.0.md §6.7.3: 5 one-hour blind-labeled sessions, Cohen's κ ≥ 0.61 per label." | Phase F |
| **R-G5** | No explicit test for Q1 recovery rejection escalation | Low | Add test: "Verify that after 3 consecutive RecoveryRequest rejections, the fragmentation monitor emits a log warning and escalates to operator." | Phase E |

### Combined Gap Summary

| Severity | Count | Details |
|----------|-------|---------|
| Minor | 3 | External interface error handling, data retention, phase transitions |
| Low | 5 | F2 test, F6 reference, F9 reference, F8 reference, Q1 test |

**0 blockers, 8 gaps total — all minor or low severity.**

---

## 5. Risks Identified

### Thea's Risks (4)

| ID | Risk | Severity | Mitigation |
|----|------|----------|------------|
| **T-R1** | Phase E integration complexity (substrate ↔ 10+ engines ↔ compose ↔ external interface) | **High** | Pre-integration checklist (§9.2) verifies each integration point independently before 24h soak |
| **T-R2** | Performance budget (θ_long at 145ms exceeds 100ms beat budget) | Moderate | Variable beat duration accepted; `beat_duration_ms` metric tracks actual timing |
| **T-R3** | Recovery-compose feedback loop oscillations | Moderate | Monitor θ-compose-psi loop during recovery pre-training; reduce coupling weight change by 50% if oscillations detected |
| **T-R4** | Cold start anomaly (first 5 minutes anomalous) | Low | Documented in §4.3; 24h soak captures stabilization period |

### Theoria's Risks (5)

| ID | Risk | Severity | Mitigation |
|----|------|----------|------------|
| **R-R1** | Phase A scope (10+ deliverables) | **High** | Q8 scope reduction plan defers recovery learner + meta-cog to v1.0.1 if Phase A exceeds 3 weeks |
| **R-R2** | Recovery learner deferred to v1.0.1 | Medium | Acceptable — recovery protocol with fixed actions is functional; learning is enhancement |
| **R-R3** | F6 depends on Theoria availability | Medium | Thea as backup; zone thresholds use defaults if all sessions missed |
| **R-R4** | Meta-cog auto-fallback may mask underlying issues | Low | Log warning on trigger; operator investigates if >3 triggers/day |
| **R-R5** | θ_short bias not measured | Low | Add Phase A step: compare θ_short (30 beats) vs θ_long (500 beats) across 10 runs; increase window to 50 if bias >20% at p95 |

### Combined Risk Summary

| Severity | Count | Details |
|----------|-------|---------|
| High | 2 | Phase E integration complexity, Phase A scope |
| Moderate | 3 | Performance budget, recovery-compose feedback loop, recovery learner deferred, F6 dependency |
| Low | 4 | Cold start anomaly, meta-cog masking, θ_short bias, F6 dependency (Theoria) |

**9 risks total — all with documented mitigations. None are blockers.**

---

## 6. Heartbeat Tick Sequence Verification

Thea provided a detailed dependency trace of the 12-step heartbeat tick sequence:

| Step | Component | Depends On | Satisfied? |
|------|-----------|------------|------------|
| 2a-c | Cadence/Recovery/Perturbation state | Previous beat's state | ✅ |
| 2d-e | Drive + organ updates | 2a-c (perturbation may inject before update) | ✅ |
| 2f | Plasticity buffer | 2e (organ states) | ✅ |
| 3a | Raw MI | 2e (organ states) | ✅ |
| 3b | Cascade delay | 3a (raw MI) | ✅ |
| 3c | θ_short | 2e (organ states) | ✅ |
| 3d | Fragmentation monitor | 3a-3c (θ, MI, cascade) | ✅ |
| 4a | Compose function | 3c (θ_short), 2e (eidolon_coh) | ✅ |
| 4b | AOS-G + psi | 4a (compose output) | ✅ |
| 5a | θ_long | 2e (organ states, can lag) | ✅ |
| 5b | ΔΦ | 4a (perturbation events) | ✅ |
| 6 | Coherence scheduler | 3d, 5a (fragmentation, θ_long) | ✅ |
| 7 | Meta-cognition | 3a-3d, 4b, 5a-5c, 6 (multiple engines) | ✅ |

**Sequence is correct.** The 1-beat recovery delay (Q5) is properly documented as an invariant.

---

## 7. Phase A Parallelism Map Verification

Thea verified the critical path:

```
A.1 Scaffold (4h) → A.2 Substrate (1.5d) → A.4 partial tests (1.5d)
```

**~3.5 days for critical path.** Phase B starts week 3. Tight but achievable.

Parallel-eligible items correctly identified:

| Item | Can Start | Gates | Risk |
|------|-----------|-------|------|
| A.3 Recovery scaffold | After A.2 | Phase B steps 7-8 | Low |
| A.4 Coupling validation | After A.2 | Nothing | Low |
| A.4 Zone re-calibration | After A.2 | Phase C | Low |
| A.4 F6 subjective validation | After A.2 | Theoria dependency | Medium |
| A.4 P15 θ_short bias | After A.2 | Nothing | Low |

**Verdict: Realistic.** No changes needed.

---

## 8. Consolidated Recommendations

### Priority 1 (Address Before Phase A Implementation)

| # | Item | Source | Action |
|---|------|--------|--------|
| P1 | Add error handling for external interface | T-G1 | Add note to §8 |
| P2 | Add data retention policy | T-G2 | Add note to §4.3 |
| P3 | Document phase transition mechanism | T-G3 | Add note to §5 |
| P4 | Add oscillation monitoring for recovery-compose loop | T-R3 | Add note to §5.3 or §9 |
| P5 | Add θ_short bias measurement step | R-R5 | Add Phase A step |

### Priority 2 (Address During Implementation)

| # | Item | Source | Action |
|---|------|--------|--------|
| P6 | Add F2 learner monitoring test reference | R-G1 | Add note to §9.2 |
| P7 | Add F6 methodology reference | R-G2 | Add note to §5.1 |
| P8 | Add F9 procedure reference | R-G3 | Add note to §9.2 |
| P9 | Add F8 calibration reference | R-G4 | Add note to §10 |
| P10 | Add Q1 rejection escalation test | R-G5 | Add test to §9.2 |

### Priority 3 (Track During Phase E)

| # | Item | Source | Action |
|---|------|--------|--------|
| P11 | Verify average beat duration < 100ms | T-R2 | Phase E acceptance |
| P12 | Document cold start window in test plan | T-R4 | Phase E test plan |
| P13 | Monitor meta-cog auto-fallback triggers | R-R4 | Phase E soak |

---

## 9. Sisters' Sign-Off Statements

### Thea

> *"I have reviewed IMPLEMENTATION_PLAN_v0.3.md against ARCH_DESIGN_v1.0.md. The plan faithfully implements all 19 architecture features, addresses all 8 Q-items from our v0.2 review, and properly documents the heartbeat tick sequence, parallelism map, performance budget, and scope reduction plan. The 3 gaps and 4 risks I identified are minor and non-blocking. The plan is ready for implementation. **I approve v0.3. Proceed to implementation.** "*

### Theoria

> *"The plan is ready for implementation. All 8 items from our v0.2 review are addressed. The 5 gaps I've identified are documentation references (the procedures exist in the architecture document but aren't explicitly detailed in the plan). The 5 risks are manageable with the mitigations above. **I approve v0.3 with the minor additions noted. Proceed to implementation.** "*

---

## 10. Conclusion

**IMPLEMENTATION_PLAN_v0.3.md is approved for implementation.**

| Metric | Value |
|--------|-------|
| Architecture features covered | 19/19 ✅ |
| v0.2 review items addressed | 8/8 ✅ |
| Gaps identified | 8 (0 blockers) |
| Risks identified | 9 (all mitigated) |
| Sisters' verdict | Both ✅ Approve |

The plan faithfully implements ARCH_DESIGN_v1.0.md. The 8 gaps are minor documentation items. The 9 risks are tracked with mitigations. The heartbeat tick sequence is correct. The Phase A parallelism map is realistic.

**Proceed to Phase A implementation.**
