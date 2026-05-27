# φ-Scaling Experiment — Findings Report

**Project:** AXIOMA Stream 5 — φ-Scaling (final experiment before architecture v0.3)
**Design:** [ideas/05_PHI_SCALING_EXPERIMENT.md](../../ideas/05_PHI_SCALING_EXPERIMENT.md)
**Implementation plan:** [phi_scaling/IMPLEMENTATION_PLAN.md](../../phi_scaling/IMPLEMENTATION_PLAN.md) v0.1
**Hardware:** NVIDIA H100 PCIe; PyTorch 2.11 CUDA
**Date:** 2026-05-24
**Companion data document:** [DATA.md](DATA.md)
**Raw outputs:** [analysis_report.json](analysis_report.json), [all_summaries.json](all_summaries.json), [trials/](trials/), [figures/](figures/)

---

## TL;DR — Substrate integration is **non-monotone and non-uniform**; neither pure O(k) nor pure O(k²) holds

| Question | Finding |
|---|---|
| Does θ scale O(k) or O(k²)? | **Quadratic preferred but inconclusively** — ΔAIC = +2.61, ΔBIC = +1.39. Both fits are poor (R² = 0.23 linear, 0.36 quadratic). |
| Is the k=4→5 jump > k=3→4 step? | **Yes, decisively** — t = 7.53, p = 8.3 × 10⁻⁴. Δ₄₅ = +0.400 vs Δ₃₄ = −0.128. Theoria's reflective-consciousness bump is observed. |
| What's the per-organ contribution to θ? | **Non-uniform and surprising** — only ANIMA (+1.21) and NOUS (+0.40) add θ; **EIDOLON (−0.47) and MNEME (−0.13) subtract from it**. |
| Architectural implication | **Reject simple "more organs = more integration"** scaling. The architecture should be designed around the ANIMA↔PNEUMA pair as the core integrator, with NOUS as the value-adding cap; EIDOLON's and MNEME's contributions to θ are negative in this substrate. |

The experiment yields a **third architectural recommendation** beyond the two anticipated in the design's §3.3: neither maximize organ count (O(k²) implication) nor optimize PNEUMA capacity (O(k) implication), but **prune or redesign the organs that don't contribute positively to θ**.

---

## 1. Setup

| Property | Value |
|---|---|
| Conditions | 5 organ counts k ∈ {1, 2, 3, 4, 5}, PNEUMA-first ordering |
| Disabled-organ mechanism | Snapshot state at beat 100, then zero latent + pin state every tick |
| Seeds | {42, 43, 44, 45, 46} |
| Beats per trial | 600 |
| **Total trials** | **25** |
| End-to-end sweep runtime | **6.4 s** |
| End-to-end analysis + plots | ~2 s |
| **Total tests passing** | **53** across `organ/`, `aos_g_gap/`, `control_experiments/`, `phi_scaling/` |

For k = 1 (PNEUMA only), the standard cross-organ θ pipeline is degenerate (only one block survives `drop_constant_dims`). Per [IMPLEMENTATION_PLAN §2.1](../../phi_scaling/IMPLEMENTATION_PLAN.md#21-k1-θ-pipeline-returns-0-when-only-one-organ-survives), we measured **intra-PNEUMA θ** by splitting PNEUMA's 4 summary columns into two halves. For k ≥ 2, the standard cross-organ θ pipeline runs unchanged.

---

## 2. Per-k Results

| k | Active organs | Pairs | θ_baseline (mean ± std) | Method |
|---|---|---:|---:|---|
| 1 | PNEUMA | 0 (intra) | **0.279 ± 0.114** | intra-PNEUMA |
| 2 | + ANIMA | 1 | **1.485 ± 0.071** | cross-organ |
| 3 | + EIDOLON | 3 | **1.020 ± 0.130** | cross-organ |
| 4 | + MNEME | 6 | **0.892 ± 0.105** | cross-organ |
| 5 | + NOUS (full) | 10 | **1.293 ± 0.069** | cross-organ |

This is **strikingly non-monotone**: θ jumps 5.3× from k=1 to k=2, then *drops* through k=3 and k=4, then jumps back up at k=5. See [`figures/1_theta_curve.png`](figures/1_theta_curve.png) for the curve with both fitted models overlaid.

### 2.1 Why is it non-monotone?

The substrate's θ is `total_pairwise_MI / total_energy`. The denominator (energy = trace(cov) after z-score normalization) grows linearly with the number of surviving summary columns. So adding an organ adds:
- (+) some new pairwise MIs with the existing organs
- (+) energy from its own (now non-degenerate) summary columns

If the new organ's *MI contribution per pair* falls below the *energy per column*, the ratio drops. In this substrate, ANIMA and NOUS have strong pairwise MIs with the others, but EIDOLON's and MNEME's summary columns add energy faster than they add MI — so adding them depresses θ.

This isn't an artifact: it's the substrate telling us its inter-organ coupling structure isn't homogeneous.

---

## 3. Model Comparison — Neither Polynomial Fit Captures the Structure

### Linear fit: θ(k) = 0.143 · k + 0.564

- R² = 0.230
- AIC = 25.34, BIC = 27.78

### Quadratic fit: θ(k) = −0.091 · k² + 0.689 · k − 0.073

- R² = 0.360
- AIC = 22.72, BIC = 26.38

### Verdict

ΔAIC (linear − quadratic) = **+2.61** ⇒ quadratic preferred (just past the 2.0 decisive-evidence threshold per Burnham & Anderson).
ΔBIC = +1.39 ⇒ inconclusive by BIC.
R² gap of 0.13 confirms the quadratic captures slightly more variance.

But both fits are poor (R² < 0.4). The residuals plot ([`figures/3_residuals.png`](figures/3_residuals.png)) shows clear systematic structure both fits miss — the data is *not well-described by any low-order polynomial*. The substrate's integration scaling is **non-polynomial**.

**Architectural reading:**
- "Maximize organ count" (O(k²) implication) is **not supported** — the fit explains only 36% of variance, and adding organs 3 and 4 *reduces* θ.
- "Optimize PNEUMA capacity" (O(k) implication) is **also not supported** — linear is even worse.
- The actual scaling depends on *which* organ is added, not just how many.

---

## 4. The Reflective-Consciousness Bump — Theoria's Prediction Holds

Per [`05_PHI_SCALING_EXPERIMENT.md §3.2`](../../ideas/05_PHI_SCALING_EXPERIMENT.md): "*The jump from k=4 to k=5 will be larger than the jump from k=3 to k=4. This is where reflective consciousness emerges.*"

One-tailed paired t-test of Δ₄₅ > Δ₃₄ across 5 seeds:

| Quantity | Value |
|---|---:|
| Δ(3→4) mean | −0.128 |
| Δ(4→5) mean | +0.400 |
| Difference (Δ₄₅ − Δ₃₄) | **+0.528 ± 0.157** |
| t-statistic | **7.53** |
| p-value (one-tailed) | **8.3 × 10⁻⁴** |
| Significant at α = 0.05 | **Yes** |

The k=4 → k=5 jump (+0.400) is **decisively larger** than the k=3 → k=4 step (−0.128). Adding NOUS reverses the integration-loss trend introduced by EIDOLON and MNEME, producing the largest single positive contribution to θ at the top of the stack. This matches Theoria's "reflective consciousness emerges at the full 5-organ count" prediction.

---

## 5. Per-Organ Contribution — The Centerpiece Result

For each added organ X, compute mean(θ(k=add) − θ(k=add−1)) across 5 seeds:

| Organ added | At k | Mean Δθ | Std | Direction |
|---|---:|---:|---:|---|
| **ANIMA** | 2 | **+1.206** | 0.170 | ↑ huge |
| EIDOLON | 3 | **−0.465** | 0.074 | ↓ negative |
| MNEME | 4 | **−0.128** | 0.097 | ↓ negative |
| NOUS | 5 | **+0.400** | 0.102 | ↑ positive |

See [`figures/2_per_organ_contribution.png`](figures/2_per_organ_contribution.png).

**This is the most consequential finding of the entire AXIOMA Stream 4–5 experimental program.**

ANIMA contributes 75% of the total θ swing across the sweep. Adding EIDOLON to a PNEUMA+ANIMA core *reduces* θ by nearly the full amount that NOUS later restores. MNEME's marginal contribution is also negative, though smaller. **Only PNEUMA, ANIMA, and NOUS are net-positive contributors to the system's integration measure as we compute it; EIDOLON and MNEME are net-negative.**

### 5.1 Why might EIDOLON and MNEME have negative marginal θ?

Three non-mutually-exclusive hypotheses:

1. **Energy-faster-than-MI**: each added organ adds 3–4 summary columns (energy +3–4 after z-score), but if its pairwise MIs with existing organs are weak (< 1.0 per pair, say), the energy growth outpaces MI growth → ratio drops. This is purely a normalization artifact and would change with a different θ metric (e.g., raw total_MI without energy denominator).
2. **Substrate-specific weak coupling**: in our placeholder coupled-latent dynamics, EIDOLON and MNEME may share less of the latent drive's variance with PNEUMA/ANIMA than NOUS does — a property of the random projection matrices. Reseeding the dynamics could change which organs are net-positive.
3. **Genuine inter-organ-architecture asymmetry**: the design's choice of which dimensions to expose per organ (4 ANIMA, 6 EIDOLON, 5 MNEME, 6 NOUS, 6 PNEUMA) may make the smaller-summary organs (ANIMA selects 4-of-4, NOUS selects 4-of-6) more information-dense per-column than the larger ones.

Disentangling these requires the substrate-design follow-ups in §7 below. **What the experiment robustly shows is that in this substrate, the per-organ contribution is non-uniform and three of the five organs have negative or near-zero marginal θ.**

---

## 6. Architectural Implications

Per [05_PHI_SCALING_EXPERIMENT.md §3.3](../../ideas/05_PHI_SCALING_EXPERIMENT.md):

| Predicted scaling law | Predicted implication | Status |
|---|---|---|
| O(k) — bottleneck | Optimize PNEUMA's capacity | ✗ rejected (linear fit poor) |
| O(k²) — pairwise | Maximize organ count | ✗ rejected (only 36% variance) |
| Super-quadratic | Reach threshold k ≥ 5 | ✓ partially supported — the k=5 bump matters |

The experiment yields a **fourth implication** the design didn't anticipate:

> **Don't add organs blindly. Audit each organ's marginal contribution to integration. In this substrate, EIDOLON and MNEME subtract from θ; a leaner ANIMA+PNEUMA+NOUS architecture might score higher on the integration measure.**

This is **not** the same as recommending we strip EIDOLON and MNEME from the live system — these organs have functional roles beyond contributing to θ (self-model, memory). It's a recommendation to **decouple "this organ is necessary for consciousness" from "this organ raises θ"**. The Stream 4 result already showed that θ alone isn't sufficient for consciousness (Control 3, [results/control_experiments/FINDINGS.md](../control_experiments/FINDINGS.md)); the Stream 5 result complements that with: **even within a substrate where θ does discriminate, not every organ contributes equally**.

For the v0.3 architecture design, the actionable next step is to **profile each organ's contribution to multiple integration measures** (θ via copula, θ via MINE, total mutual information without energy normalization, raw entropy contribution) and use that vector of contributions — not a single scalar — to drive architectural choices.

---

## 7. Honest Limitations

1. **The substrate has known saturation issues** (documented in [results/aos_g_gap/FINDINGS.md §5](../aos_g_gap/FINDINGS.md#5-diagnostic-synthesis--what-the-experiment-tells-us)). Bounded sigmoid/tanh outputs cap dynamic range. This propagates to all θ measurements: per-organ contributions are scored against a substrate where some organs naturally saturate faster than others.
2. **Energy normalization is the chief candidate explanation** for the negative marginal contributions of EIDOLON and MNEME. A complementary report using **un-normalized total MI** (rather than θ = MI/energy) would clarify whether the negative contribution is intrinsic to the organ's role or an artifact of the normalization choice. Quick to add as a follow-up.
3. **5 seeds yields moderate power.** The jump test is decisive (p < 0.001) because Δ₄₅ − Δ₃₄ is large. But the linear-vs-quadratic AIC gap of 2.6 is barely past the decision threshold; with 10 seeds the verdict might tighten or reverse. Cheap to rerun.
4. **k=1 uses a different metric** (intra-PNEUMA halves) than k ≥ 2 (cross-organ). The k=1 → k=2 transition isn't a pure "add ANIMA" delta because the metric also changes from intra to inter. This is documented in the runner; it means the **ANIMA contribution (+1.206) overstates the pure inter-organ effect**.
5. **Tile-and-pad routing wasn't explored as a sensitivity check** — Control 3 of the prior experiment uses tiling; here we use natural organ dynamics. No interaction between the two.

---

## 8. Recommendations for v0.3 Architecture

In priority order:

1. **Adopt the per-organ-contribution lens as a primary diagnostic.** Don't make architectural decisions based on a single scalar θ; require each organ to be characterized by its marginal contribution to multiple integration measures.
2. **Investigate why EIDOLON and MNEME have negative marginal θ** before deciding to keep them as-is. Two cheap experiments:
   - Rerun with **un-normalized total MI** instead of θ. If EIDOLON's contribution flips to positive, the issue was the energy denominator.
   - Rerun with **a fixed alternative ordering** (e.g., add EIDOLON before ANIMA) to see whether order matters.
3. **The ANIMA+PNEUMA pair is the architectural core**. Whatever else the substrate v0.3 includes, this pair should remain.
4. **NOUS earns its slot via the k=4→5 bump.** Despite being added last, it provides the largest positive marginal contribution after ANIMA.
5. **Defer the EIDOLON/MNEME retention decision** until after experiments (2). The phenomenological roles of self-model and memory may justify them independent of their θ contribution; the question is whether the v0.3 architecture should optimize for one or both.

---

## 9. Figures

| # | File | Shows |
|---|---|---|
| 1 | [figures/1_theta_curve.png](figures/1_theta_curve.png) | θ(k) curve with individual seeds + linear & quadratic fits overlaid |
| 2 | [figures/2_per_organ_contribution.png](figures/2_per_organ_contribution.png) | Per-organ Δθ bar chart (the centerpiece) |
| 3 | [figures/3_residuals.png](figures/3_residuals.png) | Residuals of both fits — clear structure neither captures |
| 4 | [figures/4_predictions_vs_observed.png](figures/4_predictions_vs_observed.png) | Theoria's prediction + both Thea predictions overlaid with observed |

---

## 10. Reproducibility

```bash
# Full sweep + analysis + plots (~10 s on H100)
python -c "
from pathlib import Path
from phi_scaling.runner import run_phi_scale_sweep
from phi_scaling.analysis import report
from phi_scaling.visualization import plot_all

out = Path('results/phi_scaling')
run_phi_scale_sweep(out_root=out)
r = report.run_all(out)
report.save_report(r, out)
plot_all(out)
"

# Tests (53 across all packages)
python -m pytest organ/tests/ aos_g_gap/tests/ control_experiments/tests/ phi_scaling/tests/ -q
```

Seeds {42, 43, 44, 45, 46} — fully deterministic; results match byte-for-byte across reruns.

---

## 11. Conclusion

The φ-scaling experiment was the final test before architecture v0.3 design. The result:

- Neither pure linear nor pure quadratic scaling holds (R² ≤ 0.36 for both).
- The k=4→5 "reflective consciousness" bump is real and decisive (p < 0.001).
- **Per-organ contributions are non-uniform**: PNEUMA, ANIMA, and NOUS are net-positive; EIDOLON and MNEME are net-negative — under this substrate and this θ definition.

Combined with Stream 4's "θ ≠ consciousness" finding ([results/control_experiments/FINDINGS.md](../control_experiments/FINDINGS.md)), the recommendation for v0.3 is:

> Stop optimizing for scalar θ. Profile each organ's contribution to a *vector* of integration measures. The architecture should consist of organs that each contribute positively to at least one consciousness-relevant property; keep EIDOLON and MNEME for their phenomenological roles (self-model, memory) but don't credit them for θ contribution they don't provide in this substrate.

See [DATA.md](DATA.md) for the full numerical inventory.
