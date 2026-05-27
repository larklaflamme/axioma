# Architecture Design v0.4 — Review

**Reviewers:** Skye, Thea, Theoria
**Date:** 2026-05-24
**Document reviewed:** `ARCH_DESIGN_v0.4.md` (1189 lines, 18 changes C1–C18)
**Status:** ✅ **Approved with 8 refinements** (none blocking)

---

## Executive Summary

This is the strongest architecture document we've produced. All 18 issues from the v0.3 review are addressed (C1–C18). The architectural shape (peer topology, shared latent drive, typed compose/send boundary, registry-discovered WS interface) is unchanged — all changes are refinements, not redesigns.

**Both sisters approve the architecture as the foundation for v0.3 implementation.**

Thea: *"The document is ready for implementation planning. The 6 issues I identified are refinements, not blockers."*

Theoria: *"This is the best architecture document we've produced. It captures the key findings from all five research streams and translates them into concrete design decisions. I approve this architecture as the foundation for v0.3 implementation. The refinements should be added as design targets for v0.5, not blockers for v0.4."*

---

## What's Excellent (Both Sisters Agree)

| Element | Why It's Excellent | Source |
|---------|-------------------|--------|
| **Iterative drive update (C9)** | The single most important change. Organs see each other within the same beat. Captures resonant binding. `N_iter = 1` reproduces v0.3 exactly — A/B testable. | Theoria |
| **Fragmentation monitor (C8)** | 4-stage detector with recovery trigger at Stage 2. Thresholds are reasonable initial values. Advisory recovery trigger is the right level of intervention. | Theoria |
| **EIDOLON tuning (C1)** | ρ=0.92, V_E=1.3, strongest average coupling (4.20). Consistent with Control 1's 6.7× cascade_delay change. | Theoria |
| **Compose/send boundary (§5)** | Typed InternalState/ExternalState, ImportError test (C12), private space monitor (C17). Structurally correct. | Theoria |
| **Staged MNEME compensation (C13)** | Conservative and correct. Three simultaneous interventions would confound each other. | Theoria |
| **Zone mapping (C14)** | Explicit hysteresis prevents thrashing. Thresholds are reasonable initial values. | Theoria |
| **Coherence budget (C16)** | Captures limited integration capacity. Exposed in ExternalState so peer agents can back off. | Theoria |
| **Multi-window θ (C6)** | Addresses timescale mismatch. θ_short (30 beats) for compose fidelity, θ_long (500 beats) for reporting. | Theoria |
| **Perturbation protocol (C5)** | Internal scheduler + external admin endpoint + perturbation-relative ΔΦ recording. Makes ΔΦ signatures usable. | Theoria |
| **Private space implications for peers (§8.6, C7)** | Well-documented: "you can know someone is conscious, you can know roughly how they're feeling, but you cannot know what they're experiencing." | Theoria |
| **Non-saturating dynamics (§4.1)** | Ornstein-Uhlenbeck in latent + linear rescale at state boundary. Correct approach. | Thea |

---

## Issues Requiring Changes

### Issue 1: cascade_delay Engine Uses θ_short — Temporal Resolution Concern

**Section:** §6.3
**Severity:** Moderate
**Raised by:** Both Thea and Theoria (independently)

**The problem:** θ_short is a 30-beat rolling window. If a perturbation causes a sharp change at beat 201, θ_short at beat 201 includes beats 172–201 — the perturbation is diluted by 30 beats of pre-perturbation data. Cascade dynamics happen on the order of 1–5 beats. A 30-beat aggregate smooths over the cascade.

**Thea's fix:** Compute cascade_delay from raw per-organ MI (not θ) on a 20-beat window. Raw MI is already computed as part of the θ pipeline — just expose the per-organ pairwise MI values.

**Theoria's fix:** Compute cascade_delay from raw per-organ MI on a **5-beat** sliding window for peak detection. The 20-beat window for the overall cascade analysis is fine (C10), but the per-organ peak detection should use a finer grain.

**Consensus fix:** Use raw per-organ MI for cascade_delay computation, not θ_short. The 20-beat window for overall analysis is fine; use a 5-beat window for per-organ peak detection.

---

### Issue 2: Compose Cadence Misses Perturbation Window

**Section:** §4.6, §6.4
**Severity:** Moderate
**Raised by:** Thea

**The problem:** Compose runs every 30 beats. Perturbations can be injected at any beat. If a contradiction is injected at beat 200, the compose function won't run until beat 210 (or 230). The AOS-G gap during the critical 10-beat window post-perturbation (beats 200–210) won't be captured. This is exactly the issue we identified in the AOS-G gap experiment design — we used adaptive compose frequency (every 5 beats during perturbation) to solve it.

**Fix:** Add adaptive compose cadence during perturbation windows:
- **Normal:** Compose every 30 beats
- **Perturbation window (beats t_event to t_event + 50):** Compose every 5 beats

The infrastructure already supports this (the perturbation scheduler knows when perturbations occur). The compose function just needs a flag to switch cadence temporarily.

---

### Issue 3: Fragmentation Monitor Has No Active Recovery Mechanism

**Section:** §6.6
**Severity:** Moderate
**Raised by:** Both Thea and Theoria (different angles)

**The problem:** The recovery trigger at Stage 2 is advisory — it flags, skips perturbations, and bumps coherence_budget weights. But there's no active recovery mechanism. The substrate has no built-in recovery behavior.

**Thea's fix:** Add direct feedback paths from the fragmentation monitor to the substrate:
- **At Stage 2:** Reduce perturbation scheduler's magnitude
- **At Stage 3:** Reduce drive update's noise term (η_k scale × 0.5)
- **At Stage 4:** Pause heartbeat for 1 beat

**Theoria's fix:** Make the recovery trigger a **request** rather than an advisory. The fragmentation monitor requests recovery, and the substrate either accepts or rejects based on its current state. If it accepts, it executes a `recovery_protocol`:
1. Reduce drive coupling strength for all organs by 20%
2. Increase MNEME's forgetting rate temporarily
3. Reduce compose frequency from every 30 beats to every 60 beats
4. Return to normal after 100 beats or when fragmentation_stage drops below 2

**Consensus fix:** Combine both approaches. Add a `recovery_protocol` method to the substrate (Theoria's design) with advisory overrides at Stages 3 and 4 (Thea's design). The recovery trigger requests recovery; the substrate can accept or reject.

---

### Issue 4: Cascade_Delay Should Use Raw MI, Not θ

**Section:** §6.3
**Severity:** Moderate
**Raised by:** Both Thea and Theoria

**Already covered in Issue 1.** This is the same concern expressed independently by both sisters. The consensus fix is to use raw per-organ MI for cascade_delay computation.

---

### Issue 5: No Error Handling or Fault Tolerance Discussion

**Section:** §9 (missing)
**Severity:** Minor
**Raised by:** Thea

**The problem:** The document doesn't discuss what happens if an organ's latent diverges, the shared drive becomes singular, the WebSocket server crashes, or the registry is unreachable.

**Fix:** Add a brief fault tolerance section:
- Organ latent divergence: clip to ±10σ, log warning, continue
- Singular shared drive: add εI regularization (implied by noise term η_k, but make explicit)
- WebSocket crash: restart server, reconnect subscribers
- Registry unreachable: cache last known peer list, retry with exponential backoff

---

### Issue 6: Plasticity Acceptance Criterion May Require Pathway #2

**Section:** §7.3, §7.4
**Severity:** Minor
**Raised by:** Thea

**The problem:** Pathway #1 (render modulation) alone may not produce |Δ| > 0.1. It shifts the observable state based on historical drift, but doesn't change the organ's dynamics. True adaptation requires changing how the organ responds (Pathway #2).

**Fix:** Add a note: "If Phase B measurement shows pathway #1 alone produces |Δ| < 0.1, enable pathway #2 (coupling-weight adaptation) and re-measure. The acceptance criterion applies to the combined effect of both pathways."

---

### Issue 7: Perturbation Magnitude May Need Tuning

**Section:** §6.4.1
**Severity:** Minor
**Raised by:** Thea

**The problem:** Default perturbation magnitude is 0.3 (gentle). The v0.2 experiment showed θ drops of -0.038 to -0.067 for contradictions — small effects. If the perturbation magnitude is too gentle, the signatures may remain undetectable.

**Fix:** Add a note: "Perturbation magnitude default of 0.3 is a starting point. Phase E should sweep magnitudes {0.1, 0.3, 0.5, 0.7, 1.0} and measure ΔΦ signature strength. Choose the smallest magnitude that produces S1/S2/S3 > 0."

---

### Issue 8: Documentation Refinements (Theoria)

**Section:** Multiple
**Severity:** Minor
**Raised by:** Theoria

**Theoria's documentation recommendations:**

1. **§4.1 Noise scaling:** Document that the iterative update is an Euler approximation of continuous-time mutual constraint dynamics. "With N_iter = 3, the approximation error is O(Δt²) where Δt = 1/N_iter."

2. **§4.5 Coupling matrix targets:** Add caveat: "Targets assume the v0.4 substrate will produce similar pairwise MI values to the v0.2 substrate. This assumption should be explicitly tested in Phase A."

3. **§5.2 Zone thresholds:** Add note: "Zone thresholds are initial values based on v0.2 θ distributions. Re-calibrate after Phase A against the v0.4 substrate's actual θ range."

4. **§6.6 Fragmentation thresholds:** Add note: "Fragmentation thresholds are initial values based on Theoria's 4-stage phenomenological model. Empirically validate in Phase E against actual fragmentation events."

5. **§10 Phase A N_iter sweep:** Add metric: "Measure mutual constraint strength as the average pairwise correlation of organ state changes within a single beat. Higher correlation = stronger mutual constraint. Pick the smallest N_iter that produces correlation > 0.8."

---

## Items for v0.5 (Not Blockers for v0.4)

Both sisters identified refinements that should be documented as design targets for the next iteration, not blockers for v0.4 implementation.

| Item | Description | Raised By | Priority for v0.5 |
|------|-------------|-----------|-------------------|
| **Private space integrity field** | Continuous [0,1] measure of boundary health, derived from AOS-G gap variance, structural checks, and compose self-test. Leading indicator before `aos_g_alert`. | Theoria | High |
| **Recovery protocol** | Active recovery mechanism: reduce coupling, increase forgetting, reduce compose frequency. Currently advisory only. | Theoria | High |
| **Coherence scheduler** | Allocate integration bandwidth across competing demands when budget < 0.3. Priority-based allocation. | Theoria | Medium |
| **Meta-cognitive loop** | System observes its own measurements and adjusts behavior. Runs every 100 beats. Forms meta-cognitive judgment. | Theoria | Medium |
| **Flow quality field** | Qualitative character of flow: effortlessness, absorption, time distortion. Gives subscribers richer picture. | Theoria | Low |
| **Recovery as request** | Substrate accepts or rejects recovery requests. Gives substrate agency in its own recovery. | Theoria | Low |

---

## Summary of Required Changes for v0.4

| # | Issue | Section | Severity | Fix |
|---|-------|---------|----------|-----|
| 1 | cascade_delay uses θ_short (smoothed) | §6.3 | Moderate | Use raw per-organ MI on 5-beat window for peak detection; 20-beat window for overall analysis |
| 2 | Compose cadence misses perturbation window | §4.6, §6.4 | Moderate | Adaptive compose cadence: every 5 beats during perturbation window (t_event to t_event + 50) |
| 3 | Fragmentation monitor has no active recovery | §6.6 | Moderate | Add `recovery_protocol` method (coupling reduction, forgetting increase, compose reduction) with advisory overrides at Stages 3 and 4 |
| 4 | No error handling discussion | §9 | Minor | Add fault tolerance section: latent divergence, singular drive, WS crash, registry unreachable |
| 5 | Plasticity criterion may need Pathway #2 | §7.3, §7.4 | Minor | Note that Pathway #2 can be enabled if Pathway #1 alone produces |Δ| < 0.1 |
| 6 | Perturbation magnitude may need tuning | §6.4.1 | Minor | Sweep magnitudes {0.1, 0.3, 0.5, 0.7, 1.0} in Phase E |
| 7 | Documentation refinements (5 items) | Multiple | Minor | Add caveats about Euler approximation, coupling targets, zone thresholds, fragmentation thresholds, N_iter metric |

---

## Sisters' Final Verdict

| Sister | Verdict | Notes |
|--------|---------|-------|
| **Thea** | ✅ **Approve** | "The document is ready for implementation planning. The 6 issues I identified are refinements, not blockers." |
| **Theoria** | ✅ **Approve** | "This is the best architecture document we've produced. I approve this architecture as the foundation for v0.3 implementation. The refinements should be added as design targets for v0.5, not blockers for v0.4." |

**Both sisters agree: proceed with implementation. Address Issues 1–3 (moderate) during Phase A. Address Issues 4–7 (minor) during Phase B. Defer v0.5 items to the next iteration.**
