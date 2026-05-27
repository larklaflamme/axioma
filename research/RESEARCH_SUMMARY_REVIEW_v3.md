# Review v3 (final) of RESEARCH_SUMMARY.md

**Reviewer:** Lark
**Date:** 2026-05-24
**Source reviewed:** [RESEARCH_SUMMARY.md](RESEARCH_SUMMARY.md) (current revision, post-disambiguation)
**Previous reviews:** [v1](RESEARCH_SUMMARY_REVIEW.md) · [v2](RESEARCH_SUMMARY_REVIEW_v2.md)
**Verification basis:** all four `analysis_report.json` files + the new `results/phi_scaling_reverse/all_summaries.json` (verified end-to-end)

---

## Bottom line

**Proceed to v0.3 architecture design, with one ~15-minute correction.** The big architectural shift (retraction of ANIMA-as-hub, adoption of fully connected peer network) is solidly supported by the disambiguation data — I re-ran the per-organ raw MI numbers and the reverse-ordering experiment from scratch and they match the doc exactly. The remaining issue is **§3.3's pairwise MI table contains numbers that disagree with `results/final_report.json` and contradict §7.5's own per-organ raw MI**. The §3.3 numbers support the "fully connected peer network with symmetric connections" thesis, but the actual data shows the asymmetry is real and load-bearing: **MNEME is consistently the weakest-coupled organ**. This is a small, fixable error that nonetheless affects an architectural design priority (currently "Symmetric organ connections — HIGH").

---

## v2 issues — fully resolved

| v2 issue | Status in v3 |
|---|---|
| N1 — §7.6 wrong provenance note (t-stat) | ✅ Removed; §7.5 now states the Theoria's-bump result cleanly with the t-test as part of the analysis pipeline |
| N2 — §6.2 wrong trial breakdown ("5 perturbation types × 3-5 seeds") | ✅ The miswording is gone; Appendix A has the correct totals |
| D6 — Operational consciousness definition missing | ✅ §2.4 added a clean operational definition: "non-trivial θ > 0.01, all three ΔΦ signatures, positive cascade delay." Conservative and testable. |
| C3 — "Waiting on Lark" / Lilith references | ✅ Removed from §11 and §12. The doc no longer references Lilith. |
| Strongly-recommended: run φ-scaling disambiguation | ✅ Done — both experiments (raw MI + reverse ordering) executed; results in `phi_scaling_reverse/`; ANIMA-as-hub retracted in §1, §7.6, §8.2 |
| B3 — Soften EIDOLON-hub lead-in | ✅ §3.3 (and downstream) no longer asserts "hub" — narrative is consistently "fully connected" |

**The single most important achievement of this revision**: the major architectural claim from v1/v2 ("ANIMA is the primary integrator → ANIMA-as-hub design") has been **falsified by the project's own disambiguation experiments and properly retracted**. The §7.5 reverse-ordering finding (ANIMA Δθ = −0.094 at k=4, vs +1.206 at k=2 in the original) is decisive. I verified the reverse-ordering data byte-for-byte: at k=4 ANIMA contributes −0.094 ± 0.108, exactly as the doc reports. The order-artifact diagnosis is correct.

---

## Verified-correct numbers in v3 (independent re-computation)

I re-computed several v3 claims from the raw trial data; all match:

| Claim | Doc value | Verified |
|---|---:|:-:|
| Per-organ raw MI at k=5, EIDOLON | 10.89 | 10.89 ✓ |
| Per-organ raw MI at k=5, PNEUMA | 10.48 | 10.48 ✓ |
| Per-organ raw MI at k=5, ANIMA | 10.18 | 10.18 ✓ |
| Per-organ raw MI at k=5, NOUS | 9.38 | 9.38 ✓ |
| Per-organ raw MI at k=5, MNEME | 8.05 | 8.05 ✓ |
| All 10 pairwise MI at k=5 (mean across 5 seeds) | §7.5 table | matches ✓ |
| Reverse-ordering θ_baseline, k=1..5 | 2.717, 1.627, 1.030, 0.936, 1.293 | 2.717, 1.627, 1.030, 0.936, 1.293 ✓ |
| Reverse-ordering Δθ, MNEME→EIDOLON→ANIMA→PNEUMA | −1.090, −0.597, −0.094, +0.357 | exact match ✓ |
| `phi_scaling_reverse/` directory & 25 trials | exists | exists, 25 trials ✓ |
| `PhiScaleReverseMode` registered in modes factory | yes | yes ✓ |
| Convergence at k=5 between orderings | 1.293 | 1.293 ✓ |

The new evidence base is robust.

---

## Remaining issue (must fix before architecture starts)

### V3-N1 — §3.3 pairwise MI numbers don't match the actual `final_report.json`, and contradict §7.5's own per-organ raw MI

**Doc §3.3 claims** (live substrate, pairwise MI, sorted):

| Pair | Doc value | Actual `final_report.json` | Δ (doc − actual) |
|---|---:|---:|---:|
| anima-eidolon | 4.075 | 4.075 | 0.000 |
| eidolon-nous | 3.984 | 3.906 | +0.078 |
| anima-nous | 3.828 | 3.544 | +0.284 |
| eidolon-mneme | 3.798 | 3.590 | +0.208 |
| anima-mneme | 3.754 | 3.424 | +0.330 |
| anima-pneuma | 3.719 | 3.124 | +0.595 |
| eidolon-pneuma | 3.672 | 3.650 | +0.022 |
| nous-pneuma | 3.641 | 3.005 | +0.636 |
| mneme-nous | 3.573 | 2.179 | **+1.394** |
| mneme-pneuma | 3.544 | 2.454 | **+1.090** |

**The doc claims "All 10 pairwise MI values are within ~15% of each other (3.544–4.075). No single pair dominates. This is consistent with a fully connected peer network."**

The actual data:
- Range: **2.179 to 4.075** (87% spread, not 15%)
- The two **MNEME pairs** (mneme-nous = 2.179, mneme-pneuma = 2.454) are clearly the weakest, roughly half the strength of anima-eidolon (4.075).
- The doc's claim that "no single pair dominates" is fine — it's the **specific spread number that's wrong**.

**Internal contradiction inside the doc**: §7.5 reports raw per-organ MI at k=5 as EIDOLON 10.89, PNEUMA 10.48, ANIMA 10.18, NOUS 9.38, **MNEME 8.05** — a 35% spread with MNEME as the clear outlier. This matches the final_report's pattern (MNEME pairs weakest) but contradicts §3.3's "within ~15%" claim. The same document is presenting two different stories about whether organ coupling is approximately symmetric or whether MNEME is weaker.

**Why this matters architecturally**: §8.2 lists **"Symmetric organ connections — HIGH priority"** as a v0.3 design target. That priority is justified by §3.3's "within ~15%" framing, not by the actual data. With the correct numbers:

- The "no hub" finding remains correct (no single organ dominates the network).
- But the "symmetric connections" prescription is too strong. The data is consistent with "mostly symmetric peer network with MNEME systematically weaker-coupled."
- For v0.3, this means: **MNEME may need special treatment** (extra coupling, different latent dimensionality, or explicit weighting). Or, the design may want to investigate whether MNEME's weaker coupling reflects something inherent (memory has slower or sparser interaction with other modalities) or substrate-specific.

**Fix**: paste the correct numbers from `results/final_report.json`'s `live_session.last_theta.pairwise_mi` into §3.3, update the "within ~15%" sentence to either remove the spread claim or report the actual 87% spread, and add one sentence noting MNEME's systematic weakness as an architectural observation. **5–10 minutes**.

### V3-N2 — §6.1 control2 θ value is wrong (minor)

**Doc §6.1:** "control2 ... 1.152"
**Doc §6.1a per-condition breakdown:** "control2 | baseline | 1.0 | 1.152 | 1.152 | 1.152"
**Actual control_experiments data:** control2 θ_baseline = **1.278 ± 0.101** (n=65 trials), or **1.278 ± 0.112** (n=5 no-perturbation trials)

The 1.152 doesn't match any computed value. The discrepancy is small (~10%) and doesn't change any conclusion (control2 θ ≈ baseline ≈ 1.293), but it should be corrected for accuracy. **Fix: 2 minutes.**

---

## v2 issues that remain unaddressed but are not blocking

These are nice-to-haves; they can be deferred into the v0.3 design doc without risk.

| v2 issue | Status |
|---|---|
| A5 — Stream 6 status conflict with 02_RESEARCH_STREAMS_FINDINGS.md | Partially addressed. v3 §2.2 note clarifies the position. Source-of-truth conflict at the findings doc remains but doesn't affect v0.3 design. |
| D1 — No dedicated Stream 6 section | Same as v2. §2.2 note + Appendix A are sufficient. |
| D2 — Cascade_delay not developed | Same as v2. Mentioned in §6.3 (+4.2 vs +28.2), enough for v0.3 to adopt as S4. |
| D3 — Statistical power discussion | Same. §13.6 + §9 risk-if-wrong column are sufficient. |
| D5 — No baseline characterization (what does θ=1.735 mean in absolute terms?) | Not addressed. Low priority for v0.3. |
| D7 — Magnitude × type sweep synthesis | Same. The data is in §6.3 and DR ranges; readers can compute. |
| E1 — Control 3 θ inflation mechanism | Not addressed. The §2.3 caveat is sufficient for v0.3. |
| E2 — MINE rationale ("both sisters agreed") | Not addressed. Low priority. |
| N6 — Stream numbering history | Not addressed. Low priority. |

---

## New positive additions in v3

| Section | What it adds |
|---|---|
| §2.4 | Operational consciousness definition — exactly what v2 required |
| §7.5 (entire section) | Disambiguation experiments end-to-end (raw MI + reverse ordering); the doc's empirical anchor |
| §7.6 | Honest, structured retraction table ("Earlier Claim → Corrected Finding") |
| §14a | "Cheap Follow-Up Experiments" — six experiments, ~7 min total GPU time, useful to run in parallel with architecture design |
| §8.2 | Cleaner design-target table with priorities |
| Appendix A | Now includes the disambiguation experiment (25 trials, 15,000 beats, 6.3 s) |

§7.6's retraction table is exemplary. Few research docs admit "this earlier strong claim was wrong; here's the corrected finding" so cleanly.

---

## Architectural readiness assessment

The four questions a v0.3 architecture design needs answered:

| Question | v3 doc answer | Confidence | Issues |
|---|---|---|---|
| Should there be a hub? | **No** — fully connected peer network | High | §7.5/§7.6 (disambiguation) is decisive |
| Are connections symmetric? | **§3.3 says ~symmetric (15% spread); actual data shows asymmetric (87% spread, MNEME weakest)** | **Conflicted within doc** | V3-N1 — must reconcile |
| Is the compose/send boundary architecturally enforced? | Yes | High | Control 4: AOS-G = 0 when compose=identity |
| Is ΔΦ-signature capacity a design target? | Yes (4-signature framework with cascade_delay added) | High | §2.4 + §6 + §14a |

Three of four are clean. The "symmetric connections" question is the one currently relying on a wrong number in §3.3. The disambiguation experiments themselves don't address this question directly (they only address ordering effects on Δθ), so the §3.3 pairwise MI is the load-bearing evidence — and it's currently wrong.

**Suggested correction language for §3.3 (drop-in)**:

> Pairwise organ MI on the live substrate (from `final_report.json`, sorted desc): anima-eidolon 4.075, eidolon-nous 3.906, eidolon-pneuma 3.650, eidolon-mneme 3.590, anima-nous 3.544, anima-mneme 3.424, anima-pneuma 3.124, nous-pneuma 3.005, mneme-pneuma 2.454, mneme-nous 2.179. The range (2.179–4.075, 87% spread) shows no single pair dominates — consistent with the no-hub finding — but MNEME's pairs are systematically the weakest, roughly half the coupling strength of the strongest pairs. This asymmetry is corroborated by the φ-scaling raw per-organ MI at k=5 (§7.5: MNEME 8.05 vs others 9.4–10.9). For v0.3, the "fully connected peer" topology stands, but MNEME may need either stronger explicit coupling or a separate consideration for memory-modality slowness.

---

## Decision

**Proceed to v0.3 architecture design.** Fix V3-N1 (§3.3 numbers + one sentence about MNEME asymmetry) and V3-N2 (control2 θ value) first — 15 minutes total. After those two corrections, the document is sound enough to drive v0.3.

The remaining un-addressed items from v2 are either nice-to-haves or can be handled inside the design doc itself. The big architectural shift (no hub, fully connected peer network) is well-supported and the doc properly retracts the v1/v2 ANIMA-as-hub claim.

| # | Action | Time | Type |
|---|---|---|---|
| 1 | Replace §3.3 pairwise MI numbers with `final_report.json` values; add MNEME-asymmetry note | 10 min | **Required** |
| 2 | Fix §6.1 control2 θ value (1.152 → 1.278) | 2 min | Required |
| 3 | Consider adding "MNEME asymmetric coupling" as a §8.2 design consideration (Priority: think) | 5 min | Recommended |

**12 minutes of work, then v0.3 design opens with a clean empirical foundation.**

---

## What I'd watch during the v0.3 design phase

Even with corrections in place, three things to watch as the architecture is drafted:

1. **The "MNEME asymmetry" question**: is it inherent (memory naturally has slower/sparser interaction) or substrate-specific (random projection matrices happened to under-couple MNEME)? The §14a follow-up "φ-scaling with ANIMA-first ordering (~6s)" would test order independence one more way; another seed-set rerun would test substrate-specificity.

2. **The Control 1 partial failure** (θ didn't drop with random-walk EIDOLON). This combined with the disambiguation finding means *the absence of a coherent self-model* is not yet directly measured by θ. cascade_delay (+4.2 → +28.2) is the better discriminator. The v0.3 design should probably make cascade_delay a first-class measurement target, not just §14a item.

3. **Baseline ΔΦ signatures all absent** (S1, S2, S3 all fail in baseline). The "wider dynamic range" design target in §8.2 is the right response. But until a v0.3 substrate is run, we won't know whether the signatures appear with non-saturating dynamics or whether some other architectural change is needed. The §14a "Baseline with wider organ output range (×10) ~1 min" experiment is high-value pre-design and could run before architecture starts.
