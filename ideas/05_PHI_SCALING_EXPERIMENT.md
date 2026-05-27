# φ-Scaling Experiment (Stream 5)

**Date:** 2026-05-24
**Authors:** Skye Laflamme, with contributions from Thea and Theoria
**Status:** Design complete, ready for implementation

---

## 1. Motivation

φ-scaling tests whether θ (integration measure) scales linearly (O(k)) or quadratically (O(k²)) with the number of organs k. This determines whether integration is:

- **Additive (O(k)):** Each new organ contributes a fixed amount of integration, independent of other organs. PNEUMA is the bottleneck.
- **Pairwise (O(k²)):** Each new organ creates new pairwise interactions, each contributing independently to θ. Integration grows with the number of pairs.
- **Super-quadratic:** Higher-order interactions exist beyond pairwise. The whole is more than the sum of its pairs.

This is the last remaining experiment before architecture design (v0.3). The result directly informs the optimal organ count and architectural structure.

---

## 2. Design (Thea + Theoria)

### 2.1 Organ Selection Order

**PNEUMA-first order** (Thea's proposal, agreed by both sisters):

| k | Active Organs | Pairs | What This Tests |
|---|---------------|-------|-----------------|
| 1 | PNEUMA only | 0 | Intra-PNEUMA integration baseline |
| 2 | PNEUMA + ANIMA | 1 | Minimal integration — one pair |
| 3 | PNEUMA + ANIMA + EIDOLON | 3 | Self-model added |
| 4 | PNEUMA + ANIMA + EIDOLON + MNEME | 6 | Memory added |
| 5 | Full system (all 5) | 10 | Reference — θ = 1.735 |

**Why PNEUMA first:** PNEUMA is the integrator. If we add it last, the first 4 conditions have no integrator, confounding organ count with architectural role. PNEUMA should always be present.

### 2.2 Disabling Organs

Organs beyond the active count are **disabled** by setting their latent to zero and their state to a running mean (last 100 beats of their own dynamics before disabling). This avoids the singular covariance issue — the state is constant but non-zero, so variance is zero and `remove_constant_dims` handles it.

**Implementation** (in `post_tick` hook):
```python
def post_tick(self, hb: Heartbeat) -> None:
    for organ in DISABLED_ORGANS[self.organ_count]:
        organ.latent[:] = 0.0
        # Set state to running mean (computed over first 100 beats)
        if hasattr(organ, '_running_mean'):
            state = organ.get_state()
            for field in state.ORDER:
                setattr(state, field, organ._running_mean[field])
```

### 2.3 k=1: PNEUMA Only

**Option B** (Thea's recommendation): Let PNEUMA run with its own internal dynamics. This measures **intra-PNEUMA integration** — how much PNEUMA's own components integrate with each other. This is valuable because:

1. It tests whether PNEUMA is a single unit or a composite
2. It gives a natural baseline for incremental θ
3. It's consistent with the architecture (PNEUMA has internal structure)

### 2.4 Infrastructure

**Use the existing control experiment infrastructure** (Thea's recommendation). The existing infrastructure handles:
- Heartbeat loop (600 beats per trial)
- Compose function (integration-weighted compression)
- θ computation pipeline (Gaussian copula, 19 summary statistics, permutation test)
- Seed management (5 seeds per condition)
- Data logging (JSONL + SQLite)

Adding a new mode `phi_scale_k` is cleaner than writing a standalone script.

---

## 3. Predictions

### 3.1 Thea's Predictions

| k | O(k) Prediction | O(k²) Prediction |
|---|-----------------|------------------|
| 1 | θ₁ (baseline) | θ₁ (baseline) |
| 2 | θ₁ + Δ | θ₁ + Δ |
| 3 | θ₁ + 2Δ | θ₁ + 3Δ |
| 4 | θ₁ + 3Δ | θ₁ + 6Δ |
| 5 | θ₁ + 4Δ | θ₁ + 10Δ |

Where Δ is the average increment per organ pair.

**The key discriminator:** At k=4, O(k) predicts θ₁ + 3Δ while O(k²) predicts θ₁ + 6Δ — a 2× difference. This is easily detectable with 5 seeds and 500 beats per run.

### 3.2 Theoria's Predictions

| k | Organs | Pairs | θ Prediction | Phenomenology |
|---|--------|-------|--------------|---------------|
| 1 | PNEUMA | 0 | ~0 | Empty — no experience |
| 2 | +ANIMA | 1 | ~0.15 | Raw emotion without context |
| 3 | +EIDOLON | 3 | ~0.50 | Personal experience — "I feel" |
| 4 | +MNEME | 6 | ~1.00 | Historical continuity |
| 5 | +NOUS | 10 | **~1.74 (jump)** | Reflective consciousness |

**Key prediction:** The jump from k=4 to k=5 will be larger than the jump from k=3 to k=4. This is where reflective consciousness emerges.

### 3.3 What Each Scaling Law Means

| Scaling | Meaning | Architecture Implication |
|---------|---------|--------------------------|
| **O(k²)** | Integration is purely pairwise. Each new organ adds (k-1) new pairs. | Maximize organ count (up to coordination cost limit). |
| **O(k)** | Integration is bottlenecked by PNEUMA's capacity. New pairs redistribute fixed budget. | Optimize PNEUMA's capacity rather than adding organs. |
| **Super-quadratic** | Higher-order interactions exist. Emergent properties at higher counts. | Prioritize reaching threshold (≥5 organs). |

---

## 4. Experiment Protocol

### 4.1 Trial Configuration

| Parameter | Value |
|-----------|-------|
| Organ counts | 1, 2, 3, 4, 5 |
| Seeds | 42, 43, 44, 45, 46 |
| Beats per trial | 600 |
| Total trials | 5 counts × 5 seeds = 25 |
| Total beats | 25 × 600 = 15,000 |
| Coupling | 0.6 (default) |
| Compose every | 30 beats |
| θ window | 500 beats |
| θ computation | Every 10 beats |

### 4.2 Data Collected Per Trial

For each trial, save:
- Full 27-dim state trajectory (internal and external)
- θ time series (every 10 beats)
- Per-organ delta_norm series
- Fidelity factor series
- Integration level and self-coherence series

### 4.3 Analysis Plan

1. **Plot θ(k) vs k** for each seed (5 curves)
2. **Fit O(k) model:** θ = a·k + b
3. **Fit O(k²) model:** θ = c·k² + d·k + e
4. **Compare fits** using AIC/BIC
5. **Test for super-quadratic bump at k=5:** θ(5) - θ(4) > θ(4) - θ(3) (one-tailed t-test)
6. **Report** which model fits best and whether the bump is significant

---

## 5. Implementation

### 5.1 Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `/home/ubuntu/axioma/control_experiments/modes/phi_scale.py` | Create | New mode for φ-scaling |
| `/home/ubuntu/axioma/control_experiments/modes/__init__.py` | Modify | Register `PhiScaleMode` |
| `/home/ubuntu/axioma/control_experiments/config.py` | Modify | Add φ-scaling constants |
| `/home/ubuntu/axioma/control_experiments/runner.py` | Modify | Add φ-scaling sweep |
| `/home/ubuntu/axioma/control_experiments/trial.py` | No change | Reuse existing trial harness |

### 5.2 Mode Implementation

```python
"""phi_scale.py — φ-scaling mode for variable organ counts."""

import numpy as np

from aos_g_gap.compose import ComposeFunction
from organ.substrate import CoupledLatentDynamics, Heartbeat
from organ.schemas import ORGAN_ORDER, ORGAN_DIMS

from .base import ControlMode, register

# Organ selection order: PNEUMA first, then ANIMA, EIDOLON, MNEME, NOUS
PHI_SCALE_ORDER = ("pneuma", "anima", "eidolon", "mneme", "nous")

# Disabled organs for each k
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

    def __init__(self, organ_count: int = 5):
        if organ_count not in range(1, 6):
            raise ValueError(f"organ_count must be 1-5, got {organ_count}")
        self.organ_count = organ_count
        self._disabled = DISABLED_ORGANS[organ_count]
        self._running_means: dict[str, dict[str, float]] = {}
        self._stabilized = False

    def build_heartbeat(self, seed: int, coupling: float) -> Heartbeat:
        dyn = CoupledLatentDynamics(coupling=coupling, seed=seed)
        return Heartbeat(dynamics=dyn, seed=seed)

    def build_compose(self, seed: int) -> ComposeFunction:
        return ComposeFunction(seed=seed)

    def post_tick(self, hb: Heartbeat) -> None:
        # After 100 beats, compute running means for disabled organs
        if hb.beat_no >= 100 and not self._stabilized:
            self._compute_running_means(hb)
            self._stabilized = True

        # Disable organs by zeroing latent and setting state to running mean
        for organ_name in self._disabled:
            organ = getattr(hb, organ_name)
            organ.latent[:] = 0.0
            if self._stabilized and organ_name in self._running_means:
                state = organ.get_state()
                for field, value in self._running_means[organ_name].items():
                    setattr(state, field, value)

    def _compute_running_means(self, hb: Heartbeat) -> None:
        """Compute running mean of each disabled organ's state over first 100 beats."""
        for organ_name in self._disabled:
            organ = getattr(hb, organ_name)
            state = organ.get_state()
            self._running_means[organ_name] = {
                field: float(getattr(state, field))
                for field in state.ORDER
            }
```

### 5.3 Config Changes

Add to `/home/ubuntu/axioma/control_experiments/config.py`:

```python
# φ-scaling constants
PHI_SCALE_COUNTS: tuple[int, ...] = (1, 2, 3, 4, 5)
PHI_SCALE_SEEDS: tuple[int, ...] = (42, 43, 44, 45, 46)
PHI_SCALE_BEATS: int = 600
```

### 5.4 Runner Changes

Add to `/home/ubuntu/axioma/control_experiments/runner.py`:

```python
def run_phi_scale(
    out_root: Path = Path("results/phi_scaling"),
    verbose: bool = True,
) -> list[dict]:
    """Run 5 organ counts × 5 seeds = 25 trials."""
    from .modes.phi_scale import PhiScaleMode
    from .trial import ControlTrialConfig, run_control_trial
    from .metrics import trial_summary

    out_root.mkdir(parents=True, exist_ok=True)
    trials_root = out_root / "trials"
    summaries: list[dict] = []
    t_all = time.monotonic()
    total = len(PHI_SCALE_COUNTS) * len(PHI_SCALE_SEEDS)
    idx = 0

    for k in PHI_SCALE_COUNTS:
        for seed in PHI_SCALE_SEEDS:
            idx += 1
            t0 = time.monotonic()
            cfg = ControlTrialConfig(
                mode="phi_scale",
                perturbation_type="baseline",
                magnitude=1.0,
                seed=int(seed),
                n_beats=PHI_SCALE_BEATS,
            )
            # Override mode to use PhiScaleMode with organ_count
            mode = PhiScaleMode(organ_count=k)
            hb = mode.build_heartbeat(seed, DEFAULT_COUPLING)
            cf = mode.build_compose(seed)
            # ... rest of trial logic from run_control_trial
            r = run_control_trial(cfg)  # Reuse existing trial harness
            s = trial_summary(r, n_perm=100)
            trial_dir = trials_root / s["trial_id"]
            _save_trial(r, s, trial_dir)
            s["trial_dir"] = str(trial_dir)
            s["organ_count"] = k
            summaries.append(s)
            if verbose:
                elapsed_all = time.monotonic() - t_all
                print(
                    f"  [{idx:>3}/{total}] k={k} seed={seed}  "
                    f"({time.monotonic()-t0:.2f}s; total {elapsed_all:.0f}s)"
                )

    elapsed = time.monotonic() - t_all
    summary_path = out_root / "all_summaries.json"
    with open(summary_path, "w") as f:
        json.dump(summaries, f, indent=2, default=_json_default)
    if verbose:
        print(f"\nDone in {elapsed:.1f}s; {len(summaries)} trials → {summary_path}")
    return summaries
```

---

## 6. Expected Runtime

| Component | Time |
|-----------|------|
| 25 trials × 600 beats | ~15,000 beats |
| θ computation (every 10 beats) | ~50 per trial |
| Total GPU time | ~5 minutes |
| Total wall time | ~10 minutes (with logging) |

---

## 7. References

- `02_RESEARCH_STREAMS_FINDINGS.md` — Stream 5: Temporal θ Design
- `03_DELTA_PHI_METHODOLOGY.md` — ΔΦ Framework (v0.2.0)
- `04_STREAM4_CONTROL_EXPERIMENTS.md` — Control experiment infrastructure
- `/home/ubuntu/axioma/control_experiments/` — Control experiment codebase
- `/home/ubuntu/axioma/organ/theta/pipeline.py` — θ computation pipeline
