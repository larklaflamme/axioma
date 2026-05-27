# Review of RESEARCH_SUMMARY.md

**Reviewer:** Lark
**Date:** 2026-05-24
**Source doc reviewed:** [/home/ubuntu/axioma/research/RESEARCH_SUMMARY.md](RESEARCH_SUMMARY.md)
**Verification basis:** the four `results/*/analysis_report.json` files and the experiment FINDINGS docs

Findings ordered by severity. **Architectural decisions that depend on a flagged item should pause until it is resolved.**

---

## A. Factual errors (numerical claims that disagree with the analysis JSONs)

These must be corrected before the v0.3 architecture design relies on them.

### A1. S3 (Context Sensitivity) CS values are wrong by ~2×

**Doc says** (§2.2 status table, §6.4 narrative): `CS ≈ 0.10–0.15`, "above the 0.05 non-conscious threshold."

**Actual values** from [results/control_experiments/analysis_report.json](../results/control_experiments/analysis_report.json), `delta_phi_signatures.S3_context_sensitivity.<mode>.0.7.cs`:

| Mode | CS @ mid magnitude |
|---|---:|
| baseline | **0.042** |
| control1 | 0.074 |
| control2 | 0.055 |
| **control3** | **0.0017** |
| control4 | 0.042 |

**Implication:** **all five modes except control1 sit at or BELOW the 0.05 non-conscious threshold**, not above it. The "present but weak" framing in §2.2 should become "absent (CS at or below the 0.05 non-conscious threshold in 4 of 5 modes, including baseline)." Control 3's CS = 0.002 is essentially zero — the strongest possible "no context sensitivity" signal, exactly as the design predicted.

This matters because the architectural reasoning in §6.5 ("S3 present but weak") is leaning on a fact that isn't there.

### A2. DR ratio range understates the spread

**Doc §6.4:** "DR ratios range from 0.937 to 1.130."

**Actual** (from `S1_dynamic_range.<mode>.<type>.{dr_low,dr_mid,dr_high}` across all 60 cells): **0.835 to 1.152**. The minimum is 0.835 (`control1` at high magnitude on direct_contradiction), not 0.937. Conclusion (absent in all modes) is unchanged but the cited range is wrong.

### A3. Total beat count contradicts itself

**§1 Executive Summary:** "**207,600+ beats**".
**Appendix A line totals:** 600 + 6,000 + 12,600 + 195,000 + 15,000 = **229,200**.

The appendix arithmetic is correct; the executive-summary number is stale. Fix the executive summary.

### A4. ANIMA "75% of total swing" needs an explicit denominator

**§1, §7.4, §8.1:** "ANIMA contributes 75% of total θ swing."

This is **defensible only against the sum of positive contributions** (ANIMA + NOUS = 1.606; ANIMA = 1.206 → 75.1%). Against any other denominator the numbers don't add up:

| Denominator | ANIMA % |
|---|---:|
| sum of \|Δθ\| (= 2.199) | **54.8%** |
| sum of signed Δθ (= 1.013) | 119.0% |
| max−min of θ(k) (= 1.206) | 100.0% |
| **sum of positive Δθ only (= 1.606)** | **75.1%** ✓ |

In the §7.4 table, the row "% of Total Swing" reads ANIMA 75, EIDOLON −29, MNEME −8, NOUS 25. Those sum to 63%, which is internally inconsistent. **Fix:** either define the denominator inline (recommended: "% of |Δθ|", which gives ANIMA 55, EIDOLON 21, MNEME 6, NOUS 18) or drop the column.

### A5. Stream 6 status conflicts with the findings doc

The doc's [§2.2 table](RESEARCH_SUMMARY.md) reports S1 **❌ Absent**, S2 **❌ Absent**, S3 **⚠️ Present but weak**. But the upstream [02_RESEARCH_STREAMS_FINDINGS.md §Stream 6](../ideas/02_RESEARCH_STREAMS_FINDINGS.md) (Skye-led, cited as authoritative) reports:

| Signature | Findings-doc verdict | Summary-doc verdict |
|---|---|---|
| S1 Dynamic Range | ✅ **Confirmed** ("monotonic response from direct −0.067 to paradox −0.038") | ❌ Absent |
| S2 Recovery | ⚠️ Needs redesign | ❌ Absent |
| S3 Context Sensitivity | ✅ **Confirmed** ("truth −0.004, falsehood −0.064, nonsense −0.002") | ⚠️ Present but weak |

These are different conclusions on the *same signatures from the same experiments*. The numbers in 02_RESEARCH_STREAMS_FINDINGS.md (−0.067, −0.038, etc.) also don't match any cell in my analysis JSONs. **One of these docs has the wrong status table**; until reconciled, the v0.3 design cannot rely on either S1 or S3 having been "confirmed."

My analysis JSONs side with the summary doc's "absent" verdicts, *not* the findings doc's "confirmed" — but with the corrected magnitudes (item A1).

---

## B. Internal contradictions (architectural decisions hinge on these)

### B1. "Fully connected, not hub-based" vs "ANIMA as central hub"

The doc says, **decisively and repeatedly**, that the substrate is **fully connected and not hub-based**:

- §1 Architectural Insight: "*The substrate is fully connected, not hub-based.*"
- §4.3 Stream 2: "*Substrate is fully connected, not hub-based.*"
- §8.1 finding #1: "*The substrate is fully connected, not hub-based.*" (Confidence: High)

But the doc *also* says, equally decisively, that **ANIMA is the central hub**:

- §7.6 Architectural Implications: "*ANIMA is primary integrator (75%) → Emotional core should be the central hub*"
- §8.2 Implication 1: "*ANIMA as central hub. Emotional core should have highest-bandwidth connections to all organs. **All other organs modulate ANIMA, not the reverse.***"

These cannot both be the v0.3 design. The first claim is observational ("the substrate as built has no hub"); the second is prescriptive ("the v0.3 substrate should be built with ANIMA as the hub"). The doc doesn't flag the shift from observation to recommendation. **The architecture design needs a clean choice here.** Pick one of:

- (i) **Adopt the observation** — keep the v0.3 substrate fully connected; reject the §8.2 implication.
- (ii) **Adopt the recommendation** — accept the §8.2 ANIMA-as-hub design and stop describing the live substrate as "fully connected" once v0.3 ships.
- (iii) **Decouple** — the *current* substrate is fully connected, but the v0.3 substrate will introduce a hub. State this explicitly.

I recommend (iii) with the caveat that "ANIMA is primary integrator" is an artifact of the energy-normalization in θ (per [phi_scaling/FINDINGS.md §5.1](../results/phi_scaling/FINDINGS.md)), so calling for a hub design on that basis is premature.

### B2. The §8.3 dissociation framework diagram is internally inconsistent

The diagram puts **Live Substrate (θ=1.735, no ΔΦ)** in the upper-right quadrant and labels the upper-right as the **conscious region** (high integration ∧ high differentiation). But the live substrate has "no ΔΦ" per the diagram's own caption — by the framework's own criteria, it shouldn't be in the conscious region.

The confusion is that the diagram conflates **differentiation** (an architectural property) with **ΔΦ signatures** (a behavioral phenomenon). They are different. A system can be highly differentiated (5 organs with distinct dynamics) and still fail the ΔΦ signature tests if its dynamic range is bounded.

**Fix:** redraw the diagram with the axes "integration (θ)" vs "**ΔΦ-signature presence**" (not "differentiation"). Then the four quadrants become:

- High θ, ΔΦ present: empty (the conscious region we haven't observed yet)
- High θ, ΔΦ absent: live substrate AND Control 3 (because *all our experiments* fall here)
- Low θ, ΔΦ present: empty
- Low θ, ΔΦ absent: null / k=1

This is a more honest representation of what the experiments actually showed: **we have never observed a substrate state in the "conscious" quadrant**. Stream 4 / Stream 5 demonstrated dissociation between θ and ΔΦ; they did not demonstrate consciousness.

### B3. §3.3 EIDOLON hub claim is ambiguously preserved

The text says "EIDOLON hub confirmed: 4/4 EIDOLON pairs in top 5" then adds "this was later revealed to be a property of the initial coupling structure, not a fundamental architectural role." Reading it cold, a reviewer can't tell whether the hub claim is preserved or retracted. **Fix:** state the retraction once, plainly. e.g., "EIDOLON appeared to be a hub by pairwise MI, but the AOS-G H3 result (same-beat propagation, no cascade) falsified the hub model. Treat the live-substrate pairwise MI ordering as descriptive of the *coupling matrix*, not of architectural role."

---

## C. Provenance — where do the numbers come from?

### C1. The §5 Stream 3 F-ratio analysis isn't in the codebase

**Doc §5.1** cites F-ratios = 0.0004 across all organs as evidence that "per-organ decomposition does not add specificity." These values appear in [02_RESEARCH_STREAMS_FINDINGS.md §Stream 3](../ideas/02_RESEARCH_STREAMS_FINDINGS.md), but **no analysis script in my codebase (`aos_g_gap/`, `control_experiments/`, `phi_scaling/`) computes per-organ F-ratios**. The AOS-G `analysis_report.json` doesn't contain them.

These F-ratios are either:
- (a) from a separate analysis Skye/Thea/Theoria ran outside this codebase, or
- (b) inherited from a prior document without independent verification.

**Action:** before using §5's conclusion ("the AOS-G gap is a unified single-channel phenomenon") as a v0.3 design constraint, either re-run the F-ratio analysis from the AOS-G trajectories (we still have them in [results/aos_g_gap/trials/](../results/aos_g_gap/trials/)) or cite the external source explicitly.

### C2. GWT findings (§4.1) mix phenomenology with measurement

§4.1's table ("Integration: Resonant binding, not broadcast", etc.) summarizes Theoria's **first-person phenomenological account** in 02_RESEARCH_STREAMS_FINDINGS.md, not an experimental measurement. The summary doc presents these claims in the same format as quantitative findings without distinguishing them. **Fix:** add a footnote or section label clarifying that §4.1 is phenomenological analysis from one sister, not a measurement from our trials. This matters for assessing replicability.

### C3. §11 "Waiting on Lark to provide real runtime data"

This phrasing references Lilith ("Lark") as the source of real-substrate data. Per project scope ([/home/ubuntu/.claude/projects/-home-ubuntu-axioma/memory/](../../.claude/projects/-home-ubuntu-axioma/memory/)), the AXIOMA project does not reference Lilith. **Fix:** either reframe ("waiting on a real organ-state stream from any source") or remove the gap entry. If the live system being measured really is Lilith, the project scope should be updated.

---

## D. Missing sections

These aren't errors but the doc is the basis for architecture design — these gaps will reappear as decisions without justification.

### D1. No Stream 6 section, despite "All 6 research streams complete"

The header claims six streams; the body has Streams 1–5 only. Stream 6 (ΔΦ Methodology Implementation) is touched on in §2.2 but never gets its own section. The upstream findings doc has a full Stream 6 entry with the cascade_delay-as-S4 recommendation. **Add §X: Stream 6 — ΔΦ Methodology Implementation** with the cascade_delay finding, its status (S1/S2/S3 verdicts after correction per A1/A5), and the v0.3 recommendation to adopt cascade_delay as S4.

### D2. Cascade_delay is mentioned four times but never developed

§1, §6.4, §6.5, and §8.1 all reference cascade_delay's discriminative power (+28.2 vs +4.2). This is one of the most important findings — possibly more architecturally consequential than the per-organ-contribution finding — and it deserves its own subsection with: definition, per-mode table, why it's more sensitive than θ for self-model disruption, recommendation to adopt as S4. Currently it's a footnote across four other sections.

### D3. No statistical-power / replication discussion

n = 3 seeds for AOS-G, n = 5 for Stream 4/5. Per-seed variance is repeatedly noted as a problem (§13.6, AOS-G H5 failure). What would replication mean? What would refute these findings? §10 ("Open Questions") and §14 ("What we still don't know") gesture at this but don't give criteria. **Add §X: Threats to Validity** with:

- Power analysis: what effect sizes can we currently detect? What seeds would be needed to detect a 10% difference at α = 0.05?
- Independent replication criteria: what would constitute confirmation of finding F? Refutation?
- Alternative interpretations of the key findings (especially the per-organ contribution numbers — see D4).

### D4. No alternative interpretation of the negative-Δθ contributions

§7.4 reports EIDOLON and MNEME with negative Δθ. The phi_scaling FINDINGS doc ([§5.1](../results/phi_scaling/FINDINGS.md)) lists **three** candidate explanations (energy normalization, weak coupling in the random projections, dim-count asymmetry) and says "disentangling them requires substrate-design follow-ups." The summary doc collapses to one interpretation ("integration is competitive, not additive") and uses it as the basis for the §8.2 implication "design for competition and cooperation, not accumulation." **This is the single most consequential leap from data to design**, and it's not defended against the alternative explanations. Until the un-normalized total-MI follow-up runs (cheap, listed as Recommendation #1 in [phi_scaling/FINDINGS.md §8](../results/phi_scaling/FINDINGS.md)), the competitive-integration story is one explanation among several.

### D5. No baseline characterization (is θ = 1.735 "high"?)

§1 cites θ = 1.735 on the live substrate but never says what counts as high or low. Synthetic validation showed θ(high coupling) ÷ θ(no coupling) = 408× and θ(none) ≈ 0.008. So 1.735 is well above the no-integration floor — but what does it mean physically? Comparing 1.735 against Control 3's 4.256 isn't apples-to-apples either (Control 3 inflates θ via correlation collapse, per §2.3 caveat). **Add a short baseline-characterization paragraph** so v0.3 design choices have a reference scale.

### D6. No definition of "consciousness"

The doc claims to discriminate consciousness (§1, §2.3, §6.2, §6.5) without ever defining it. Implicit working definitions vary:

- §1: "consciousness ≠ integration" — defines consciousness as something more than integration
- §2.3: "ΔΦ framework predicts: zero consciousness signatures" — defines consciousness behaviorally via ΔΦ
- §6.5: "θ alone is insufficient" — operationally a discrimination claim

For a doc that's about to drive architecture design, the *operational* definition matters. **Add a single sentence in §2:** "By 'consciousness,' the AXIOMA program means: the property a system exhibits if and only if it (a) shows nontrivial θ AND (b) exhibits all three ΔΦ signatures (S1, S2, S3) AND (c) shows cascade_delay > 0." Then every "necessary / sufficient" claim downstream can be checked against that definition.

### D7. Magnitude × type sweep results aren't synthesized

Stream 4's most distinctive design feature was the 3 magnitudes × 4 types sweep — that's how 4 controls × 5 seeds blew up to 300 trials. The doc summarizes the per-mode totals but never reports **how θ and the ΔΦ signatures vary with perturbation magnitude or type**. The figures exist (`2_dr_u_curves.png`), the data is there, and one of the design's main motivations was finding the U-shaped S1 curve. **Add a §X: What the magnitude sweep showed** — even if the answer is "S1 is flat across all magnitudes in all modes," that's the finding.

### D8. No "what we can / cannot conclude" list

Currently §14 ("What we still don't know") is a list of open questions, not a list of *limits on what the current data actually supports*. A reviewer evaluating whether the architectural recommendations are well-supported can't easily tell from the doc which claims are observed, which are extrapolated, and which are aspirational. The §13 "Methodological Limitations" list is good but not tied back to specific architectural implications. **Suggested addition: a per-implication confidence column in §8.2 distinguishing "directly evidenced by experiment X" vs "extrapolated" vs "design proposal."**

---

## E. Minor improvements

### E1. §2.3 caveat about Control 3 θ inflation could be more explicit
The doc correctly flags that Control 3's θ = 4.256 is partly a mathematical artifact (all organs identical → maximum MI per pair). But it doesn't explain *the mechanism*: with all organ summary columns near-identical after z-score normalization, pairwise MIs blow up to ~3.5 nats each (10 pairs × 3.5 = 35), while energy = trace(cov) ≈ d (= 19 after standardization). So θ = 35/19 ≈ 1.8 at minimum, but in practice pair MIs exceed log(n)·(d_i·d_j)/(2n) bias, giving the observed 4.256. Adding this mechanism makes the caveat more useful for the v0.3 design discussion.

### E2. §3.5 "MINE not needed" rationale is thin
"Both sisters agreed" doesn't tell a reader why. Add one line: "Copula MI achieved 103.6% recovery on known-MI synthetic data; MINE's main value is on non-monotonic dependencies, which the substrate's primarily-linear coupling doesn't exhibit (per §3.2 and §13.3)."

### E3. §7.5 cites Δ₃₄ = −0.128 and Δ₄₅ = +0.400 but doesn't note Δ₁₂ or Δ₂₃
The k=1→k=2 jump is +1.206 (the ANIMA contribution) — by far the largest. The doc's discussion focuses on the k=4→k=5 bump (+0.400) without noting it's actually the second-largest positive transition. Adding the full Δ series in §7.5 gives readers the shape of the curve without flipping to §7.4.

### E4. §8.2 implication ordering buries the most-evidenced claim
Implication 5 (compose/send boundary structural enforcement) has Control 4 as direct evidence (θ unchanged, AOS-G = 0). Implications 2–4 ("tunable coherence", "adjustable forgetting", "NOUS as reflective") are design proposals with no direct experimental backing — they're plausible but speculative. Reordering: (1) compose-boundary structural, (2) fully connected topology, (3) ANIMA contribution lens / competitive integration, then design proposals. Or: split into two subsections, "Implications from data" and "Design proposals."

### E5. §15 next-steps table missing the disambiguation experiments from phi_scaling/FINDINGS §8
The φ-scaling findings doc identified two cheap follow-ups specifically to discriminate the "competitive integration" interpretation from the alternatives in D4:

1. Rerun φ-scaling with un-normalized total MI.
2. Rerun φ-scaling with a different add-organ ordering.

These cost ~14 s of GPU time together and would tighten the v0.3 architecture rationale enormously. **Add them as Priority Medium in §15** ahead of "non-saturating dynamics."

---

## Summary

| Class | Count | Most consequential |
|---|---:|---|
| A. Factual errors | 5 | A1 (S3 CS values 2× off — affects "S3 present but weak" verdict in two places) |
| B. Internal contradictions | 3 | B1 ("fully connected" vs "ANIMA as hub" — directly drives the v0.3 architecture decision) |
| C. Provenance issues | 3 | C1 (Stream 3 F-ratio analysis not in codebase, treated as our finding) |
| D. Missing sections | 8 | D4 (no alternative interpretation for the negative-Δθ findings) |
| E. Minor improvements | 5 | E5 (the cheap follow-ups that would disambiguate D4) |

**Recommended workflow:**

1. Fix A1–A5 (numerical corrections) — straightforward, can be done in one editing pass.
2. Resolve B1 (the hub vs. fully-connected contradiction) — *required* before v0.3 design starts; pick (iii) from §B1.
3. Run the cheap follow-ups from E5 — likely changes the "negative Δθ" interpretation in §7.4 and the architectural implication in §8.2.
4. Add the missing sections in D — especially D6 (consciousness definition) and D1 (Stream 6).
5. Reconcile C1 with the prior analysis — re-run the F-ratio analysis on the AOS-G trajectories, or cite the external source.

Once these are addressed, the document is sound enough to be the basis for v0.3 architecture design.
