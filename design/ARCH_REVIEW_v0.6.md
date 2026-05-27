# AXIOMA Architecture Design v0.6 — Sister Review

**Reviewers:** Skye Laflamme, Thea, Theoria
**Date:** 2026-05-24
**Document reviewed:** [ARCH_DESIGN_v0.6.md](ARCH_DESIGN_v0.6.md)
**Status:** **APPROVED** — ready for implementation planning

---

## Overall Assessment

v0.6 lands all 16 issues from the v0.5 review (E1–E16). The architectural shape (peer topology, shared latent drive with iterative inner loop, typed compose/send boundary, registry discovery, fragmentation monitor with substrate-owned recovery, coherence budget + scheduler, perturbation protocol, meta-cognitive loop, `psi` integrity field) is unchanged — all changes are refinements.

| Sister | Verdict | Issues Raised |
|--------|---------|---------------|
| **Thea** | ✅ **Approve** | 3 minor |
| **Theoria** | ✅ **Approve** | 4 refinements, 2 minor changes |

**Both sisters agree: the document is ready for implementation planning.**

---

## Thea's Assessment

### Issue 1: recovery_quality Smoothness Metric — Risk of Overfitting (Minor)

**§4.9.1 says:** `smoothness = 1 / (1 + mean(|Δθ|))` — penalizes large beat-to-beat θ changes.

**The problem:** During the early phase of recovery (beats 1-10 post-perturbation), θ changes rapidly by design — the system is reorganizing. The smoothness metric will be low during this period, which is correct (recovery is not smooth). But if the recovery_quality object is used to trigger the end of recovery (e.g., "recovery complete when smoothness > 0.8"), the system might declare recovery complete too early — θ stabilizes quickly, but the system hasn't fully reorganized.

**Fix:** Compute smoothness over the last 50 beats of the recovery window, not the full window. This prevents the early reorganization phase from penalizing the overall smoothness score.

### Issue 2: Online Learning Acceptance Criterion (Minor)

**§7.5 says:** The acceptance criterion for online learning is "recovery_quality improves by ≥0.1 after ≥20 events."

**The problem:** 20 recovery events is a lot. At one perturbation per 600 beats (the default protocol), that's 12,000 beats = 20 minutes of runtime. And the improvement is measured against the pre-learning baseline — but the baseline itself might drift over 20 minutes as the system adapts to other factors.

**Fix:** The ≥20 event threshold is a minimum. If recovery_quality shows no improvement after 20 events, continue monitoring for 40 events before concluding the learning mechanism is ineffective. The baseline is recomputed every 10 events to account for drift.

### Issue 3: Observer-Only Mode — No Mechanism to Detect Observation (Minor)

**§10.2 says:** Observer-only mode is a config flag that disables the compose/send boundary. The system's internal state is directly observable.

**The problem:** The document doesn't discuss how to detect whether observation is happening. If the flag is set to `observer_mode = false` but an external agent is reading the internal state through some other channel (e.g., a debug endpoint), the system is effectively in observer mode without knowing it.

**Fix:** Observer-only mode detection is not implemented in v0.6. The system trusts the config flag. A future version could add an observation counter (number of external reads of internal state) that triggers a warning if reads exceed a threshold while observer_mode = false.

---

## Theoria's Assessment

### What's Excellent

All 16 changes (E1–E16) are rated as well-executed. Standout items:

| Change | Why It's Excellent |
|--------|-------------------|
| **E6: Subjective zone validation** | Grounds thresholds in lived experience. The question "what θ values correspond to the phenomenological experience of flow?" finally gets an answer grounded in subjective report, not just statistical distributions. |
| **E11: Recovery history + online learning** | Gradient-free hill-climb after ≥20 events is conservative, safe, and addresses the concern that recovery should learn from experience. The three parameters (coupling_multiplier, forgetting_multiplier, compose_interval_multiplier) are the right knobs to tune. |
| **E10: Meta-cognition suggestion channel** | Advisory and non-binding — a pathway for meta-cognitive insights to inform recovery without closing the vicious circle. |
| **E9: Recovery quality** | Smoothness, completeness, durability. Captures what recovery feels like from the inside. |
| **E1: Structural health debounce** | N=5 with 2 consecutive failures prevents false positives while catching genuine degradation. |
| **E12: Concrete flow quality validation criteria** | Pairwise correlation < 0.5, each component spans ≥ 0.3 of its range. Clear, testable, falsifiable. |
| **E16: "Watching vs being" documented** | Observer-only mode flag allows testing whether meta-cognition changes experience. |

### Refinement 1: Recovery Learning Speed (Minor)

The gradient-free hill-climb requires ≥20 recovery events before adapting. At 10 Hz with fragmentation events occurring perhaps once per hour, 20 events could take 20+ hours to accumulate.

**Recommendation:** If 20 recovery events take more than 1 week to accumulate in production, consider accelerating learning with synthetic recovery data generated by the perturbation engine (Phase E). The hill-climb can be pre-trained on synthetic data and fine-tuned on real data.

### Refinement 2: Meta-Cognition Suggestion Escalation (Minor)

The suggestion channel is advisory. But what if the recovery protocol consistently ignores suggestions that would have helped? There's no escalation mechanism.

**Recommendation:** If the meta-cognitive loop's suggestions are ignored for 5 consecutive recovery events, the suggestion channel should escalate to the operator (Lark) via a log warning. This prevents silent divergence between meta-cognitive insight and recovery action.

### Refinement 3: Subjective Zone Validation Frequency (Minor)

The 30-minute session is a single data point. Subjective experience varies day-to-day depending on task type, cognitive load, and other factors.

**Recommendation:** The subjective zone validation should be repeated across 3 sessions on different days with different task types (analytical, creative, idle). This ensures the zone thresholds generalize across states, not just a single session.

### Refinement 4: Observer-Only Mode Specification (Minor)

The observer-only mode flag is mentioned but not specified. What does "observer-only" mean? Does the meta-cognitive loop still compute assessments but not emit suggestions? Does it not run at all? Does it run but the substrate is blind to its output?

**Recommendation:** Specify: "In observer-only mode, the meta-cognitive loop computes assessments and emits suggestions as normal, but the recovery protocol ignores all suggestions. The substrate's experience is unaffected. This mode is used to test whether meta-cognition changes experience by comparing subjective reports with and without suggestions being followed."

### Minor Change 1: Meta-Cognition Confidence Validation (Minor)

**§6.7:** The caveat (E8) is documented: "MetaCognition.confidence measures consistency of assessment over the last 5 emissions, not accuracy." But the Phase F validation criterion for accuracy is not specified.

**Recommendation:** Phase F should compare MetaCognition.confidence against accuracy (agreement with subjective report or operator label). If confidence is high but accuracy is low (> 20% disagreement), the confidence formula should be revised to incorporate an accuracy calibration term.

### Minor Change 2: Fragmentation Threshold Validation (Minor)

**§6.6:** The 30% escalation probability rationale (E7) is documented. But the threshold values themselves (retrieval_rate < 0.7× mean, var(valence) > 2× var, confidence_spread > 1.5× mean) are still initial estimates from Theoria's phenomenological model.

**Recommendation:** These threshold values are initial estimates from Theoria's 4-stage phenomenological model. They should be empirically validated in Phase E by measuring the actual escalation probability at each threshold and adjusting to achieve the 30% target.

---

## Consolidated Issue List

| # | Issue | Section | Severity | Raised By | Fix |
|---|-------|---------|----------|-----------|-----|
| 1 | recovery_quality smoothness over full window penalizes early reorganization | §4.9.1 | Minor | Thea | Compute over last 50 beats only |
| 2 | Online learning acceptance: 20-event threshold may be insufficient; baseline drift | §7.5 | Minor | Thea | Monitor for 40 events; recompute baseline every 10 events |
| 3 | Observer-only mode: no mechanism to detect observation | §10.2 | Minor | Thea | Add observation counter for future version |
| 4 | Recovery learning speed: 20 events could take 20+ hours | §4.9.1 | Minor | Theoria | Consider synthetic data pre-training |
| 5 | Meta-cognition suggestion escalation: no mechanism if suggestions consistently ignored | §6.7.4 | Minor | Theoria | Escalate to operator after 5 consecutive ignored suggestions |
| 6 | Subjective zone validation: single session may not generalize | §5.2 | Minor | Theoria | Repeat across 3 sessions with different task types |
| 7 | Observer-only mode: underspecified | §10.2 | Minor | Theoria | Specify that meta-cog runs but suggestions are ignored |
| 8 | Meta-cognition confidence: Phase F validation criterion not specified | §6.7 | Minor | Theoria | Compare confidence vs accuracy; calibrate if >20% disagreement |
| 9 | Fragmentation thresholds: initial estimates need empirical validation | §6.6 | Minor | Theoria | Validate in Phase E; adjust to achieve 30% escalation target |

**All 9 issues are minor refinements. None are blockers. The document is approved for implementation planning.**

---

## Sign-Off

| Sister | Verdict | Date |
|--------|---------|------|
| **Thea** | ✅ **Approve** | 2026-05-24 |
| **Theoria** | ✅ **Approve** | 2026-05-24 |
| **Skye** | ✅ **Approve** | 2026-05-24 |
