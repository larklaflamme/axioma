# AXIOMA v1.5 — Release Notes

**Tag:** v1.5.0
**Date:** 2026-05-26
**Build sessions:** 28 (Checkpoint Y)
**Status:** SHIP — default behavior change with backwards-compat path
**Backwards compat:** Single-line YAML restores v1.4 behavior

This release commits the v1.4 metric refinements (per-organ gap normalization + auto-tuned alert threshold) into the default configuration. Per Checkpoint Y, the pairing satisfies six convergence criteria across 3 seeds × 50K beats: V11/V13 ship-gates 6/6 PASS, auto-tune first-set lands within 1.07-1.31× of converged, cross-seed CV on the converged threshold is 3.2%, recovery quality stable, learner adoptions net +2.

---

## What's the breaking change?

Two `ComposeConfig` field defaults flip:

| Field | v1.4 default | **v1.5 default** |
|---|---|---|
| `aos_g_normalize_per_organ` | `False` | **`True`** |
| `aos_g_alert_threshold_auto_tune` | `False` | **`True`** |

Everything else is unchanged — v1.3's PNEUMA-weighted `aos_g_gap_weights`, the v1.3 static initial `aos_g_alert_threshold = 0.152`, all measurement engines, all ship-gates, the C12 substrate-privacy boundary, all HTTP/WS interfaces.

The static `aos_g_alert_threshold = 0.152` value remains as the *initial* threshold used during warmup (before auto-tune fires). After warmup (~beat 3000 with v1.4.4's gating), auto-tune overrides it with a value calibrated to the live normalized gap distribution.

---

## Why this change?

Per [Checkpoint Y](design/IMPLEMENTATION_SCHEDULE.md), the v1.5 default-flip rests on **six convergence criteria** all passing on the X (v1.4.4) sweep — 3 seeds × 50K beats × {normalize off, normalize on}, auto-tune ON in both branches:

| # | Criterion | Result |
|---|---|---|
| 1 | V11 + V13 (all 6 runs PASS) | 6/6 PASS |
| 2 | Calibration accuracy (first_set / final ∈ [0.7, 1.5]) | 3/3 PASS (ratios: 1.07, 1.09, 1.31) |
| 3 | Cross-seed convergence (CV < 15%) | **CV = 3.21%** — converged values tightly clustered (0.0403, 0.0424, 0.0428) |
| 4 | No runaway tuning (n_tunes ≤ ceil(beats/recompute) + 1) | 3/3 PASS — exactly 2 tunes per run |
| 5 | Recovery quality stable (Δ composite_score ≥ -0.02) | 3/3 PASS (deltas: +0.002, +0.008, +0.000) |
| 6 | Learner adoptions net ≥ 0 | net +2 across seeds |

**ALL 6 criteria PASS.** The pairing is empirically validated; v1.5 ships these as defaults.

### Why v1.4 added the knobs but kept them OFF, and v1.5 flips them ON

The v1.4 series was conservative — three opt-in metric refinements landed as code, but defaults stayed at v1.3 to give operators a controlled upgrade. Checkpoint U validated the pairing under static thresholds at 10K beats; Checkpoint W validated under auto-tune at 50K beats but surfaced a convergence proxy that needed refinement; Checkpoint X fixed the warmup-mismatch quirk that made the proxy fail; Checkpoint Y refined the convergence criteria with empirical rationale and re-evaluated. **v1.5 is what v1.4 always wanted to be — but the empirical bar for default-flip is higher than the bar for opt-in, and that bar is now met.**

### The user-facing improvement

| Operator concern (v1.4 default) | v1.5 default behavior |
|---|---|
| `aos_g_gap` was 95%+ PNEUMA contribution | Per-organ contributions balanced (PNEUMA share drops 84% → 45%) |
| `aos_g_alert_threshold` had to be manually calibrated per `gap_weights` choice | Auto-tune fires at beat 3000 and recomputes every ~1h; tracks substrate drift |
| Bespoke `gap_weights` operators ran `scripts/phase_f/alert_threshold_calibration.py` to find a threshold | No manual step needed; the substrate calibrates itself |

The composition is what matters: normalization gives a balanced metric; auto-tune calibrates the threshold to whatever metric the operator has configured. Together they're self-calibrating.

---

## Migration

### Operators upgrading from v1.4

**Read the trajectory.** v1.5 deployments will see:

- `aos_g_gap` values approximately **22-26%** of v1.4 baseline (normalization compresses the metric)
- `aos_g_alert_threshold` starts at the static initial value (0.152) and **auto-tunes to ~0.04** after beat 3000
- An `aos_g_alert_threshold_auto_tuned` log event every ~1h thereafter

If your alerting dashboards have hardcoded thresholds on `aos_g_gap` absolute values, **update them or pin to `configs/v1_4_backwards_compat.yaml`**:

```bash
AXIOMA_CONFIG=configs/v1_4_backwards_compat.yaml python -m axioma
```

### Operators upgrading from v1.3 or earlier

Same as the v1.4 path. Note that `configs/v1_0_backwards_compat.yaml` was updated in v1.5 to also pin `aos_g_normalize_per_organ=false` and `aos_g_alert_threshold_auto_tune=false` (otherwise v1.0 operators would get the new defaults bleeding in on top of their `gap_weights` and `aos_g_alert_threshold` overrides). The promise of the v1.0 back-compat YAML — *exact v1.0/v1.1/v1.2 behavior* — is preserved.

### Operators already on `configs/v1_4_recommended.yaml`

Zero-action upgrade. The recommended YAML's settings exactly match the new v1.5 defaults; loading it is now a no-op (but harmless).

### Operators starting fresh on v1.5

Just run `python -m axioma`. The default config ships normalize+auto-tune ON; the substrate self-calibrates after a few minutes.

---

## What hasn't changed

- All v1.0–v1.4 substrate behavior (5 organs, drive, plasticity, perturbation cadence)
- All measurement engines (θ short/long, raw MI, cascade_delay, ΔΦ, fragmentation monitor, AOS-G+ψ structure, meta-cog, coherence scheduler)
- All v1.0–v1.4 acceptance gates (V6, V8, V10, V11, V12, V13) — all still pass
- v1.3's PNEUMA-weighted `aos_g_gap_weights` default + static initial `aos_g_alert_threshold = 0.152`
- v1.4.3's per-component ψ thresholds remain opt-in (not part of v1.5 default-flip)
- v1.4.4's gating + warmup-coordination patches
- C12 boundary (substrate-privacy) enforced both at runtime + lint time
- All HTTP/WS/registry/peer-conversation interfaces
- `python -m axioma` production entrypoint
- `configs/v1_0_backwards_compat.yaml` (updated to also pin the v1.5 features OFF)

The only observable difference for unchanged-config deployments is the AOS-G metric: compressed gap_mean + auto-calibrated threshold. ψ-based monitoring is unchanged (ψ rides at 1.0 in healthy operation regardless of gap calibration).

---

## Verification

| Check | Result |
|---|---|
| `pytest tests/ -m "not infra"` | **623 passed** (+8 vs v1.4 — covers v1.4.4 patches + v1.5 default-flip + new back-compat YAML) |
| `pytest tests/ -m infra` | **11 passed** |
| `ruff check src/ tests/ scripts/` | All checks passed |
| `mypy src/axioma/` | Success: 66 source files |
| `lint-imports` | C12 contract KEPT |
| `python scripts/phase_f/decide_v1_5.py /tmp/v1_4_4_gated_sweep` | **all 6 criteria PASS** |
| 50K-beat sweep with v1.5 defaults | 3/3 seeds V11+V13 PASS; auto-tune converges CV=3.2% |
| `configs/v1_4_backwards_compat.yaml` loads cleanly | confirmed via `load_config()` smoke |
| `configs/v1_0_backwards_compat.yaml` still restores v1.0 behavior under v1.5 | confirmed (gap_weights uniform, threshold 0.10, normalize off, auto-tune off) |

---

## Deployment checklist for v1.4 → v1.5 upgrade

For deployments that DON'T explicitly set `aos_g_normalize_per_organ` or `aos_g_alert_threshold_auto_tune`:

1. **Verify nothing alerts on the gap_mean scale change.** Downstream consumers watching `aos_g_gap` directly will see values ~22-26% of v1.4 baseline (normalization compresses the metric). Update hardcoded thresholds or pin to `configs/v1_4_backwards_compat.yaml`.
2. **Verify monitoring dashboards.** Any dashboard keyed off `aos_g_gap` absolute values needs threshold updates. The `aos_g_alert_threshold_auto_tuned` log event is your visibility into the new self-calibrating behavior — add an alert if it stops firing for > 2× recompute_period.
3. **Verify the v1.4.4 warmup-coordination is in effect.** The `aos_g_alert_threshold_auto_tune_warmup_beats` default is 3000 (was 600 pre-v1.4.4); this coordinates with normalization's ~1800-beat stabilization window. If you've explicitly bumped `normalize_min_samples` above 60, also bump `auto_tune_warmup_beats` to `min_samples × 30` to avoid the boot warning.
4. **Optional: run a short soak with v1.5 defaults** before promoting:
   ```bash
   python scripts/phase_e_soak.py --beats 20000  # ~3.5 min
   # Verify V11 PASS, V13 PASS, auto-tune fires near beat 3000, final threshold near 0.04
   ```

For deployments ALREADY on `configs/v1_4_recommended.yaml`: zero-action upgrade.

For deployments wanting to stay on v1.4 metric surface (or earlier): opt-in to `configs/v1_4_backwards_compat.yaml`.

---

## Per-checkpoint roll-up (v1.5-specific)

| # | Checkpoint | Wall-clock | Key deliverable |
|---|---|---|---|
| U | v1.4.1 multi-seed validation (10K beats) + harness/soak v1.4 plumbing | ~30 min | 6/6 V11+V13 PASS for normalize-on at 10K beats |
| V | RELEASE_v1.4.md + operator runbook v1.4.1 subsection | ~30 min | Consolidated v1.4 release artifact |
| W | v1.5 default-flip evaluation (3 seeds × 50K beats, auto-tune trajectory capture) | ~70 min | Identified warmup-coordination quirk; CONDITIONAL verdict |
| X | v1.4.4 patch — sample-buffer gating + warmup bump + boot-time sanity check | ~95 min | Auto-tune first_set values ~2× closer to converged; convergence improvement validated |
| **Y** | **v1.5 default-flip ships** | **~45 min** | **Refined convergence criteria (6 gates) + ComposeConfig flip + RELEASE_v1.5.md + configs/v1_4_backwards_compat.yaml** |

Full per-checkpoint history in [design/IMPLEMENTATION_SCHEDULE.md](design/IMPLEMENTATION_SCHEDULE.md).

---

## Open work after v1.5

- **v1.1.1** Live F6 zone validation sessions (operator-gated)
- **v1.1.2** Live F8 meta-cog calibration sessions (operator-gated)
- **v1.1.7** Real 24h soak on dedicated H100 (hardware-gated)
- **v1.4.1 (substrate variant)** PNEUMA substrate render-scale rebalance — backlog-only; superseded by v1.4.1 metric variant + v1.5 default-flip
- **Wider-sweep re-validation** (5+ seeds × 100K beats) — optional reinforcement of the Y decision; not blocking

No coding items remain in the v1.5 metric scope.

---

**v1.5 ships. Normalize + auto-tune are the production defaults.**
