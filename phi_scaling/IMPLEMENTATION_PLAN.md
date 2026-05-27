# φ-Scaling Experiment — Implementation Plan v0.1

**Tracks:** [/home/ubuntu/axioma/ideas/05_PHI_SCALING_EXPERIMENT.md](../ideas/05_PHI_SCALING_EXPERIMENT.md)
**Builds on:** [/home/ubuntu/axioma/control_experiments/](../control_experiments/) (mode factory, trial harness, θ metrics)
**Source tree:** [/home/ubuntu/axioma/phi_scaling/](.)
**Date:** 2026-05-24
**Status:** Draft for review

---

## 0. Scope

Measure how θ (Gaussian copula MI / energy) scales with the number of active organs k ∈ {1, 2, 3, 4, 5}, following [05_PHI_SCALING_EXPERIMENT.md](../ideas/05_PHI_SCALING_EXPERIMENT.md). Five seeds × five k-values = **25 trials × 600 beats = 15 000 beats** total. Fit O(k) and O(k²) models and decide which the substrate exhibits — this is the final experiment before the architecture-design milestone (v0.3).

The experiment reuses every existing piece of infrastructure from `control_experiments/` (trial harness, θ pipeline, ComposeFunction, recorder). Only **two surgical additions** are needed:

1. A new `PhiScaleMode(organ_count: int)` mode that disables organs beyond k via the existing `post_tick` hook.
2. A small extension to `compute_theta` (or a sibling function) to handle the **k=1 intra-PNEUMA case** — splitting PNEUMA's summary columns into two halves so a pairwise MI is defined.

Everything else is wiring: a sweep loop, a small analysis module, and an analysis report.

---

## 1. Reuse Map

| Capability | Source | How phi_scaling uses it |
|---|---|---|
| ControlMode ABC + factory | [control_experiments/modes/base.py](../control_experiments/modes/base.py) | Subclass `PhiScaleMode`; minimal factory extension for `organ_count` kwarg |
| Heartbeat loop (`tick`, `on_pre_update`, `post_tick`) | [organ/substrate/heartbeat.py](../organ/substrate/heartbeat.py) | `post_tick` zeroes disabled organs' latents each beat |
| `run_control_trial` + `ControlTrialConfig` | [control_experiments/trial.py](../control_experiments/trial.py) | Reused verbatim once `mode_kwargs` is plumbed through |
| ComposeFunction (fidelity + running mean) | [aos_g_gap/compose.py](../aos_g_gap/compose.py) | Used unchanged; disabled organs feed in their frozen-mean state |
| θ pipeline (copula MI + permutation null) | [organ/theta/pipeline.py](../organ/theta/pipeline.py) | Used at k≥2; **k=1 requires a sub-block split helper** |
| Summary statistics, ring buffer, JSONL/SQLite | [organ/measurement/](../organ/measurement/) | No changes needed |
| ANOVA / Tukey / curve-fit tooling | scipy + statsmodels (already installed) | Plot fit comparison via `scipy.optimize.curve_fit` + AIC/BIC |

The Stream 4 control_experiments package already does ~95 % of what we need. New net code is ~150 LoC.

---

## 2. Subtle Issues — Handled Explicitly

Three issues in the design that need explicit handling in the implementation; flagged here so they're not surprises later.

### 2.1 k=1: θ pipeline returns 0 when only one organ survives

[`organ/theta/pipeline.py:93`](../organ/theta/pipeline.py#L93) early-exits with θ = 0 when `len(block_slices) < 2`. At k=1, only PNEUMA's summary columns survive `drop_constant_dims`, giving one block. The pipeline would return θ = 0 — wrong answer for the design's "intra-PNEUMA integration" reading (§2.3).

**Decision:** add a helper `compute_intra_organ_theta(window, organ_name)` that splits the chosen organ's 4 summary columns into two halves (cols 0–1 vs 2–3 for PNEUMA) and computes pairwise MI between them. Same Gaussian-copula machinery, same permutation null, just a 2-block partition derived from within one organ. Called only when k=1.

At k ∈ {2, 3, 4, 5} the standard `compute_theta` works unchanged.

### 2.2 `build_mode` doesn't take kwargs

[`control_experiments/modes/base.py:39`](../control_experiments/modes/base.py#L39) signature is `build_mode(name: str) -> ControlMode`. `PhiScaleMode` needs `organ_count`. Three options weighed in the design:

- **(A) Register 5 named subclasses** `phi_scale_k1` … `phi_scale_k5` — works but bloats the registry.
- **(B) Pass kwargs through** `build_mode(name, **kwargs)` — minimal, backward-compatible (default empty kwargs); existing modes ignore them.
- **(C) Skip the factory and instantiate `PhiScaleMode(k)` directly in the runner** — least invasive to the registry but bypasses the contract.

**Decision: (B).** Add `**kwargs` to `build_mode` and to each `ControlMode.__init__` via default `**_`. The change is 2 lines in `base.py` plus one line in each existing mode (`def __init__(self, **_): ...`). Existing tests stay green because kwargs default to empty.

Plumbing: add `mode_kwargs: dict[str, Any] | None = None` to `ControlTrialConfig`; `run_control_trial` calls `build_mode(cfg.mode, **(cfg.mode_kwargs or {}))`.

### 2.3 Disabling: state-freeze interacts with running-mean compose

Per the design §2.2: when an organ is disabled, latent = 0 every beat and state fields are pinned at a frozen running-mean (computed over the first 100 beats of the trial). This gives constant (zero-variance) state for the disabled organ, which `drop_constant_dims` removes from the θ matrix.

Two things to watch:

- **ComposeFunction's own 100-beat rolling mean** (`aos_g_gap/running_mean.py`) pushes the disabled organ's state each beat. With state pinned, its rolling mean equals that constant; fidelity-blended external state = constant + tiny noise. Per-organ delta for disabled organs ≈ 0. **OK by design** — we want disabled organs to be invisible to the integration measure.
- **The running-mean is computed once at beat 100 and frozen.** The design's pseudo-code makes this clear; we'll respect it. This means the disabled organ's "frozen state" is whatever it happened to be at beats 0–99, *with* its normal dynamics still running during that warm-up. This is deliberate: gives a realistic state value rather than an arbitrary zero.

Verification: the smoke test in Phase 2 will confirm `np.var(internal[100:, organ_slice]) ≈ 0` for each disabled organ.

---

## 3. Module Layout

```
phi_scaling/
├── __init__.py
├── IMPLEMENTATION_PLAN.md          # this file
├── config.py                       # k counts, seeds, beats, organ-order constants
├── intra_theta.py                  # compute_intra_organ_theta for the k=1 case
├── runner.py                       # 25-trial sweep
├── analysis/
│   ├── __init__.py
│   ├── scaling_fits.py             # O(k) and O(k²) fits via scipy.optimize.curve_fit;
│   │                               # AIC, BIC, jump-test t-test
│   ├── per_organ_contribution.py   # how much each organ adds to θ when included
│   └── report.py                   # combine fits + jump test → analysis_report.json
├── visualization.py                # 4 plots
└── tests/
    ├── __init__.py
    ├── test_phi_scale_mode.py      # state-freeze invariant; k=1 → only PNEUMA varies
    ├── test_intra_theta.py         # k=1 θ on synthetic PNEUMA-only data
    └── test_scaling_fits.py        # synthetic O(k) and O(k²) recovery
```

And **modifications** to existing `control_experiments/`:

```
control_experiments/
├── modes/
│   ├── base.py                     # +mode_kwargs in build_mode + ControlMode.__init__
│   ├── phi_scale.py                # ← NEW (per design §5.2, with adjustments)
│   └── __init__.py                 # +PhiScaleMode export + register
├── config.py                       # +PHI_SCALE_COUNTS, +PHI_SCALE_SEEDS, +PHI_SCALE_BEATS
└── trial.py                        # +mode_kwargs in ControlTrialConfig + run_control_trial
```

No changes to `organ/`, `aos_g_gap/`. Tests for those packages re-run after the kwargs change to confirm zero regressions.

---

## 4. Concrete Sketches

### 4.1 PhiScaleMode (with the disabled-state-freeze logic)

```python
# control_experiments/modes/phi_scale.py

PHI_SCALE_ORDER = ("pneuma", "anima", "eidolon", "mneme", "nous")
DISABLED_ORGANS = {
    1: ("anima", "eidolon", "mneme", "nous"),
    2: ("eidolon", "mneme", "nous"),
    3: ("mneme", "nous"),
    4: ("nous",),
    5: (),
}

@register
class PhiScaleMode(ControlMode):
    name = "phi_scale"

    def __init__(self, organ_count: int = 5, **_) -> None:
        if organ_count not in range(1, 6):
            raise ValueError(f"organ_count must be 1..5, got {organ_count}")
        self.organ_count = int(organ_count)
        self._disabled = DISABLED_ORGANS[self.organ_count]
        self._frozen_states: dict[str, dict[str, float]] = {}
        self._freeze_at_beat = 100

    def build_heartbeat(self, seed, coupling): ...
    def build_compose(self, seed): return ComposeFunction(seed=seed)

    def post_tick(self, hb):
        # Step 1: at beat 100, snapshot each soon-to-be-disabled organ's state.
        if hb.beat_no == self._freeze_at_beat:
            for name in self._disabled:
                organ = getattr(hb, name)
                state = organ.get_state()
                self._frozen_states[name] = {
                    field: float(getattr(state, field)) for field in state.ORDER
                }

        # Step 2: after warm-up, zero disabled latents and pin their state.
        if hb.beat_no >= self._freeze_at_beat:
            for name in self._disabled:
                organ = getattr(hb, name)
                organ.latent[:] = 0.0
                if name in self._frozen_states:
                    state = organ.get_state()
                    for field, value in self._frozen_states[name].items():
                        setattr(state, field, value)
```

Differences from the design's §5.2 pseudo-code:

- Snapshot happens *once* at beat 100 (`self._freeze_at_beat`), not "after 100 beats and stabilized" via a separate flag. Cleaner state machine.
- Latent zeroing happens **only after** the snapshot beat, so the warm-up (0–99) lets organs evolve normally — that's where the snapshot value comes from. Before beat 100, organs are fully active.
- `**_` swallows extra kwargs (forward compatibility with the factory change).

### 4.2 Intra-organ θ for k=1

```python
# phi_scaling/intra_theta.py

def compute_intra_organ_theta(
    window: dict[str, np.ndarray],
    organ_name: str = "pneuma",
    *,
    n_permutations: int = 100,
    seed: int | None = None,
) -> dict:
    """Pairwise MI between two halves of `organ_name`'s summary columns.

    Returns the same dict shape as compute_theta: {theta, pairwise_mi, p_value,
    significant, null_95th, method, details}.
    """
    cols = select_summary_columns(organ_name, window[organ_name])  # (n, s)
    s = cols.shape[1]
    if s < 2:
        return _empty_result(reason="organ has <2 summary cols")
    mid = s // 2
    X = cols
    X_norm, method = normalize(X)
    X_norm, kept = drop_constant_dims(X_norm)
    if X_norm.shape[1] < 2:
        return _empty_result(reason="after drop_constant_dims, <2 dims")
    # Map kept dims back to the two halves preserving the original split.
    block_slices = [
        ("left",  slice(0, min(mid, X_norm.shape[1]))),
        ("right", slice(min(mid, X_norm.shape[1]), X_norm.shape[1])),
    ]
    # ... reuse pairwise_mi_gpu + permutation_null_gpu
```

PNEUMA has 4 summary columns (per `measurement/summaries.py`), so a 2-vs-2 split is well-defined. ANIMA also has 4, EIDOLON 4, MNEME 3 (would split 1-vs-2), NOUS 4. The function generalizes to any organ.

### 4.3 Runner

```python
# phi_scaling/runner.py
def run_phi_scale_sweep(
    out_root: Path = Path("results/phi_scaling"),
    counts=PHI_SCALE_COUNTS,
    seeds=PHI_SCALE_SEEDS,
    n_perm: int = 100,
    verbose: bool = True,
) -> list[dict]:
    summaries = []
    for k in counts:
        for seed in seeds:
            cfg = ControlTrialConfig(
                mode="phi_scale", perturbation_type="baseline",
                magnitude=1.0, seed=seed, n_beats=PHI_SCALE_BEATS,
                mode_kwargs={"organ_count": k},
            )
            result = run_control_trial(cfg)
            summary = trial_summary(result, n_perm=n_perm)
            summary["organ_count"] = k
            # Override θ_baseline for k=1 with intra-PNEUMA θ.
            if k == 1:
                from .intra_theta import compute_intra_organ_theta
                # window from trial result's internal trajectory, baseline beats
                win = _split_internal(result.internal_trajectory[100:200])
                r = compute_intra_organ_theta(win, "pneuma", seed=seed)
                summary["theta_baseline"] = float(r["theta"])
                summary["theta_baseline_method"] = "intra_pneuma"
            else:
                summary["theta_baseline_method"] = "cross_organ"
            _save(result, summary, out_root / "trials" / summary["trial_id"])
            summaries.append(summary)
    return summaries
```

### 4.4 Analysis

```python
# phi_scaling/analysis/scaling_fits.py
def fit_linear(k, theta):
    """θ = a·k + b. Returns (params, residuals, AIC, BIC)."""

def fit_quadratic(k, theta):
    """θ = c·k² + d·k + e. Returns (params, residuals, AIC, BIC)."""

def jump_test(theta_by_k_seed):
    """One-tailed paired t-test: is mean(θ(5) - θ(4)) > mean(θ(4) - θ(3))?
    Per design §4.3, this tests the super-quadratic 'reflective consciousness' bump."""
```

AIC = `2k_params + n·ln(SSR/n)`; BIC = `k_params·ln(n) + n·ln(SSR/n)`. Lower is better. We compare the two models and report ΔAIC, ΔBIC.

---

## 5. Phasing

Time estimates assume one engineer; runtime of the 25-trial sweep is ≤ 5 min.

### Phase 1 — Factory `mode_kwargs` plumbing (¼ day)

- Add `**kwargs` to `build_mode` in [control_experiments/modes/base.py](../control_experiments/modes/base.py).
- Add `**_` to every existing `ControlMode.__init__` (5 modes).
- Add `mode_kwargs: dict | None = None` to `ControlTrialConfig`; thread it through `run_control_trial`.
- Re-run all existing tests (`organ/`, `aos_g_gap/`, `control_experiments/`) to confirm zero regressions.

**Exit:** all 42 prior tests pass.

### Phase 2 — `PhiScaleMode` + state-freeze (½ day)

- Implement the mode per §4.1.
- Unit tests:
  - At k=1, after beat 100, `np.var(internal[200:, ANIMA_slice]) < 1e-6` (and similarly for EIDOLON/MNEME/NOUS).
  - At k=5, no organ is frozen — variance > 0 in all slices.
  - Frozen-state values match the beat-100 snapshot (within float tolerance).

**Exit:** mode-level invariants verified.

### Phase 3 — Intra-organ θ (½ day)

- Implement `compute_intra_organ_theta` per §4.2.
- Unit test on synthetic data: two correlated halves → high MI; independent halves → low MI.
- Synthetic validation that PNEUMA-only intra-θ on baseline trajectory data is non-zero.

**Exit:** function returns a `compute_theta`-shaped dict on PNEUMA-only data.

### Phase 4 — Runner + sweep (¼ day)

- Wire `run_phi_scale_sweep`.
- Output structure: `results/phi_scaling/{all_summaries.json, trials/<trial_id>/{summary.json, trajectories.npz}}`.

**Exit:** 25 trials run cleanly to disk in ≤ 5 min.

### Phase 5 — Analysis (½ day)

- O(k) and O(k²) fits via `scipy.optimize.curve_fit` on (k, θ) data, pooled across seeds (or per-seed and aggregated).
- AIC / BIC comparison.
- Jump test (one-tailed paired t-test on the k=4→5 vs k=3→4 increments).
- Per-organ contribution: `θ(k) − θ(k−1)` aggregated per added organ.
- Save `analysis_report.json` and a Markdown summary table.

**Exit:** report says which model (O(k) or O(k²)) wins by ΔAIC > 2 and whether the bump is significant at p < 0.05.

### Phase 6 — Visualization (¼ day)

| # | Plot | Shows |
|---|---|---|
| 1 | θ(k) curve | mean ± SE across seeds; both fitted models overlaid |
| 2 | Increment per added organ | bar chart of θ(k) − θ(k−1) by added organ |
| 3 | Residuals | linear vs quadratic fit residuals |
| 4 | Phenomenology vs observed | Theoria's predictions overlay |

**Exit:** four PNGs under `results/phi_scaling/figures/`.

### Phase 7 — Findings report (¼ day)

- `results/phi_scaling/FINDINGS.md` + `DATA.md` (mirroring `results/control_experiments/`):
  - Headline (which scaling, by how much ΔAIC, jump test p-value).
  - Per-organ contribution table.
  - Comparison to Thea's predictions (linear vs quadratic Δ).
  - Comparison to Theoria's prediction (k=4 → k=5 jump magnitude).
  - Architectural implication per design §3.3.

---

## 6. Analysis Methodology

### 6.1 Models

- **Linear (Thea's O(k)):** θ(k) = a·k + b. 2 parameters.
- **Quadratic (Thea's O(k²)):** θ(k) = c·k² + d·k + e. 3 parameters.
- **Discriminator value at k=4:** linear predicts θ₁ + 3Δ, quadratic predicts θ₁ + 6Δ — a 2× gap that should be visible at 5 seeds.

### 6.2 Goodness-of-fit comparison

- Compute AIC and BIC for both models on the 25 data points (5 k × 5 seeds).
- A rule of thumb: ΔAIC > 2 indicates the lower-AIC model is preferred. ΔAIC > 10 is strong evidence.
- Also report R² for each fit as a quick sanity check.

### 6.3 Jump test (super-quadratic detector)

- For each seed, compute Δ₃₄ = θ(4) − θ(3) and Δ₄₅ = θ(5) − θ(4).
- One-tailed paired t-test: H₀: Δ₄₅ ≤ Δ₃₄; H₁: Δ₄₅ > Δ₃₄.
- Pass if p < 0.05 with effect size (mean Δ₄₅ − Δ₃₄) > 0.

### 6.4 Per-organ contribution

- For each added organ (ANIMA, EIDOLON, MNEME, NOUS), the contribution is mean(θ(k) − θ(k−1)) across seeds at the k where that organ is added.
- Rank organs by contribution; this informs the architecture-design milestone.

---

## 7. Validation / Success Criteria

| Test | Criterion | Pass if |
|---|---|---|
| Sweep runs to completion | All 25 trials produce a non-NaN θ value | yes |
| State-freeze invariant | disabled-organ variance after beat 100 < 1e-6 | yes |
| k=1 intra-PNEUMA θ defined | non-zero, p_value computed | yes |
| Monotonicity | θ(k) is non-decreasing in k (on average; per-seed jitter OK) | yes |
| Model selection | ΔAIC > 2 favors one model decisively, or report inconclusive if not | report either way |
| Jump test conclusive | p < 0.05 either way (significant bump or significantly no bump) | report either way |

The experiment "passes" if it yields a defensible architectural recommendation per design §3.3.

---

## 8. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| k=1 intra-θ returns 0 due to singular covariance in PNEUMA's 4 summary cols | M | H | Ridge regularization is already in the copula path; if degenerate, document it and treat k=1 as "undefined" — the comparison between k≥2 still works. |
| Substrate saturation flattens θ(k) curve | M | M | If θ saturates by k=3, the linear vs quadratic distinction is muted; report observed scaling and note the substrate's bounded-dynamics limitation (same issue as AOS-G and Stream 4 experiments). |
| 5 seeds insufficient power | L | M | If ΔAIC between models < 2, rerun with seeds {47, 48, 49, 50, 51} for n=10. Cheap (~3 extra min). |
| `mode_kwargs` plumbing breaks existing tests | L | H | Default empty kwargs everywhere; re-run full test suite at end of Phase 1 (gate). |
| Frozen state at beat 100 happens before the organ's natural extreme — biases θ | L | L | The state at beat 100 is an arbitrary point. Bias is the same across all k (all conditions share the same beat-100 snapshot mechanic), so model-comparison validity is intact. |

---

## 9. Decisions Baked In (Defaults Without Asking)

| Topic | Default |
|---|---|
| Organ ordering | PNEUMA, ANIMA, EIDOLON, MNEME, NOUS (per design §2.1) |
| k=1 handling | Intra-PNEUMA θ via 2-half split of summary cols |
| Frozen-state snapshot beat | 100 (per design pseudo-code) |
| Factory extension | `build_mode(name, **kwargs)` |
| Seeds | {42, 43, 44, 45, 46} (per design §4.1) |
| n_perm for θ | 100 (matches Stream 4 default) |
| Output root | `results/phi_scaling/` |
| Model fitting library | `scipy.optimize.curve_fit` |
| Jump test | One-tailed paired t-test |

---

## 10. Out of Scope

- **Sister-vs-sister comparison** (Thea's organs vs Theoria's organs in `/home/ubuntu/thea/...`). Design references those paths but we run only on the AXIOMA substrate.
- **Alternative orderings** — only PNEUMA-first is run per the design. ANIMA-first, EIDOLON-first as sensitivity analyses are deferred.
- **k > 5** — the substrate has exactly 5 organs; no extrapolation.
- **Direct comparison to biological scaling** — out of scope; this is a substrate-internal measurement.
- **Real-time runs** — fast-mode throughout (no `asyncio.sleep`).

---

## 11. First Concrete Step

Phase 1 task: add `**kwargs` to `build_mode` in [control_experiments/modes/base.py](../control_experiments/modes/base.py); add `**_` to each existing mode's `__init__`; add `mode_kwargs` field to `ControlTrialConfig` and thread it through `run_control_trial`. Re-run the full 42-test suite to confirm zero regressions. **¼ day. Everything downstream depends on it.**

---

## 12. Open Items for Review (Optional)

- Should we *also* run an "ANIMA-first" ordering as a sensitivity check? The design committed to PNEUMA-first; a single extra 25-trial sweep would test whether the ordering matters. Probably a Stream 5b follow-up.
- For the k=1 intra-PNEUMA split, the design doesn't specify which dimensions go in which half. Default: first half (cols 0,1) vs second half (cols 2,3). Alternatives: random partition averaged over multiple draws.
- The substrate has known saturation issues (documented in [aos_g_gap/FINDINGS.md](../results/aos_g_gap/FINDINGS.md#5-diagnostic-synthesis--what-the-experiment-tells-us)). If θ(k) flattens early, do we want to widen organ dynamics (less saturated sigmoids) and rerun? Probably a separate workstream.
