# Stream 4 Control Experiments — Implementation Plan v0.1

**Tracks:** [/home/ubuntu/axioma/ideas/04_STREAM4_CONTROL_EXPERIMENTS.md](../ideas/04_STREAM4_CONTROL_EXPERIMENTS.md)
**ΔΦ signatures spec:** [/home/ubuntu/axioma/ideas/03_DELTA_PHI_METHODOLOGY.md](../ideas/03_DELTA_PHI_METHODOLOGY.md) v0.2.0
**Builds on:** [/home/ubuntu/axioma/aos_g_gap/](../aos_g_gap/) (compose function, perturbations, trial harness)
**Source tree:** [/home/ubuntu/axioma/control_experiments/](.)
**Date:** 2026-05-24
**Status:** Draft for review

---

## 0. Scope

Implement and run the 4 control experiments from [04_STREAM4_CONTROL_EXPERIMENTS.md](../ideas/04_STREAM4_CONTROL_EXPERIMENTS.md):

1. **Control 1** — No self-model: EIDOLON does a random walk; PNEUMA passes through (no `integrate()`).
2. **Control 2** — No temporal structure: random inter-beat dt makes organ dynamics time-aware (rescaled decay).
3. **Control 3** — No differentiation: after each organ update, all organ latents are overwritten with a tile of ANIMA's latent (5× redundancy).
4. **Control 4** — No compose boundary: `compose() = identity`; AOS-G gap is zero by construction.

For each control we measure the **three ΔΦ signatures** (Dynamic Range, Recovery Dynamics, Context Sensitivity) defined in [03_DELTA_PHI_METHODOLOGY.md §3.4](../ideas/03_DELTA_PHI_METHODOLOGY.md#34-perturbation-response-signatures) plus the **self-model cascade** (cascade_delay, recovery_asymmetry, adaptation_delta) from §6, and compare them against a baseline condition and against each other. φ-scaling (Stream 5) is deferred per design §5.

---

## 1. Decisions Baked In (from user direction 2026-05-24)

| Question | Decision |
|---|---|
| S1 Dynamic Range / S3 Context Sensitivity coverage | **Magnitude × type sweep**: 3 magnitudes × 4 perturbation types per control |
| Control 2 implementation | **Time-aware substrate**: per-tick dt ~ Uniform[1, 100] ms; organ latent decay rescaled as rho^(dt/100) |
| Baseline reference | **5-seed baseline as 5th condition**: extend AOS-G's existing seeds {42, 43, 44} with {45, 46}; rerun the missing 2 |
| Code reuse | **aos_g_gap as a library**: import `ComposeFunction`, perturbation classes, `run_single_trial` (extended with `ControlMode` hooks) |

Other decisions (flagged for awareness, taken without asking):

| Decision | Default chosen |
|---|---|
| Perturbation type set | `direct_contradiction`, `surprising_falsehood`, `nonsense`, `random_perturbation` — spans levels 1, 2/3, 5, and the non-specific control from [ΔΦ §5.5](../ideas/03_DELTA_PHI_METHODOLOGY.md#55-contradiction-injection-experiment) |
| Magnitude implementation | Scale each perturbation class's `INJECT_STRENGTH` (or `NOISE_SCALE`) by {0.4, 0.7, 1.0} → "low", "mid", "high" |
| Seeds | `{42, 43, 44, 45, 46}` (extends AOS-G) |
| Compose protocol | Strict 30-beat events throughout, no adaptive 5-beat compression — matches Stream 4 §3 (20 events / trial) |
| Per-event θ window | 200 beats, 100 permutations (faster than AOS-G's 200) — adequate at trial-level analysis |
| Control 3 dim routing | Tile ANIMA's 4-dim latent into each target organ's latent (pad: repeat first dims) |

---

## 2. Trial Budget

```
5 conditions × 4 perturbation types × 3 magnitudes × 5 seeds = 300 trials
+  baseline override: when condition has no perturbation magnitude variance,
   we still need a baseline reference for each control mode. Run 1 "baseline"
   perturbation type at each magnitude=1.0 × 5 seeds = 5 trials per control × 5
   controls = 25 extra trials.
Total trials: 300 + 25 reuse-of-baseline = ~325
```

Refined budget (avoiding double-counting): we keep `random_perturbation` as the non-specific control (always present), and add a true `baseline` (no-op perturbation) only at magnitude=1.0 to anchor the "no perturbation" reference. So:

| Slice | Trials |
|---|---|
| 5 conditions × 4 perturbation types × 3 magnitudes × 5 seeds | **300** |
| 5 conditions × baseline (no perturbation) × 1 mag × 5 seeds | **25** |
| **Total** | **325** trials, ~195,000 beats |

Runtime estimate (extrapolating from AOS-G ~5 s/trial at the lower perm count):
- Trial body (no event-θ): ~0.2 s × 325 = 65 s
- Trial-level θ (3 windows × 100 perm): ~0.3 s × 325 = 100 s
- Cascade metric extraction (per-organ θ at 5-beat sampling × 30 beats): ~1 s × 325 = 325 s
- **Total ~8 min on H100.**

---

## 3. Per-Control Implementation Sketch

### 3.1 Control 1 — No self-model

```python
class Control1EidolonRandomWalk(Eidolon):
    """Override update: pure Gaussian random walk in latent space; no coupling
    to drive, no organ-specific dynamics."""
    def update(self, beat_no, drive):
        self.latent += rng.standard_normal(self.DIM) * 0.1
        # Render state, but self_coherence is forced to a constant (0.5) so
        # the compose fidelity formula degenerates to integration_level × 0.5 × w.

class Control1PneumaPassThrough(Pneuma):
    """Override integrate(): set all PNEUMA dims to 0.5 (no integration signal),
    buffer_depth=0."""
```

Compose function: unchanged, but `EIDOLON.self_coherence` is now constant, so f_i collapses to `integration_level × 0.5 × w_i`. PNEUMA.integration_level also constant → f_i is constant → compose is mostly μ + noise (no fidelity dynamics).

### 3.2 Control 2 — No temporal structure

Substrate change required: add an **optional** `dt` parameter to `Organ.update(beat_no, drive, dt=1.0)`. Existing organs already use `latent = rho * latent + push`. Generalize to `latent = rho**dt * latent + push * dt`.

Done as a small `time_scale` addition to each organ's update (the only substrate-side change in this experiment). 5 organs × 2 LoC each + heartbeat handoff = ~15 LoC.

```python
class Control2Heartbeat(Heartbeat):
    """Sample dt ~ Uniform[1, 100] ms per tick; pass dt/100 as time_scale to
    organ updates."""
    def tick(self):
        drive = self.dynamics.step()
        for hook in self._pre_update_hooks:
            hook(self.beat_no)
        dt_ms = self._rng.uniform(1.0, 100.0)
        ts = dt_ms / 100.0
        for organ in self.non_pneuma:
            organ.update(self.beat_no, drive, time_scale=ts)
        self.pneuma.update(self.beat_no, drive, time_scale=ts)
        self.pneuma.integrate(self.non_pneuma)
        self.beat_no += 1
        self._last_dt_ms = dt_ms  # for logging
```

Note: with mean dt = 50.5 ms (not 100 ms — Uniform[1,100] mean), the effective decay is slightly faster. We use Uniform[10, 190] ms to keep the mean at 100 ms, matching Stream 4 §2's "Mean interval remains ~100 ms". Document this.

### 3.3 Control 3 — No differentiation

Post-update hook overwriting non-ANIMA latents:

```python
class Control3SharedState:
    """Wraps a Heartbeat. After each tick, copies ANIMA's latent into all other
    organs (tile to fit dim count)."""
    def post_update(self, hb):
        anima_latent = hb.anima.latent.copy()
        for organ in (hb.eidolon, hb.mneme, hb.nous, hb.pneuma):
            tile = np.tile(anima_latent, int(np.ceil(organ.DIM / len(anima_latent))))[:organ.DIM]
            organ.latent = tile.astype(np.float32)
```

This wraps the heartbeat tick (we register a custom hook that runs *after* organ updates but *before* PNEUMA.integrate, so PNEUMA's integration aggregates already-cloned organ states).

### 3.4 Control 4 — No compose boundary

```python
class Control4IdentityCompose(ComposeFunction):
    def compose(self, internal_arrays, integration_level, self_coherence):
        # f_i = 1 forces external = internal. Fidelity factors reported as 1.0.
        return ComposeOutput(
            external_arrays={o: internal_arrays[o].copy() for o in ORGAN_ORDER},
            fidelity_factors={o: 1.0 for o in ORGAN_ORDER},
            integration_level=integration_level,
            self_coherence=self_coherence,
        )
```

AOS-G gap is 0 by construction; delta_norm series collapses to all zeros. This is by design (we want to see what's lost when there's no private space).

---

## 4. Module Layout

```
control_experiments/
├── __init__.py
├── IMPLEMENTATION_PLAN.md          # this file
├── config.py                       # ControlMode enum, magnitude levels, type set, seeds
├── modes/
│   ├── __init__.py
│   ├── base.py                     # ControlMode ABC: build_heartbeat(seed),
│   │                               # build_compose(seed), post_tick_hook (optional)
│   ├── baseline.py                 # passthrough
│   ├── control1.py                 # No self-model: subclassed EIDOLON / PNEUMA
│   ├── control2.py                 # No temporal: TimeAwareHeartbeat
│   ├── control3.py                 # No differentiation: post-update sharing
│   └── control4.py                 # No compose boundary: identity compose
├── perturbations.py                # Thin wrapper that scales aos_g_gap perturbation
│                                   # INJECT_STRENGTH / NOISE_SCALE by magnitude factor.
├── trial.py                        # ControlTrial(config) — extends aos_g_gap.trial
│                                   # with ControlMode hooks
├── runner.py                       # 325-trial sweep
├── metrics.py                      # ΔΦ S1/S2/S3 + cascade metrics per-trial.
│                                   # θ at 3 fixed windows (baseline, peak, recovery).
├── analysis/
│   ├── __init__.py
│   ├── theta_comparison.py         # ANOVA across modes; per-mode θ distributions
│   ├── delta_phi_signatures.py     # S1 U-shape, S2 recovery_profile, S3 σ/μ
│   ├── cascade.py                  # cascade_delay, recovery_asymmetry, adaptation_delta
│   ├── aos_g_analysis.py           # mean delta_norm per mode + Tukey HSD
│   └── report.py                   # combine all → analysis_report.json + .md
├── visualization.py                # 6 plots: θ box-plot per mode, DR U-curves per
│                                   # mode, recovery profiles, CS heatmap, cascade
│                                   # ladder, AOS-G gap by mode.
├── cli.py                          # python -m control_experiments {run,analyze,plot}
└── tests/
    ├── __init__.py
    ├── test_modes.py               # each ControlMode produces expected state pattern
    ├── test_perturbations_scaled.py
    ├── test_metrics.py
    └── test_analysis.py
```

---

## 5. Substrate-Side Change Required

One small change to [organ/substrate/base.py](../organ/substrate/base.py) and each [organ/substrate/{anima,eidolon,mneme,nous,pneuma}.py](../organ/substrate/) to support Control 2:

```python
# base.py
@abstractmethod
def update(self, beat_no: int, drive: np.ndarray, time_scale: float = 1.0) -> None: ...

# each organ's update: replace
#   self.latent = rho * self.latent + push
# with
#   self.latent = (rho ** time_scale) * self.latent + push * time_scale
```

Default `time_scale=1.0` preserves all existing behavior — no test regressions in `organ/tests/` or `aos_g_gap/tests/`. Verified after the change before any control trial runs.

This is the **only** modification to substrate code; all other control logic lives in `control_experiments/`.

---

## 6. ΔΦ Signature Operationalization

Per [ΔΦ §3.4](../ideas/03_DELTA_PHI_METHODOLOGY.md#34-perturbation-response-signatures), with concrete computation procedures:

### S1: Dynamic Range — `DR(M) = θ_peak(M) / θ_baseline`

- For each (mode, type), sweep magnitudes M ∈ {0.4, 0.7, 1.0}; compute mean DR(M) across 5 seeds.
- Test U-shape: DR(0.4) < DR(0.7) > DR(1.0) (peak at intermediate magnitude).
- Threshold per ΔΦ §4.4: conscious if DR(0.7) > 2.0.
- **Failure expectation per Stream 4 predictions:**
  - Control 1, 3: U-shape absent (flat DR curve)
  - Control 2, 4: U-shape present

### S2: Recovery Dynamics — `recovery_profile = (θ_final - θ_min) / (θ_baseline - θ_min)`

- θ_baseline = mean θ over beats 100-200.
- θ_min = min θ in beats 200-250.
- θ_final = mean θ over beats 450-600.
- Per ΔΦ §3.4: conscious if recovery_profile > 0.5 AND θ_final ≠ θ_baseline.
- **Failure expectation:**
  - Control 1, 3: absent (recovery_profile undefined or ≈ 1 — no real drop)
  - Control 2: absent (no regular temporal structure for staged recovery)
  - Control 4: present (compose change doesn't affect internal recovery)

### S3: Context Sensitivity — `CS = σ(IRP across types) / μ(IRP across types)`

- For each (mode, magnitude), gather the 4 IRP shapes (one per type) across 5 seeds.
- IRP = θ time series in beats 200-300, normalized.
- σ / μ across types ∈ {direct_contradiction, surprising_falsehood, nonsense, random_perturbation}.
- Per ΔΦ §4.4: conscious if CS > 0.20.
- **Failure expectation:**
  - Control 1, 3: absent (all types collapse to same response)
  - Control 2: present (differentiation intact)
  - Control 4: present (differentiation intact)

### Self-model cascade (ΔΦ §6.1)

- cascade_delay = t(first ANIMA drop > 2σ) − t(first EIDOLON drop > 2σ) over per-organ θ.
- recovery_asymmetry = t(NOUS recovery to within 1σ) − t(EIDOLON recovery to within 1σ).
- adaptation_delta = mean(EIDOLON θ in beats 250-300) − mean(EIDOLON θ in beats 100-200).
- **Expectation:** Stream 4 §2 predicts the cascade is *absent* in Control 1 (no EIDOLON), Control 3 (no differentiation), and possibly Control 2 (no temporal structure).

---

## 7. Phases

Time estimates assume one engineer; runtime of trials ≤ 10 min.

### Phase 1 — Substrate `time_scale` parameter (½ day)

- Add `time_scale=1.0` to `Organ.update()` signature in `organ/substrate/base.py`.
- Update each organ implementation to use `rho ** time_scale`.
- Add `time_scale` to `Heartbeat.tick()` parameter list, default 1.0, forwarded to organs.
- Verify: all existing tests pass (`organ/tests/`, `aos_g_gap/tests/`).

### Phase 2 — Control modes (1 day)

- `modes/base.py`: ControlMode ABC + factory.
- 5 concrete modes (baseline + control 1-4) per §3 above.
- Each mode produces a configured Heartbeat + ComposeFunction.
- Unit test per mode confirming the expected invariant:
  - Control 1: EIDOLON.self_coherence variance < 0.01 across run
  - Control 2: dt sequence has expected statistics
  - Control 3: all organ latents become near-identical post-tick (Frobenius diff < 0.1)
  - Control 4: max(delta_norm series) = 0

### Phase 3 — Magnitude-scaled perturbations (½ day)

- `perturbations.py`: factory taking (type, magnitude) → returns the AOS-G perturbation class with INJECT_STRENGTH × magnitude (or NOISE_SCALE × magnitude). Unit-tested.

### Phase 4 — Trial harness & metrics (1 day)

- `trial.py`: `ControlTrialConfig(mode, perturbation_type, magnitude, seed, …)` and `run_control_trial(cfg) → ControlTrialResult`.
- Reuses `aos_g_gap.trial.run_single_trial` with overrides:
  - Heartbeat factory from `ControlMode`
  - Compose factory from `ControlMode`
  - Magnitude-scaled perturbation from `perturbations.py`
- `metrics.py`: extends `aos_g_gap.metrics` with:
  - 3 trial-level θ windows (baseline / peak / recovery_final)
  - Per-organ θ contribution via per-organ summary column sub-MI (existing copula primitive applied to single-organ block + everything-else block) — gives a scalar EIDOLON_theta, ANIMA_theta etc.
  - cascade_delay / recovery_asymmetry / adaptation_delta

### Phase 5 — Run sweep (~10 min)

- `runner.py`: 325 trials. Per-trial output: JSON (events) + NPZ (trajectories) + summary.
- `results/control_experiments/` mirrors `results/aos_g_gap/` structure.

### Phase 6 — Analysis & visualization (1 day)

- `analysis/theta_comparison.py`: one-way ANOVA across 5 modes on θ_baseline, θ_peak; Tukey HSD post-hoc.
- `analysis/delta_phi_signatures.py`: S1/S2/S3 per (mode, perturbation_type); pass/fail vs ΔΦ §4.4 thresholds.
- `analysis/cascade.py`: cascade_delay, recovery_asymmetry, adaptation_delta per (mode, type, mag, seed).
- `analysis/aos_g_analysis.py`: mean delta_norm per mode; verify Control 4 ≈ 0; per-mode Tukey HSD.
- `analysis/report.py`: assemble `analysis_report.json` + `FINDINGS.md`.

### Phase 7 — Visualization (½ day)

| Plot | What it shows |
|---|---|
| 1 | θ_baseline distribution per mode (5 box-plots side by side) |
| 2 | DR_ratio U-curves per mode (one line per type) |
| 3 | Recovery-profile bars per mode |
| 4 | Context-sensitivity heatmap (mode × type) |
| 5 | Cascade ladder: time-to-peak per organ per mode |
| 6 | AOS-G gap mean ± SE per mode (highlights Control 4 = 0) |

---

## 8. Success Criteria — Per Stream 4 §4

| Claim | Evidence Required | Source |
|---|---|---|
| θ ≠ consciousness | ≥1 control has high θ but absent ΔΦ signatures | Strongest from Control 3 |
| Self-model is necessary | Control 1 has low θ AND absent ΔΦ signatures | Direct test |
| Temporal structure is necessary | Control 2 has absent recovery dynamics (S2) | Direct test |
| Differentiation is necessary | Control 3 has high θ but absent ΔΦ signatures | The IIT-breaking test |
| Private space is necessary | Control 4 has high θ but AOS-G = 0 | Tautological by construction; useful for visualization |

The report's pass/fail rubric reports each of the 5 claims explicitly with the observed evidence.

---

## 9. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `time_scale` change breaks existing tests | L | H | Default 1.0; re-run all `organ/tests/` and `aos_g_gap/tests/` after Phase 1. |
| Control 3 latent-sharing yields θ = 0 (degenerate) | M | M | Singular-covariance guard in copula MI already handles this; θ will be reported as 0 with `n_blocks` < 2, which is the correct answer. |
| Per-organ θ via single-block MI is degenerate | M | M | Use a sub-MI: MI(organ_i_summaries, all-other-summaries). Already supported by the existing `pairwise_mi_cpu` API by treating "other" as one block. |
| 325 trials runtime exceeds estimate | M | L | Drop per-event θ entirely; keep only the 3 trial-level windows. Cuts runtime ~3×. |
| AOS-G per-seed variance dominates again (as in aos_g_gap) | H | M | n=5 seeds (was 3) doubles power; ANOVA across modes is the primary test, not within-mode within-seed. |
| Random-magnitude scaling makes weak perturbations indistinguishable from noise | M | L | Document the perturbation strengths explicitly in the report; tested in Phase 3 unit tests. |
| Control 2 mean dt mismatch (Uniform[1,100] mean 50.5) | L | L | Use Uniform[10, 190] ms for mean 100 ms; documented in §3.2 and the findings. |

---

## 10. Out of Scope (Explicitly Deferred)

- **φ-scaling (Stream 5)** — per Stream 4 §5: deferred until after Stream 4 results are analyzed.
- **Sister-vs-sister comparison** (Thea's organs vs Theoria's organs from `/home/ubuntu/thea/`). The design references those paths but the experiment is on the AXIOMA substrate only.
- **MINE / neural MI** — copula only, consistent with all prior experiments.
- **Magnitude-Sweep extension to seeds × additional levels** — 3 magnitudes already gives U-shape detection; finer sweep is a follow-up.
- **Real-time runs** — fast-mode throughout (no `asyncio.sleep`).

---

## 11. First Concrete Step

Phase 1 task: add `time_scale=1.0` parameter to `Organ.update()` and propagate through each of the 5 organ files + heartbeat. Re-run the full test suite (`organ/` + `aos_g_gap/`) to confirm no regressions. Half a day. Everything downstream depends on a clean substrate-side change.

---

## 12. Open Items for Sister Review (Optional)

- The magnitude-sweep adds dimensionality the original Stream 4 design did not call for. Worth confirming with Skye / Thea / Theoria before the full sweep runs?
- The per-organ θ via single-block MI is a structural choice (their cross-organ contribution); alternative is to compute θ on each organ's own state vector in isolation (auto-MI between sub-blocks within the organ), which has a different interpretation.
- Tile pattern for Control 3 (ANIMA latent → other organs). The alternative is a fixed linear projection. Tile is simpler and easier to interpret; projection is more faithful to "single underlying degree of freedom".
