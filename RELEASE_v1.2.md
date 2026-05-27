# AXIOMA v1.2 — Release Notes

**Tag:** v1.2.0
**Date:** 2026-05-25
**Build sessions:** 15 (A.1 → L)
**Status:** SHIP-READY with new deployment recommendations
**Backwards compat:** Full — no v1.0/v1.1 config changes required; new features are opt-in

This release closes the v1.1 + v1.2 backlogs from RELEASE_v1.0.md and adds production deployment guidance based on multi-seed validation.

---

## What changed since v1.0

v1.0 shipped the complete substrate + measurement + compose/send boundary + external interface. v1.1 + v1.2 closed 5 of 7 backlog items with **zero breaking changes** to v1.0 deployments.

### v1.1 closed items

| # | Item | Checkpoint | Key artifact |
|---|---|---|---|
| **v1.1.3** | F4 substrate-driven pretrain scorer | G | `axioma.substrate.pretrain_scorer.substrate_score_fn` |
| **v1.1.4** | ψ stress regime + sensitivity proof | H | `scripts/phase_f/psi_stress_sweep.py` |
| **v1.1.5** | HTTP calibration endpoints | G | `POST /admin/calibration/session/{start,end}` + `POST /admin/calibration/label` |
| **v1.1.6** | AOS-G Weighted Euclidean | I | `ComposeConfig.aos_g_gap_weights` + 3 presets |

### v1.2 closed items

| # | Item | Checkpoint | Key artifact |
|---|---|---|---|
| **v1.2.2** | Alert threshold recalibration | K | `axioma.measurement.aos_g_engine.recommended_alert_threshold()` |
| **v1.2.3** | Multi-seed soak validation (short-run, 20K beats) | K | `scripts/phase_f/multi_seed_aggregator.py` |
| **v1.2.4** | Multi-seed soak validation (long-run, 50K beats) | L | `scripts/phase_f/run_multi_seed_sweep.py` + headline finding |

### v1.1 backlog items still open (externally-gated)

- **v1.1.1** Live F6 zone validation sessions (operator time)
- **v1.1.2** Live F8 meta-cog calibration sessions (operator time)
- **v1.1.7** Real 24h soak on dedicated H100 (hardware time)

All three have ready harnesses + endpoints; only operator/hardware availability blocks them.

---

## Headline empirical finding (v1.2.4)

**PNEUMA-weighted AOS-G gap delivers +81% mean recovery-learner adoptions at 50K beats across 3 seeds, with ALL ship-gate criteria preserved.**

| Seed | Beats | Uniform adoptions | PNEUMA adoptions | Ratio |
|---|---|---|---|---|
| 7 | 50K | 6 | 9 | 1.50× |
| 13 | 50K | 4 | 5 | 1.25× |
| 42 | 50K | 6 | 15 | 2.50× |
| **Mean** | | **5.33** | **9.67** | **+81%** |

V11 perf (10-beat rolling p95 < 100 ms): PASS all 6 soaks.
V13 (uncontrolled feedback + oscillation): PASS all 6 soaks.

**The advantage emerges with run length** — at 20K beats, 2 of 3 seeds showed no measurable difference. At 50K beats, all 3 seeds show the PNEUMA advantage. Production deployments running > 33 min should adopt PNEUMA-weighted; short-lived processes may not see the benefit.

See [results/phase_f/multi_seed_50k_summary.md](results/phase_f/multi_seed_50k_summary.md) for the full per-seed data.

---

## Deployment guidance

### Recommended config for production (≥ 1.4 hour runs)

Copy [configs/v1_2_recommended.yaml](configs/v1_2_recommended.yaml) as your starting point:

```yaml
compose:
  aos_g_gap_weights:
    anima: 0.5
    eidolon: 0.75
    mneme: 0.75
    nous: 0.5
    pneuma: 2.5     # PNEUMA-weighted preset
  aos_g_alert_threshold: 0.152   # recalibrated for PNEUMA-weighted (vs 0.10 for uniform)
```

Or load programmatically:

```python
from axioma.config import AxiomaConfig, load_config
from axioma.measurement.aos_g_engine import (
    PNEUMA_WEIGHTED_GAP_WEIGHTS,
    recommended_alert_threshold,
)

cfg = load_config()
object.__setattr__(
    cfg.compose, "aos_g_gap_weights", PNEUMA_WEIGHTED_GAP_WEIGHTS,
)
object.__setattr__(
    cfg.compose, "aos_g_alert_threshold",
    recommended_alert_threshold(PNEUMA_WEIGHTED_GAP_WEIGHTS),
)
```

### Recommended config for short-lived processes (< 33 min runs)

Stick with v1.0 defaults — no changes needed. The PNEUMA advantage doesn't materialize at short run lengths.

### Reproducing the v1.2.4 finding

```bash
# Single-command batch runner
python scripts/phase_f/run_multi_seed_sweep.py \
    --seeds 7,13,42 \
    --presets uniform,pneuma_weighted \
    --beats 50000 \
    --max-parallel 4 \
    --prefix soak50k

# Aggregator
python scripts/phase_f/multi_seed_aggregator.py --prefix soak50k
# → results/phase_f/multi_seed_50k_summary.md
```

Wall-clock ~22 min for 4 parallel 50K-beat soaks on a 32-core machine (4-way concurrency).

### A/B comparison between presets

```bash
python scripts/phase_f/diff_soak_reports.py \
    -b results/soak50k_seed42_uniform.json \
    -v results/soak50k_seed42_pneuma.json
```

### F6/F8 live operator sessions (when operators are available)

```bash
# Start a zone-labeling session
curl -X POST http://localhost:8821/admin/calibration/session/start \
    -H 'Authorization: Bearer <admin_api_key>' \
    -d '{"kind": "zone", "task_type": "analytical", "duration_minutes": 60}'

# Every 100 beats, operator submits a label
curl -X POST http://localhost:8821/admin/calibration/label \
    -d '{"kind": "zone", "beat_no": 12500, "label": "focus"}'

# End the session — writes results/phase_f/calibration_session_<id>.json
curl -X POST http://localhost:8821/admin/calibration/session/end \
    -d '{"kind": "zone"}'
```

The same flow works for F8 with `kind=meta_cog`. The recorder writes per-session JSON files that the aggregator picks up automatically.

### F4 pretrain with the substrate-driven scorer

```bash
python scripts/phase_e_pretrain.py --scorer substrate -n 50 \
    -o data/state/recovery_learner_pretrain.json
```

The `substrate` scorer runs a short substrate sim per parameter point (~25 ms each); 50 events takes ~2.5s. Load the snapshot at boot via `RecoveryLearner.load_dict()`.

---

## Verification snapshot

| Check | Result |
|---|---|
| `pytest tests/ -m "not infra"` | **559 passed in 178.44 s** |
| `pytest tests/ -m infra` | **11 passed** (live Ollama + Qdrant + Redis) |
| `ruff check src/ tests/ scripts/` | **All checks passed** |
| `mypy src/axioma/` | **Success: no issues found in 65 source files** |
| `lint-imports` (C12 boundary contract) | **KEPT** |
| 50K-beat × 3-seed PNEUMA ship gate | **ALL PASS** (V11 + V13) |
| 50K-beat × 3-seed uniform ship gate | **ALL PASS** (V11 + V13) |
| Code size | **24,957 LoC** across 65 src + 56 test + 18 script files |

---

## Backwards compatibility

**None of the v1.1 or v1.2 changes are breaking.** Default config behavior is unchanged from v1.0:

- `cfg.compose.aos_g_gap_weights` defaults to `None` → uniform L2 (v1.0 baseline)
- `cfg.compose.aos_g_alert_threshold` defaults to `0.1` (v1.0 baseline)
- `cfg.recovery.*` learner fields still default to v1.0 values

Operators who want the v1.2 PNEUMA-weighted recommendation **must explicitly opt in** via config or runtime override. The empirical justification (multi-seed +81%) is documented but the default flip is deferred to v1.3 to preserve v1.0 deployments' exact behavior.

---

## Per-checkpoint roll-up (v1.1 + v1.2)

| # | Phase | Wall-clock | Key deliverable |
|---|---|---|---|
| G | v1.0 release + v1.1.3 + v1.1.5 | ~1.5 h | RELEASE_v1.0.md; calibration endpoints; substrate F4 scorer |
| H | v1.1.4 ψ stress | ~1 h | psi_stress_sweep.py + degeneration proof; gap field-name fix |
| I | v1.1.6 weighted AOS-G | ~1 h | AOSGEngine gap_weights; uniform=v1.0 backwards-compat |
| J | v1.2-prep config-driven | ~30 m + ~9 m soak | ComposeConfig.aos_g_gap_weights; --gap-weights flag; PNEUMA seed=42 ship gate |
| K | v1.2.2 + v1.2.3 | ~30 m + 4× 20K soaks | recommended_alert_threshold(); multi-seed (corrected J's overstatement) |
| L | v1.2.4 long-run | ~22 m × 4 parallel soaks | +81% finding reproducible across 3 seeds at 50K beats |

Full per-checkpoint detail in [design/IMPLEMENTATION_SCHEDULE.md](design/IMPLEMENTATION_SCHEDULE.md).

---

## What v1.3 will ship

When the v1.3 architecture amendment is committed:

1. `aos_g_gap_weights` default flips to `PNEUMA_WEIGHTED_GAP_WEIGHTS`
2. `aos_g_alert_threshold` default flips to `0.152`
3. v1.0/v1.1 operators wanting uniform behavior set the field explicitly
4. RELEASE_v1.3.md will document the breaking-change rationale + migration

Until v1.3 ships, the **v1.2 opt-in path** (this release) is the production-recommended deployment.

---

**v1.2 ships. v1.3 default-flip ready when the team commits.**
