# AXIOMA v1.4 — Release Notes

**Tag:** v1.4.0
**Date:** 2026-05-26
**Build sessions:** 22 → 24 (Checkpoints R, S, T, U)
**Status:** SHIP — three opt-in AOS-G refinements; zero breaking changes
**Backwards compat:** All new features default OFF; v1.3 behavior preserved bit-for-bit when defaults are kept

This release adds three opt-in refinements to the AOS-G + ψ measurement surface. Each addresses a specific operator pain point identified during v1.3 deployment:

| Knob | Pain it fixes | Default |
|---|---|---|
| `aos_g_alert_threshold_auto_tune` (v1.4.2) | Operators on bespoke `aos_g_gap_weights` had to manually run `scripts/phase_f/alert_threshold_calibration.py` to find a sensible threshold. | OFF |
| `psi_per_component_thresholds` (v1.4.3) | A single `psi_alert_threshold` couldn't simultaneously tolerate `compose_probe_health` dipping to ~0.5 during recovery AND catch `structural_health` regressions early. | OFF |
| `aos_g_normalize_per_organ` (v1.4.1, metric variant) | PNEUMA contributed >95% of the gap signal regardless of `aos_g_gap_weights`; small-magnitude organs (ANIMA, EIDOLON) couldn't move the metric. | OFF |

**All three are opt-in.** Deployments that don't touch any of these fields run exactly the same as v1.3 — same defaults, same gap baseline, same alert behavior. There is no breaking change.

---

## What's new

### v1.4.2 — Auto-tuned `aos_g_alert_threshold`

```yaml
compose:
  aos_g_alert_threshold_auto_tune: true
  aos_g_alert_threshold_auto_tune_ratio: 0.014                 # 1.4% of typical magnitude
  aos_g_alert_threshold_auto_tune_warmup_beats: 3000           # v1.4.4: outlasts normalize warmup (60 × 30 = 1800 beats)
  aos_g_alert_threshold_auto_tune_recompute_period_beats: 36000  # ~1h @ 10 Hz
```

After `warmup_beats` AND ≥20 non-zero gap samples, `AOSGEngine` sets `aos_g_alert_threshold = ratio × mean(observed_gap)` and re-tunes every `recompute_period_beats` so the threshold tracks drift. The static `aos_g_alert_threshold` value becomes the initial threshold used during warmup. Each tune emits an `aos_g_alert_threshold_auto_tuned` log event with previous/new/sample-count for visibility.

**Who benefits most**: operators running non-default `aos_g_gap_weights`, where the v1.3 static 0.152 calibration doesn't apply.

### v1.4.3 — Per-component ψ alert thresholds

```yaml
compose:
  psi_alert_threshold: 0.3   # fallback for any unspecified component
  psi_per_component_thresholds:
    structural_health: 0.95   # tight — catches architectural regressions early
    gap_variance_health: 0.2  # loose — substrate dynamics vary naturally
    # compose_probe_health unspecified → 0.3 fallback
```

When set, alert fires if ANY component drops below ITS own threshold (instead of `min(...) < single_threshold`). Missing keys fall back to `psi_alert_threshold`. Out-of-range values rejected at boot; unknown keys silently ignored (tolerant of typos).

**Who benefits most**: operators who want to catch structural-integrity regressions (which should always sit near 1.0) without false-alerting on compose-probe dips during recovery (which legitimately drop to ~0.5).

### v1.4.1 (metric variant) — Per-organ gap normalization

```yaml
compose:
  aos_g_normalize_per_organ: true
  aos_g_normalize_per_organ_window_beats: 600
  aos_g_normalize_per_organ_min_samples: 60
```

When enabled, each organ's raw gap is divided by its rolling mean before the weighted sum:

```
raw_organ_gap_i = ||internal_i − external_i||
scale_i         = rolling_mean(raw_organ_gap_i, window)
gap = sqrt(Σ_organ w_organ × (raw_organ_gap_i / scale_i)²)
```

Under raw L2, PNEUMA's natural magnitude (~7.26) is 130× larger than ANIMA's (~0.036) per Checkpoint I's measurement. Weighting alone can't fix this — even at weight 1.0, PNEUMA's raw magnitude overwhelms any multiplier on other organs. Normalization separates two concerns the old metric conflated: **per-organ scale** (rolling-mean division — every organ contributes on its own scale) and **architectural bias** (`gap_weights` — operators decide which organs should matter more).

**Original v1.4.1 plan was a substrate amendment** (rescaling organ-render magnitudes). That stays in the backlog as a separately-tracked, lower-priority item — this metric-only fix achieves the same architectural goal (balanced per-organ contribution) without touching substrate dynamics.

#### Live-substrate smoke (400 beats, default v1.3 config)

| Organ | Unnormalized share | Normalized share | Δ |
|---|---|---|---|
| anima | 0.01% | 8.58% | +8.56pp |
| eidolon | 0.03% | 11.02% | +10.98pp |
| mneme | 0.79% | 18.48% | +17.70pp |
| nous | 15.21% | 16.94% | +1.72pp |
| **pneuma** | **83.95%** | **44.98%** | **−38.97pp** |

PNEUMA still leads (its v1.3-default weight is 2.5× the others) but the other four organs now contribute meaningfully.

#### Multi-seed validation (Checkpoint U)

3 seeds × 2 modes × 10K beats = 6 soaks:

| seed | mode | V11 | V13u | V13o | rolling10_p95 (ms) | gap_mean | adoptions | overall |
|---|---|:---:|:---:|:---:|---|---|---|:---:|
| 42 | off | ✓ | ✓ | ✓ | 11.589 | 6.9810 | 2 | PASS |
| 42 | **on** | ✓ | ✓ | ✓ | 11.691 | **2.9575** | 1 | PASS |
| 7  | off | ✓ | ✓ | ✓ | 11.605 | 6.3351 | 4 | PASS |
| 7  | **on** | ✓ | ✓ | ✓ | 11.533 | **2.7067** | 5 | PASS |
| 13 | off | ✓ | ✓ | ✓ | 11.572 | 5.9815 | 2 | PASS |
| 13 | **on** | ✓ | ✓ | ✓ | 11.530 | **2.6689** | 4 | PASS |

**All 6 runs PASS V11 + V13.** Perf overhead within ±0.1 ms on rolling p95. Recovery quality net-positive (Δ composite_score: −0.001, +0.009, +0.017). Substrate dynamics essentially unchanged (frag-stage events ±1-6, recovery events ±0-4).

---

## Recommended production pairing

If you enable `aos_g_normalize_per_organ`, also enable `aos_g_alert_threshold_auto_tune`:

```yaml
compose:
  aos_g_normalize_per_organ: true
  aos_g_alert_threshold_auto_tune: true
```

**Why**: normalization shifts `aos_g_gap` mean by ~50% (Checkpoint U: 6.4 → 2.9). The static v1.3 default `aos_g_alert_threshold = 0.152` was calibrated for the unnormalized regime; under normalization it becomes too loose (threshold-to-baseline ratio drops from ~1.4% to ~5%). Auto-tune recalibrates automatically after warmup, so you get a balanced *and* properly-tuned alert surface with no manual calibration step.

The three knobs compose cleanly:

| Combination | Effect |
|---|---|
| All defaults | Pure v1.3 behavior (PNEUMA-weighted, static 0.152 threshold, single ψ threshold) |
| `+ auto_tune` | v1.3 baseline + self-calibrating threshold (good for bespoke `gap_weights`) |
| `+ per_component` | v1.3 baseline + finer per-channel alerting |
| `+ normalize` | Balanced per-organ contributions; gap_mean halves |
| `+ normalize + auto_tune` ⭐ | Balanced AND self-calibrating; recommended for v1.5 default candidate |
| All three | Balanced + self-calibrating + per-channel — full alerting surface |

---

## What hasn't changed

- All v1.0–v1.3 substrate behavior (5 organs, drive, plasticity, perturbation cadence)
- All v1.0–v1.3 measurement engines (θ short/long, raw MI, cascade_delay, ΔΦ, fragmentation monitor, AOS-G+ψ structure, meta-cog, coherence scheduler)
- All v1.0–v1.3 acceptance gates (V6, V8, V10, V11, V12, V13) — all still pass
- v1.3 defaults: PNEUMA-weighted `aos_g_gap_weights`, `aos_g_alert_threshold = 0.152`, `psi_alert_threshold = 0.3`
- C12 boundary (substrate-privacy) enforced both at runtime + lint time
- HTTP/WS/registry/peer-conversation interfaces (D)
- `python -m axioma` production entrypoint with signal-handled lifecycle (N + O)
- `configs/v1_0_backwards_compat.yaml` opt-out path to v1.0 uniform

The only observable difference for unchanged-config deployments is **nothing**. v1.4 is purely additive.

---

## Verification

| Check | Result |
|---|---|
| `pytest tests/ -m "not infra"` | **615 passed** (+23 vs v1.3 — covers v1.4.2/v1.4.3/v1.4.1) |
| `pytest tests/ -m infra` | **11 passed** |
| `ruff check src/ tests/ scripts/` | All checks passed |
| `mypy src/axioma/` | Success, 66 source files |
| `lint-imports` | C12 contract KEPT |
| `python -m axioma` smoke | Full stack boots, all v1.4 knobs respected, clean shutdown |
| Multi-seed normalize V11/V13 validation | **6/6 runs PASS** (Checkpoint U) |
| Live-substrate normalize smoke | PNEUMA share 83.95% → 44.98% (Checkpoint T) |

---

## Migration

### Operators upgrading from v1.3

**Zero action required.** All v1.4 knobs default OFF; v1.3 behavior is preserved bit-for-bit. Upgrade in place.

### Operators wanting v1.4's normalize + auto-tune pairing

Add to your config YAML:

```yaml
compose:
  aos_g_normalize_per_organ: true
  aos_g_alert_threshold_auto_tune: true
```

Optionally also set:

```yaml
compose:
  psi_per_component_thresholds:
    structural_health: 0.95
    gap_variance_health: 0.2
```

### Operators on bespoke `aos_g_gap_weights`

You're the primary beneficiary of v1.4.2 auto-tune — it eliminates the manual `scripts/phase_f/alert_threshold_calibration.py` step. Enable just auto-tune:

```yaml
compose:
  aos_g_alert_threshold_auto_tune: true
```

### Operators on `configs/v1_0_backwards_compat.yaml`

Continue using the YAML. v1.4 doesn't change v1.0 backwards-compat semantics. If you want to opt into auto-tune in the v1.0 regime, set `aos_g_alert_threshold_auto_tune: true` in that YAML.

---

## Per-checkpoint roll-up (v1.4-specific)

| # | Checkpoint | Wall-clock | Key deliverable |
|---|---|---|---|
| R | v1.4.2 auto-tuned `aos_g_alert_threshold` | ~30 min | `_maybe_auto_tune_threshold` + 12 unit tests + cfg + app wiring |
| S | v1.4.3 per-component ψ alert thresholds | ~25 min | `_resolve_per_component_thresholds` + 11 unit tests + cfg + app wiring |
| T | v1.4.1 per-organ gap normalization (rescoped: metric-only) | ~40 min | `_per_organ_gap_history` + 12 unit tests + cfg + app wiring + live-substrate smoke |
| U | v1.4.1 multi-seed validation + harness/soak v1.4 plumbing | ~30 min | 6/6 normalize-on V11/V13 PASS + harness threads all v1.4 knobs + soak `--normalize-per-organ` CLI |
| **V** | **v1.4 release artifact** | **~30 min** | **This release** + runbook v1.4.1 subsection + recommended-pairing note |

Full per-checkpoint history in [design/IMPLEMENTATION_SCHEDULE.md](design/IMPLEMENTATION_SCHEDULE.md).

---

## Open work after v1.4

- **v1.5 default-flip evaluation** — whether to make `aos_g_normalize_per_organ=True` + `aos_g_alert_threshold_auto_tune=True` the v1.5 default. Bar is higher than v1.3: 5+ seeds × 50K beats × full ship-gate sweep. Multi-seed validation in Checkpoint U is *sufficient evidence to recommend the pairing*; *not yet sufficient to flip the default*.
- **v1.1.1** Live F6 zone validation sessions (operator-gated; HTTP endpoints + recorder ready since G)
- **v1.1.2** Live F8 meta-cog calibration sessions (operator-gated; same)
- **v1.1.7** Real 24h soak on dedicated H100 (hardware-gated)
- **v1.4.1 (substrate variant)** PNEUMA substrate render-scale rebalance — backlog-only; superseded by the metric fix shipped here.

No coding items remain in the v1.4 metric scope.

---

**v1.4 ships. Three opt-in AOS-G refinements; zero breaking changes.**
