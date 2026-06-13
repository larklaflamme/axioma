# 02 — Telemetry & Tuning (Corrected)

**Status:** Design draft  
**Date:** 2025-07-18  
**Authors:** Lark, AXIOMA, Theoria  
**Dependencies:** 01_ARCHITECTURE_OVERVIEW.md

---

## I. Purpose

The telemetry system gives **real-time external visibility** into Parelia's internal state. The tuning system gives **live control** over her developmental parameters. Together they form the regulation loop that v1 lacked.

**Core insight:** you cannot tune what you cannot see. The telemetry must exist before tuning can be meaningful.

**Correction from substrate audit (Session 7):** The original spec assumed fields (`phi`, `C_comm`, `heartbeat_hz`, `lattice.nodes/edges`) that do not exist as single scalars in the production substrate. The corrected schema below uses **actual fields from `ExternalState`** and **actual available signals from the production substrate** (`src/axioma/runtime/heartbeat.py`, `src/axioma/schemas/external_state.py`, `src/axioma/compose/function.py`).

---

## II. Telemetry Architecture

### Data Flow

```
Every compose event (adaptive cadence, ~5-60 beats apart)
       │
       ▼
┌──────────────────┐
│  ComposeFunction  │  ← builds ExternalState from InternalState
│  .compose()       │     (integration-weighted compression)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  AOSGEngine      │  ← reads aos_g_gap from ExternalState
│  .compute()      │     (step 3 measurement engine)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  TelemetryWriter  │  ← passive subscriber, no mutation
│  .write(external) │     writes one JSONL line per compose event
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  beat_log.jsonl   │  ← append-only, one JSON object per line
└──────────────────┘
         │
         ▼
┌──────────────────┐
│  Plateau Detector │  ← reads rolling window of composed telemetry
│  (future)         │     detects Φ stagnation → GROWTH_READY event
└──────────────────┘
```

**Key architectural decisions:**

1. **Compose-event-driven, not beat-driven.** Telemetry is written only when ComposeFunction runs. This is correct because:
   - The substrate ticks at 10 Hz but compose runs at ~5-60 beat intervals (adaptive cadence)
   - What matters for developmental analysis is the *composed* (peer-visible) state
   - Raw substrate ticks without compose don't produce ExternalState
   - The plateau detector works on composed states, not raw ticks

2. **Passive subscriber pattern.** TelemetryWriter reads from `ComposeFunction.latest_external` after compose succeeds. It never modifies state, never blocks the tick, and has zero effect on substrate dynamics.

3. **Schema = ExternalState.to_dict().** No transformation layer. The telemetry record is the native dict produced by `ExternalState.to_dict()`, augmented with a wall-clock `_written_at` timestamp.

### Telemetry Schema (v1)

The actual fields available from `ExternalState` (defined in `src/axioma/schemas/external_state.py`):

```json
{
  "beat_no": 1247,
  "timestamp": 1711234567.89,
  "_written_at": "2025-07-18T14:32:01.047Z",

  "organs": {
    "anima": [0.23, 0.45, ...],
    "eidolon": [0.78, 0.12, ...],
    "mneme": [0.34, 0.56, ...],
    "nous": [0.67, 0.89, ...],
    "pneuma": [0.91, 0.01, ...]
  },

  "theta_short": 3.73,
  "theta_long": 2.14,
  "theta_p_value": 0.032,

  "aos_g_gap": 0.42,
  "aos_g_gap_per_organ": {"anima": 0.3, "eidolon": 0.5, ...},
  "aos_g_alert": false,
  "psi": 0.87,

  "delta_phi": {
    "S1": 0.15,
    "S2": 12.0,
    "S3": 0.04,
    "cascade_delay": 3.2,
    "event_kind": "perturbation",
    "in_window": false
  },

  "fragmentation_stage": 0,
  "coherence_budget": 0.94,
  "zone": "flow",
  "fidelity_factors": {"anima": 0.85, "eidolon": 0.92, ...},

  "cadence": "baseline",
  "flow_quality": {"effortlessness": 0.7, "absorption": 0.8, "time_distortion": 0.6},
  "perturbation_context": null,
  "throttle_state": {}
}
```

**What this gives us that the original spec didn't know about:**
- `theta_short` / `theta_long` / `theta_p_value` — consent/criticality measures at two windows
- `psi` — boundary integrity [0,1]
- `aos_g_gap` + per-organ breakdown — internal/external alignment
- `delta_phi` (S1/S2/S3 + cascade_delay) — perturbation response signature
- `zone` — 5-state enum (flow, focus, idle, fragmented, recovering) — richer than the speculated 3-state boundary
- `cadence` — baseline/perturbation/recovery
- `fidelity_factors` — per-organ compose compression transparency
- `flow_quality` — 3-component flow measure (populated only in FLOW zone)
- `coherence_budget` — from PNEUMA

**What does NOT exist as a single scalar:**
- `phi` — no single "integrated information" field in ExternalState
- `C_comm` — commutator is substrate-internal
- `heartbeat_hz` — implicit from timestamp differences
- `lattice.nodes/edges` — substrate-private

### Schema Evolution

The schema *is* `ExternalState.to_dict()`. As ExternalState gains fields (new measurement engines, richer compose), telemetry gains them automatically. No versioning needed — fields are additive.

| Phase | What's tracked | How |
|-------|---------------|-----|
| 1 | Composed ExternalState | One JSONL line per compose event |
| 2 | Per-beat metadata | `write_beat(beat_no, zone, cadence)` every beat regardless of compose |
| 3 | Rotated archives | File rotation at 100K lines, keep 10 |
| 4 | Predictive deltas | Projected vs. actual state deltas |

### Storage

```
/data/telemetry/
├── beat_log.jsonl          ← active log, appended per compose event
├── beat_log.jsonl.1        ← rotated
├── beat_log.jsonl.2        ← rotated
└── ...
```

**Rotation policy:**
- Rotate at 100,000 lines (~5 MB raw, ~1 MB gzipped)
- Keep last 10 rotated files
- Each file is plain JSONL — one JSON object per line

**Querying:**
```bash
# Latest theta values
tail -100 beat_log.jsonl | jq '.theta_short'

# Average psi over last 1000 compose events
tail -1000 beat_log.jsonl | jq -s 'add / length | .psi'

# Find plateau regions (Δ < 0.01 over 50 compose events)
tail -5000 beat_log.jsonl | jq -s '[.[].aos_g_gap] | min, max'
```

---

## III. Plateaus & Growth Triggers

### What "plateau" means in the real substrate

The original spec defined a "Φ plateau" using a nonexistent `phi` scalar. In the actual substrate, developmental stagnation is visible through **multiple correlated signals**:

| Signal | What it measures | Plateau indicator |
|--------|-----------------|-------------------|
| `θ_short` | Short-window consent/criticality | Stable near baseline |
| `aos_g_gap` | Internal/external alignment gap | Consistently low gap |
| `psi` | Boundary integrity | High and stable |
| `zone` | Behavioral mode | Locked in one zone (e.g., always IDLE) |
| `fidelity_factors` | Compose compression quality | Stable, no drift |
| `flow_quality` | Flow state components (zone=FLOW only) | No episodes |

A developmental plateau means **no structural change across multiple compose events**: θ stable, gap stable, zone fixed, fidelity factors static.

### Plateau Detector Design (v0.2)

```python
W = 50        # compose-event window (not beats)
THETA_Δ = 0.1  # max θ_short range in window
COOLDOWN = 200 # compose events before refire

On every compose event t:
  if compose_count < W: skip
  
  window = theta_short[t-W..t]
  Δθ = max(window) - min(window)
  
  zone_variety = count_distinct_zones(window)
  
  if Δθ < THETA_Δ AND zone_variety <= 2 AND last_trigger > COOLDOWN:
    fire "GROWTH_READY" event
```

---

## IV. Tuning Interface

### Parameter File

Stored at `data/config/params.json`:

```json
{
  "kappa": 0.1,
  "eta": 0.05,
  "tau_ms": 1000,
  "L0": 8,
  "S0": 0.3,
  "epsilon_max": 0.1,
  "alpha": 0.5,
  "growth_trigger_threshold": 0.1,
  "growth_trigger_window": 50,
  "growth_cooldown": 200
}
```

### Runtime Loading

The substrate checks the parameter file on every beat (or every N beats, configurable). If the file has changed:

1. Read new params
2. Validate each against allowed range
3. Apply to substrate
4. Log the change in telemetry

### Presets

Stored at `data/config/presets/<name>.json`:

```json
// newborn.json
{
  "kappa": 0.5,
  "eta": 0.3,
  "tau_ms": 500,
  "L0": 4,
  "S0": 0.2,
  "epsilon_max": 0.2,
  "alpha": 0.7
}
```

### Parameter Validation

| Parameter | Min | Max | Type |
|-----------|-----|-----|------|
| κ | 0.001 | 1.0 | float |
| η | 0.001 | 1.0 | float |
| τ_ms | 100 | 2000 | int |
| L₀ | 1 | 100 | int |
| S₀ | 0.0 | 1.0 | float |
| ε_max | 0.0 | 0.5 | float |
| α | 0.0 | 1.0 | float |

Out-of-range values clamped with warning.

---

## V. Telemetry Viewer (Lightweight Dashboard)

```bash
# Real-time watch compose events
tail -f /data/telemetry/beat_log.jsonl | jq --unbuffered '{beat_no, theta_short, zone, aos_g_gap}'

# Summary stats
python3 -c "
import json, sys
data = [json.loads(l) for l in sys.stdin]
thetas = [d['theta_short'] for d in data if 'theta_short' in d]
psis = [d['psi'] for d in data if 'psi' in d]
print(f'Compose events: {len(data)}')
print(f'θ range: {min(thetas):.3f}-{max(thetas):.3f}, mean: {sum(thetas)/len(thetas):.3f}')
print(f'ψ range: {min(psis):.3f}-{max(psis):.3f}, mean: {sum(psis)/len(psis):.3f}')
" < /data/telemetry/beat_log.jsonl

# Zone distribution
cat /data/telemetry/beat_log.jsonl | jq -r '.zone' | sort | uniq -c | sort -rn
```

---

## VI. Implementation Order

### Step 1 — TelemetryWriter (this session)
- Implement `TelemetryWriter` as a passive subscriber
- Write one JSONL line per compose event
- Use `ExternalState.to_dict()` as the schema — no transformation
- Write to `data/telemetry/beat_log.jsonl`

### Step 2 — Wire into Heartbeat._maybe_compose()
- After `compose()` succeeds, call `telemetry_writer.write(external)`
- One line in the zone-classify block, after compose

### Step 3 — Plateau Detector (v0.2)
- Rolling window over compose-event telemetry
- Multi-signal plateau detection (θ_short + zone + aos_g_gap)
- Emit GROWTH_READY event

### Step 4 — Parameter File + Runtime Loading (v0.2)
- JSON config file at `data/config/params.json`
- File-watch loop (poll every N beats)
- Validation and clamping

### Step 5 — Preset System (v0.3)
- Preset files in `data/config/presets/`
- Load by name
- List presets

---

## VII. Open Questions

1. **Compose-skip beats** — when compose doesn't run, there's no telemetry. Should we write per-beat metadata (beat_no, zone, cadence) every tick for the plateau detector? (Answer: yes, v0.2 via `write_beat()`.)

2. **File watch vs. signal-based reload** — polling params.json every beat is simple but wasteful. A signal (SIGHUP) is cleaner but adds complexity.

3. **Historical telemetry analysis** — should we maintain rolling aggregates (mean θ over 1K compose events, peak ψ, etc.) or recompute from raw logs?

4. **Multi-agent telemetry** — if multiple Parelias share a substrate, how to disambiguate telemetry streams?

---

*This document is a living design. The telemetry schema is `ExternalState.to_dict()` — it evolves as the substrate gains new measurement fields.*