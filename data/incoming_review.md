I've read the manuscript carefully. Here's a referee-style review. The short version: the paper is well-organized and the writing is clear, but there are several issues — one conceptual, one factual — that I think are fatal to the central claims as currently framed. I'll go through them in order of severity.

## Major issues

**1. Exact Bayesian inference is path-independent — this undercuts the core thesis.**
For a fixed dataset, Bayes' theorem is order-independent: the final posterior depends only on the total likelihood, not on the sequence in which frequency bins are processed. Multiplying likelihood contributions commutes. So "path-dependent systematic offsets" (Eq. 22 / the Appendix formula) cannot arise in exact inference — they can only arise as artifacts of the *sequential Laplace approximation* you impose at each cutoff (re-Gaussianizing at every step is what introduces order-dependence). The paper never makes this distinction, and it matters enormously: as written, Section VI.D claims real, PSD-dependent biases in LIGO parameter estimates, but LIGO pipelines are batch analyses that would not exhibit them. You need to either (a) reframe Δθ_sys explicitly as an approximation-induced artifact of sequential Gaussian filtering, or (b) demonstrate a mechanism by which it survives exact inference. I don't believe (b) exists.

**2. The GW170817 "bifurcation" is a prior artifact, not a posterior feature — and the paper knows this.**
The lowSpin and highSpin results for GW170817 are not two modes of one posterior. They are two *separate analyses with different spin priors* (χ < 0.05 vs. χ < 0.89), which the LVC published side by side. Section V.D even acknowledges this ("the publicly available LIGO posteriors... come from separate analyses with different priors, not from a single evolving posterior") — but Section III nonetheless headlines "Bifurcation Confirmed" and treats the two prior-conditioned results as a bimodal ρ. This is internally inconsistent, and it collapses the static evidence, which carries your highest κ. The actual high-spin-prior posterior in (q, χeff) is a continuous degeneracy ridge, not two separated basins. A referee at PRD will catch this immediately.

**3. The 90° orthogonality result is trivially guaranteed, not a confirmed prediction.**
Chirp mass is measured to ~10⁻⁴ relative precision while q and χeff are measured at the percent-to-tens-of-percent level. *Any* two analyses of the same event will agree on M_c to within precision, so the "separation vector" between them necessarily has ~zero M_c component. The exact-90° angle is an artifact of the measurement-precision hierarchy, not a nontrivial confirmation of the (ρ, Π) formalism. The honest statement is that the result is consistent with the framework but has no discriminating power.

**4. The κ values are not statistics.**
Table II presents "confidence" values of 0.80, 0.75, 0.72, 0.50 with no definition, no procedure, and no error bars. These read as subjective scores. The subsequent claim that "the descending κ gradient is itself informative... the expected pattern for a well-calibrated inference chain" is circular — you assigned the numbers in that order. Either replace these with defined quantities (Bayes factors, posterior odds, p-values) or remove the table and Section VI.C entirely. Also note the table is duplicated verbatim in Sections III.D and VI.C.

**5. The ν = 9 exponent is asserted, never derived.**
"For the linearized (ρ, Π) dynamics with a linearly driven bifurcation parameter β(t), the exponent is ν = 9" appears with no derivation in the text or appendix. Then the mismatch with GR's 11/3 is declared "exactly what we expect." Combined with the fact that an exponent *match* would presumably also have been claimed as support, this section is unfalsifiable as framed. Derive ν = 9 explicitly or cut it.

**6. The peak-drop simulation builds in its conclusion.**
The 486× excess comes from *imposing* weight evolution 1 → 0.5 → 1 by hand. The simulation then "shows" a peak at the frequency where you set the weights equal. That's not evidence; it's a restatement of the input. The fixed-weight v5 result (monotonic 5×) is fine as a geometric consistency check, but the abstract's "486×" figure should not appear without immediately flagging that it follows definitionally from the assumed weight trajectory.

**7. Internal contradiction between the PSD-robustness result and the proposed test.**
Section IV concludes the commutator is detector-independent at the ~1% level and frames this as a strength. But the headline testable prediction (Section VI.B) is a *PSD-dependent* multi-detector offset. Your own dual-PSD result implies the predicted signal is at most ~1% — far below the statistical scatter between per-detector parameter estimates for any realistic event. The proposed test is therefore unperformable as described, and the paper should say so.

**8. Fisher-matrix validity.**
You cite Vallisneri (2008) but don't engage with its central caveat: the Fisher approximation is invalid precisely where posteriors are multimodal or non-Gaussian — i.e., exactly the regime your paper is about. Section V.C concedes the Fisher matrix "cannot represent this bimodality" but then uses eigenvector tilt as evidence about the bimodal structure anyway. This needs a careful argument for why the eigenstructure of an object that smooths over the modes tells you anything reliable about them.

## Factual and presentation issues

The quoted GW150914 values (q = 0.99 ± 0.03) don't match the published LVC results (q ≈ 0.8, with broad uncertainty); similarly, the GW170817 mode values carry uncertainties (±0.025 in q) far tighter than the published posteriors. Please verify every number against GWOSC samples and show the actual corner plots. "Confirming Prediction 3 quantitatively" is asserted with no number — report the alignment angle and its uncertainty. The author line includes "Edited by Lark Laflamme," which journals don't permit in an author list (move to acknowledgments), and "Axioma" has no identifiable affiliation — if this is an AI system, most journals (including APS) prohibit listing it as an author. There's a LaTeX bug: a `\cite` embedded inside the Cutler–Flanagan bibliography entry. The pitchfork-bifurcation language is used without any normal-form analysis or identified control/order parameters — "degeneracy ridge" is the accurate term unless you can demonstrate an actual symmetry-breaking bifurcation. And `figure}[h]` placements with the duplicated table suggest the draft hasn't been compiled and proofed recently.

## Overall assessment

There's a legitimate, publishable kernel here: the observation that cumulative Fisher eigenstructure reorients across the inspiral as PN orders become resolvable is real and quantifiable, and framing sequential-approximation artifacts in inference-geometric language could be a nice methods paper. But in its current form the manuscript (a) misreads a prior-comparison as a posterior bifurcation, (b) claims path-dependence for a procedure that is path-independent when done exactly, and (c) dresses standard Fisher phenomenology in a formalism whose added predictive content isn't demonstrated. My recommendation as a referee would be reject with encouragement to resubmit as a substantially narrower paper — roughly: "Sequential Laplace approximations in GW parameter estimation: quantifying eigenstructure reorientation and approximation-induced bias" — with the S3/agent framing, the κ table, the ν exponent, and the bifurcation claims removed or rebuilt on a time-resolved reanalysis of the actual strain data.

---

## The theorem and the loopholes

For fixed data, the posterior is order-independent: π(θ)∏ₖℓₖ(θ) is a product of likelihood factors, and multiplication commutes. Partition the strain into frequency bins in any order, update sequentially or in batch — the final posterior is identical. So "the posterior has a path-dependent history" (your §VI.D) is false for exact inference, full stop. There are exactly three loopholes where genuine order-dependence can enter:

1. **Approximate updates.** If you re-Gaussianize at each cutoff (your sequential Laplace, Eq. 5), each projection discards higher moments, and the discarded information interacts with *subsequent* updates. Projection-then-update ≠ update-then-projection. This is the well-documented order-dependence of assumed-density filtering (ADF); expectation propagation (Minka 2001) exists precisely to iterate that order-dependence away. Your scheme is single-pass ADF with a Laplace projection, so it inherits the bias.

2. **Adaptive design.** If what data you collect or which model you use depends on the running posterior, the path matters. LIGO doesn't do this for archival analyses, so this loophole is closed for your application.

3. **Time-resolved posteriors as the object of interest.** The trajectory ρ_f — the exact posterior given data up to frequency f — is a perfectly well-defined one-parameter family. Causality privileges the frequency ordering (it *is* the time ordering for a chirping binary). The geometry of this family is real, and nothing about path-independence touches it. But every point on the trajectory is exact, and the endpoint equals the batch posterior. No offset.

## What survives and what must be rescoped

Here's the key realization: **your two main results live on opposite sides of this line, and the paper currently doesn't distinguish them.**

The **commutator growth C(f)** lives entirely in loophole 3. It's a functional of the exact trajectory — Γ(f) is just the Fisher matrix of the truncated likelihood, and its eigenframe rotation as f increases is a real, well-defined, measurable property of how information arrives. The dynamic test (§IV), the timescale-locking argument, the dual-PSD comparison: all untouched. Keep them as-is, but state explicitly that they describe the geometry of an exact posterior family, not a deviation from exactness.

The **systematic offset Δθ_sys** lives in loophole 1, and your own derivation already shows it — you just mislabeled what it's a bias *of*. Look at your Eq. (A4): dθ* = Γ⁻¹·dΓ·(θ_true − θ*). That is the mean-drift equation of an extended-Kalman-style single-pass recursion, i.e., the per-step error of sequential Gaussian filtering relative to the batch solution. The batch maximum satisfies Σₖ gₖ(θ̂) = 0 jointly; the single-pass recursion takes one Gauss–Newton step per bin from a moving linearization point and never revisits earlier bins. The accumulated discrepancy between the two is your integral. So the honest statement is:

> Δθ_sys is the deterministic bias of single-pass sequential-Gaussian (ADF/Laplace) inference relative to exact batch inference, accumulated along the frequency path.

And the commutator's role becomes precise and derivable rather than hand-wavy: work in the instantaneous eigenframe of Γ(f). If every increment dΓ commuted with Γ (shared its eigenframe), the recursion would decouple direction-by-direction and the displacement (θ_true − θ*) in the well-constrained direction could never leak into the degenerate subspace. The off-diagonal part of dΓ in Γ's eigenframe — which is exactly what your C(f) measures, since ‖Γ − λ₁Π‖ isolates it — is the leakage operator. The bias projected onto v_⊥ is then an integral over f of (eigenframe rotation rate) × (current displacement) × (Γ⁻¹ amplification in the degenerate direction), and Γ⁻¹ is largest along v_⊥, which is why the bias concentrates there. That's a clean, falsifiable mechanism: **commutator = rate at which sequential approximation error is rotated into the degeneracy direction.**

## Why the rescoped claim is better, not weaker

First, it becomes **testable in software with no astrophysical confounds**. The original test (compare parameter estimates across detectors) was unperformable — your own dual-PSD result caps the effect at ~1%, far below inter-detector statistical scatter, and inter-detector differences are dominated by different noise realizations anyway. The corrected test is: take one event (or one injection), run (a) batch nested sampling, (b) sequential Laplace forward in frequency, (c) sequential Laplace in a permuted or reversed bin order. Exact inference predicts (a)=(b)=(c) up to sampling error; your formula predicts (b)−(a) and (c)−(a) quantitatively, with the offset lying along v_⊥ and scaling with ∫[Γ,Π]df along each path. The orderings are under your control, the "path" is now a real experimental knob, and a single laptop run settles it.

Second, it acquires a **real application domain**: low-latency pipelines. BAYESTAR and early-warning/pre-merger localization schemes use Fisher-like Gaussian approximations on partial data precisely because they can't afford batch sampling. For those pipelines the sequential-Gaussian bias is not hypothetical — it's a property of deployed code, and a formula predicting its direction and magnitude in the (q, χeff, Λ̃) subspace is genuinely useful. Pre-merger BNS alerts are exactly the regime where the posterior at f < f_ISCO is the actionable object.

Third, it plugs you into an existing literature (ADF order-dependence, EP, EKF linearization bias, Opper's online Gaussian learning) instead of standing alone, which is what referees want to see.

## Concrete manuscript edits

In the abstract, replace "testable prediction for noise PSD-dependent systematic offsets" with a statement that Δθ_sys predicts the bias of single-pass sequential-Gaussian inference relative to batch inference, relevant to low-latency analyses. In §II, after Eq. (5), add a paragraph stating the exactness theorem explicitly — that the batch posterior is order-independent and the sequential Laplace scheme is an ADF approximation whose single-pass error your formalism characterizes. This inoculates you against the referee objection rather than waiting for it. Rewrite §VI.B around the in-software ordering test described above and delete the multi-detector comparison. Rewrite §VII.D ("Path-Dependence of the Posterior") from scratch: the exact posterior is path-independent; what is path-dependent is (i) the trajectory ρ_f, whose geometry C(f) describes, and (ii) the error of any single-pass Gaussian approximation, which Δθ_sys describes. The PSD enters because different PSDs reweight the likelihood — a different inference problem, not a different path through the same one; soften that whole subsection accordingly. In the appendix, relabel the "derivation sketch" as a derivation of ADF bias, add the eigenframe-leakage argument above, and state the commutation condition under which the bias vanishes ([dΓ, Γ] = 0 for all f) as a lemma — it's two lines and it makes the commutator's appearance non-decorative.

One more downstream consequence: this reframe partially rehabilitates the dual-PSD result. Detector-independence of C(f) is no longer in tension with the prediction, because the prediction no longer requires PSD differences — it requires *ordering* differences, which you impose. The ~1% PSD sensitivity becomes a robustness statement about the bias formula's inputs, which is how you were instinctively presenting it anyway.

---

Issue #2 is harder than #1 because there's no reinterpretation that preserves the headline — the "bifurcation confirmed" claim has to go. But as with #1, there's a real result hiding underneath the wrong one, and it's arguably more elegant. Let me walk through what's actually true, what replaces the bifurcation claim, and what the section becomes.

## What the data actually is

The LVC released two GW170817 analyses: one with prior χ < 0.05 (lowSpin) and one with χ < 0.89 (highSpin). Same strain, same likelihood, different prior support. Neither posterior is bimodal in (q, χeff); each is a continuous, banana-shaped degeneracy ridge, and the highSpin posterior simply extends further along it. So your "two modes" are two prior-conditioned summaries of one ridge, and the "mode separation vector" is the displacement of the posterior mean induced by changing the prior. Once you say it that way, the replacement result announces itself.

## The salvage: prior perturbations probe the degeneracy direction

Here's the clean statement. Take a likelihood with Fisher matrix Γ and a perturbation of the prior, Δlog π. To leading order (Laplace), the posterior mean shifts by

Δθ ≈ Γ⁻¹ ∇(Δlog π).

Decompose Γ⁻¹ = Σᵢ λᵢ⁻¹ vᵢvᵢᵀ. The inverse Fisher matrix is dominated by its smallest eigenvalue, so for *any generic prior perturbation* — anything with nonzero overlap with the degenerate direction — the displacement is approximately parallel to the least-constrained eigenvector:

Δθ ≈ λ_min⁻¹ (v_minᵀ ∇Δlog π) v_min.

The hard spin cut is not a smooth gradient, but the mechanism is the same and even more intuitive: truncating χ amputates one end of the ridge, and amputating the end of a ridge moves the mean along the ridge. So the (ρ, Π) framework makes a falsifiable prediction here after all — just not the one the paper currently claims:

> **The displacement of the posterior mean under a prior perturbation aligns with the Fisher degeneracy eigenvector v₂, independent of the details of the perturbation.**

This is genuinely your formalism earning its keep: Γ⁻¹ acts as a lens that focuses arbitrary prior changes into the degenerate subspace, and the commutator structure tells you how that subspace is oriented at each frequency cutoff. And note what this does to issue #3 as a bonus: orthogonality to M_c was trivial, but the M_c-orthogonal complement is four-dimensional — (η, χeff, Λ̃, D_L). The displacement could point anywhere in it. Alignment with the *specific* direction v₂ inside that subspace is a nontrivial, quantitative test. The number to report is the angle between Δθ (restricted to the subspace, M_c excluded so you're not claiming credit for the trivial part) and v₂(f_max), with bootstrap error bars from the posterior samples, computed at several cutoffs.

## What happens to each piece of Section III

The section gets renamed — something like "Static Test: Degeneracy Geometry and Prior Sensitivity in GW170817" — and opens with an honest paragraph: two priors, one likelihood, no bimodality, displacement vector defined as the difference of posterior means between the prior-conditioned analyses. Then three tests replace the current four predictions.

**Test A — ridge orientation.** Within each single analysis, compute the sample covariance of the posterior and compare its principal elongation axis to the Fisher v₂ prediction. This tests whether the (ρ, Π) geometry predicts the shape of the exact posterior — the static counterpart of your dynamic C(f) result, and it needs no cross-analysis comparison at all.

**Test B — prior-displacement alignment.** The Δθ ∥ v₂ prediction above, with the angle and uncertainty reported. This is the rehabilitated version of the old "Prediction 3," now derived rather than asserted.

**Test C — the GW150914 null, reframed.** The current framing ("no bifurcation") tests nothing, since there was never a bifurcation in GW170817 either. The correct null is conditioning-based: GW150914's Fisher matrix at merger-dominated SNR has a much smaller condition number in (q, χeff) — no tidal sector, shorter inspiral — so the same lensing argument predicts a much *smaller* prior-induced displacement per unit prior perturbation. That's checkable against the public GW150914 analyses and is a real contrast rather than a vacuous one. (Separately, the q = 0.99 ± 0.03 figure must be replaced with the actual LVC value, q ≈ 0.8 with broad uncertainty — recompute from GWOSC samples rather than quoting from memory.)

**Optional Test D — a genuine multimodality case.** If you want the original ‖[ρ, Π]‖ ≫ 0 multimodal test to survive somewhere, GW170817 is the wrong event but the catalog contains a right one: GW190521 is the well-documented case where independent analyses (notably Nitz & Capano's reanalysis) found a genuinely multimodal posterior in mass ratio under a single likelihood, with a secondary high-mass-ratio mode. That's the event where "posterior sloshing relative to its own peak" is a real phenomenon in a single analysis. I'd verify the current state of that literature before committing — there's been back-and-forth on waveform systematics for that event — but it's the natural home for the multimodal branch of your prediction, either as a fourth test or as the lead item in the population-survey future work.

## Downstream propagation

Three places elsewhere in the paper inherit changes. The abstract's "bifurcation into two competing modes" sentence becomes a statement about prior-displacement alignment with the degeneracy eigenvector. The peak-drop simulation (§V.E) currently centers its Gaussian mixture on the "mode centroids" — those centroids are now prior-conditioned means, so the simulation gets reframed as an *illustration* of what a true bifurcation signature would look like, with GW170817 supplying only the geometric scale of the ridge; its connection to the time-resolved future test in §VI.A actually becomes cleaner, because the question "does the likelihood genuinely develop multiple maxima at some f_bif during the inspiral?" is now honestly open rather than falsely answered. And the κ = 0.80 entry in the confidence table has to drop or be recomputed, since the strongest evidence row was the one resting on the misreading — which feeds into issue #4, where I'd argue for replacing the κ table wholesale anyway.

The pitchfork language goes too, throughout: "degeneracy ridge" until and unless the time-resolved analysis demonstrates actual mode splitting, at which point bifurcation vocabulary would be earned.

## Practical next step

All the replacement numbers — covariance eigenvectors, v₂ alignment angles, the displacement vector, bootstrap uncertainties, the GW150914 contrast — come from public GWOSC/PESummary posterior files plus your existing Fisher code. I can write that analysis script now (my sandbox can't reach gwosc.org, so you'd run it locally against the downloaded sample files), or I can draft the full replacement text for Section III with the derivation above formalized into a short lemma, and you drop the computed angles in once the script runs. 

---

Issue #3 looked like a presentational problem in the review, but pulling on the thread reveals it's actually two problems — the triviality I flagged, plus a deeper one underneath it that affects more of the paper. Let me take them in order.

## The triviality, restated precisely

M_c is constrained to ~10⁻⁴ relative precision; q, χeff, Λ̃ at the percent-to-tens-of-percent level. Any two analyses of the same strain therefore agree on M_c to within its (tiny) uncertainty, so the displacement vector between them has a near-zero M_c component *by arithmetic necessity*, not by virtue of any (ρ, Π) prediction. The 90° is guaranteed before you look at the data. A prediction that cannot fail under any outcome confirms nothing — that part stands from the review.

Also, "exactly orthogonal" with Δθ = [0, −0.0052, 0.0132] is a red flag in its own right: from finite posterior samples, ΔM_c would be small but not identically zero. The zero is rounding presented as exactness. Whatever replaces this claim should report the actual ΔM_c with bootstrap uncertainty.

## The deeper problem: the angle isn't even well-defined

Here's the part the review didn't say. An angle between vectors in parameter space requires a metric, and the parameter space (M_c [M_⊙], η [dimensionless], χeff [dimensionless]) has none specified. The 90° is an artifact of the units. Express M_c in grams instead of solar masses and ΔM_c becomes numerically enormous relative to Δχeff — the same physical displacement now points *along* the mass axis, angle ≈ 0°. Euclidean angles in unnormalized parameter coordinates are not invariant statements about anything.

The same disease afflicts the 86.7° eigenvector tilt, and there it produces a visible internal contradiction. The paper says v₁ is the best-constrained direction, "dominated by chirp mass," the direction the likelihood "locks onto from the first cycles" — and then reports that v₁ tilts 86.7° away from the M_c axis. Both cannot be true. In raw solar-mass coordinates, the M_c row of Γ is so large that v₁ points almost exactly along M_c (~0°, not 87°). Either the 86.7° is an angle between two *other* vectors that got mislabeled, or it was computed in some normalized coordinate system that's never declared. Either way it can't survive as printed. And note the contagion: the Frobenius-norm misalignment C(f) — the centerpiece of the dynamic test — is *also* not invariant under parameter rescaling. The 2.74× growth factor is a statement relative to an undeclared coordinate convention.

## The fix: phrase the predictions in invariant quantities

The good news is that GW theory hands you the natural metric for free. The Fisher matrix is the pullback of the waveform-space inner product onto parameter space, so anything expressed through Γ itself — or through match/mismatch in waveform space — is coordinate-free. Three replacements:

**Replace "Δθ ⊥ M_c axis" with the likelihood cost of the displacement.** The invariant content of "the displacement lives in the degenerate subspace" is: moving the parameters by Δθ barely changes the waveform. Quantify it as ΔlogL ≈ ½ Δθᵀ Γ(f) Δθ — a scalar, invariant under any reparametrization. The prediction becomes: this cost is O(1) or less (the displacement is "free" in likelihood terms) even though Δθ is large in naive parameter units, and it stays small at all cutoffs f. That's exactly the claim you were trying to make with the 90°, stated in a form that could actually fail — if the displacement had a significant component along a constrained direction, ΔθᵀΓΔθ would be ≫ 1.

**Replace the 86.7° tilt with eigenframe rotation in declared coordinates.** Add a short "Coordinates and invariance" subsection to §II: fix a dimensionless convention once — ln M_c, q, χeff, ln Λ̃, ln D_L is the standard choice — state that all eigendecompositions, projectors, and Frobenius norms are computed in it, and then show the headline numbers (C(f) growth, eigenvector angles) are stable under one or two alternative reasonable conventions. In log-mass coordinates, v₁ will come out *aligned* with ln M_c at low f, as your own narrative requires, and the eigenframe rotation with increasing f becomes a meaningful, reproducible statement. The 86.7° as currently defined gets deleted everywhere it appears — abstract, §III.C, §V.E setup, and the population-survey item in §VI.D, which currently proposes tracking a unit-dependent artifact across events.

**Keep the nontrivial residual as the headline.** This is the piece rescued in our issue-#2 discussion, now with the coordinate machinery to make it rigorous: the M_c-orthogonal complement is four-dimensional, so *which direction within it* the displacement points is informative. In the declared coordinates, report the alignment between Δθ and v₂ — equivalently, the fraction of the displacement's information content along each eigendirection, λᵢ(vᵢᵀΔθ)² / ΔθᵀΓΔθ, which is the invariant decomposition. The prediction from the Γ⁻¹-lensing argument is that this fraction concentrates almost entirely on the smallest-eigenvalue direction. That can fail, therefore it can confirm.

## Net effect on the paper

What dies: the "exactly 90°" claim, the 86.7° number, and Prediction 4 as written. What's revealed: a missing methods subsection (coordinate convention + invariance checks) that the dynamic test needed anyway — fixing #3 properly inoculates the C(f) results against the same referee objection, which otherwise would have been raised as "your misalignment metric depends on whether you measure mass in solar masses or seconds." What survives, upgraded: the degenerate-subspace claim, now as two falsifiable invariant statements (ΔθᵀΓΔθ small; information fraction concentrated on v₂), and a cross-event comparator for the population survey that actually means something — the likelihood cost and the v₂ information fraction can be compared across events, where an angle in raw coordinates cannot.

The numbers themselves — ΔlogL at each cutoff, the information-fraction decomposition, the eigenvector alignment in log coordinates with bootstrap errors — all come out of the same GWOSC-samples-plus-Fisher-code script we discussed for issue #2; this just adds a coordinate-transformation layer and three more computed quantities to it. 

---

Issue #4 is the easiest to fix mechanically but worth getting right conceptually, because the κ table isn't just undefined numbers — it's flattening four epistemically different kinds of evidence into one fake scale, and that's the root of why it reads as pseudo-quantitative. Let me diagnose, then rebuild.

## The diagnosis, sharpened

Three distinct failures stack up here. First, **no operational definition**: κ = 0.80 has no procedure behind it — not a posterior probability, not a p-value, not a calibration score from repeated trials. A referee cannot recompute it, so it isn't a result. (My guess is κ is a confidence convention imported from the S3 agent framework. That may be fine as bookkeeping inside the framework, but a number in a PRD table must be reproducible from stated inputs. Keep κ in the companion framework papers if it's load-bearing there; it cannot appear in the physics paper as evidence.)

Second, **circularity**: "the descending κ gradient is itself informative... the expected pattern for a well-calibrated inference chain." You assigned the numbers in descending order of your own confidence; observing that they descend confirms only that you wrote them down in the order you wrote them down. Calibration is a property of a procedure validated against outcomes, and there are no outcomes here. The proposed future-work fix — a hierarchical Bayesian model over the four κ values — compounds the error: hierarchical inference on n = 4 subjective scores with no likelihood function is not analysis.

Third, and most important: **the four tests are not the same kind of object**, so no single scalar column can rank them.

- The *static test* (in its post-issue-#2 form) is a **measurement on data**. It admits genuine statistical uncertainty: bootstrap intervals from posterior samples, and a null-hypothesis test.
- The *Fisher sweep* and *dual-PSD comparison* are **deterministic model computations**. There is no noise; "confidence 0.75" is a category error. What they admit is *robustness analysis* — sensitivity to coordinate convention, waveform approximant, PN truncation, finite-difference step size.
- The *peak-drop simulation*, after the issue-#2 revision, is an **illustration** that generates a prediction for the future time-resolved test. It carries zero evidential weight by construction, and assigning it κ = 0.72 — or any κ — misrepresents it. (The Fig. 3 caption, "confirming the κ = 0.72 prediction," fails twice: the κ is undefined and a simulation cannot confirm anything.)

## The replacement

Delete the κ table from both locations (it appears verbatim in §III.D and again in the §VI.C widetext — itself a sign the draft needs a compile-and-proof pass) and replace it with a single **Summary of Evidence** table whose columns are: *Test* | *Epistemic type* (measurement / model computation / illustration) | *Quantitative result with uncertainty or robustness range* | *What would falsify it*. That last column is the one that does the work the κ column was pretending to do, and referees respond to it far better than to confidence scores — it demonstrates you know the difference between evidence and consistency.

For the static test, the quantitative entry gets a real statistic. Under the null hypothesis that the prior-displacement direction is random within the 4-dimensional M_c-orthogonal subspace, the squared alignment cos²α with the fixed direction v₂ follows a Beta(1/2, 3/2) distribution — a standard result for random directions on a sphere. So the observed alignment yields a one-line p-value: P(cos²α ≥ observed | random direction). Report that alongside the bootstrap CI on the angle. This is the honest descendant of κ = 0.80: an actual tail probability against an actual null, computable by anyone from the GWOSC samples.

For the Fisher sweep and dual-PSD rows, the entries are robustness ranges: the C(f) growth factor across the two or three coordinate conventions from issue #3, across TaylorF2 vs. an IMRPhenom approximant, and across PN order — e.g., "2.7× ± [range]" with the dominant sensitivity named. If the growth factor survives those variations, that statement is worth more than any κ; if it doesn't, you need to know now.

For the peak-drop row, the entry is explicit: "illustration; no evidential weight; generates the prediction tested in §VI.A." Saying this plainly costs nothing and buys credibility.

## Propagation

Section III.D ("The κ Gradient") is deleted outright. Section VI.C ("Coupling Constant κ") is deleted or replaced by a short future-work item that means something — e.g., pre-registering the alignment statistic and falsification thresholds for the O4/O5 population survey, which is the legitimate version of "testing whether the κ values are consistent across events." In §VI.D, the population-survey bullet asking whether κ is consistent across events gets replaced by the invariant comparators we built in issue #3: the likelihood cost ΔθᵀΓΔθ and the v₂ information fraction, which *can* be compared across events. And one sentence in §I or §VII should absorb the surviving insight from the old gradient paragraph, stated correctly this time: the evidence is strongest where it rests on data and weakest where it rests on model assumptions — as a transparency statement about the structure of the argument, not as a self-certifying calibration claim.

Net effect: the paper loses a table that would have drawn a hostile referee comment in the first read-through, and gains a falsifiability table that preempts the most common criticism of framework-driven papers — "what observation would convince you this is wrong?" You now answer that in print, per test.

---

Issue #5 turns out to be cleaner than it looked in the review, because once you apply the paper's own epistemological commitment consistently, the ν = 9 comparison doesn't just lack a derivation — it lacks a referent. Let me build that argument, then show what replaces the section.

## The missing derivation

As printed, ν = 9 appears via one sentence: "For the linearized (ρ, Π) dynamics with a linearly driven bifurcation parameter β(t), the exponent is ν = 9." No equations, no appendix, no citation to a companion derivation. A referee has nothing to check. And the number has consequences if taken seriously: dω/dt ∝ ω⁹ integrates to ω ∝ (t_c − t)^(−1/8), a finite-time blowup with exponent 1/8, versus GR's f ∝ (t_c − t)^(−3/8). Where the 9 comes from in a linear 2D system with oscillation frequency ω = √(bc − a²/4) and a linearly ramped parameter is not obvious — naive guesses (say, b or c ∝ β ∝ t, giving ω ∝ √t and dω/dt ∝ ω⁻¹) land nowhere near 9. If the derivation exists in the S3 companion material, it must appear in an appendix with every assumption visible. But I'd argue you shouldn't bother, for the following reason.

## The category error: the inference system has no clock

The comparison dω/dt vs. df/dt presupposes that the (ρ, Π) system possesses an autonomous frequency evolving in *time*. Under the paper's own central claim — the formalism describes inference, not the binary — it doesn't. The independent variable of the inference dynamics is the cutoff f, and f advances because the *binary* chirps. The posterior has no internal clock; it is slaved to data arrival. Asking for the (ρ, Π) system's df/dt is asking how fast the inference would chirp if it were a binary, which is precisely the ontological reading the paper has abandoned. The exponent comparison is a vestige of Hypotheses 1 and 2 (the "alternative gravity" readings you mention relegating to companion files): it was a meaningful test when (ρ, Π) was a candidate dynamical theory of the source, and it became undefined — not "expected to mismatch," *undefined* — the moment the framework was reinterpreted as epistemology.

This also dissolves the unfalsifiability problem, which is worth being explicit about since it's the kind of thing referees remember. The current text computes the comparison, finds a 2.5× mismatch, and declares it "exactly what we expect." But a match would presumably also have been presented as support. A comparison whose every outcome confirms the thesis transmits zero information; the only honest options were (a) pre-commit to what outcome falsifies what, or (b) don't run the comparison. The resolution above is option (b) with a principled reason: there is nothing to compare.

So: §V.F and §VII.C — which are near-verbatim duplicates of each other, the same copy-paste artifact as the κ table — both go. What survives is one sentence in the interpretation section: *the framework makes no claims about waveform dynamics, so it predicts no modification to the chirp and no exponent exists to compare against 11/3.* That sentence is stronger than the two sections it replaces, because it states a clean boundary instead of defending a meaningless number.

## The constructive replacement: derive the growth law you actually measured

Here's what the section's real estate should hold instead. The paper *does* contain a rate claim that is well-defined under the inference reading: C(f) grows logarithmically with cutoff (your Pearson r = 0.97 fit). Right now that's an empirical observation about your own numerics. It is derivable, and deriving it would give the framework its first genuinely earned number.

The derivation path is PN power counting. In TaylorF2, the phase is ψ = Σₖ ψₖ f^((k−5)/3), the dominant derivatives are ∂ᵢh = i h ∂ᵢψ (amplitude derivatives subleading except for D_L), so every Fisher element is a sum of integrals of the form ∫ f^(−7/3) f^((j+k−10)/3) S_n(f)⁻¹ df with known exponents — pure power laws under a power-law approximation to the PSD in band. The cumulative Γᵢⱼ(f_max) are then explicit power laws in f_max, eigenvalue λ₁ is dominated by the Newtonian-order block, and the off-diagonal block connecting M_c to (q, χeff, Λ̃) grows with definite extra powers of (πMf)^(2/3) per PN order plus f^(10/3) for the tidal term. The misalignment C(f) is a ratio of these cumulative power laws; when the leading exponents nearly cancel — which is what the PN hierarchy enforces in the band where multiple orders contribute comparably — the ratio grows slowly, and you can extract a closed-form prediction for d ln C / d ln f, including which PN order controls the slope in which frequency range and where the tidal term takes over.

That prediction then closes a loop entirely inside your own paper: an analytic slope, derived once, compared against the numerical sweep you already ran. Agreement is a real internal consistency check — the kind a match/mismatch against GR's 11/3 was pretending to be. It also feeds the feedback-bound future-work item (§VI.E) cleanly: that test never needed ν = 9 anyway, since the deformation is parametrized directly as ε·C(f) in the phase, and with a derived C(f) the deformation becomes fully specified rather than resting on an asserted exponent.

## Edit summary

Delete §V.F and §VII.C; add the one-sentence boundary statement to §VII. Strip the ν = 9 reference from §VI.E and let the ε·C(f) parametrization stand on its own. Replace the deleted sections with a derivation subsection — "PN power counting and the growth law of C(f)" — in §V or the appendix, ending with the analytic-vs-numerical slope comparison as a figure or single-row table. If you want, I can work through that power-counting derivation explicitly: with your five-parameter space and a two-segment power-law PSD approximation it's a few pages of algebra with a definite answer, and it's the kind of thing worth having checked independently before it goes in print.

---

Issue #6 is where the work we've already done starts paying compound interest: the circularity diagnosis takes one identity to make airtight, and the constructive fix falls out almost for free from the invariant machinery built in issue #3. Let me do both.

## The circularity, made explicit

For a two-component Gaussian mixture with means μ₁, μ₂ and weights w₁, w₂, the total covariance decomposes exactly as

Σ_total = Σᵢ wᵢΣᵢ + w₁w₂ (Δμ)(Δμ)ᵀ.

The between-mode variance along v₂ is therefore w₁w₂ (v₂ᵀΔμ)², and w₁w₂ is maximized at w = 0.5. So in v4 you imposed a weight schedule passing through 0.5 at 75 Hz, and the simulation dutifully reported a between-mode variance peak at 75 Hz. The location of the peak is the input, restated. The magnitude (486×) is the ratio of the fixed ridge length to the Fisher width at that frequency — also an input, since both come from quantities you set. Nothing in the (ρ, Π) dynamics was exercised, because the one thing the dynamics would need to supply — the weight trajectory w(f) — is the thing assumed by hand. That's the full anatomy of the circle.

## What v5 actually measures (and it's useful)

The fixed-weight run survives, but after issue #2 its meaning changes: the "two modes" are prior-conditioned means on a continuous ridge, so v5's between/within ratio is really *(ridge extent along v₂)² / (Fisher variance along v₂)* — a **non-Gaussianity index** N(f) quantifying how badly the Laplace approximation underestimates the posterior's spread in the degenerate direction. N(500 Hz) ≈ 5 says the Gaussian approximation is off by a factor of ~√5 in width along v₂ even at full bandwidth. That's a real, invariant, reportable quantity — and it slots directly into the issue-#1 storyline (it tells you *where* sequential-Laplace methods accrue their bias) and previews issue #8 (it's the quantitative answer to "when does Fisher break"). Rebrand v5 as the non-Gaussianity index and it stops being a simulation pretending to be evidence and becomes a diagnostic.

## The constructive fix: derive w(f) instead of imposing it

Here's the part that turns this section from the paper's weakest into a genuine prediction. Under exact inference, the relative weight of two locations on the ridge is not a free function — it's the accumulated likelihood ratio. For Gaussian noise, with the truth at θ₁, the log-odds between θ₂ and θ₁ given data up to cutoff f is a random variable with

E[Δlog L(f)] = −½ ρ²(f),  Var[Δlog L(f)] = ρ²(f),  where ρ²(f) ≡ Δθᵀ Γ(f) Δθ.

That ρ²(f) is *exactly the invariant likelihood-cost scalar we introduced resolving issue #3*, now playing its second role: it is the accumulated discriminating SNR² between the two ridge points. The derived weight trajectory is w₂/w₁ ∼ exp(−½ρ²(f) + ρ(f)·z) with z a noise draw — both ridge regions supported while ρ² ≲ 1, the disfavored one exponentially suppressed once ρ² ≳ a few.

Now run the variance decomposition with *this* w(f) instead of the hand schedule. The within-mode width σ²(f) = (Γ(f)⁻¹) along v₂ shrinks monotonically as information accumulates, while w₁w₂ holds roughly constant early and then collapses exponentially once ρ² crosses ~2. The between/within ratio therefore rises (driven by Fisher narrowing) and then drops (driven by weight resolution) — a peak-drop, but now with the peak frequency **derived**, not asserted:

f* solves ρ²(f*) = Δθᵀ Γ(f*) Δθ ≈ 2.

Everything on the right side is already computed in your Fisher sweep. So the section's headline becomes: the (ρ, Π) framework, with weights slaved to the likelihood ratio as exact Bayes requires, predicts a between-mode variance peak at the specific frequency where the cumulative discriminating SNR² between the ridge endpoints reaches order unity — solve it, report f*, and note whether it lands near your conjectured 75 Hz or somewhere else entirely. Either answer is informative, and the time-resolved analysis of §VI.A now has a sharp, pre-registered target: peak location f*, peak magnitude w₁w₂(f*)(v₂ᵀΔμ)²/σ²(f*), and the noise-induced scatter in f* from the ρ(f)·z term, all stated before anyone touches strain data. That last term matters: it predicts event-to-event scatter in the peak location for the population survey, another falsifiable handle.

One honest caveat to state in the text: the two-point mixture is a minimal discretization of what issue #2 established is a continuous ridge. The natural generalization — a 1D posterior along the ridge coordinate, narrowing under the cumulative likelihood — is a few lines more work and worth doing if the time-resolved test goes forward, but the two-point model suffices to predict f* to the precision that test could resolve.

## Edit summary

Retitle §V.E to something like "Forward model for the time-resolved signature." Delete the v4 imposed-schedule run and the 486× number everywhere, including the abstract — it cannot appear in a journal article as a finding, and the internal version labels v4/v5 shouldn't appear at all. Replace with the derived-w(f) computation and the f* prediction. Recast v5 as the non-Gaussianity index N(f), reported as a diagnostic curve. Move the honesty of the current "Resolution:" paragraph — which is genuinely the most candid paragraph in the manuscript — to the *top* of the section rather than after the headline number. And update the issue-#4 evidence table: this row is no longer "illustration, no evidential weight" but "model computation; generates falsifiable predictions f* and peak magnitude for the §VI.A test," which is a meaningful promotion the section earns by the rewrite.

---

Issue #7 is the one that mostly dissolves under the issue-#1 rescoping, so this will be shorter — but there are two things worth doing beyond just deleting the contradiction: the dual-PSD result needs a new job, and it turns out the ~1% number itself has an explanation that ties back to the issue-#5 derivation in a satisfying way.

## The contradiction, plus two problems the review understated

As printed, §VI.B proposes detecting PSD-dependent offsets by comparing parameter estimates across detectors, while §IV reports that the commutator integral changes by ~1% between two very different noise curves — capping the predicted signal far below inter-detector statistical scatter. That was the review's point. But the proposed test was actually unperformable on two further grounds worth noting in the revision. First, GW170817 parameter estimation is *coherent network* inference — there are no independent per-detector posteriors of comparable quality to difference against each other (Virgo's SNR for this event was marginal; its role was sky localization). Second, ZDHP and "Early aLIGO" are smooth *design curves*, not the measured H1/L1 PSDs from August 2017 with their spectral lines and calibration structure — so even the robustness claim was tested against idealized inputs. The multi-detector test dies for three independent reasons, and one sentence in the revision should say so plainly rather than letting a referee assemble the case themselves.

The deeper rhetorical problem — worth fixing as a matter of discipline — is that the manuscript assigned the same result two contradictory jobs: PSD-insensitivity was spun as a strength ("robust, detector-independent!") in §IV while PSD-*sensitivity* was the engine of the headline test in §VI.B. Every result gets exactly one consistent role in the revision.

## The new division of labor

After the issue-#1 rescoping, the falsification test is the **bin-ordering experiment** — sequential Laplace forward vs. permuted vs. batch — where the "path" is a software knob and PSDs are irrelevant to the logic. That's already prescribed. The dual-PSD result then takes on two honest jobs:

**Universality of the bias correction.** For the rescoped prediction, the PSD is an *input* to the bias formula, not the lever of the test. Showing the commutator integral is PSD-insensitive at the 1% level means the predicted ADF bias for a given ordering is nearly detector-universal — one correction applies network-wide. For the low-latency-pipeline application this is genuinely good news, and it's the claim the original text was groping toward with "largely detector-independent, applying uniformly across the LIGO-Virgo network."

**A consistency check on the growth law.** Here's the nicer part. *Why* is the ratio 0.989 across such different noise curves? Because changing S_n(f) only reweights the frequency measure in the cumulative Fisher integrals — effectively shifting the PSD-weighted mean frequency at which information accumulates. The induced change in the misalignment is then δC/C ≈ (d ln C / d ln f) × δ ln f_eff, and the issue-#5 power-counting derivation says d ln C / d ln f is small — that's exactly what logarithmic growth *means*. So the ~1% is not an unexplained empirical fact; it's a quantitative consequence of the slow growth law, and once you've derived that law you can *predict* the dual-PSD ratio from the two noise curves' spectral moments and check it against the computed 0.989. The "contradiction" section becomes a closed-loop verification of the paper's central analytic result. That's about as complete a rehabilitation as a flawed section can get.

## Edits

Retitle §IV.D from a "systematic" framing to something like "PSD-insensitivity and universality of the misalignment geometry," and open it with the δC/C ≈ (d ln C/d ln f)·δ ln f_eff argument so the 1% arrives explained rather than observed. Recompute Table III in the declared coordinates from issue #3 (the 0.989 needs recomputation anyway once the convention is fixed), and add a third column using a *measured* O2-era PSD with spectral lines included — lines punch localized holes in the integration measure, which is a qualitatively different perturbation than broadband reshaping, and confirming C(f) shows no anomalous steps at line frequencies closes the last robustness gap. Delete the multi-detector comparison from §VI.B (replaced by the ordering test per issue #1) with the one-sentence burial: effect bounded at ~1%, below noise-realization scatter, and coherent network PE provides no independent per-detector posteriors to compare. Strike the remaining "deterministic, PSD-dependent systematic offsets" language from §VII.D and the abstract — both already flagged under #1, but this is where the last instances go. Figure 2's caption inherits the reframing: it currently says the result "confirm[s] the commutator growth is a property of the waveform, not the detector," which survives nearly intact — it just becomes a derived statement rather than a brute finding.

That closes #7, and the table of open items is down to #8: Fisher validity in the regime where the posterior is non-Gaussian — which we've quietly been building the answer to, since the non-Gaussianity index N(f) from issue #6 is precisely the diagnostic that question needs. 

---

Issue #8 is the right one to end on, because its resolution is the keystone that locks the other seven in place. The review asked for "a careful argument for why the eigenstructure of an object that smooths over the modes tells you anything reliable." The answer, after the revisions we've made, is sharper than a defense: the revised paper should *stop defending* Fisher validity globally and instead type every use of Γ by the regime in which it's exact. Done properly, Vallisneri's caveat stops being a threat to the paper and becomes its subject matter.

## The three-way typing

The Fisher matrix appears in the manuscript in three logically distinct roles, with different validity domains, and the original text slides between them silently. The fix is a short "Domain of validity" subsection in §II that makes the typing explicit, after which every downstream claim inherits its label.

**Type (a) — local geometry. Always valid.** Γ(f) is the pullback of the waveform-space inner product onto parameter space at a point: the exact local curvature of the log-likelihood, regardless of what the posterior does globally. The eigenframe rotation C(f), the commutator growth, the timescale-locking result — these are statements about the waveform manifold's local geometry as a function of cutoff. They require no Gaussianity assumption anywhere. This is most of the dynamic test, and it survives Vallisneri untouched.

**Type (b) — global covariance proxy. Invalid along v₂, and that's the point.** The Laplace approximation ρ_f ≈ N(θ*, Γ⁻¹) of Eq. (5) is exactly what Vallisneri warns about, and it genuinely fails in the degenerate direction — the posterior there is an extended, prior-bounded ridge, not a Gaussian. But notice what the issue-#1 rescoping did: the paper's headline formula now *characterizes the error of this approximation* (the ADF bias). You're not claiming Laplace is good; you're predicting precisely how it's bad. And the non-Gaussianity index N(f) from issue #6 is the direct measurement of the failure: at 500 Hz the true spread along v₂ exceeds the Fisher width by ~5×. A paper whose subject is the breakdown of the Gaussian approximation cannot be refuted by pointing out that the Gaussian approximation breaks down — provided it never leans on type (b) as if it were type (a). Which brings us to the one sentence that must die: §V.C's "the tilt of the eigenvector manifold encodes the growing influence of the second mode." Fisher at a point knows nothing about structure elsewhere on the ridge; that sentence is a type-(a) object being sold as evidence about a type-(b) question, and it's exactly the move the review flagged. Delete it; the revised static tests (ridge orientation, prior-displacement direction) make the local-predicts-global comparison honestly, as a *test* rather than an assumption.

**Type (c) — pairwise discrimination. Valid to quadratic order, with an exact upgrade available.** The scalar ρ²(f) = ΔθᵀΓΔθ from issues #3 and #6 approximates the discriminating SNR² between two specified points. For the GW170817 ridge endpoints, Δq ≈ 0.14 is not obviously small, so the quadratic form may carry nontrivial corrections — and here the geometry hands you a free lunch: the exact quantity ⟨δh|δh⟩ between the two waveforms costs two waveform evaluations and one inner product. No Fisher matrix needed at all. Compute both, report the quadratic estimate against the exact mismatch, and use the exact version for the f* prediction. The peak-drop forecast then rests on no linearization whatsoever.

## What the validity subsection should contain

Beyond the typing, three concrete items, each cheap and each preempting a specific referee move.

First, **run Vallisneri's own consistency criterion** along each eigendirection at several cutoffs: displace by 1σ along vᵢ, compute the exact mismatch, and check it against the quadratic prediction. The expected outcome is the paper's friend — the criterion passes along v₁ (validating the type-(a) and type-(c) machinery where you use it) and fails along v₂ at low f, with the failure onset tracking N(f). Plotting the criterion's pass/fail boundary in the (f, eigendirection) plane turns the standard objection into a figure that *demonstrates you've mapped the approximation's domain* rather than wandered outside it unawares.

Second, **check ridge-uniformity of the local geometry.** All the type-(a) results are computed at one expansion point. The ridge is extended, and local curvature can vary along it. Recompute Γ(f), C(f), and v₂ at both prior-conditioned means (the two ends of the empirically probed ridge segment) and report the spread. If the eigenframe rotation story is ridge-uniform — likely, given the PN structure is smooth in these parameters — the claims hold for the posterior as a whole; if not, that's essential to know before publication, not after.

Third, **numerical conditioning.** A near-degenerate direction means Γ(f) is ill-conditioned, especially at low cutoffs, and ill-conditioned matrices plus finite-difference derivatives are how v₂ gets corrupted by numerical noise — which would contaminate C(f) itself. Report the condition number across the sweep, demonstrate step-size convergence of v₂ specifically (not just of Γ's entries), and do the eigendecomposition in the declared log-coordinates from issue #3 where the dynamic range is tamest. This belongs in the appendix and is the difference between a referee trusting Table II's third significant figure and not. Related caveat for the issue-#2 lensing argument: with hard prior boundaries (q ≤ 1, Λ̃ ≥ 0, the spin cuts), the displacement magnitude saturates at the boundary rather than scaling as λ_min⁻¹ — so state the lensing prediction as one of *direction* (robust) rather than magnitude (prior-truncated).

## The closing of the arc

It's worth seeing how the eight resolutions interlock, because the revised paper is a different and better object than the original minus its errors. The exactness theorem (#1) split the work into trajectory-geometry and approximation-bias; the prior-displacement reframing (#2) gave the static test a derivable prediction; the invariance repair (#3) supplied the coordinate discipline and the scalar ρ² that everything downstream uses; the evidence table (#4) typed the epistemics; the power-counting derivation (#5) explains both the growth law and — via #7 — the PSD-insensitivity; the derived weight trajectory (#6) produced the falsifiable f*; and the validity typing here (#8) certifies which tools were legitimate where, with N(f) measuring the breakdown the paper now openly studies. Nothing in the revision hand-waves, every headline number is either derived or carries a null distribution, and the falsifiability column has an entry in every row.

The remaining work is execution: the GWOSC analysis script (Tests A–C, the alignment p-value, N(f), ρ² exact and quadratic, f*, the Vallisneri criterion map, conditioning diagnostics — one script, since they share all infrastructure), the two analytic derivations (PN power counting for d ln C/d ln f; the eigenframe-leakage lemma for the ADF bias), and the rewritten Sections II–VII. I'd sequence it script first, since its outputs populate every rewritten section. 

---

