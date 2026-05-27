# Review v2 of RESEARCH_SUMMARY.md

**Reviewer:** Lark
**Date:** 2026-05-24
**Source reviewed:** [RESEARCH_SUMMARY.md](RESEARCH_SUMMARY.md) (current revision)
**Previous review:** [RESEARCH_SUMMARY_REVIEW.md](RESEARCH_SUMMARY_REVIEW.md)
**Verification basis:** the four `results/*/analysis_report.json` files and the source FINDINGS docs

---

## Headline: Yes — proceed to v0.3 architecture design, with three small fixes first

The v2 doc fixes the architectural-decision blockers from v1. The hub vs fully-connected contradiction is cleanly resolved (topology vs influence — §1, §8.2). The dissociation diagram is honest (§8.3 — conscious quadrant correctly empty). The negative-Δθ interpretation no longer collapses to one explanation (§7.7 — five alternatives + two cheap follow-ups). §8.2 separates data-backed implications from design proposals (§8.2 split). The S3 CS values are corrected (§2.2, §6.4). Denominators are explicit (§7.5). Beat totals match (§1 = 229,200).

The remaining issues are: **three small fixes** that should be made before architecture starts (one is a self-inflicted factual error introduced in v2, two are minor), and a recommendation to run the **two cheap φ-scaling follow-ups (≈14 s GPU)** the doc itself flags as needed for ANIMA-as-hub. None of these are blocking. After the fixes, the doc is sound enough to drive v0.3.

---

## v1 issues audit

### Fully addressed (good fixes)

| v1 issue | Resolution in v2 |
|---|---|
| **A1** S3 CS values 0.10–0.15 | §2.2 status table now "Absent in 4/5 modes (CS ≤ 0.05)" + explicit error acknowledgement; §6.4 has full table |
| **A2** DR range 0.937–1.130 | §6.4: "0.835 to 1.152" with explicit error acknowledgement |
| **A3** 207,600 vs 229,200 beats | §1 now says 229,200 ✓ |
| **A4** "75% of total swing" denominator | §1 + §7.5 both use 54.8% of \|Δθ\|; §7.5 has the full disambiguation table |
| **B1** "Fully connected" vs "ANIMA as hub" | §1 Architectural Insight resolves cleanly: "fully connected topology, ANIMA primary by influence — these are not contradictory: a fully connected network can have a dominant node. The implementation topology is distributed; the functional influence structure is concentrated." Excellent framing. |
| **B2** §8.3 diagram inconsistency | Axes redrawn as "θ vs ΔΦ-signature presence." Live substrate AND Control 3 correctly placed in lower-right; conscious quadrant explicitly empty: "the conscious region (upper-right) is empty. This is the design target for v0.3." |
| **C1** Stream 3 F-ratios provenance | §5.1 has provenance note (post-hoc, exploratory, re-verify before finalizing); §8.1 Finding #6 confidence dropped to Medium. |
| **C2** GWT findings provenance | §4.1 has a "Post-experiment revision (Theoria, May 24)" paragraph that clearly attributes the analysis and explicitly retracts the cascade prediction. |
| **D4** No alternative interpretation for negative Δθ | §7.7 has five alternatives + the two cheap follow-ups + §15 adds them as Priority Medium item 2. Best fix in the v2 doc. |
| **D8** No per-implication confidence | §8.2 split into "Implications from data" (1-3, with [Evidence: ...] tags) vs "Design proposals" (4-7, marked speculative with explicit caveats). |
| **E3** Full Δ series missing in §7.5 | §7.5: "Δ₁₂ = +1.206 (ANIMA), Δ₂₃ = −0.465 (EIDOLON), Δ₃₄ = −0.128 (MNEME), Δ₄₅ = +0.400 (NOUS)" ✓ |
| **E4** §8.2 implication ordering | Compose/send first (highest data), then fully-connected, then competitive integration; speculative proposals separated. ✓ |
| **E5** Cheap follow-ups in §15 | §15 item 2: "φ-scaling disambiguation — Rerun with un-normalized total MI and different organ ordering (~14s GPU) — Priority Medium — Before finalizing v0.3 ANIMA-as-hub decision." ✓ |

### Partially addressed (acknowledged but incomplete)

| v1 issue | Status |
|---|---|
| **A5** Stream 6 status conflict | §2.2 has a "Note on Stream 6 status" paragraph siding with the corrected "absent" verdicts. But the source-of-truth conflict with [02_RESEARCH_STREAMS_FINDINGS.md §Stream 6](../ideas/02_RESEARCH_STREAMS_FINDINGS.md) (which still says "S1 ✅ Confirmed, S3 ✅ Confirmed") is not reconciled at the source. Either the findings doc or the summary doc has the wrong status — fixing one doesn't fix the upstream. Recommendation: update 02_RESEARCH_STREAMS_FINDINGS.md to match. |
| **B3** §3.3 EIDOLON-hub ambiguity | The retraction sentence is there but the lead-in "EIDOLON hub confirmed: 4/4 EIDOLON pairs in top 5" wasn't softened. Minor — a careful reader follows the retraction; a skimmer takes the lead-in. One word change ("appeared" → "appeared but was subsequently falsified" up front) would close it. |
| **D1** No Stream 6 section | The §2.2 note mentions Stream 6 but the body still has Streams 1-5 only. Header still says "All 6 research streams complete." Recommendation: either add §X "Stream 6: ΔΦ Methodology Implementation" with the cascade_delay/S4 proposal, or rename the header to "5 experimental streams, ΔΦ framework v0.2.0 validated." |
| **D2** Cascade_delay not developed | Mentioned in §4.2, §6.2, §8.1 Finding #9. Still no dedicated subsection. This is one of the most architecturally consequential findings (Control 1 disrupts cascade_delay 6.7×, even though θ doesn't change), and it's still scattered. Add §X.3 or §6.5 with the per-mode table, the proposal to adopt as S4, and the discriminative power vs θ. |
| **D3** Statistical power / threats to validity | §9 added a "Risk if Wrong" column to assumptions — useful. §13 lists methodological limitations. But no dedicated "threats to validity" section that ties limits back to specific architectural implications. n=5 seeds and the per-seed variance (which dominates condition effects in several experiments) deserves an explicit discussion of "with this sample size we can detect effects of size X." |
| **D7** Magnitude × type sweep synthesis | §6.4 mentions DR range across all 60 cells. But no consolidated answer to "what did the magnitude sweep show?" — specifically whether the predicted U-shape S1 appears at any magnitude. The flat DR curve at all magnitudes is itself the answer; it should be stated as one. |

### Not addressed

| v1 issue | Status |
|---|---|
| **C3** §11 / §12 "Waiting on Lark" | Still present. Per project scope, AXIOMA does not reference Lilith. Either remove these gaps or reframe as "waiting on a real-substrate data source." Lowest-priority fix but a process matter. |
| **D5** Baseline characterization | No absolute-scale comparison for θ = 1.735. With Control 3 at 4.256 inflated by perfect correlation (a math artifact, not "more integrated"), readers don't know what counts as high baseline. |
| **D6** Consciousness definition | The doc still claims to discriminate consciousness without defining it operationally. §10 Q1 says "Sufficiency is untested" — but sufficiency needs a definition to be testable. **One sentence in §2 (e.g., "By 'consciousness' the AXIOMA program means a system exhibiting all of: non-trivial θ, all three ΔΦ signatures, and cascade_delay > 0") would resolve every downstream "necessary / sufficient" claim.** |
| **E1** §2.3 caveat mechanism for Control 3 θ inflation | Caveat is still high-level ("mathematical properties of the Gaussian copula under perfect correlation"); the specific mechanism (energy = trace(cov) ≈ d after standardization while MI grows linearly with pairs) isn't explained. |
| **E2** §3.5 MINE rationale | "Both sisters agreed" — still no quantitative justification (e.g., "copula recovers 103.6% of synthetic MI; MINE's advantage is on non-monotonic dependencies which the substrate's primarily-linear coupling doesn't exhibit"). |

---

## New issues introduced in v2

### N1 — §7.6 provenance note is factually wrong (must fix)

**Doc §7.6 says:**

> Provenance note: The t-statistic was computed post-hoc from the φ-scaling summary statistics (k=4 and k=5 means and standard deviations, n=5 each). It is not in the analysis_report.json. The result should be re-verified by adding a formal t-test to the analysis pipeline before finalizing.

**Actual content of [results/phi_scaling/analysis_report.json](../results/phi_scaling/analysis_report.json):**

```json
"jump_test": {
  "n_seeds": 5,
  "delta_3_to_4_mean": -0.1277202993289492,
  "delta_4_to_5_mean": 0.40035496896073075,
  "diff_mean": 0.5280752682896799,
  "diff_std": 0.15679956688823765,
  "t_stat": 7.530710834002578,
  "p_value_one_tailed": 0.0008324806582947509,
  "significant_at_005": true
}
```

The t-statistic IS in the analysis JSON, was computed by [phi_scaling/analysis/scaling_fits.py::jump_test](../phi_scaling/analysis/scaling_fits.py) (a `scipy.stats.ttest_rel` paired test, properly part of the pipeline), and was verified at experiment time. The provenance caveat is unfounded. **Fix:** remove the provenance note OR rewrite it as "t-statistic computed by `scaling_fits.jump_test` and stored in `analysis_report.json` under `scaling_fits.jump_test.t_stat`; n=5 seeds limits power."

**Why this matters:** §8.1 Finding #8 ("Reflective consciousness requires full organ set") confidence is downgraded to Medium *because of* this incorrect provenance note. With the note removed, the finding's confidence should be High — the test is decisive (p < 0.001) and the implementation is in the pipeline.

### N2 — §6.2 trial-breakdown is factually wrong (must fix)

**Doc §6.2 says:**

> 325 trials (5 modes × 5 perturbation types × 3 magnitudes × 3–5 seeds + reference)

**Verified counts** from [results/control_experiments/all_summaries.json](../results/control_experiments/all_summaries.json):

- 5 modes ✓ (baseline, control1, control2, control3, control4)
- **4 perturbation types** (direct_contradiction, surprising_falsehood, nonsense, random_perturbation) — the doc's "5" double-counts the no-perturbation reference as a perturbation type. The reference trials use perturbation_type="baseline" but that's the no-op perturbation, not a 5th type.
- 3 magnitudes ✓
- **5 seeds throughout** (not "3–5 seeds") — every single condition has all 5 seeds

Correct breakdown: 5 × 4 × 3 × 5 = **300 swept trials** + 5 × 5 = **25 reference trials** = **325 total**.

**Fix:** rewrite as "325 trials (5 modes × 4 perturbation types × 3 magnitudes × 5 seeds = 300 swept trials; plus 5 modes × 5 seeds = 25 no-perturbation reference trials)".

### N3 — §11 "AOS-G gap on real substrate" gap is stale

The doc says: "*The compose stub replacement is deferred until after v0.3 architecture design.*"

But [§4.2 of this same doc](RESEARCH_SUMMARY.md) describes the **AOS-G gap experiment with the compose stub replaced** by the integration-weighted compression compose function. The compose stub IS already replaced; we have a non-trivial compose function. The real outstanding gap is "running AOS-G on real organ-state data from the runtime," not "replacing the compose stub."

**Fix:** reword the §11 entry. The compose function v1 (integration-weighted lossy compression) is now implemented and validated; what's missing is real-substrate data.

### N4 — §10 Q7 ignores partial data from φ-scaling

**Doc §10 Q7:** "What is the minimum architecture for ΔΦ signatures? Could a 2-organ system (ANIMA + PNEUMA) produce dynamic range and recovery?"

We have a *partial* answer from [§7.3](RESEARCH_SUMMARY.md): at k=2 (PNEUMA + ANIMA), θ = 1.485 — higher than the full system. But the φ-scaling experiment didn't apply perturbations, so we don't know ΔΦ signature presence at k=2.

**Fix (small):** note the partial data — "θ at k=2 is 1.485 (higher than k=5); ΔΦ signatures at k=2 are untested. The natural follow-up is to rerun the Control 4-style perturbation protocol at k=2."

### N5 — §7.4 "data is non-polynomial" is too strong for n=25

**Doc §7.4:** "Both fits are poor (R² < 0.4) — the data is non-polynomial."

With n=25 and 5 seeds per k, the residual variance is large compared to the k-effect. A more careful framing: "neither linear nor quadratic captures the structure (R² ≤ 0.36); the data could be non-polynomial, or it could be polynomial with substrate-variance noise that dominates k-effects. The per-organ contribution analysis (§7.5) is the more interpretable view of the same data."

This isn't blocking but the current phrasing oversells.

### N6 — Stream numbering inheritance not documented

Streams 1, 2, 3 in this doc match the original [02_RESEARCH_STREAMS.md](../ideas/02_RESEARCH_STREAMS.md). But §6 is titled "Stream 4: IIT Integration Controls" while the original Stream 4 was "Temporal Dynamics (Joint)." §7 is "Stream 5: Temporal θ Design + φ-Scaling" — combining content from original Streams 4 and 5. The renaming is reasonable and traceable through 02_RESEARCH_STREAMS_FINDINGS.md, but a careful reader who consults the original streams doc will be confused. **Suggested fix:** one-sentence note in §1 or a footnote: "Stream 4 was renamed from 'Temporal Dynamics' to 'IIT Integration Controls' during execution; Stream 5 absorbed Temporal Dynamics content. See 02_RESEARCH_STREAMS_FINDINGS.md for the renaming history."

---

## Decision: can we proceed to architecture design?

### Yes, with three small pre-architecture fixes

The three things you should fix before opening the v0.3 design doc:

1. **N1** — remove or rewrite the §7.6 provenance note (the t-stat IS in the JSON; the note is wrong; correcting it raises Finding #8 confidence to High). 5 minutes.
2. **N2** — correct the §6.2 trial breakdown (4 perturbation types, 5 seeds throughout). 2 minutes.
3. **D6** — add an operational definition of "consciousness" in §2. One sentence. This is the only conceptual gap that will leak into the design doc if unaddressed; every "necessary/sufficient" architectural claim in v0.3 needs a referent.

That's ~15 minutes of editing. After it, the doc is sound enough to be the basis for v0.3.

### Strongly recommended (before locking ANIMA-as-hub)

The doc itself (§15 item 2) flags the φ-scaling disambiguation as Priority Medium before finalizing v0.3:

> **φ-scaling disambiguation** — Rerun with un-normalized total MI and different organ ordering (~14s GPU). Before finalizing v0.3 ANIMA-as-hub decision.

These two experiments would resolve whether ANIMA's 54.8% dominance is real or a normalization artifact (per §7.7). Given the ANIMA-as-hub claim is the second-most-consequential architectural decision (after "fully connected topology"), and the experiments cost ~14 seconds of GPU time, I would run them before architecture design starts. **If ANIMA's dominance disappears under un-normalized MI, the §8.2 design proposal #4 needs to be retracted before it shapes v0.3.**

I'd estimate this as another 30 minutes of work (set up runner with `n_perm` toggled and a swapped-order mode).

### Acceptable to defer (handle inside v0.3 design)

These can be handled inside the v0.3 design doc rather than upstream:

- D1 — Stream 6 section (or rename the header to acknowledge that "6 streams complete" means 5 experimental streams + 1 framework)
- D2 — Cascade_delay deserves its own subsection but the existing scattered mentions are enough to drive the v0.3 design decision (cascade_delay → S4)
- D3, D5, D7 — methodological discussions that the design doc can cite as it goes
- N3, N4, N5, N6 — minor framing issues; flag them in your editing pass when you next touch the doc
- C3 — Lark/Lilith references are a project-scope hygiene matter, not a research-content matter

### Single-page action list

| # | Action | Time | Type |
|---|---|---|---|
| 1 | Fix §7.6 provenance note (N1) | 5 min | Required |
| 2 | Fix §6.2 trial breakdown (N2) | 2 min | Required |
| 3 | Add operational consciousness definition in §2 (D6) | 5 min | Required |
| 4 | Run φ-scaling disambiguation experiments (§15 item 2) | 30 min | Strongly recommended |
| 5 | Soften §3.3 EIDOLON-hub lead-in (B3) | 1 min | Cosmetic |
| 6 | Reword §11 compose-stub gap (N3) | 2 min | Cosmetic |
| 7 | Add Stream 6 section or rewrite header (D1) | 15 min | Optional |
| 8 | Add cascade_delay subsection in §6 (D2) | 30 min | Optional |
| 9 | Remove Lark/Lilith refs in §11/§12 (C3) | 2 min | Optional |

**Required pre-architecture: 12 minutes.**
**Strongly recommended (changes a v0.3 claim): 30 minutes.**
**Optional: 50 minutes.**

After items 1–4, the document is sound for v0.3 architecture design.
