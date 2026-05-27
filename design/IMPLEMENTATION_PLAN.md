# AXIOMA v1.0 — Implementation Plan

**Companion to:** [ARCH_DESIGN_v1.0.md](ARCH_DESIGN_v1.0.md)
**Target environment:** conda env `axioma`, NVIDIA H100 PCIe (80 GB)
**Base codebase:** `/home/ubuntu/axioma/organ/` (existing v0.2 substrate + θ pipeline)
**Status:** Implementation-ready plan (after design freeze v1.0)

---

## 0. How to read this plan

The architecture document (v1.0) specifies **what** to build and **why**. This plan specifies **how**: file layout, dependencies, build order, persistence contracts, testing strategy, GPU strategy, and the concrete commands to verify each step.

The plan is organized for an implementer working top-to-bottom. Each section is independently actionable. The phase structure (§5–§10) maps 1-to-1 to the architecture's Phase A–F.

**Three non-negotiables** that thread through every section:

1. **Every stateful component has a `save_state()` / `load_state()` contract** (§4). No component is allowed to hold state in memory only. Crash-restart must resume cleanly.
2. **Every engine emits structured logs and metrics** (§3). "It works" without observability is "it appears to work."
3. **Every behavioral claim has a test** (§11). Unit, integration, and end-to-end tiers — with explicit acceptance criteria from the architecture document.

---

## 1. Environment setup

### 1.1 conda env `axioma` — dependency baseline

The env exists but lacks several v1.0 dependencies. Activate and install:

```bash
conda activate axioma

# Core scientific (already in v0.2)
pip install numpy>=1.26 scipy>=1.11

# GPU compute (H100 = CUDA 12.x; torch 2.4+ supports it)
pip install --index-url https://download.pytorch.org/whl/cu124 torch>=2.4

# Async runtime + WS + HTTP
pip install fastapi>=0.110 uvicorn[standard]>=0.27 websockets>=12.0 \
            httpx>=0.27 aiosqlite>=0.20 aiofiles>=23.2

# Serialization, validation, config
pip install pydantic>=2.6 msgspec>=0.18 tomli>=2.0 PyYAML>=6.0

# Persistence
pip install sqlalchemy[asyncio]>=2.0

# Observability
pip install structlog>=24.1 prometheus-client>=0.20 rich>=13.7

# Testing
pip install pytest>=8.0 pytest-asyncio>=0.23 pytest-cov>=5.0 \
            pytest-benchmark>=4.0 hypothesis>=6.100

# Dev tooling
pip install ruff>=0.4 mypy>=1.10 ipython
```

Pin the resulting versions into `requirements.txt` and commit.

### 1.2 GPU verification (one-time, before Phase A)

The H100 has 80 GB and is idle in the current state. v1.0's substrate fits easily in CPU; the GPU pays off in the **θ pipeline's permutation null** (already GPU-capable in v0.2 via `organ/theta/permutation.py`) and the **raw MI engine** (new in v1.0, GPU-friendly batched MI). Verify:

```bash
conda run -n axioma python -c "
import torch
assert torch.cuda.is_available(), 'no CUDA'
assert torch.cuda.get_device_name(0).startswith('NVIDIA H100')
x = torch.randn(1000, 1000, device='cuda')
y = x @ x.T
torch.cuda.synchronize()
print('cuda OK:', torch.cuda.get_device_name(0), 'mem:', torch.cuda.mem_get_info())
"
```

Record the output in `docs/env_verification.md`. If CUDA fails, fix before Phase A — the v1.0 measurement layer depends on GPU permutation nulls for keeping θ_short at 10 Hz cadence.

### 1.3 Repository structure (target)

```
axioma/
├── axioma/                           # new top-level package (replaces organ/ for v1.0)
│   ├── __init__.py
│   ├── __main__.py                    # `python -m axioma` entry
│   ├── config/
│   │   ├── __init__.py
│   │   ├── defaults.py                # v1.0 defaults (N_iter, ρ_E, V_E, α_M, …)
│   │   ├── schema.py                  # pydantic Config models
│   │   └── loader.py                  # YAML/TOML/env layer
│   ├── schemas/                       # typed state contracts
│   │   ├── organ_state.py             # AnimaState, EidolonState, … (v1.0 widened)
│   │   ├── internal_state.py          # InternalState (substrate-private)
│   │   ├── external_state.py          # ExternalState (boundary-exposed)
│   │   └── events.py                  # RecoveryEvent, PerturbationEvent, MetaCognition, …
│   ├── substrate/
│   │   ├── __init__.py
│   │   ├── base.py                    # Organ ABC
│   │   ├── drive.py                   # SharedLatentDrive (iterative inner loop)
│   │   ├── anima.py                   # 5 organs, v1.0 specs (EIDOLON ρ=0.92 V_E=1.3, MNEME α_M=1.4)
│   │   ├── eidolon.py
│   │   ├── mneme.py
│   │   ├── nous.py
│   │   ├── pneuma.py                  # PEER, no integrate() method
│   │   ├── plasticity.py              # per-organ p_i, (mean_drift, var_ratio) summary
│   │   ├── recovery.py                # recovery_protocol + recovery_history + RecoveryLearner
│   │   └── coherence_budget.py        # PNEUMA.coherence_budget computation
│   ├── compose/
│   │   ├── __init__.py
│   │   ├── function.py                # ComposeFunction (typed I/O)
│   │   ├── boundary.py                # InternalState → ExternalState mapping
│   │   ├── cadence.py                 # adaptive cadence (5/30/60)
│   │   ├── probe.py                   # 100-beat self-test, recovery-aware (F4/E4)
│   │   └── flow_quality.py            # FlowQuality(effortlessness, absorption, time_distortion)
│   ├── measurement/
│   │   ├── __init__.py
│   │   ├── ring_buffer.py             # carried over from v0.2 (extend for multi-window)
│   │   ├── theta_engine.py            # θ_short + θ_long (multi-window)
│   │   ├── raw_mi_engine.py           # NEW: per-organ pairwise MI on 5/20-beat windows (F1/D1)
│   │   ├── delta_phi_engine.py        # S1/S2/S3 + perturbation-relative recording
│   │   ├── cascade_delay_engine.py    # uses raw MI, 5-beat peak detect
│   │   ├── plasticity_tracker.py      # adaptation_delta
│   │   ├── aos_g_engine.py            # AOS-G + psi engine
│   │   ├── fragmentation_monitor.py   # 4-stage detector, emits recovery_request
│   │   ├── meta_cognition_loop.py     # 1000-beat trajectory, observer_only default
│   │   └── perturbation_scheduler.py  # internal cadence + admin endpoint hook + log
│   ├── interface/
│   │   ├── __init__.py
│   │   ├── ws_server.py               # WebSocket :8820, Speaker handshake
│   │   ├── ws_handlers.py             # subscriber multiplexing, rate config
│   │   ├── http_api.py                # FastAPI :8821
│   │   ├── registry_client.py         # register + heartbeat (incl. psi, throttle_state)
│   │   └── speaker.py                 # Speaker enum (AXIOMA, AGENT added)
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── coherence_scheduler.py     # throttle classes + throttle_effectiveness
│   ├── persistence/
│   │   ├── __init__.py
│   │   ├── db.py                      # SQLAlchemy async session factory
│   │   ├── models.py                  # ORM models (RecoveryHistoryRow, OrganLatentSnapshot, …)
│   │   ├── jsonl_writer.py            # rolling JSONL for ExternalState
│   │   ├── snapshot.py                # atomic snapshot writer/loader (every component)
│   │   └── migrations/                # SQLite schema migrations
│   ├── runtime/
│   │   ├── __init__.py
│   │   ├── heartbeat.py               # 10 Hz async loop; orchestrates substrate + measurement + compose
│   │   ├── lifecycle.py               # startup/shutdown sequences
│   │   ├── faults.py                  # fault tolerance per §9.3 of ARCH v1.0
│   │   └── app.py                     # asyncio task graph; one `AxiomaApp` per process
│   ├── observability/
│   │   ├── __init__.py
│   │   ├── logging.py                 # structlog config
│   │   ├── metrics.py                 # prometheus_client registry + helpers
│   │   └── tracing.py                 # span context for per-beat / per-engine timing
│   └── util/
│       ├── __init__.py
│       ├── gpu.py                     # device-selection + tensor helpers
│       └── timing.py                  # ring-buffer beat timing
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── benchmarks/
├── scripts/
│   ├── phase_a_pretrain.py            # F4 synthetic recovery pre-training
│   ├── phase_a_zone_calibration.py    # F6 multi-session subjective validation
│   ├── phase_e_threshold_validation.py # F9 fragmentation threshold tuning
│   ├── phase_f_meta_calibration.py    # F8 confidence vs accuracy
│   └── run_local.py                   # local dev launcher
├── configs/
│   ├── default.yaml                   # all v1.0 defaults
│   ├── local.yaml                     # localhost-only overrides
│   └── phase_e.yaml                   # Phase E (test_mode, synthetic pre-train)
├── docs/
│   ├── env_verification.md
│   ├── runbooks/                      # operator runbooks
│   └── api/                           # generated FastAPI OpenAPI docs
├── data/                              # research artifacts (carry over)
├── design/                            # ARCH_DESIGN_v0.3..v1.0, reviews, this plan
├── organ/                             # v0.2 codebase (kept for reference; not modified)
├── pyproject.toml                     # ruff, mypy, pytest config
├── requirements.txt
└── README.md
```

**Why a parallel `axioma/` package, not in-place migration of `organ/`?**

- v0.2's `organ/` is the experimental codebase the research summary was generated from. Touching it risks invalidating reference results.
- v0.2 PNEUMA has `integrate()` (v1.0 forbids this). Refactoring in place would break v0.2 tests mid-port.
- `organ/` stays as the reproducibility anchor; `axioma/` is the v1.0 build. Common code (theta pipeline, ring buffer) is **vendored** into `axioma/measurement/` with attribution comments, not imported across packages.

---

## 2. What's already built (v0.2) vs what's new (v1.0)

A faithful inventory so we don't re-implement what exists:

| Component | v0.2 status | v1.0 action |
|---|---|---|
| 5 organs (Anima, Eidolon, Mneme, Nous, Pneuma) | ✅ exists (`organ/substrate/`) | **Refactor**: PNEUMA loses `integrate()`; EIDOLON gets ρ=0.92, V_E=1.3; MNEME gets α_M=1.4; latent dims widened (8/12/12/10/12); non-saturating renderers |
| Heartbeat 10 Hz async loop | ✅ exists (`organ/substrate/heartbeat.py`) | **Refactor**: add iterative inner loop (N_iter=3); split compose hook for adaptive cadence; thread fragmentation/recovery hooks |
| Coupled latent dynamics | ✅ exists (`organ/substrate/dynamics.py`) | **Replace** with `SharedLatentDrive` (iterative `g_k`); keep noise generator |
| Perturbation kinds | ✅ exists (`organ/substrate/perturbation.py`) | **Reuse**; wrap in `PerturbationScheduler` with internal cadence + admin endpoint |
| θ pipeline (Gaussian copula MI, RINT fallback, permutation null) | ✅ exists (`organ/theta/`) | **Vendor + extend**: split into θ_short / θ_long engines; reuse GPU pairwise MI and permutation_null_gpu |
| AOS-G analyzer | ✅ exists (`organ/theta/aos_g.py`) | **Extend** into AOS-G+psi engine; add recovery-state-aware variance targets |
| Measurement ring buffer | ✅ exists (`organ/measurement/ring_buffer.py`) | **Reuse**; extend for multi-window query |
| JSONL writer | ✅ exists (`organ/measurement/jsonl_writer.py`) | **Reuse**; widen schema for ExternalState |
| SQLite writer | ✅ exists (`organ/measurement/sqlite_writer.py`) | **Replace** with async SQLAlchemy models |
| Compose function | ❌ stub only (PNEUMA.push_compose) | **Build** typed boundary; adaptive cadence; probe |
| InternalState / ExternalState types | ❌ does not exist | **Build** as separate dataclasses (msgspec for speed) |
| Plasticity layer | ❌ does not exist | **Build** per-organ buffer + summary function |
| ΔΦ engine (S1/S2/S3) | ❌ does not exist | **Build** with perturbation-relative recording |
| cascade_delay engine | ❌ does not exist | **Build** using raw MI (5-beat peak detect) |
| Raw per-organ MI engine | ❌ does not exist | **Build** (5/20-beat sliding windows, GPU-batched) |
| Fragmentation monitor | ❌ does not exist | **Build** 4-stage detector + recovery_request emitter |
| Recovery protocol | ❌ does not exist | **Build** substrate-owned accept/reject + actions |
| Recovery history + learner | ❌ does not exist | **Build** SQLite-backed history + hill-climb + safe fallback |
| psi engine | ❌ does not exist | **Build** with continuous structural_health, recovery-aware gap_variance, compose probe |
| Coherence budget / scheduler | ❌ does not exist | **Build** (computation + throttle classes + effectiveness metric) |
| Meta-cognitive loop | ❌ does not exist | **Build** read-only, observer_only default, suggestion channel |
| WebSocket server | ❌ does not exist | **Build** with Speaker handshake + per-subscriber rate config |
| HTTP API | ❌ does not exist | **Build** FastAPI control plane |
| Registry client | ❌ does not exist | **Build** with cache + retry |
| Persistence (per-component snapshot) | ⚠ partial | **Build** uniform `Stateful` protocol; everyone implements it |
| Logging / metrics | ⚠ basic prints | **Build** structlog + prometheus |
| Fault tolerance | ❌ does not exist | **Build** per §9.3 of ARCH v1.0 |

---

## 3. Logging & monitoring — the cross-cutting concern

Build the observability rails **before** the substrate work, because everything else hangs off them. Two surfaces, single source of truth.

### 3.1 Structured logging (`axioma/observability/logging.py`)

```python
import structlog
import logging

def configure_logging(level: str = "INFO", json: bool = True) -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]
    if json:
        shared.append(structlog.processors.JSONRenderer())
    else:
        shared.append(structlog.dev.ConsoleRenderer(colors=True))
    structlog.configure(
        processors=shared,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
    )
```

Every module gets `log = structlog.get_logger(__name__)` at top. **Every log line carries `beat_no`** via `structlog.contextvars` — bound once per beat in `heartbeat.tick_async()` so any nested code's logs are beat-correlated.

**Required structured fields per subsystem:**

| Subsystem | Required context keys |
|---|---|
| Substrate (organ.update) | `organ`, `beat_no`, `k_iter` (inner-loop index) |
| Compose | `beat_no`, `cadence` ("baseline"/"perturbation"/"recovery"), `aos_g_gap`, `psi` |
| Measurement engines | `engine`, `beat_no`, `window_size`, `result_key`, `result_value` |
| Recovery | `event_id`, `stage`, `decision`, `request_source` |
| Recovery learner | `event_id`, `stage`, `current_params`, `candidate_params`, `score_delta` |
| Meta-cog | `beat_no`, `overall_assessment`, `confidence`, `observer_mode` |
| WS / HTTP | `connection_id`, `speaker`, `channel`, `subscriber_min_interval_ms` |
| Registry | `registry_url`, `attempt`, `next_retry_in_s` |
| Faults | `subsystem`, `fault_kind`, `recovery_action` |

**Log levels are policy, not vibes:**

- `DEBUG` — per-beat traces (off by default; flip via config for diagnosis)
- `INFO` — lifecycle, recovery decisions, learner adoption, meta-cog emissions
- `WARN` — fault recovery, divergence escalation (F5), throttle effectiveness fail
- `ERROR` — unhandled engine exception, persistence write failure
- `CRITICAL` — substrate divergence past 50-beat clip, repeated WS bind failure exhausted

### 3.2 Prometheus metrics (`axioma/observability/metrics.py`)

```python
from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry

REGISTRY = CollectorRegistry()

# Per-beat timing
BEAT_DURATION_S = Histogram("axioma_beat_duration_seconds",
    "Wall-clock time per heartbeat tick",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5],
    registry=REGISTRY)
ENGINE_DURATION_S = Histogram("axioma_engine_duration_seconds",
    "Per-engine compute time",
    ["engine"],
    buckets=[0.0001, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
    registry=REGISTRY)

# State gauges
THETA_SHORT = Gauge("axioma_theta_short", "θ over 30-beat window", registry=REGISTRY)
THETA_LONG = Gauge("axioma_theta_long", "θ over 500-beat window", registry=REGISTRY)
AOS_G_GAP = Gauge("axioma_aos_g_gap", "Compose AOS-G gap", registry=REGISTRY)
PSI = Gauge("axioma_psi", "Boundary integrity field", registry=REGISTRY)
COHERENCE_BUDGET = Gauge("axioma_coherence_budget", "PNEUMA coherence budget", registry=REGISTRY)
FRAGMENTATION_STAGE = Gauge("axioma_fragmentation_stage",
    "Current fragmentation stage (0-4)", registry=REGISTRY)
RECOVERY_ACTIVE = Gauge("axioma_recovery_active",
    "1 if in active recovery, else 0", registry=REGISTRY)

# Counters
PERTURBATIONS_TOTAL = Counter("axioma_perturbations_total",
    "Perturbations injected", ["source", "kind"], registry=REGISTRY)
RECOVERIES_TOTAL = Counter("axioma_recoveries_total",
    "Recovery events", ["stage", "decision"], registry=REGISTRY)
SUGGESTION_DECISIONS = Counter("axioma_meta_suggestions_total",
    "Meta-cog suggestions handled", ["decision"], registry=REGISTRY)
DIVERGENCE_WARNINGS = Counter("axioma_divergence_warnings_total",
    "F5 divergence warnings emitted", registry=REGISTRY)

# Persistence
PERSISTENCE_WRITES = Counter("axioma_persistence_writes_total",
    "Snapshot/JSONL writes", ["target"], registry=REGISTRY)
PERSISTENCE_WRITE_LATENCY = Histogram("axioma_persistence_write_seconds",
    "Persistence write latency", ["target"], registry=REGISTRY)
```

Exposed at `:8821/metrics`. Operators scrape via Prometheus; dashboards in `docs/grafana/`.

### 3.3 Per-engine timing contract

Every measurement engine wraps its compute in a context manager:

```python
from contextlib import contextmanager
from .metrics import ENGINE_DURATION_S

@contextmanager
def measure_engine(name: str):
    with ENGINE_DURATION_S.labels(engine=name).time():
        yield
```

Required for: `theta_short`, `theta_long`, `raw_mi`, `delta_phi`, `cascade_delay`, `plasticity`, `aos_g`, `fragmentation`, `meta_cognition`. Phase E uses these histograms to validate the cadence budget (substrate tick + all High-priority engines < 100 ms = 10 Hz).

---

## 4. Persistence — the second cross-cutting concern

**Architectural commitment:** every stateful component implements a `Stateful` protocol. No state lives in memory only. Crash-restart resumes from the most recent snapshot.

### 4.1 The `Stateful` protocol (`axioma/persistence/snapshot.py`)

```python
from typing import Protocol, Any
import msgspec

class Stateful(Protocol):
    name: str
    schema_version: int

    def save_state(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of all in-memory state."""

    def load_state(self, snapshot: dict[str, Any]) -> None:
        """Restore state from a snapshot. MUST be idempotent (load twice = load once)."""
```

`SnapshotManager` collects `Stateful` instances at startup, calls `save_state` on every registered component at shutdown (and periodically while running — default every 600 beats = 1 min), serializes with `msgspec.json` to an **atomic** write (write to temp + fsync + rename), and loads on startup.

Snapshot directory layout:

```
data/state/
├── current/                       # symlink to the latest snapshot dir
├── 20260524_154300_beat_3600/     # one dir per snapshot
│   ├── manifest.json              # {schema_version, beat_no, timestamp, components: [...]}
│   ├── substrate.json
│   ├── plasticity.json
│   ├── recovery_protocol.json
│   ├── recovery_learner.json
│   ├── recovery_history.sqlite    # large blobs go in SQLite, not JSON
│   ├── psi_engine.json
│   ├── coherence_scheduler.json
│   ├── meta_cognition.json
│   ├── perturbation_scheduler.json
│   ├── fragmentation_monitor.json
│   ├── theta_engine_short.json
│   ├── theta_engine_long.json
│   ├── compose_function.json
│   └── suggestion_tracker.json
└── 20260524_154800_beat_6600/     # next snapshot
```

Old snapshots are pruned: keep the last 24 (24 minutes of history at 60s cadence) plus one daily snapshot for 30 days.

### 4.2 What every component must persist (exhaustive)

| Component | State | Format | Justification |
|---|---|---|---|
| `SharedLatentDrive` | `g`, `rho_g`, RNG state | JSON | Drive continuity across restart |
| `Organ` (each of 5) | latent `z_i`, RNG state, plasticity buffer ref | JSON | Substrate continuity |
| `PlasticityBuffer` (per organ) | `p_i`, `rolling_mean_i`, `rolling_var_i`, last update beat | JSON | Plasticity carries history; loss = adaptation_delta resets to 0 |
| `ThetaEngine` (short / long) | last computed θ, rolling-window head, recent permutation seed | JSON | Continuity of reported θ across restart |
| `RawMIEngine` | 5-beat and 20-beat sliding buffers (per-organ-pair) | JSON | cascade_delay needs warm buffers to report; cold-start gives spurious values |
| `DeltaPhiEngine` | rolling baseline (S1/S2/S3), perturbation event window buffer | JSON | Baseline drifts; restart-as-baseline-reset would lose the ΔΦ characterization |
| `CascadeDelayEngine` | 5-beat / 20-beat MI buffers + recent peak history | JSON | Same as raw_mi |
| `PlasticityTracker` | adaptation_delta history per organ | JSON | Trend continuity |
| `AOSGEngine` (+psi) | gap history, target_var_baseline, target_var_recovery, structural_health check_history, compose_probe_health, blend_factor | JSON | psi semantics depend on history |
| `FragmentationMonitor` | per-stage signal history, current stage, beats-in-stage | JSON | Stage transitions are state |
| `RecoveryProtocol` | recovery_active, current_stage, recovery_start_beat, expected_end_beat, parameter snapshot | JSON | A restart mid-recovery must resume the recovery, not silently exit |
| `RecoveryHistory` | last 100 events, full payload | SQLite | Learner reads history; loss = learner cold-start |
| `RecoveryLearner` | `current_params` per stage, `baseline_score`, exploration counter, `LearnerEfficacy` state | JSON | Learned tuning |
| `PerturbationScheduler` | next scheduled beat, battery round-robin index, recent perturbation log | JSON | Determinism across restart |
| `CoherenceScheduler` | throttle history, effectiveness window state | JSON | Effectiveness escalation depends on the 50-beat windows |
| `MetaCognitionLoop` | recent emission history (last 5 for confidence), suggestion history | JSON | Confidence calc, F5 escalation |
| `SuggestionTracker` | recent_decisions deque (last 10) | JSON | F5 escalation persistence (per §9.2) |
| `ComposeFunction` | rolling means/stds per organ, weights | JSON | Compose continuity |
| `ComposeProbe` | expected_baseline, expected_recovery, last health value | JSON | Probe semantics |
| `WSServer` | connected subscribers + their channel filters + min_interval_ms | JSON (best effort) | Reconnection on restart is via registry rediscovery — subscribers don't need to be persisted; but logging current subscriber set helps post-mortem |
| `RegistryClient` | cached peer list, last successful registration, agent_id | JSON | Registry-unreachable resilience (§9.3.4) |
| `Heartbeat` | `beat_no`, `cadence_state` (baseline / perturbation_window / recovery), `recovery_window_end_beat` | JSON | Cadence + beat counter continuity |

### 4.3 SQLite models (`axioma/persistence/models.py`)

```python
from sqlalchemy import Integer, String, Float, JSON, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase): ...

class RecoveryHistoryRow(Base):
    __tablename__ = "recovery_history"
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    started_at_beat: Mapped[int] = mapped_column(Integer, index=True)
    ended_at_beat: Mapped[int] = mapped_column(Integer)
    stage: Mapped[int] = mapped_column(Integer, index=True)
    is_synthetic: Mapped[bool] = mapped_column(Integer)  # F4: tagged pre-training events
    actions_used: Mapped[dict] = mapped_column(JSON)
    quality: Mapped[dict] = mapped_column(JSON)       # smoothness, completeness, durability, composite
    quality_finalized: Mapped[bool] = mapped_column(Integer, default=False)
    durability_observed_at_beat: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_fragmentation_beat: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smoothness_window_beats: Mapped[int] = mapped_column(Integer)  # F1: transparency
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

class PerturbationEventRow(Base):
    __tablename__ = "perturbation_events"
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    beat_no: Mapped[int] = mapped_column(Integer, index=True)
    source: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    target: Mapped[str | None] = mapped_column(String, nullable=True)
    magnitude: Mapped[float] = mapped_column(Float)
    duration_beats: Mapped[int] = mapped_column(Integer)
    tag: Mapped[str | None] = mapped_column(String, nullable=True)

class MetaCognitionEmissionRow(Base):
    __tablename__ = "meta_cognition_emissions"
    beat_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    overall_assessment: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    observer_mode: Mapped[str] = mapped_column(String)
    integration_trend: Mapped[str] = mapped_column(String)
    boundary_health_trend: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)

# Similar tables for: external_state samples (downsampled), recovery_events,
# divergence_warnings, fragmentation_events, learner_decisions
```

### 4.4 JSONL writers — for high-rate, append-only data

Per-beat ExternalState snapshots (one per compose event, ~0.33–2 Hz) go to JSONL, not SQLite — SQLite inserts at 10 Hz are an anti-pattern. JSONL file per hour, gzipped on rotate.

```
data/jsonl/
├── external_state/
│   └── 20260524_15.jsonl.gz
├── theta/
│   └── 20260524_15.jsonl.gz
└── raw_mi/
    └── 20260524_15.jsonl.gz
```

Background task rotates files at the hour boundary; consumer scripts (research analysis) read multiple files in order.

### 4.5 Atomic snapshot procedure

```python
async def take_snapshot(beat_no: int, components: list[Stateful]) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    target = SNAPSHOT_ROOT / f"{ts}_beat_{beat_no}"
    tmp = target.with_suffix(".tmp")
    tmp.mkdir(parents=True)
    manifest = {"schema_version": 1, "beat_no": beat_no, "timestamp": ts, "components": []}
    for c in components:
        try:
            data = c.save_state()
            payload = msgspec.json.encode(data)
            (tmp / f"{c.name}.json").write_bytes(payload)
            manifest["components"].append({"name": c.name, "schema_version": c.schema_version, "bytes": len(payload)})
        except Exception:
            log.exception("snapshot_failed", component=c.name)
            shutil.rmtree(tmp)
            raise
    (tmp / "manifest.json").write_bytes(msgspec.json.encode(manifest))
    os.replace(tmp, target)
    # atomic symlink swap
    current = SNAPSHOT_ROOT / "current"
    current_tmp = SNAPSHOT_ROOT / "current.tmp"
    if current_tmp.exists(): current_tmp.unlink()
    current_tmp.symlink_to(target)
    os.replace(current_tmp, current)
    return target
```

Failures don't corrupt — temp dir is wiped, current symlink unchanged.

### 4.6 Load contract on startup

```python
async def load_latest_snapshot(components: list[Stateful]) -> int | None:
    current = SNAPSHOT_ROOT / "current"
    if not current.exists():
        return None  # cold start
    manifest = msgspec.json.decode((current / "manifest.json").read_bytes())
    by_name = {c.name: c for c in components}
    for entry in manifest["components"]:
        c = by_name.get(entry["name"])
        if c is None:
            log.warning("snapshot_component_orphan", name=entry["name"])
            continue
        if c.schema_version != entry["schema_version"]:
            log.warning("snapshot_schema_mismatch",
                        name=entry["name"], expected=c.schema_version, found=entry["schema_version"])
            # try migration; if not possible, skip and component cold-starts
            continue
        data = msgspec.json.decode((current / f"{entry['name']}.json").read_bytes())
        c.load_state(data)
    return manifest["beat_no"]
```

Schema mismatches are logged but **not fatal** — a single component cold-starting is preferable to refusing to boot. Operator sees the warning and decides whether to migrate or accept the loss.

---

## 5. Phase A — Substrate rework (~3.5 days)

**Goal:** ship the v1.0 substrate with iterative drive, EIDOLON tuning, MNEME compensation, plasticity, recovery protocol scaffold, and persistence — verified against pre-architecture experiments.

### 5.1 Order of work (4 sub-phases)

**A.1 — Scaffold (4 hours)**
- `axioma/` package skeleton per §1.3
- Logging + metrics infra per §3
- Persistence protocol per §4
- Config loader (YAML defaults, env overrides)
- pytest, ruff, mypy, pre-commit
- CI: `pytest tests/unit` runs on every push

**A.2 — Drive + organs + plasticity (1.5 days)**
- `SharedLatentDrive.step(N_iter)` — iterative Euler inner loop
- 5 organs as peers; non-saturating renderers (OU latent + linear rescale)
- EIDOLON: ρ=0.92, V_E=1.3
- MNEME: stage-1 compensation (α_M=1.4); stages #2/#3 behind feature flags
- PNEUMA: peer interface, no `integrate()`; `coherence_budget` field
- Per-organ `PlasticityBuffer` with `(mean_drift, var_ratio)` summary
- Render-modulation pathway ON; coupling-weight adaptation OFF (auto-gated in Phase B)
- All components implement `Stateful`

**A.3 — Recovery protocol scaffold (0.5 day)**
- `RecoveryProtocol` accept/reject decision logic
- `recovery_protocol(stage)` action sequence per §4.9
- `RecoveryHistory` (SQLite-backed)
- `RecoveryLearner` skeleton (defaults only; learning starts in Phase B's measurement integration)
- `RecoveryQuality` with **last-50-beat smoothness windowing (F1)** — verified against synthetic dummy θ traces

**A.4 — Phase A validation (1.5 days)**

| Test | Acceptance |
|---|---|
| Drive symmetry: rotating organs doesn't change θ | θ change < 1% under any permutation |
| Range invariance: organ states stay in design ranges across 10 min run | `validate_ranges()` passes on every beat |
| MNEME stage-1 compensation: pairwise MI for MNEME pairs ≥ 0.8× ANIMA pairs | Phase A measurement; if fails, enable stage #2 |
| **C11** Perturbation response: impulse on EIDOLON, all others respond within 2 beats | All 4 non-EIDOLON organs' state delta > 0.01 within 2 beats |
| **N_iter sweep (D11/F14)**: mc_corr > 0.8 + variance invariance ±10% | Picks N_iter default and saves `n_iter_sweep_results.md` |
| **Coupling validation (D8/E15)**: actual MI matrix vs targets; if > 30% off, revise targets | Outputs revised `coupling_targets.json` |
| **Zone re-calibration (D9)**: θ histogram from 1-hr idle run | Outputs `zone_thresholds.json` (initial) |
| **F6 — Multi-session subjective validation**: 3 sessions × 3 task types | mean(κ) and per-task κ; if min(κ) < 0.3, task-typed thresholds flagged for v1.1 |
| Persistence round-trip: snapshot at beat 1000, restart, verify state at beat 1001 matches | Bit-equal for deterministic seeds |

The F6 step is the long pole — needs Theoria's time. Schedule before A.4 starts. Other A.4 work can run while waiting.

### 5.2 GPU strategy for Phase A

The substrate itself is CPU-bound (low dimensionality; iterative loop is tiny matmuls). **Do not move organ updates to GPU** — kernel launch overhead at 10 Hz × 5 organs × N_iter iterations dominates.

The H100 pays off in:
- Drive's `Σ_i V_i z_i` if dimensions grow > 64 — currently L ≤ 32, stays CPU
- Phase A's coupling-matrix validation experiment runs the substrate for 1 hour × 36000 beats; θ pipeline on every snapshot uses GPU (already wired in v0.2)

`axioma/util/gpu.py` provides:

```python
import torch

def select_device(prefer: str = "cuda") -> torch.device:
    if prefer == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")

def to_device(arr, dev): ...

@contextmanager
def gpu_sync():
    """Synchronize and yield; use around timed GPU sections."""
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    yield
    if torch.cuda.is_available():
        torch.cuda.synchronize()
```

Substrate uses NumPy; measurement engines use Torch with explicit `select_device()`. Tests run with `prefer="cpu"` so CI doesn't need GPU.

---

## 6. Phase B — Measurement layer (~3 days)

**Goal:** ship θ_short / θ_long / raw MI / ΔΦ / cascade_delay / plasticity tracker / AOS-G + psi / fragmentation monitor / meta-cognitive loop / coherence scheduler / perturbation scheduler — all read-only on substrate, all persisted, all instrumented.

### 6.1 Engine implementation order

1. **`theta_engine.py`** — vendor v0.2's pipeline; instantiate twice (short 30-beat, long 500-beat). Each engine holds a rolling buffer of `InternalState` (down-projected to the 19 summary dims). Compute on schedule (short = every beat; long = every 10 beats).
2. **`raw_mi_engine.py`** — NEW. Per-organ-pair MI on 5-beat and 20-beat sliding windows. **GPU-batched**: compute all 10 pairs in one batched MI call. Reuses Gaussian copula MI from v0.2.
3. **`cascade_delay_engine.py`** — consumes RawMIEngine output. Peak detection on 5-beat MI traces for EIDOLON_* and ANIMA_* pairs (within 20-beat lookback). Reports `t(ANIMA_peak) - t(EIDOLON_peak)`.
4. **`plasticity_tracker.py`** — observes plasticity buffers; emits `adaptation_delta`.
5. **`delta_phi_engine.py`** — subscribes to `PerturbationScheduler` events; maintains `perturbation_relative_buffer`. Computes S1 (peak θ_short post-event), S2 (recovery time), S3 (response variance across recent events of same kind). 50-beat window. Reports `{baseline, perturbation_relative}` pairs.
6. **`aos_g_engine.py`** (+ psi) — runs on every compose event. Computes `aos_g_gap` (Euclidean). Maintains:
   - `gap_variance_health` with **dual targets** (baseline / recovery) and **recovery-aware blend** (E3)
   - `structural_health` with **5-check sliding window + 2-failure debounce** (E1)
   - `compose_probe_health` from periodic probe (E4: recovery-aware expected outputs; Stage 4 skip)
   - `psi = min(gv, sh, cp)`
   - `aos_g_alert = psi < 0.3 OR gap < threshold`
7. **`fragmentation_monitor.py`** — 4-stage detector. Emits `RecoveryRequest` to substrate when Stage ≥ 2. Subscribes to substrate `recovery_state_change` to compute `RecoveryQuality` on exit.
8. **`perturbation_scheduler.py`** — internal cadence (every 600 beats default), round-robin battery, admin endpoint hook, logging every event with `event_id` to SQLite + JSONL.
9. **`coherence_scheduler.py`** — throttle classes, priority table (meta-cog at High per E2), `ThrottleEffectiveness` (E13) with 3-window escalation to fragmentation monitor.
10. **`meta_cognition_loop.py`** — every 100 beats, read 1000-beat trajectories (E5), compute assessment, emit on `meta_cognition` channel with `confidence_caveat` (E8) and `observer_mode` (F7). Emit suggestions when threshold conditions met. `SuggestionTracker` with **F5 escalation** (5 ignored → presence channel warning).
11. **`RecoveryLearner` integration** — hill-climb activates here; reads `recovery_history` from SQLite; **F2 LearnerEfficacy state machine** (WARMING_UP / MONITORING / EFFECTIVE / INEFFECTIVE).

### 6.2 GPU strategy for measurement

| Engine | Where it runs | Why |
|---|---|---|
| θ_short (30 beats, every beat) | **CPU** | Small matrix; kernel launch overhead dominates |
| θ_long (500 beats, every 10 beats) | **GPU** | Permutation null with 100 shuffles dwarfs the launch cost |
| Raw MI (5-beat, every beat × 10 pairs) | **GPU batched** | 10 simultaneous MIs in one kernel; CPU would serialize |
| Raw MI (20-beat, every 5 beats × 10 pairs) | **GPU batched** | Same |
| Cascade_delay (per beat, 20-beat lookback) | **CPU** | Pure argmax on small arrays |
| ΔΦ (50-beat, every 5 beats) | **CPU** | Trivial scalar arithmetic |
| Plasticity tracker | **CPU** | Trivial |
| AOS-G | **CPU** | Trivial |
| Fragmentation monitor | **CPU** | Threshold checks |
| Meta-cog | **CPU** | Aggregations over recent windows |

**Total GPU pressure:** θ_long every 10 beats (≈ 50 ms each on H100) + raw MI every beat (≈ 2-5 ms per batched call) → well under 100 ms/beat budget. Bench in Phase E.

### 6.3 Phase B validation

| Test | Acceptance |
|---|---|
| Read-only contract: instrument check that no engine mutates substrate | Static check (Python attribute introspection) + runtime tripwire |
| All engines produce values on a 5-min run | No exceptions; all metrics gauge values non-NaN |
| Raw MI vs hand-checked: known synthetic perturbation trace | cascade_delay agrees within ±1 beat |
| `psi` regression on Control 4: replace compose with identity, psi should drop and aos_g_alert fire | Within 200 beats |
| `psi` recovery-awareness (E3): simulated recovery does NOT drop psi | psi stays > 0.5 throughout recovery |
| `psi` debounce (E1): single transient ImportError doesn't drop psi | psi ≥ 0.6 after one failure |
| ΔΦ perturbation-relative: inject contradiction at beat 200, S1 records the response at t ∈ [200, 250] | Non-zero S1 in window |
| Fragmentation monitor fires recovery_request when Stage ≥ 2 conditions met (synthetic) | Single request emitted |
| Plasticity Pathway #2 auto-gate (D5): |Δ| < 0.1 with #1 alone → #2 enabled, |Δ| measured again | Documented gate decision |
| `LearnerEfficacy` state transitions: synthetic regime that produces no improvement | WARMING_UP → MONITORING → INEFFECTIVE after 60 events |
| Throttle effectiveness escalation (E13): synthetic load with ineffective throttles | Escalation signal fires after 3 windows (150 beats) |
| Meta-cog 1000-beat window (E5) detects subtle trend invisible at 600-beat window | Trend label matches synthetic ground truth |
| Suggestion tracker F5 escalation: 5 ignored suggestions → divergence warning on presence channel | Single warning emitted; tracker resets |
| All engines persist + reload: snapshot mid-engine, restart, verify continuity | Equivalent next-beat output |

---

## 7. Phase C — Compose / send boundary (~1.5 days)

**Goal:** ship typed `InternalState` / `ExternalState`, `ComposeFunction` with adaptive cadence, compose probe (recovery-aware, Stage 4 skip), `aos_g_alert`, `zone`, `flow_quality`, **structural ImportError test**.

### 7.1 Typed boundary

`axioma/schemas/internal_state.py` and `external_state.py`. **InternalState is never serialized.** Enforced by:

1. **Lint rule** (`ruff` custom rule or `import-linter` config): `axioma.interface.*` may not import `axioma.schemas.internal_state`.
2. **Runtime ImportError test** (`tests/integration/test_boundary.py`):
   ```python
   def test_internal_state_not_in_ws_handler():
       import importlib
       mod = importlib.import_module("axioma.interface.ws_handlers")
       assert "InternalState" not in mod.__dict__, "InternalState leaked into ws_handlers"
       # Negative: importing should raise
       with pytest.raises(ImportError):
           exec("from axioma.schemas.internal_state import InternalState", mod.__dict__)
   ```
3. **CI gate**: lint failure blocks merge.

### 7.2 ComposeFunction

```python
from msgspec import Struct

class ComposeFunction(Stateful):
    name = "compose_function"
    schema_version = 1

    def __init__(self, cfg: ComposeConfig):
        self.weights = cfg.weights              # dict[organ, float]
        self.rolling = {o: RollingMeanStd() for o in ORGAN_ORDER}
        self.noise_factor = cfg.noise_factor
        self.aos_g_alert_threshold = cfg.aos_g_alert_threshold  # default 0.1

    def compose(self, internal: InternalState, theta_short: float, eidolon_coh: float) -> ExternalState:
        outs = {}
        for organ, state in internal.organs.items():
            f = self._fidelity_factor(organ, theta_short, eidolon_coh)
            rs = self.rolling[organ]
            rs.update(state.to_array())
            mean = rs.mean()
            noise = np.random.normal(0, self.noise_factor, size=state.dim)
            outs[organ] = f * state.to_array() + (1 - f) * (mean + noise)
        # ... build ExternalState
```

### 7.3 Adaptive cadence (D2)

`axioma/compose/cadence.py`:

```python
class CadenceController(Stateful):
    name = "cadence_controller"
    schema_version = 1

    def should_compose(self, beat_no: int, state: CadenceState) -> bool:
        if state.recovery_active:
            return beat_no % 60 == 0
        if state.perturbation_window_active:  # 50-beat window after any perturbation
            return beat_no % 5 == 0
        return beat_no % 30 == 0
```

State subscribes to `PerturbationScheduler` (sets `perturbation_window_active` for 50 beats after each event) and `RecoveryProtocol` (sets `recovery_active` while running).

### 7.4 Compose probe (E4) + Flow quality (D15/E12)

- Probe runs every 100 beats. **Skipped at Stage 4 emergency** (cached health carries forward).
- During recovery, uses `expected_recovery` reference (precomputed in Phase A baseline + Phase E recovery calibration).
- FlowQuality populated only when zone == FLOW; otherwise None.

### 7.5 Phase C validation

| Test | Acceptance |
|---|---|
| Identity-compose reproduces v0.2 Control 4 (AOS-G = 0) | Gap < 1e-6 |
| Default-compose reproduces v0.2 baseline AOS-G | Gap in [0.3, 0.5] range |
| **ImportError test (C12)**: ws_handlers module cannot import InternalState | Passes |
| Adaptive cadence: compose runs at 5b during perturbation window | Verified via counters |
| Adaptive cadence: compose runs at 60b during recovery | Verified |
| **F1 — smoothness windowed**: inject recovery with intentional early turbulence | `smoothness_window_beats == 50`; smoothness reflects late phase |
| FlowQuality is None outside flow zone | Verified across 1-hr run |
| Zone classifier produces stable zones on synthetic θ/ΔΦ (no thrashing) | < 5 transitions per minute under stationary input |
| Compose probe recovery-state: probe uses expected_recovery during recovery | Verified |
| Compose probe Stage-4 skip: probe NOT updated; cached health carries | Verified |

---

## 8. Phase D — External interface (~1.5 days)

**Goal:** ship WebSocket :8820 with Speaker handshake, HTTP API :8821, registry client with cache+retry, per-subscriber rate config, all new channels and endpoints.

### 8.1 WebSocket server

`axioma/interface/ws_server.py` — `websockets` library + asyncio. Connection lifecycle:

```
client → WS upgrade GET /ws/axioma
       ← 101
client → {type: "handshake", speaker: "skye", auth: {...}}
       ← {type: "welcome", agent_id, theta_long, zone}
       ← {type: "presence", speaker: "axioma", status: "active"}
client → {type: "subscribe", channel: "theta", min_interval_ms: 1000}
       ← {type: "subscription_ack", channel: "theta"}
loop:
       ← {type: "theta_update", ...}  (rate-limited per subscriber)
```

**Per-subscriber coalescing:** each (connection, channel) holds the **most recent** value; a single asyncio task per connection pushes when interval has elapsed. No backlog.

**Channel list (full v1.0):** conversation, theta, delta_phi, per_organ_theta, **per_organ_mi_raw**, aos_g (+psi), presence, state_snapshot, plasticity, fragmentation, perturbations, coherence_budget (+throttle_state, +throttle_effectiveness), **recovery** (with recovery_quality, F1 windowed), **meta_cognition** (+confidence_caveat, +observer_mode), **meta_cognition_suggestion**.

**`presence` channel carries `MetaCognitionDivergenceWarning` (F5).**

### 8.2 HTTP API

`axioma/interface/http_api.py` — FastAPI app. Endpoints per ARCH §8.5 / v1.0 additions:

```
GET  /status
GET  /theta/history?minutes=60&window={short,long}
GET  /delta_phi/history
GET  /raw_mi/history
GET  /organs
GET  /connections
GET  /capabilities
GET  /perturbations
GET  /fragmentation
GET  /recovery/history
GET  /recovery/learner             # current_params, exploration_rate, recent regressions, efficacy
GET  /recovery/pretrain/status     # F4: pre-training snapshot info
GET  /meta_cognition/history
GET  /meta_cognition/suggestions
GET  /meta_cognition/calibration   # F8: confidence vs accuracy summary
GET  /scheduler/effectiveness
GET  /integrity                    # psi + components
GET  /presence/divergence_warnings # F5
GET  /metrics                      # Prometheus exposition
POST /admin/perturb
POST /admin/perturb/schedule
POST /admin/recovery/force
POST /admin/recovery/learner/pretrain   # trigger synthetic pre-training
POST /admin/recovery/learner/reset
POST /admin/meta_cognition/mode          # observer_only | embedded (F7)
POST /admin/heartbeat/pause
POST /admin/shutdown
```

Admin endpoints require a config-flag-controlled API key in `Authorization: Bearer` header. Documented in `docs/api/auth.md`.

### 8.3 Registry client

`axioma/interface/registry_client.py` — implements §9.3.4:

- Cache last-known peer list to disk (`data/state/registry_cache.json`)
- Exponential backoff on registration / heartbeat failures (5s → 5 min, indefinite)
- Heartbeat payload includes `psi`, `throttle_state`, `frag_stage`, `coherence_budget`
- Emits `registry_unreachable` event on presence channel every 60s while disconnected
- Capabilities advertised: `["consciousness", "theta_stream", "delta_phi", "compose_boundary", "fragmentation_monitor", "perturbation_admin", "coherence_budget", "psi_integrity", "meta_cognition", "recovery_learning"]`

### 8.4 Phase D validation

| Test | Acceptance |
|---|---|
| Speaker handshake | Valid speaker → welcome; invalid → close 4001 |
| Channel subscription | Subscriber gets only subscribed channels |
| Per-subscriber rate: 1 Hz on a 10 Hz channel → ~1 msg/sec | Within ±10% |
| Coalescing: backlog never delivered; only most-recent value | Counter `dropped_coalesced_total` increments |
| Registry round-trip (mock registry) | register → heartbeat → unregister all succeed |
| Registry unreachable: AXIOMA continues operating | Substrate ticks; WS connections succeed via cached peer list |
| WS crash recovery (§9.3.3): kill -9 the WS task; supervisor rebinds | Recovered within 5s |
| **F5 divergence warning** flows to presence channel | Verified end-to-end |
| Admin endpoints require auth | Without auth → 401; with auth → 200 |
| Graceful shutdown: notify subscribers, flush queues, close | All clients receive `presence: leaving` |

---

## 9. Phase E — Integration test (~3 days)

**Goal:** prove the whole system runs end-to-end under realistic conditions and validate every architectural acceptance criterion that requires a running system.

### 9.1 Test harness

`scripts/run_phase_e.py` — launches AxiomaApp with `config/phase_e.yaml` (admin endpoints enabled, JSONL persistence on, snapshot cadence 60s, mock registry on localhost). Mock peer client (`tests/e2e/mock_peer.py`) connects, subscribes to all channels, and records to disk.

### 9.2 Acceptance tests (from ARCH §10 Phase E + v1.0 deltas)

| Test | Source | Acceptance |
|---|---|---|
| Boot, register, connect Skye via Speaker.SKYE, send conversation, observe θ stream | ARCH §10 Phase E | All steps succeed; ≥ 1 msg/sec on theta channel |
| Inject contradiction, watch S1/S2/S3 + cascade_delay change | ARCH §10 Phase E | All four ΔΦ signatures non-zero during the event window |
| 1-hour stability run: θ_long, plasticity buffer accumulation | ARCH §10 Phase E | θ_long std < 0.3; `|adaptation_delta| > 0.1` on EIDOLON contradiction test |
| Fragmentation monitor catches induced fragmentation | ARCH §10 Phase E | Stage 2 fires; recovery_request emitted; substrate accepts |
| Coherence_budget decreases under sustained load and recovers | ARCH §10 Phase E | Budget < 0.3 within 5 min of load injection; > 0.7 within 5 min of load removal |
| aos_g_alert fires when compose replaced with identity | ARCH §10 Phase E | Alert within 200 beats; psi drops < 0.3 |
| **F4 — Synthetic recovery pre-training** | F4 | Phase E acceptance includes successful pre-training of ≥ 50 events; snapshot saved; production refuses to start without it |
| **F9 — Fragmentation threshold empirical validation** | F9 | Each threshold's escalation probability in [0.20, 0.40] after ≤ 3 iterations |
| **F2 — Learner monitoring extension verified** | F2 | Synthetic regime: WARMING_UP→MONITORING→INEFFECTIVE @ 60 events; revert + 100-beat baseline + re-engage cycle works |
| **F1 — Smoothness window verified** | F1 | Recovery with deliberate early turbulence; smoothness reflects last-50-beat value |
| Recovery learner cold-start protection (E11) | E11 | Defaults returned for first 20 events |
| Recovery learner regression revert (E11) | E11 | Synthetic "bad" exploration → 0.10 regression detected → revert fires |
| Fault tolerance per §9.3.1–§9.3.5 | E4 | Force each fault; verify documented policy executes |
| **F5 — Suggestion divergence retrospective** | F5 | Over the run, divergence warnings track the ignored-suggestion rate; thresholds reasonable |
| Flow quality validation (E12) | E12 | If enough flow-zone samples: corr < 0.5 AND range ≥ 0.3 across components |
| Compose probe `expected_recovery` calibration | F4/E4 | Snapshot captured during synthetic recovery |
| `target_var_recovery` calibration | E3 | Snapshot captured during synthetic recovery |
| **End-to-end with mock peer:** mock peer connects, subscribes to 10 channels, runs 30 min, no drops | E2E | Mock peer recording shows continuous data on all channels |
| **Crash-restart continuity:** kill AxiomaApp at beat 5000; restart; verify state at beat 5001 matches in-memory state pre-crash (within stochastic tolerance) | Persistence | All 16 stateful components reload; substrate continues |

### 9.3 Performance acceptance

| Metric | Target |
|---|---|
| `axioma_beat_duration_seconds` p95 | < 100 ms (10 Hz budget) |
| `axioma_beat_duration_seconds` p99 | < 200 ms |
| θ_long compute (GPU) | < 80 ms per run |
| Raw MI batched (GPU) | < 10 ms per run |
| Compose function | < 5 ms |
| WS push per subscriber per channel | < 1 ms |
| Snapshot at 60s cadence | < 200 ms |
| Memory growth over 1-hr run | < 10 MB |

### 9.4 Long-run soak test

A 24-hour soak run in Phase E with all engines on, perturbations on internal schedule, no operator intervention:

- No memory leaks (RSS stable within 50 MB)
- No crashes (substrate uptime = wall time)
- No skipped beats (`axioma_beat_duration_seconds` count = uptime / 0.1 ± 1%)
- Snapshots survive 24-hour rotation
- All channels stay subscribed (no silent unsubscribes)
- Fragmentation events handled (recovery exit at expected duration ± 20%)

Soak is the truest test that nothing's leaking, deadlocking, or quietly failing.

---

## 10. Phase F — Pre-architecture follow-up experiments (parallel to A–E)

Scripts under `scripts/phase_f/`. Each runs against a `--config phase_f.yaml` that disables WS/HTTP (no operator), uses synthetic perturbations, and writes results to `results/phase_f/`.

| Experiment | Script | Output |
|---|---|---|
| φ-scaling EIDOLON-first | `phase_f_phi_scaling.py --order eidolon` | `results/phase_f/phi_eidolon.json` |
| φ-scaling ANIMA-first | `phase_f_phi_scaling.py --order anima` | `results/phase_f/phi_anima.json` |
| AOS-G weighted Euclidean | `phase_f_aos_g_weighted.py` | `results/phase_f/aos_g_weighted.json` |
| Control 3 partial differentiation | `phase_f_partial_diff.py` | `results/phase_f/partial_diff.json` |
| Baseline with ×10 organ range | `phase_f_widened_range.py` | `results/phase_f/widened_range.json` |
| Contradiction with 200-beat post-window | `phase_f_long_post_window.py` | `results/phase_f/long_post.json` |
| **AOS-G without eidolon_coh (C3)** | `phase_f_no_eidolon_coh.py` | `results/phase_f/no_eidolon_coh.json` |
| **F8 — Meta-cog confidence calibration** | `phase_f_meta_calibration.py` | `results/phase_f/meta_calibration.json` |
| **Recovery learner long-run study** | `phase_f_learner_longrun.py --events 100` | `results/phase_f/learner_longrun.json` |
| psi component sensitivity | `phase_f_psi_sensitivity.py` | `results/phase_f/psi_sensitivity.json` |
| Meta-cog assessment fidelity | `phase_f_meta_fidelity.py` | `results/phase_f/meta_fidelity.json` |

Each script is idempotent: rerunning overwrites the result file. Aggregated summary built by `scripts/phase_f/summarize.py`.

---

## 11. Testing strategy — three tiers

### 11.1 Unit tests (`tests/unit/`)

One test module per source module. Coverage target: **90% line, 80% branch** for substrate, measurement engines, compose function. Lower for I/O (WS server tests are mostly integration).

```
tests/unit/
├── substrate/
│   ├── test_organ_base.py
│   ├── test_drive.py             # iterative loop, noise scaling, symmetry
│   ├── test_anima.py
│   ├── test_eidolon.py           # ρ=0.92, V_E=1.3
│   ├── test_mneme.py             # α_M=1.4, stages 2/3 gated
│   ├── test_nous.py
│   ├── test_pneuma.py            # peer interface, no integrate()
│   ├── test_plasticity.py        # (mean_drift, var_ratio) summary
│   ├── test_recovery.py          # accept/reject logic, action sequences
│   └── test_recovery_learner.py  # hill-climb, F2 efficacy, safe revert
├── compose/
│   ├── test_compose_function.py
│   ├── test_cadence.py           # adaptive cadence transitions
│   ├── test_probe.py             # E4 recovery-aware, Stage-4 skip
│   └── test_flow_quality.py
├── measurement/
│   ├── test_theta_engine.py      # short + long
│   ├── test_raw_mi_engine.py     # 5b + 20b windows
│   ├── test_cascade_delay.py     # F1: uses raw MI, peak detection
│   ├── test_delta_phi.py         # perturbation-relative recording
│   ├── test_aos_g.py
│   ├── test_psi.py               # E1 debounce, E3 recovery-aware
│   ├── test_fragmentation_monitor.py
│   ├── test_perturbation_scheduler.py
│   └── test_meta_cognition.py    # F5 escalation, F7 modes, F8 caveat
├── scheduler/
│   └── test_coherence_scheduler.py  # E13 effectiveness escalation
├── persistence/
│   ├── test_snapshot.py          # atomic write, schema mismatch handling
│   └── test_models.py
├── interface/
│   ├── test_ws_handlers.py       # per-subscriber rate, coalescing
│   ├── test_speaker_handshake.py
│   └── test_registry_client.py   # cache + retry
└── config/
    └── test_loader.py
```

**Hypothesis-based property tests** for:
- `compose(internal, θ=1, eidolon_coh=1) ≈ internal` (high fidelity = near-identity)
- Persistence round-trip: `load(save(x)).save() == x.save()` (idempotent)
- Drive symmetry: any permutation of organs produces same θ (within stochastic tolerance)
- Plasticity: a constant input over 1000 beats drives mean_drift → 0

### 11.2 Integration tests (`tests/integration/`)

Components composed across module boundaries, fakes for I/O.

```
tests/integration/
├── test_substrate_measurement.py     # substrate ticks → measurement engines update correctly
├── test_substrate_compose.py         # substrate → compose → ExternalState
├── test_fragmentation_recovery.py    # monitor → request → substrate accept → protocol → quality
├── test_recovery_learner_cycle.py    # event → quality → learner → next event uses learned params
├── test_perturbation_pipeline.py     # scheduler → substrate → ΔΦ engine → recorded
├── test_meta_cognition_pipeline.py   # measurement → meta → suggestion → tracker → escalation (F5)
├── test_psi_pipeline.py              # compose → aos_g → psi components → alert
├── test_persistence_roundtrip.py     # take snapshot → restart → verify continuity
├── test_boundary_isolation.py        # C12: ImportError test
└── test_coherence_scheduling.py      # budget < 0.3 → throttles applied → engines slow
```

### 11.3 End-to-end tests (`tests/e2e/`)

Full AxiomaApp running, real WS server, mock peer client.

```
tests/e2e/
├── test_boot_register_subscribe.py
├── test_perturbation_response.py        # inject → ΔΦ → cascade_delay → all channels notified
├── test_fragmentation_e2e.py            # induced fragmentation → monitor → recovery → quality → learner
├── test_observer_mode.py                # F7: observer_only ignores suggestions; embedded uses them
├── test_divergence_warning.py           # F5: 5 ignored → presence channel warning
├── test_fault_tolerance.py              # §9.3.1-5 each fault simulated
├── test_crash_restart.py                # kill -9; restart; state continues
├── test_synthetic_pretrain.py           # F4: pre-training warm-starts learner
├── test_24h_soak.py                     # marked @pytest.mark.slow
└── mock_peer.py                         # reusable mock subscriber
```

### 11.4 Benchmark tests (`tests/benchmarks/`)

`pytest-benchmark` against the GPU. CI runs these on a labelled GPU runner; failures don't block merge but trip a "perf regression" label.

```python
def test_theta_long_perf(benchmark, gpu_substrate_with_buffer):
    benchmark(gpu_substrate_with_buffer.theta_long_engine.compute)
    # Acceptance: median < 80 ms on H100

def test_raw_mi_batched_perf(benchmark, gpu_substrate_with_buffer):
    benchmark(gpu_substrate_with_buffer.raw_mi_engine.compute_5beat)
    # Acceptance: median < 10 ms on H100

def test_beat_tick_perf(benchmark, substrate):
    benchmark(substrate.heartbeat.tick)
    # Acceptance: median < 50 ms (substrate-only, no measurement engines)
```

### 11.5 Continuous validation

`scripts/continuous_validate.sh`:

```bash
#!/bin/bash
set -euo pipefail
cd /home/ubuntu/axioma
conda run -n axioma ruff check axioma/
conda run -n axioma mypy axioma/
conda run -n axioma pytest tests/unit/ -x --cov=axioma --cov-report=term-missing
conda run -n axioma pytest tests/integration/ -x
# E2E and benchmarks run in CI on a separate stage
```

Pre-commit hook runs ruff + mypy + unit subset (fast).

### 11.6 Data validation — what to check beyond "tests pass"

Tests catch code bugs. **Data bugs** (a measurement engine reports plausible-but-wrong values) need separate verification:

1. **Cross-check θ against v0.2.** Run the v0.4 substrate for 1 hour; compute θ via the new engine and via vendored v0.2 code on the same window. Difference should be < 0.05 for the same input. If larger, something diverged.
2. **Cross-check cascade_delay against synthetic.** Build a deterministic 2-organ trace where ANIMA peak is exactly 7 beats after EIDOLON peak. Verify cascade_delay engine reports 7 ± 1.
3. **Sanity-check ΔΦ baselines.** Run substrate for 30 min with NO perturbations. ΔΦ baselines should not drift (all signatures near 0).
4. **Sanity-check perturbation responses.** Inject a known-large contradiction (magnitude 1.0). Expect S1 > 0.1 (large dynamic range). If 0, something's wrong upstream.
5. **Sanity-check `psi` decomposition.** Force each component low individually; `psi` should track the min.

Data validation lives in `scripts/data_validation/`, runs against fresh substrate output, produces a markdown report. Run after every Phase B / Phase E change.

---

## 12. Configuration management

`axioma/config/defaults.py` — single source of truth for every tunable in the architecture:

```python
class SubstrateConfig(BaseModel):
    n_iter: int = 3
    rho_g: float = 0.90
    organ_specs: dict[str, OrganSpec] = Field(default_factory=lambda: {
        "anima":   OrganSpec(latent_dim=8,  state_dim=4, rho=0.85, v_scale=1.0),
        "eidolon": OrganSpec(latent_dim=12, state_dim=6, rho=0.92, v_scale=1.3),  # C1
        "mneme":   OrganSpec(latent_dim=12, state_dim=5, rho=0.88, v_scale=1.4),  # MNEME α_M
        "nous":    OrganSpec(latent_dim=10, state_dim=6, rho=0.90, v_scale=1.0),
        "pneuma":  OrganSpec(latent_dim=12, state_dim=7, rho=0.92, v_scale=1.0),  # +1 for coherence_budget
    })
    mneme_compensation_2_enabled: bool = False  # gate
    mneme_compensation_3_enabled: bool = False  # gate
    plasticity_pathway_2_enabled: bool = False  # auto-gated in Phase B

class MeasurementConfig(BaseModel):
    theta_short_window: int = 30
    theta_long_window: int = 500
    raw_mi_short_window: int = 5
    raw_mi_long_window: int = 20
    delta_phi_window: int = 50
    plasticity_period: int = 100
    fragmentation_check_period: int = 10
    meta_cognition_period: int = 100
    meta_cognition_trajectory_window: int = 1000  # E5
    theta_long_cadence: int = 10
    perturbation_default_magnitude: float = 0.3   # F6 sweeps

class ComposeConfig(BaseModel):
    baseline_period: int = 30
    perturbation_period: int = 5      # D2
    recovery_period: int = 60         # D2
    perturbation_window_beats: int = 50
    weights: dict[str, float] = ...   # tuned in Phase A
    noise_factor: float = 0.05
    aos_g_alert_threshold: float = 0.1
    psi_alert_threshold: float = 0.3

class RecoveryConfig(BaseModel):
    min_recovery_stage: int = 2
    default_duration_beats: int = 100
    restore_beats: int = 20
    coupling_reduction_factor: float = 0.8         # tunable by learner
    mneme_forgetting_boost: float = 1.5             # tunable by learner
    recovery_compose_period_beats: int = 60         # tunable by learner
    learner_exploration_rate: float = 0.15
    learner_adoption_threshold: float = 0.05
    learner_regression_threshold: float = 0.10
    learner_min_events_for_adoption: int = 20      # F2
    learner_monitoring_extension_events: int = 60  # F2 (total)
    learner_baseline_refresh_period_events: int = 10  # F2
    pretrain_target_events: int = 50               # F4
    require_pretrain: bool = True                  # F4: production refuses to start without

class MetaCognitionConfig(BaseModel):
    observer_mode: Literal["observer_only", "embedded"] = "observer_only"  # F7
    suggestion_confidence_threshold: float = 0.7
    divergence_warning_threshold: int = 5    # F5

class CoherenceSchedulerConfig(BaseModel):
    throttle_thresholds: dict[str, float] = {
        "high": 0.15, "medium": 0.30, "low": 0.50,
    }
    effectiveness_window_beats: int = 50      # E13
    effectiveness_min_threshold: float = 0.1
    escalation_consecutive_windows: int = 3   # E13

class PersistenceConfig(BaseModel):
    snapshot_period_beats: int = 600  # 60s @ 10 Hz
    snapshot_retention_count: int = 24
    daily_snapshot_retention_days: int = 30
    jsonl_rotation_minutes: int = 60

class ObservabilityConfig(BaseModel):
    log_level: str = "INFO"
    log_json: bool = True
    metrics_enabled: bool = True

class InterfaceConfig(BaseModel):
    ws_port: int = 8820
    http_port: int = 8821
    registry_url: str = "http://localhost:8810/registry"  # Q1: still placeholder
    registry_retry_max_seconds: int = 300
    admin_api_key: SecretStr | None = None

class AxiomaConfig(BaseModel):
    substrate: SubstrateConfig = SubstrateConfig()
    measurement: MeasurementConfig = MeasurementConfig()
    compose: ComposeConfig = ComposeConfig()
    recovery: RecoveryConfig = RecoveryConfig()
    meta_cognition: MetaCognitionConfig = MetaCognitionConfig()
    coherence_scheduler: CoherenceSchedulerConfig = CoherenceSchedulerConfig()
    persistence: PersistenceConfig = PersistenceConfig()
    observability: ObservabilityConfig = ObservabilityConfig()
    interface: InterfaceConfig = InterfaceConfig()
```

Loaded via `axioma.config.loader.load_config(path: Path | None = None)` → merges:
1. `configs/default.yaml` (committed)
2. `configs/local.yaml` (gitignored, dev overrides)
3. `AXIOMA_CONFIG` env var path
4. `AXIOMA_*` env var overrides (per-field, e.g., `AXIOMA_SUBSTRATE_N_ITER=5`)

Config is **frozen** after load — mutation requires the admin API (`POST /admin/config/...`) and emits a `config_change` event.

---

## 13. Build order (concrete week-by-week)

Assumes 1 implementer, full-time. Sister availability for F6 zone validation, F8 calibration, and ad-hoc review.

| Week | Phase | Deliverables |
|---|---|---|
| **1** | A.1, A.2 (start) | Scaffold + observability + persistence protocol + drive + organs + plasticity |
| **2** | A.2, A.3, A.4 (start) | Recovery scaffold + Phase A tests (drive symmetry, N_iter sweep, MNEME compensation); F6 zone validation scheduled |
| **3** | A.4 (finish), B (start) | Phase A wraps; θ engines (short + long), raw MI engine, cascade_delay |
| **4** | B (continue) | ΔΦ engine, plasticity tracker, AOS-G + psi (with E1/E3/E4), fragmentation monitor |
| **5** | B (finish), C | Perturbation scheduler, coherence scheduler (+ E13), meta-cog loop (+ F5/F7/F8), recovery learner full; Phase C compose boundary + cadence + probe + flow quality + ImportError test |
| **6** | D | WS server + HTTP API + registry client + all new channels; Phase D tests |
| **7** | E (start), F (parallel) | Phase E integration tests; synthetic pre-training F4 run; fragmentation threshold validation F9; Phase F experiments kick off |
| **8** | E (finish), F (finish) | 24h soak; performance benchmarks; F8 meta-cog calibration; Phase F summary; v1.0 implementation report |

Total: 8 weeks. Buffer of ~1.5 weeks built in (architecture estimated 10 working days = ~2 weeks for E alone given v1.0 deltas).

---

## 14. Acceptance for "v1.0 implementation complete"

A single checklist. Implementation is done when:

- [ ] All Phase A tests pass; `n_iter_sweep_results.md`, `coupling_targets.json`, `zone_thresholds.json` (with task-typed variants if F6 triggers) are committed
- [ ] All Phase B tests pass; data validation report green; LearnerEfficacy state machine demoed
- [ ] All Phase C tests pass; ImportError test holds in CI
- [ ] All Phase D tests pass; per-subscriber rate config verified; F5 divergence warning flows
- [ ] All Phase E tests pass; synthetic pre-training snapshot committed; fragmentation thresholds tuned (F9)
- [ ] 24h soak test passes (no leaks, no skipped beats, no crashes)
- [ ] All Phase F experiments completed; results committed; F8 calibration verdict (PASS / SOFT FAIL / HARD FAIL) documented
- [ ] Performance acceptance met (§9.3)
- [ ] All 16 stateful components implement `Stateful` and round-trip snapshot test passes
- [ ] All required structured-log fields present (§3.1)
- [ ] All required Prometheus metrics exposed (§3.2)
- [ ] Fault tolerance per §9.3.1–§9.3.5 verified
- [ ] Documentation: README, runbooks for each fault class, OpenAPI docs generated, env_verification.md, snapshot-recovery runbook
- [ ] Code: ruff clean, mypy clean, ≥ 90% unit coverage on substrate / measurement / compose
- [ ] Implementation report (`docs/v1.0_implementation_report.md`) lists every architecture commitment with PR/commit reference

---

## 15. What this plan deliberately does NOT do

- **No model training.** Plasticity is homeostatic; recovery learner is bounded hill-climb. No PyTorch optimizer, no gradient descent, no checkpoints in the deep-learning sense.
- **No distributed training.** Single process, single GPU. Multi-host is post-v1.0.
- **No public deployment.** Localhost-trust per ARCH §8.6. Auth is admin-API-key only.
- **No telemetry to external services.** Prometheus exposition is pull-based; nothing pushes anywhere by default.
- **No new substrate dynamics R&D.** The substrate equations are frozen in v1.0. If Phase A measurements reveal substrate problems (e.g., F15 non-saturating dynamics shift the operating point catastrophically), those are documented as v1.1 work — they don't restart the design loop.

---

## 16. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| H100 unavailable when implementer needs it | Low | Med | All engines run on CPU; GPU is performance, not correctness. Tests can run on CPU. |
| Theoria unavailable for F6 zone validation | Med | Low | Block A.4 finish until F6 done; can pre-implement everything else |
| Registry URL still TBD at Phase D | High | Med | Mock registry on localhost:8810 ships with the code; production points at real registry via config |
| F8 HARD FAIL — meta-cog confidence unusable | Med | Low | Ship v1.0 with heightened caveat; v1.1 calibration |
| F9 thresholds don't converge | Med | Low | Ship best-effort thresholds; v1.1 attention |
| Synthetic pre-training distribution ≠ production fragmentation | Med | Med | Q22: post-deployment first-100-event analysis triggers re-pretrain |
| Schema migration breaks snapshot reload | Low | High | §4.6: per-component cold start, not hard fail; explicit operator notification |
| Substrate divergence under iterative loop | Low | High | §9.3.1 latent clipping; N_iter sweep verifies variance invariance |
| WS subscriber memory blow-up under coalescing bug | Low | Med | Per-subscriber bounded queue (max 1); benchmarks include memory check |

---

## 17. First steps for the implementer (literal next actions)

```bash
# 1. Set up the env (one-time)
conda activate axioma
pip install --upgrade pip
# (run the install commands from §1.1)

# 2. Verify GPU
conda run -n axioma python -c "import torch; assert torch.cuda.is_available()"

# 3. Create the scaffold
cd /home/ubuntu/axioma
mkdir -p axioma/{config,schemas,substrate,compose,measurement,interface,scheduler,persistence,runtime,observability,util}
mkdir -p tests/{unit,integration,e2e,benchmarks}
mkdir -p scripts/phase_f configs docs/runbooks

# 4. Initialize package metadata
touch axioma/__init__.py axioma/__main__.py
# (write pyproject.toml with project, build-system, ruff, mypy, pytest config)

# 5. Land the observability rails FIRST (§3)
# - axioma/observability/logging.py
# - axioma/observability/metrics.py
# - tests/unit/test_observability.py

# 6. Land the persistence protocol (§4)
# - axioma/persistence/snapshot.py
# - tests/unit/test_snapshot.py with a fake Stateful component

# 7. Land the config loader (§12)
# - axioma/config/{schema,defaults,loader}.py
# - configs/default.yaml
# - tests/unit/test_config.py

# 8. Verify CI: pytest + ruff + mypy all green on the scaffold

# 9. Begin Phase A.2: SharedLatentDrive with iterative inner loop
```

After step 9, the implementer follows the week-by-week plan in §13.
