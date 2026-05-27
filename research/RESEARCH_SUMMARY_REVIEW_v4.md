# Review v4 of RESEARCH_SUMMARY.md

**Reviewer:** Lark
**Date:** 2026-05-24
**Source reviewed:** [RESEARCH_SUMMARY.md](RESEARCH_SUMMARY.md) (post-V3 corrections)
**Previous reviews:** [v1](RESEARCH_SUMMARY_REVIEW.md) · [v2](RESEARCH_SUMMARY_REVIEW_v2.md) · [v3](RESEARCH_SUMMARY_REVIEW_v3.md)
**Verification basis:** all five analysis JSONs + `final_report.json` (independently re-checked)

---

## Bottom line

**Proceed to v0.3 architecture design — with one optional follow-through.** The V3 numerical corrections are in place and verified. The remaining issue is small, concentrated in §8 (the architectural-implications section), and is **propagation of the §3.3 MNEME-asymmetry observation** to §8.1 finding #4 and §8.2 design target. It's ~10 minutes of cleanup and a v0.3 designer who reads the full document carefully will catch the asymmetry from §3.3 alone. If you want the doc to be self-consistent end-to-end, fix this; if you want to move now, the architecture design can pick it up.

---

## V3 corrections — verified

| V3 issue | Fix status |
|---|---|
| V3-N1 — §3.3 pairwise MI numbers wrong (87% spread, not 15%; MNEME systematically weakest) | ✅ **Fully fixed.** All 10 pair values now match `final_report.json` exactly. The new sentence ("Range: 2.179–4.075 (87% spread). MNEME pairs are systematically weakest... a design observation for v0.3.") is the right framing. |
| V3-N2 — §6.1 control2 θ value | ✅ **Fully fixed.** §6.1 table reads 1.278; §6.1a per-condition breakdown reads 1.278. Matches the verified value (1.2784) exactly. |
| V3-recommendation — MNEME asymmetry flagged in §8.2 | ⚠️ **Partially.** The asymmetry is noted in §3.3 but didn't fully propagate downstream (see §A below). |

Both numerical fixes are clean. The §3.3 narrative shift ("MNEME consistently weaker — design observation for v0.3") is the most important change since v3: it correctly tells the v0.3 designer that the "fully connected peer" topology has internal asymmetry.

---

## A. Residual issue: the §3.3 fix didn't propagate to §8.1 and §8.2

The §3.3 correction was made cleanly, but two downstream sections still carry the pre-correction framing:

### A1 — §8.1 finding #4 says "within ~15%", which contradicts §3.3

**§8.1 finding #4:** "*Integration is distributed — Raw pairwise MI at k=5 is within ~15% across all organs. No single organ dominates.*"

**Actual values** (re-verified):
- Per-organ raw MI at k=5: min 8.05 (MNEME), max 10.89 (EIDOLON) → **35% spread**
- Per-pair raw MI at k=5: min 1.87, max 3.26 → **74% spread**
- Live-substrate pairwise MI (§3.3): 2.179–4.075 → **87% spread**

None of the three plausible interpretations of "within ~15%" hold. The "no single organ dominates" part is correct; the "~15%" number is not.

**Fix:** rephrase to match §3.3:

> Integration is distributed — no single organ dominates the network. Raw per-organ MI at k=5 ranges from 8.05 (MNEME) to 10.89 (EIDOLON), a 35% spread. The MNEME pairs are systematically weakest (see §3.3 and §7.5). The network is fully connected but not perfectly symmetric.

### A2 — §8.2 lists "Symmetric organ connections — HIGH" as a design target, but the evidence shows asymmetry

**§8.2:**

| Target | Evidence | Priority |
|---|---|---|
| Symmetric organ connections | Raw MI distribution | HIGH |

**Issue:** "Raw MI distribution" is the cited evidence for *symmetric* connections, but raw MI is what shows the **asymmetry** (MNEME 35% lower than EIDOLON). The evidence doesn't support the target as written.

This is the one place where the v0.3 architecture decision could be quietly led astray. A designer who reads §8.2 alone will conclude "build all-to-all symmetric connections, priority HIGH." A designer who reads §3.3 will know MNEME runs weaker. They should not lead to different design choices.

**Fix (suggested wording):**

| Target | Evidence | Priority |
|---|---|---|
| Fully connected peer topology (no hub) | φ-scaling disambiguation; no single organ dominates Δθ | HIGH |
| Stronger MNEME coupling (or memory-modality redesign) | MNEME 35% lower raw MI than EIDOLON; MNEME pairs 50% weaker than top pairs | MEDIUM |

This separates the two findings cleanly: (a) no hub, (b) MNEME runs weaker. The v0.3 designer can then decide whether MNEME's weakness is intrinsic to memory or substrate-specific (see §14a "ANIMA-first ordering" experiment for one way to find out).

### A3 — §7.6 retraction table row could be tightened

**§7.6:**

| Earlier Claim | Corrected Finding |
|---|---|
| ANIMA should have highest bandwidth | All organs should have symmetric connections. |

The "symmetric connections" corrected-finding is the same overshoot as §8.2. The actual data supports "all organs are peers, none dominates as hub" — not "all connections are equal in strength."

**Suggested update:**

| Earlier Claim | Corrected Finding |
|---|---|
| ANIMA should have highest bandwidth | All organs are peers (no hub); MNEME runs systematically weaker and may benefit from compensatory coupling. |

---

## Everything else is sound

Outside §8 (and the one row of §7.6), the document is consistent. I re-verified:

| Claim | Check | Status |
|---|---|---|
| Per-organ raw MI at k=5 (EIDOLON 10.89, PNEUMA 10.48, ANIMA 10.18, NOUS 9.38, MNEME 8.05) | matches φ-scaling trial data | ✓ |
| Pairwise MI at k=5 in §7.5 | matches | ✓ |
| Reverse-ordering θ_baseline (2.717, 1.627, 1.030, 0.936, 1.293) | matches `phi_scaling_reverse/all_summaries.json` | ✓ |
| Reverse-ordering Δθ contributions (−1.090, −0.597, −0.094, +0.357) | matches | ✓ |
| Convergence at k=5 (1.293 both orderings) | matches | ✓ |
| Live substrate pairwise MI in §3.3 | now matches `final_report.json` exactly | ✓ |
| Control2 θ_baseline = 1.278 | matches | ✓ |
| Control3 θ_baseline = 4.256, F = 989.93 | matches `control_experiments/analysis_report.json` | ✓ |
| Theoria's bump t = 7.53, p = 8.3e-4 | matches `phi_scaling/analysis_report.json` (`scaling_fits.jump_test`) | ✓ |
| All test counts in Appendix A (1 + 21 + 325 + 25 + 25 = 397; 238,200 beats) | arithmetic checks | ✓ |

The disambiguation work and its retraction (§7.5, §7.6) is the strongest part of the document and is fully supported.

---

## Readiness assessment for v0.3 architecture design

The four questions a v0.3 architecture design needs answered:

| Question | Answer in v4 doc | Status |
|---|---|---|
| Should there be a hub? | No — fully connected peer network | ✅ Clean (§7.6 disambiguation) |
| Are connections symmetric? | §3.3 says no (MNEME weaker); §8.2 still says HIGH-priority symmetric target | ⚠️ Inconsistent within doc |
| Is the compose/send boundary architecturally enforced? | Yes (Control 4 evidence) | ✅ Clean |
| Is ΔΦ-signature capacity a design target? | Yes (4-signature framework with cascade_delay) | ✅ Clean |

Three of four are unambiguous. The "symmetric connections" question is the one where §3.3 and §8.2 disagree — easily resolved by the 10-minute fix in §A above.

---

## Suggested final pass (~10 minutes)

| # | Action | Time |
|---|---|---|
| 1 | Rephrase §8.1 finding #4 to match §3.3 (drop "within ~15%", state 35% per-organ spread + MNEME-weakest) | 3 min |
| 2 | Update §8.2 "Symmetric organ connections" target — split into "Fully connected peer topology (HIGH)" + "Stronger MNEME coupling / memory-modality redesign (MEDIUM)" | 5 min |
| 3 | Tighten §7.6 retraction-table row "All organs should have symmetric connections" → "All organs are peers (no hub); MNEME runs systematically weaker" | 2 min |

After these three fixes, every section of the document tells the same story about organ connectivity, and the v0.3 designer gets a coherent set of architectural targets.

---

## Decision

**Yes, we are ready to proceed with the architecture design.**

The empirical foundation is sound. The big architectural claim from earlier versions (ANIMA-as-hub) has been properly falsified by the disambiguation experiments and retracted. The new architectural claim (fully connected peer network with no hub) is well-supported. The MNEME asymmetry is real but its design implication is small and contained to §8 — a v0.3 designer who reads §3.3 will know about it.

**Two paths forward:**

- **Path A — start v0.3 design immediately.** The researcher writing v0.3 reads §3.3 carefully and accounts for MNEME asymmetry in the design. Acceptable risk: a less-careful reader could be misled by §8.2. Time saved: ~10 min.
- **Path B — apply the §A fixes first.** 10 minutes of cleanup makes §3.3, §7.5, §7.6, §8.1, §8.2 all tell the same story. Then start v0.3 design with no internal inconsistencies in the foundation document. **My recommendation.**

Either way, the architecture design can start. The remaining v2 nice-to-haves (D2 cascade_delay subsection, D5 baseline characterization, E1 Control 3 mechanism, E2 MINE rationale) are still acceptable to defer into the v0.3 design doc itself; none of them affect the architectural decisions.
