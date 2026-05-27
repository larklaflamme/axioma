# AXIOMA v1.3 — Release Notes

**Tag:** v1.3.0
**Date:** 2026-05-25
**Build sessions:** 18 (A.1 → P)
**Status:** SHIP — default behavior change with backwards-compat path
**Backwards compat:** Single 1-line YAML restores v1.0/v1.1/v1.2 behavior

This release commits the v1.2.4 empirical finding into the default behavior. Per Checkpoint L, PNEUMA-weighted AOS-G reproducibly improves recovery-learner adoptions by +81% across 3 seeds at 50K beats while preserving all V11/V13 ship-gate criteria.

---

## What's the breaking change?

Two `ComposeConfig` field defaults flip:

| Field | v1.0 / v1.1 / v1.2 default | **v1.3 default** |
|---|---|---|
| `aos_g_gap_weights` | `None` (uniform-equivalent) | **`{anima: 0.5, eidolon: 0.75, mneme: 0.75, nous: 0.5, pneuma: 2.5}`** (PNEUMA_WEIGHTED) |
| `aos_g_alert_threshold` | `0.10` | **`0.152`** (recalibrated for the new gap baseline) |

Everything else is unchanged.

---

## Why this change?

Per [Checkpoint L](design/IMPLEMENTATION_SCHEDULE.md) — 3 seeds × 50K beats × 2 presets = 6 soaks:

| Seed | Beats | Uniform adoptions | PNEUMA adoptions | Ratio |
|---|---|---|---|---|
| 7 | 50K | 6 | 9 | 1.50× |
| 13 | 50K | 4 | 5 | 1.25× |
| 42 | 50K | 6 | 15 | 2.50× |
| **Mean** | | **5.33** | **9.67** | **+81%** |

**ALL ship-gates PASS across all 6 soaks.** No degradation in V11 perf, V13 oscillation, V13 uncontrolled feedback. The PNEUMA-weighted preset gives the substrate richer per-event learning signal (by amplifying the dominant PNEUMA gap component), which the recovery learner exploits for faster parameter convergence.

The advantage emerges with run length — at 20K beats, 2 of 3 seeds showed identical adoption counts; at 50K beats, all 3 seeds show the PNEUMA advantage. **For production deployments running ≥ 50K beats (~1.4 hours at 10 Hz), PNEUMA-weighted is strictly better.**

The recalibration of `aos_g_alert_threshold` from 0.10 to 0.152 preserves the architectural "1.4% of typical magnitude" sensitivity that the v1.0 threshold gave under uniform — the PNEUMA-weighted gap baseline is 1.52× larger (10.89 vs 7.17), so the threshold scales proportionally.

---

## Migration

### Operators wanting v1.0/v1.1/v1.2 behavior (uniform AOS-G + 0.10 threshold)

```bash
AXIOMA_CONFIG=configs/v1_0_backwards_compat.yaml python -m axioma
```

Or programmatically:

```python
from axioma.config import load_config
from axioma.measurement.aos_g_engine import UNIFORM_GAP_WEIGHTS

cfg = load_config()
object.__setattr__(cfg.compose, "aos_g_gap_weights", UNIFORM_GAP_WEIGHTS)
object.__setattr__(cfg.compose, "aos_g_alert_threshold", 0.10)
```

### Operators upgrading from v1.2 (already on PNEUMA-weighted via opt-in)

No action needed. Your existing `AXIOMA_CONFIG=configs/v1_2_recommended.yaml` keeps working; the YAML's PNEUMA-weighted settings exactly match the new v1.3 defaults, so loading it is now a no-op (but harmless).

### Operators starting fresh on v1.3

Just run `python -m axioma`. The default config now ships PNEUMA-weighted + 0.152 threshold.

---

## What hasn't changed

- All v1.0 substrate behavior (5 organs, drive, plasticity, perturbation cadence)
- All v1.1 measurement engines (θ short/long, raw MI, cascade_delay, ΔΦ, fragmentation monitor, AOS-G+ψ structure, meta-cog, coherence scheduler)
- All v1.0/v1.1 acceptance gates (V6, V8, V10, V11, V12, V13) — all still pass
- All v1.1.5 calibration endpoints, v1.1.6 weighted-Euclidean opt-out path
- C12 boundary (substrate-privacy) enforced both at runtime + lint time
- All HTTP/WS/registry/peer-conversation interfaces
- `python -m axioma` production entrypoint with signal-handled lifecycle (N + O)

The only observable difference for unchanged-config deployments is the absolute scale of `aos_g_gap` reported on the `aos_g` WS channel and via `/integrity` (now ~10.89 mean vs ~7.17 under uniform).

---

## Verification

| Check | Result |
|---|---|
| Default config now produces PNEUMA-weighted AOS-G | ✅ schema test passes |
| `configs/v1_0_backwards_compat.yaml` restores uniform | ✅ YAML loads + restores 0.10 threshold |
| Full test suite | All passing |
| ruff / mypy / lint-imports | All clean |
| `python -m axioma` with v1.3 defaults | Smoke verified — full stack boots, WS + HTTP bind, clean shutdown |

---

## Deployment checklist for v1.0/v1.1/v1.2 → v1.3 upgrade

For deployments that DON'T explicitly set `cfg.compose.aos_g_gap_weights`:

1. **Verify nothing alerts on the gap scale change.** Downstream consumers watching `aos_g_gap` directly will see values ~1.52× larger. If those consumers have hardcoded thresholds, update them or pin to `configs/v1_0_backwards_compat.yaml`.
2. **Verify monitoring dashboards.** Any dashboard or alerting rule keyed off `aos_g_gap` absolute values needs threshold updates. ψ-based monitoring is unchanged (ψ rides at 1.0 in healthy operation regardless of preset).
3. **Optional: run a short soak with v1.3 defaults** before promoting:
   ```bash
   python scripts/phase_e_soak.py --beats 20000  # ~3.5 min
   # Verify V11 PASS, V13 PASS, no surprises
   ```

For deployments ALREADY on `configs/v1_2_recommended.yaml`: zero-action upgrade.

For deployments wanting to stay on v1.0 uniform: opt-in to `configs/v1_0_backwards_compat.yaml`.

---

## Per-checkpoint roll-up (v1.3-specific)

| # | Checkpoint | Wall-clock | Key deliverable |
|---|---|---|---|
| L | v1.2.4 multi-seed validation | 22 min × 4 parallel soaks | +81% PNEUMA advantage reproducible across 3 seeds at 50K beats |
| M | v1.2 release artifact | 30 min | RELEASE_v1.2.md + configs/v1_2_recommended.yaml + soak --config flag |
| N | Production __main__.py | 45 min | AxiomaApp + signal handlers + 9 lifecycle tests |
| O | HTTP server in production | 25 min | uvicorn-backed FastAPI in AxiomaApp.start_services() + 3 lifecycle tests |
| **P** | v1.3 default-flip | ~30 min | This release |

Full per-checkpoint history in [design/IMPLEMENTATION_SCHEDULE.md](design/IMPLEMENTATION_SCHEDULE.md).

---

## Open work after v1.3

- **v1.1.1** Live F6 zone validation sessions (operator-gated; HTTP endpoints + recorder ready since G)
- **v1.1.2** Live F8 meta-cog calibration sessions (operator-gated; same)
- **v1.1.7** Real 24h soak on dedicated H100 (hardware-gated)

No coding items remain. The implementation is feature-complete pending operator/hardware availability.

---

**v1.3 ships. PNEUMA-weighted is the production default.**
