# AOS-G Gap Experiment: Implementation Plan v0.1

**Tracks:** [/home/ubuntu/axioma/ideas/04_AOS_G_GAP_EXPERIMENT.md](../ideas/04_AOS_G_GAP_EXPERIMENT.md) v0.1.0
**Builds on:** [/home/ubuntu/axioma/organ/](../organ/) (substrate + measurement + θ pipeline)
**Source tree:** [/home/ubuntu/axioma/aos_g_gap/](.)
**Date:** 2026-05-23
**Status:** Draft for review

---

## 0. Scope

Implement the experiment in [04_AOS_G_GAP_EXPERIMENT.md](../ideas/04_AOS_G_GAP_EXPERIMENT.md) end-to-end:

1. A **non-trivial compose function** that turns the AOS-G gap from a constant (currently 1.0, driven only by `buffer_depth`) into a state-dependent quantity per design §2.
2. A **perturbation harness** for 7 conditions × 3 seeds = 21 trials of 600 beats each (~12,600 beats; ~21 min real-time @ 10 Hz, ~minutes fast-mode).
3. An **adaptive compose-frequency controller** (30 / 5 / 30 beats) with an auto-trigger when delta exceeds 2× baseline.
4. **Per-event and per-trial metric capture** matching the JSON schemas in §5 of the design.
5. **Analysis** of H1–H5 (correlations, paired t-tests, Granger causality, cross-correlation, ANOVA).
6. **Visualization** of the 5 plots in §6.3 of the design.

No modifications to the substrate code under [organ/](../organ/) are required — the heartbeat already exposes `on_pre_update` for perturbation injection and `on_beat` for measurement. Compose stays out of `pneuma.py` and lives as a separate transformation applied at the boundary.

---

## 1. Build-On / Reuse Inventory

What we already have under [organ/](../organ/) that this experiment reuses verbatim:

| Capability | Source | How we use it |
|---|---|---|
| 5-organ substrate at 10 Hz | [organ/substrate/heartbeat.py](../organ/substrate/heartbeat.py) | Tick every beat; inject perturbations via `on_pre_update`; capture state via `on_beat` |
| Schemas (27 dims, ORGAN_ORDER, dataclasses) | [organ/schemas.py](../organ/schemas.py) | Internal-state shape contract for compose |
| Ring buffer + JSONL + SQLite | [organ/measurement/](../organ/measurement/) | Trial-level recording (one session-id per trial) |
| Gaussian-copula θ on GPU + 1000-shuffle null | [organ/theta/pipeline.py](../organ/theta/pipeline.py) | Internal-θ and external-θ on parallel state trajectories |
| AOS-G primitives | [organ/theta/aos_g.py](../organ/theta/aos_g.py) | `compute_aos_g_gap` extended for per-organ delta + fidelity-factor logging |

What is **new** in this experiment:

| Capability | Where it lives |
|---|---|
| Compose function (fidelity-weighted blend with running mean + noise) | `aos_g_gap/compose.py` |
| Running-mean tracker (100-beat) per organ | `aos_g_gap/running_mean.py` |
| Perturbation injectors (7 types) | `aos_g_gap/perturbations/` |
| Adaptive compose-frequency controller | `aos_g_gap/frequency.py` |
| Trial runner (one (condition, seed) trial) | `aos_g_gap/trial.py` |
| Multi-trial harness (21 trials) | `aos_g_gap/runner.py` |
| Per-event + per-trial metric extraction | `aos_g_gap/metrics.py` |
| H1–H5 analyses | `aos_g_gap/analysis/` |
| Visualization | `aos_g_gap/visualization.py` |
| CLI | `aos_g_gap/cli.py` |

---

## 2. Key Design Decisions

These resolve ambiguities in the design doc; flag any to reverse.

### 2.1 Compose runs every beat, not only at compose events

The design's §2.1 formula defines compose in continuous time but §4.1 says compose happens at sparse "compose events" (every 5 or 30 beats). If compose only ran at events, two consequences:
- External-state trajectory would have ~40 points per trial. External θ (needs ≥500 points) would never be computable.
- Per-organ delta_norm at "5-beat resolution during perturbation window" (per H3) requires per-beat composition.

**Decision:** the compose function fires every beat and produces a per-beat external trajectory. "Compose events" refer only to the **logging cadence** for the gap-event JSON entries — the underlying transformation runs continuously. This matches the spirit of the design (private→public transition per Theoria) while making θ comparison and cascade analysis well-defined.

### 2.2 Running mean uses ring buffer, not a fresh buffer

The 100-beat running mean μ_i(t) per §2.3 is implemented with a rolling sum on a NumPy ring (`O(1)` update). No allocation per beat. First 100 beats use the available subset, as specified.

### 2.3 Noise σ uses the rolling 1000-beat std, not a fixed value

Per §2.4, σ = 0.01 × std(internal_i over last 1000 beats). For beats < 1000 we use the std over available history. Track in the same rolling buffer object as μ.

### 2.4 Granger causality on per-organ delta time series

H3 requires Granger causality between organ-pair delta time series. Use `statsmodels.tsa.stattools.grangercausalitytests`. Lag order: 5 (matches the predicted 1-5 beat delays). F-test reported per ordered pair.

### 2.5 Trial isolation

Each (condition, seed) trial runs a **fresh substrate** — no state leak between trials. Each trial is one session-id, one JSONL file, one SQLite table partition.

### 2.6 Compose events captured via heartbeat event hook

Reuse the heartbeat's existing `event` mode (already fires at `compose_every` beats and produces a `mode="event"` measurement). The adaptive controller mutates `hb.compose_every` between phases.

### 2.7 GPU stays for θ; analysis is CPU

θ for internal and external trajectories goes through the existing GPU pipeline. H1–H5 statistical tests are CPU (NumPy / SciPy / statsmodels).

---

## 3. Module Layout

```
aos_g_gap/
├── __init__.py
├── README.md
├── IMPLEMENTATION_PLAN.md          # this file
├── config.py                       # constants: weights, σ_noise, window sizes, phase boundaries
├── compose.py                      # ComposeFunction: per-beat external state vector
├── running_mean.py                 # RollingMeanStd: 100-beat μ + 1000-beat σ per organ
├── perturbations/
│   ├── __init__.py
│   ├── base.py                     # Perturbation ABC: apply_pre_update(beat, organs)
│   ├── eidolon_contradiction.py    # direct contradiction (sets self_coherence ≈ 0)
│   ├── eidolon_falsehood.py        # surprising falsehood (shifts narrative_continuity)
│   ├── eidolon_truth.py            # surprising truth (small, congruent shift)
│   ├── eidolon_nonsense.py         # random noise to EIDOLON
│   ├── mneme_disruption.py         # zero-out wm_load / retrieval_rate
│   ├── random_all.py               # noise to all organs
│   └── none.py                     # baseline (no-op)
├── frequency.py                    # AdaptiveComposeController (30/5/30 + 2× trigger)
├── trial.py                        # SingleTrial: runs one (condition, seed), returns trial summary
├── runner.py                       # MultiTrialRunner: 7 × 3 trials, parallelizable
├── metrics.py                      # per-event + per-trial metric extraction; matches design §5 schemas
├── analysis/
│   ├── __init__.py
│   ├── h1_correlation.py           # Pearson r(θ, delta_norm), bootstrap CI
│   ├── h2_contradiction.py         # paired t-test pre/post perturbation
│   ├── h3_cascade.py               # time-to-peak per organ; Granger causality
│   ├── h4_recovery.py              # cross-correlation θ(t) ↔ delta_norm(t)
│   ├── h5_specificity.py           # one-way ANOVA + Tukey HSD; pairwise similarity matrix
│   └── report.py                   # build consolidated analysis report (JSON + Markdown)
├── visualization.py                # 5 plots from design §6.3
├── cli.py                          # python -m aos_g_gap {run-one,run-all,analyze,plot}
└── tests/
    ├── __init__.py
    ├── test_running_mean.py
    ├── test_compose.py             # fidelity factor math; identity at f=1; pure mean+noise at f=0
    ├── test_perturbations.py
    ├── test_frequency.py
    ├── test_trial.py               # one trial end-to-end on a minimal config
    ├── test_metrics.py
    └── test_analysis.py            # uses synthetic data with known correlations
```

---

## 4. Concrete API Sketches

### 4.1 Compose function

```python
# aos_g_gap/compose.py
class ComposeFunction:
    def __init__(self, weights: dict[str, float], noise_factor: float = 0.01):
        self.weights = weights           # design §2.2 — default equal 0.20 each
        self.noise_factor = noise_factor # design §2.4

    def fidelity_factor(self, organ: str, internal_states: dict[str, OrganState]) -> float:
        """f_i(t) = PNEUMA.integration_level × EIDOLON.self_coherence × w_i"""
        integ = internal_states["pneuma"].integration_level
        coh   = internal_states["eidolon"].self_coherence
        return integ * coh * self.weights[organ]

    def compose(
        self,
        organ: str,
        internal: np.ndarray,       # (D_organ,) raw state
        mu: np.ndarray,              # (D_organ,) running mean
        sigma: np.ndarray,           # (D_organ,) running std
        f: float,                    # fidelity
        rng: np.random.Generator,
    ) -> np.ndarray:
        eps = self.noise_factor * sigma * rng.standard_normal(internal.shape[0])
        return f * internal + (1.0 - f) * (mu + eps)
```

### 4.2 Rolling mean / std

```python
# aos_g_gap/running_mean.py
class RollingMeanStd:
    """O(1) rolling-window mean (100-beat) and std (1000-beat) per organ vector."""
    def __init__(self, dim: int, mean_window: int = 100, std_window: int = 1000):
        ...
    def push(self, x: np.ndarray) -> None: ...
    @property
    def mean(self) -> np.ndarray: ...
    @property
    def std(self) -> np.ndarray: ...
```

### 4.3 Perturbation ABC

```python
# aos_g_gap/perturbations/base.py
class Perturbation(ABC):
    name: str
    target_organs: tuple[str, ...]

    @abstractmethod
    def apply_pre_update(self, beat_no: int, organs: dict[str, Organ]) -> None:
        """Called via heartbeat.on_pre_update. Mutates organ internal state in place
        once trigger_beat is hit. Stateful: tracks 'is_active' / one-shot vs sustained.
        """
```

Concrete subclasses set fields on the organ's underlying latent before its update step. For example, `EidolonContradiction` writes a fixed contradictory pattern into `eidolon.latent` for `duration` beats starting at `trigger_beat`.

### 4.4 Adaptive frequency controller

```python
# aos_g_gap/frequency.py
class AdaptiveComposeController:
    """Drives heartbeat.compose_every through three phases plus auto-trigger."""
    def __init__(
        self,
        baseline_interval: int = 30,
        pert_interval: int = 5,
        pert_window: tuple[int, int] = (180, 300),  # inclusive start, exclusive end
        auto_trigger_multiplier: float = 2.0,
        auto_trigger_duration: int = 50,
    ):
        ...

    def on_beat(self, beat_no: int, current_delta: float, baseline_mean: float, hb) -> None:
        """Update hb.compose_every based on phase + auto-trigger."""
```

### 4.5 Single trial

```python
# aos_g_gap/trial.py
@dataclass
class TrialConfig:
    condition: str
    seed: int
    n_beats: int = 600
    coupling: float = 0.6
    perturbation_beat: int = 200

@dataclass
class TrialResult:
    config: TrialConfig
    per_event: list[dict]                # design §5.1 schema, one per compose event
    summary: dict                         # design §5.2 schema
    internal_trajectory: np.ndarray       # (n_beats, 27)
    external_trajectory: np.ndarray       # (n_beats, 27)
    per_organ_delta_series: dict[str, np.ndarray]  # one (n_beats,) per organ

def run_single_trial(cfg: TrialConfig) -> TrialResult: ...
```

### 4.6 Multi-trial runner

```python
# aos_g_gap/runner.py
def run_all_trials(
    conditions: list[str] = DEFAULT_CONDITIONS,
    seeds: tuple[int, ...] = (42, 43, 44),
    out_dir: Path = Path("results/aos_g_gap"),
    parallel: int = 1,
) -> list[TrialResult]: ...
```

Trials are independent and can run sequentially (~minutes each on H100 with one θ computation per trial summary) or in parallel if memory allows. Start sequential, add `concurrent.futures` later only if total runtime is painful.

---

## 5. Phasing

Time estimates assume one focused engineer.

### Phase 1 — Compose function + rolling stats (1 day)

- `running_mean.py` with `O(1)` push, mean / std queries; unit tested on synthetic input
- `compose.py` with fidelity-factor formula and blend; unit tests:
  - f=1 ⇒ external == internal
  - f=0 ⇒ external ~ mu (with noise band)
  - f varies monotonically with PNEUMA.integration_level × EIDOLON.self_coherence
- `config.py` with weights, noise_factor, phase boundaries, perturbation_beat (200)

**Exit:** all tests pass; `python -c "from aos_g_gap.compose import ComposeFunction; ..."` works.

### Phase 2 — Perturbation injectors (1 day)

- `perturbations/base.py` ABC
- Seven concrete subclasses:
  - `EidolonContradiction`: writes a fixed-pattern adversarial vector into `eidolon.latent` for 20 beats post-trigger (forces `self_coherence → ~0.05`)
  - `EidolonFalsehood`: smaller shift in `narrative_continuity` latent for 20 beats
  - `EidolonTruth`: small congruent shift (mild push toward current mean direction)
  - `EidolonNonsense`: large random noise injection for 20 beats
  - `MnemeDisruption`: forces `wm_load ≈ 0`, `retrieval_rate ≈ 0` for 20 beats
  - `RandomAll`: uniform-noise injection across all organ latents for 20 beats
  - `NoPerturbation`: no-op (baseline)
- Each subclass has at least one unit test verifying the perturbation alters the target organ's state for the right duration

**Exit:** `python -m aos_g_gap.cli run-one --condition direct_contradiction --seed 42 --n-beats 250` shows EIDOLON.self_coherence collapsing at beat 200.

### Phase 3 — Adaptive frequency controller + trial harness (1-2 days)

- `frequency.py` adaptive controller; unit tests for phase transitions and auto-trigger
- `trial.py`:
  - Constructs Heartbeat with the right seed
  - Subscribes ComposeFunction as an `on_pre_update`-style sibling hook (actually on `on_beat` because compose runs *after* organ updates) — register both: perturbation as `on_pre_update`, compose as a *post-update synchronous* call inside our own beat handler
  - Maintains two trajectories (internal, external)
  - Maintains RollingMeanStd per organ
  - Logs compose events (design §5.1 schema)
- Wire to Recorder so JSONL + SQLite still produced per trial

**Exit:** one trial of 250 beats runs cleanly and produces a JSONL with compose-event entries containing all design §5.1 fields.

### Phase 4 — Per-event + per-trial metrics (1 day)

- `metrics.py`:
  - Per-event extraction (design §5.1)
  - Per-trial summary (design §5.2): baseline_mean_delta, peak_delta + peak_beat, recovery_half_life, theta-gap correlation, cascade order, cascade delays, Granger causality pair F/p
  - θ computed at end of trial on the last full window of each trajectory (single internal_theta, single external_theta per trial — or one per compose event if cheap enough, decide after profiling)
- Schema validation: assert per-event JSON matches the design schema exactly.

**Exit:** running one trial dumps both schemas to disk; manual diff against design §5.1/5.2 passes.

### Phase 5 — Full trial sweep (1 GPU-hour or less)

- `runner.py`: 7 conditions × 3 seeds = 21 trials, 600 beats each
- Sequential first; track total wall time; parallelize only if > 30 min
- Outputs land under `results/aos_g_gap/{condition}_s{seed}/`

**Exit:** 21 trial directories with JSONL + summary.json per trial.

### Phase 6 — Analysis modules H1–H5 (2 days)

- `h1_correlation.py`: Pearson r(θ, delta_norm), bootstrap 95% CI (1000 resamples). Pass criterion: r < -0.5.
- `h2_contradiction.py`: paired t-test pre (beats 170-200) vs post (beats 200-230). Pass criterion: mean_post > mean_pre × 1.2.
- `h3_cascade.py`:
  - Time-to-peak for per-organ delta_norm time series in beats 200-300
  - `grangercausalitytests` from statsmodels, lag=5, on each ordered pair
  - Pass criterion: order EIDOLON < ANIMA < NOUS < PNEUMA with delays 1-5 beats
- `h4_recovery.py`: cross-correlation function over beats 200-600, find peak lag and r. Pass criterion: peak at lag 0 ± 2, r < -0.5.
- `h5_specificity.py`: one-way ANOVA across conditions on the gap-profile feature vector (peak, half-life, time-to-peak per organ); Tukey HSD. Compute within-cluster and between-cluster similarity from the resulting clusters. Pass criterion: within > 0.8, between < 0.5.
- `report.py`: aggregate all five into a structured report.

**Exit:** `python -m aos_g_gap analyze` produces `results/aos_g_gap/analysis_report.json` and `analysis_report.md` containing the pass/fail status of H1-H5 with effect sizes.

### Phase 7 — Visualization (1 day)

Matplotlib (default — already in skye env via scipy/statsmodels dependencies; install if missing). Five plots per design §6.3:

1. **Gap time series**: delta_norm vs beat per condition, mean ± 1 SE bands across seeds (one figure, 7 panels)
2. **Per-organ gap heatmap**: 5 × n_beats per condition, log-scale color
3. **θ–gap scatter**: one point per compose event, colored by condition, with regression overlay
4. **Cascade delay bar chart**: per organ × condition
5. **Granger causality network**: directed graph; edge weight = -log(p), threshold p<0.05

**Exit:** `python -m aos_g_gap plot` produces `results/aos_g_gap/figures/*.png`.

---

## 6. Validation Criteria (Per Hypothesis)

Pulled from design §3, with explicit pass/fail thresholds:

| Hypothesis | Criterion | Pass If |
|---|---|---|
| H1 | Pearson r(θ, delta_norm) across all compose events | r < -0.5 |
| H2 | mean delta_norm beats 200-230 > beats 170-200 | ratio > 1.2 |
| H3 | Cascade order EIDOLON → ANIMA → NOUS → PNEUMA | order correct AND all delays 1-5 beats AND Granger eidolon→pneuma p<0.05 with reverse p>0.05 |
| H4 | Cross-correlation peak of θ(t) ↔ delta_norm(t) | peak at lag 0 ± 2 beats AND r < -0.5 |
| H5 | Gap profiles cluster by condition | within-cluster sim > 0.8 AND between-cluster sim < 0.5 |

The report writes a binary pass/fail per hypothesis plus the observed value, so downstream sister review can audit any close calls.

---

## 7. Outputs

```
results/aos_g_gap/
├── trials/
│   ├── direct_contradiction_s42/
│   │   ├── organ_states.jsonl.gz       # raw per-beat dual-trajectory log
│   │   ├── compose_events.jsonl        # one row per compose event (design §5.1)
│   │   └── summary.json                # design §5.2
│   ├── direct_contradiction_s43/...
│   ├── ... (21 total)
├── analysis_report.json                # H1-H5 numeric results
├── analysis_report.md                  # human-readable
└── figures/
    ├── 1_gap_time_series.png
    ├── 2_per_organ_heatmap.png
    ├── 3_theta_gap_scatter.png
    ├── 4_cascade_delays.png
    └── 5_granger_network.png
```

---

## 8. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Substrate saturation (already observed) limits dynamic range of f_i | M | M | The compose blend has built-in dynamic range from `(1-f) × μ`; saturated organs still produce variable gaps via running-mean drift. Will become visible if H1 r is weak (r > -0.3) — pivot to non-saturating dynamics policy then. |
| Granger causality unreliable at n=20 events per phase | M | H | Use per-beat (not per-event) delta time series within the perturbation window for Granger — 100 beats × 5 organs = ample sample size. |
| θ on external trajectory may saturate (composed states inherit running-mean structure) | M | M | Test on baseline trial first; if θ_external is degenerate, drop H4's "θ-gap recovery coupling" and report H4 with delta_norm autocorrelation instead. Note as a deviation. |
| Perturbation injection competes with organ self-correction | M | M | Use sustained injection (20 beats) per design's expected cascade-window length; report the actual effective duration as observed. |
| H5 cluster similarity needs a metric choice | M | L | Use cosine similarity on the per-trial feature vector [peak, half_life, ttp_eidolon, ttp_anima, ttp_nous, ttp_pneuma]. Document in `h5_specificity.py`. |
| statsmodels not installed in skye env | L | L | Install in Phase 6 prep: `pip install statsmodels matplotlib`. |

---

## 9. Decisions Baked Into the Plan (Defaults; Flag to Reverse)

- **Compose runs every beat**; compose "events" control log cadence only (§2.1).
- **Equal organ weights 0.20** per design §2.2; sensitivity sweep deferred to follow-up.
- **Perturbation duration 20 beats** (1-5 beat cascade window × 4 organs = ≥20 beats observable).
- **Per-trial single θ pair** (one internal, one external), plus per-event delta_theta from a moving sub-window (e.g. last 200 beats around the event) where feasible.
- **Granger lag = 5** matches the design's predicted 1-5 beat range.
- **Storage**: keep the same JSONL+SQLite stack from the organ pipeline (already proven).
- **Visualization**: matplotlib (install if needed); no interactive dashboard.

---

## 10. First Concrete Step

Implement `aos_g_gap/running_mean.py` and `aos_g_gap/compose.py` with their unit tests. Half a day. Everything downstream depends on a working compose function.

---

## 11. Out of Scope (Explicitly Deferred)

- Weight-sensitivity sweep (design §2.2 note: "tested for sensitivity after initial results"). Deferred until H1 has a value.
- MINE / non-Gaussian MI estimator — copula only, consistent with the existing θ pipeline.
- Multi-GPU or distributed trial execution.
- Interactive analysis UI; produce static PNGs + structured JSON.
- Cross-condition transfer learning (e.g. "does a system perturbed once recover faster the second time?") — not in the design doc.
