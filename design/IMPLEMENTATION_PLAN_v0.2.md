# AXIOMA v1.0 — Implementation Plan v0.2

**Companion to:** [ARCH_DESIGN_v1.0.md](ARCH_DESIGN_v1.0.md)
**Supersedes:** [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) (v0.1)
**Review addressed:** [IMPL_REVIEW_v0.1.md](IMPL_REVIEW_v0.1.md) — 17 tracked items (P1–P17)
**Target environment:** conda env `axioma`, NVIDIA H100 PCIe (80 GB)
**Base codebase:** `/home/ubuntu/axioma/organ/` (existing v0.2 substrate + θ pipeline)
**Status:** Implementation-ready (after sister review)

---

## 0. Changelog from v0.1

The review approved v0.1 (0 blockers) and identified 9 gaps + 8 risks. v0.2 lands every item. Structure is unchanged; precision is added in 17 places.

| Δ | Section | What changed | Source |
|---|---|---|---|
| **P1** | §5.0 (new) | **Heartbeat tick sequence**: explicit 12-step per-beat ordering of substrate → measurement → compose → scheduler → meta → interface → persistence. Removes "ad-hoc decisions at Phase E" risk. | Gap 1 (Moderate) |
| **P2** | §5.3 (new) | **Phase A parallelism map**: identifies the critical path (A.1 + A.2.1) that gates everything; A.2.2/A.3 can proceed in parallel with Phase B sub-steps. | Risk 1 (High) |
| **P3** | §6.1 step 7 + new §6.7 | **Recovery accept/reject criteria specified** before implementation. | Gap 6 (Medium) |
| **P4** | §6.7 (new) | **`MetaCognitionSuggestion` schema** specified with all 6 fields. | Gap 8 (Medium) |
| **P5** | §10.3 (new) | **Phase F calibration criteria**: 3 numeric pass/fail thresholds for meta-cog. | Gap 9 (Medium) |
| **P6** | §6.3 (new) | **Performance budget table**: per-engine costs, worst-case beat (205 ms acceptable), variable-beat policy. | Risk 3 (Moderate) |
| **P7** | §9.0 (new) | **Pre-integration checklist**: 8-step verification gating the 24 h soak. | Risk 2 (High) |
| **P8** | §9.4 (added test) | **Recovery-compose feedback monitoring**: detect ψ oscillations during pre-training; auto-halve coupling-weight change if period < 100 beats. | Risk 4 (Moderate) |
| **P9** | §5.4 (new) | **Cold start documentation**: first-boot semantics; ~100-beat stabilization window flagged as expected. | Observation (Thea) |
| **P10** | §3.4 (new) + §6.2 | **Engine scheduling pattern**: every engine implements `should_run(beat_no, coherence_budget) → bool`. Heartbeat consults; scheduler integrates. | Gap 2 (Minor) |
| **P11** | §3.5 (new) | **`AxiomaContext` pub/sub**: components communicate through a shared context (dependency injection + lightweight event bus). | Gap 3 (Minor) |
| **P12** | §9.2 (F4 detail) | **Recovery pre-training data source** specified: 6 contradictions × 3 magnitudes + 2–12 random = 20–30 events from PerturbationScheduler standard battery. | Gap 4 (Minor) |
| **P13** | §7.2 (added note) | **`eidolon_coh` signal path**: extracted from `EidolonState.self_coherence`, read live at compose time. | Gap 5 (Low) |
| **P14** | §6.1 step 8 (extended) | **PerturbationScheduler battery enumerated**: contradiction, impulse, step — round-robin with magnitude sweep. | Gap 7 (Low) |
| **P15** | §5.2 A.4 (added test) | **θ_short bias measurement**: compare against θ_long; if p95 bias > 20%, widen θ_short window to 50. | Risk 8 (Low) |
| **P16** | §5.2 A.4 (added test) | **Adaptive cadence cost verification**: measure compose cost at {5,10,20,30,60}-beat intervals; verify budget. | Risk 7 (Low) |
| **P17** | §5.3 + §13 (timeline) | **F6 subjective zone validation scheduled first**: Theoria booked in week 2; Thea as documented backup. | Risk 6 (Medium) |
| Additionally | §9.2 (F4 extended) | **Recovery event accumulation fallback**: if Phase E produces < 20 organic recovery events, extend with additional synthetic perturbation sessions until threshold met. | Risk 5 (Medium) |

Architecture feature coverage (all 19 features) was confirmed by the reviewers — see [IMPL_REVIEW_v0.1.md §1](IMPL_REVIEW_v0.1.md). v0.2 preserves coverage and adds precision.

---

## 1. Environment setup

### 1.1 conda env `axioma` — dependency baseline (unchanged from v0.1)

```bash
conda activate axioma

# Core scientific
pip install numpy>=1.26 scipy>=1.11

# GPU compute (H100 = CUDA 12.x)
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

### 1.2 GPU verification (unchanged from v0.1)

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

Record output in `docs/env_verification.md`.

### 1.3 Repository structure (target, unchanged from v0.1)

```
axioma/
├── axioma/                           # new top-level package
│   ├── config/                        # pydantic Config + YAML/TOML/env layer
│   ├── schemas/                       # InternalState, ExternalState, events
│   ├── substrate/                     # 5 organs, drive, plasticity, recovery
│   ├── compose/                       # ComposeFunction, cadence, probe, flow_quality
│   ├── measurement/                   # θ, ΔΦ, raw MI, cascade, plasticity tracker,
│   │                                  # AOS-G+psi, fragmentation, meta-cog,
│   │                                  # perturbation scheduler
│   ├── interface/                     # WS server, HTTP API, registry client
│   ├── scheduler/                     # coherence scheduler
│   ├── persistence/                   # Stateful protocol, snapshot, DB, JSONL
│   ├── runtime/                       # heartbeat, lifecycle, faults, app
│   ├── observability/                 # logging, metrics, tracing, context
│   └── util/                          # GPU helpers, timing
├── tests/                             # unit, integration, e2e, benchmarks
├── scripts/                           # phase_a_*, phase_e_*, phase_f_*
├── configs/                           # default.yaml, local.yaml, phase_*.yaml
├── docs/                              # env_verification.md, runbooks/, api/
├── data/                              # research artifacts + state snapshots
├── design/                            # ARCH_DESIGN_v*.md, reviews, plans
├── organ/                             # v0.2 codebase (reference; not modified)
├── pyproject.toml
├── requirements.txt
└── README.md
```

Why parallel `axioma/` (not in-place migration of `organ/`):
- v0.2's `organ/` is the reproducibility anchor for the research summary
- PNEUMA still has `integrate()` (v1.0 forbids); refactoring in place would break v0.2 tests
- Common code (theta pipeline, ring buffer) **vendored** into `axioma/measurement/` with attribution

---

## 2. What's already built (v0.2) vs what's new (v1.0)

(Unchanged from v0.1.) Inventory table maps every component to ✅ reuse / 🔄 refactor / ❌ build. See v0.1 §2 for the full table.

---

## 3. Cross-cutting concerns built FIRST

Three concerns thread through every phase. Build the rails before the substrate.

### 3.1 Structured logging (unchanged from v0.1 §3.1)

`structlog` with `beat_no` bound as a context var once per beat in `heartbeat.tick_async()`. Required structured fields per subsystem; log-level policy (DEBUG/INFO/WARN/ERROR/CRITICAL) per behavior class.

### 3.2 Prometheus metrics (unchanged from v0.1 §3.2)

Per-beat timing histograms, per-engine duration histograms, state gauges (θ_short, θ_long, AOS-G, psi, coherence_budget, fragmentation_stage, recovery_active), counters (perturbations, recoveries, suggestions, divergence warnings), persistence write counters. Exposed at `:8821/metrics`.

### 3.3 Per-engine timing contract (unchanged from v0.1 §3.3)

Every measurement engine wraps compute in `with measure_engine(name):`. Phase E uses the histograms to validate the cadence budget.

### 3.4 `AxiomaContext` — pub/sub for component communication (new in v0.2 — P11)

Components need to communicate across modules: the cadence controller subscribes to perturbation scheduler events; the fragmentation monitor subscribes to recovery state changes; the meta-cognitive loop reads from multiple engines; the coherence scheduler escalates to the fragmentation monitor. v0.2 specifies the mechanism.

`axioma/observability/context.py`:

```python
from typing import Any, Callable, Awaitable
from collections import defaultdict
import structlog

log = structlog.get_logger(__name__)

EventHandler = Callable[[Any], Awaitable[None] | None]

class AxiomaContext:
    """Single shared object holding references to all engines + a lightweight event bus.

    Constructed once at app startup; passed to every engine/organ at construction.
    Two purposes:
      1. Dependency injection — engines find each other via the context, not globals
      2. Pub/sub — components emit named events; subscribers register handlers

    Events are processed synchronously in subscription order (no async queue in v1.0;
    simple and predictable). For high-throughput data flows (per-beat measurements),
    use direct context.<engine>.method() calls — events are for state changes,
    not data plane.
    """

    def __init__(self):
        # Components register themselves under stable names
        self.components: dict[str, Any] = {}
        # Event subscribers, keyed by event name
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)

    # --- Dependency injection ---
    def register(self, name: str, component: Any) -> None:
        if name in self.components:
            raise KeyError(f"component already registered: {name}")
        self.components[name] = component
        log.debug("ctx_register", name=name, type=type(component).__name__)

    def get(self, name: str) -> Any:
        if name not in self.components:
            raise KeyError(f"component not registered: {name}")
        return self.components[name]

    # Typed accessors for the common cases (avoids string keys at call sites)
    @property
    def substrate(self): return self.get("substrate")
    @property
    def heartbeat(self): return self.get("heartbeat")
    @property
    def perturbation_scheduler(self): return self.get("perturbation_scheduler")
    @property
    def fragmentation_monitor(self): return self.get("fragmentation_monitor")
    @property
    def recovery_protocol(self): return self.get("recovery_protocol")
    @property
    def coherence_scheduler(self): return self.get("coherence_scheduler")
    @property
    def meta_cognition_loop(self): return self.get("meta_cognition_loop")
    @property
    def compose_function(self): return self.get("compose_function")
    @property
    def cadence_controller(self): return self.get("cadence_controller")

    # --- Event bus ---
    def subscribe(self, event: str, handler: EventHandler) -> None:
        self._subscribers[event].append(handler)
        log.debug("ctx_subscribe", event=event, handler=handler.__qualname__)

    async def emit(self, event: str, payload: Any) -> None:
        """Synchronous-order dispatch. Handlers may be coroutines."""
        for handler in self._subscribers[event]:
            try:
                result = handler(payload)
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                log.exception("ctx_event_handler_failed", event=event,
                              handler=handler.__qualname__)
                # one handler failing does not stop the others — safety property
```

**Event names used in v1.0:**

| Event | Emitter | Subscribers |
|---|---|---|
| `perturbation_injected` | PerturbationScheduler | CadenceController (sets `perturbation_window_active = True` for 50 beats), DeltaPhiEngine (records event_id), JSONLWriter |
| `recovery_state_change` | RecoveryProtocol | CadenceController, AOSGEngine (toggles gap_variance target), ComposeProbe (toggles expected reference), JSONLWriter |
| `recovery_event_finalized` | FragmentationMonitor (computes quality on exit) | RecoveryLearner (records to history), MetricsExporter |
| `fragmentation_stage_change` | FragmentationMonitor | MetaCognitionLoop (factor in assessment), MetricsExporter |
| `meta_suggestion_emitted` | MetaCognitionLoop | RecoveryProtocol (consults if `embedded`), SuggestionTracker (records) |
| `suggestion_decision` | RecoveryProtocol | SuggestionTracker (records `used` / `ignored`; triggers F5 escalation after 5 consecutive ignored) |
| `divergence_warning` | SuggestionTracker | WSServer (emits on presence channel), MetricsExporter |
| `throttle_state_change` | CoherenceScheduler | MetricsExporter, WSServer (emits on coherence_budget channel) |
| `throttle_effectiveness_fail` | CoherenceScheduler | FragmentationMonitor (additional Stage-2 evidence) |
| `config_change` | HTTP admin endpoint | Every Stateful component (re-binds config-derived state) |
| `recovery_learner_adopted` | RecoveryLearner | MetricsExporter, JSONLWriter |
| `recovery_learner_reverted` | RecoveryLearner | MetricsExporter, JSONLWriter (logged at WARN) |

The event bus is deliberately tiny — no async queue, no message broker. Per-beat data flows go through direct method calls on context-resolved components; the event bus carries only state-change notifications and discrete events.

**Why this matters for testing.** Every component takes `AxiomaContext` as a constructor argument; tests inject a `FakeContext` that records `emit` calls and lets the test inspect them. No global state, no monkey-patching.

### 3.5 Engine scheduling — `should_run` pattern (new in v0.2 — P10)

Every measurement engine exposes:

```python
class MeasurementEngine(Stateful, Protocol):
    name: str

    def should_run(self, beat_no: int, coherence_budget: float) -> bool:
        """Return True if the engine should compute this beat.

        Combines the engine's natural cadence with the coherence scheduler's
        throttle policy. The heartbeat calls this before invoking compute.
        """

    async def compute(self) -> None:
        """Run the engine and update internal state. Read-only on substrate."""
```

A reference implementation pattern:

```python
class ThetaShortEngine:
    name = "theta_short"
    natural_period_beats = 1   # every beat

    def should_run(self, beat_no: int, coherence_budget: float) -> bool:
        if beat_no % self.natural_period_beats != 0:
            return False
        # Consult coherence scheduler's throttle policy via context
        throttle = self.ctx.coherence_scheduler.throttle_for(self.name)
        # throttle returns an effective period (≥ natural_period)
        return beat_no % throttle.effective_period_beats == 0
```

This means coherence-scheduler throttling is **single-source-of-truth**: each engine asks "may I run?" and the scheduler answers. Heartbeat doesn't need to know any engine's cadence. Easy to test: replace `throttle_for` with a fake that returns whatever the test wants.

**Heartbeat invocation order:** the heartbeat iterates engines in a fixed order (per §5.0), calls `should_run`, and invokes `compute` only when True. The scheduler decides; the heartbeat dispatches.

---

## 4. Persistence — the second cross-cutting concern

(Unchanged structurally from v0.1 §4.)

### 4.1 The `Stateful` protocol

Every stateful component implements `save_state()` and `load_state()` with `schema_version`. No state lives in memory only.

### 4.2 What every component must persist (unchanged from v0.1 §4.2)

22-component table. JSON snapshots for in-memory state, SQLite for high-volume `RecoveryHistory` and `PerturbationEvent` and `MetaCognitionEmission` rows, JSONL for high-rate append-only data (`ExternalState`, `theta`, `raw_mi`).

### 4.3–4.6 (unchanged from v0.1)

Atomic snapshot procedure, load contract with schema-mismatch tolerance, SQLite models, JSONL writer rotation.

---

## 5. Phase A — Substrate rework (~3.5 days)

### 5.0 Heartbeat tick sequence (new in v0.2 — P1)

Every beat (target 100 ms wall-clock) executes the following sequence. The heartbeat is the orchestrator; engines are invoked via the `should_run` pattern (§3.5).

```
on tick(beat_no):
  1. bind beat_no to structlog context var (so all nested logs carry it)
  2. SUBSTRATE                                                  (CRITICAL — every beat)
     a. CadenceController.update_state(beat_no)                  -- consumes perturbation/recovery events
     b. RecoveryProtocol.tick(beat_no)                           -- decrements recovery countdown if active
     c. PerturbationScheduler.tick(beat_no)                      -- may inject perturbation (pre-update)
     d. SharedLatentDrive.step(N_iter)                           -- iterative inner loop
     e. for organ in (anima, eidolon, mneme, nous, pneuma):
          organ.update(beat_no, drive, time_scale=1.0)
     f. PlasticityBuffer.maybe_update(beat_no)                   -- every 100 beats
  3. MEASUREMENT — high-priority (CRITICAL — every beat unless throttled)
     a. RawMIEngine.should_run/compute()                         -- 5-beat + 20-beat windows
     b. CascadeDelayEngine.should_run/compute()                  -- depends on RawMI output
     c. ThetaShortEngine.should_run/compute()                    -- 30-beat window
     d. FragmentationMonitor.should_run/compute()                -- every 10 beats (default cadence)
  4. COMPOSE — boundary
     a. if CadenceController.should_compose(beat_no):
          ext = ComposeFunction.compose(internal, theta_short, eidolon_coh)
          AOSGEngine.update(ext, internal)                        -- gap + psi components
          ComposeProbe.maybe_run(beat_no, recovery_state)          -- every 100 beats
          PersistJSONL.write("external_state", ext)
  5. MEASUREMENT — medium-priority (throttled at budget < 0.30)
     a. ThetaLongEngine.should_run/compute()                     -- every 10 beats
     b. DeltaPhiEngine.should_run/compute()                      -- every 5 beats
     c. PlasticityTracker.should_run/compute()                   -- every 100 beats
  6. SCHEDULER (every 10 beats)
     a. CoherenceScheduler.update(beat_no)                       -- recompute throttle state
     b. CoherenceScheduler.maybe_emit_effectiveness_event()      -- E13
  7. META-COGNITION (every 100 beats, High priority)
     a. MetaCognitionLoop.should_run/compute()                   -- emit assessment + possible suggestion
  8. INTERFACE
     a. WSServer.flush_pending()                                  -- coalesced per-subscriber push
     b. (HTTP API responds in its own task, not in tick path)
  9. PERSISTENCE
     a. SnapshotManager.maybe_snapshot(beat_no)                  -- every 600 beats (60 s)
     b. flush in-flight JSONL writes
 10. unbind beat_no from context var
 11. emit BEAT_DURATION_S histogram observation
 12. if duration > 100 ms: emit `beat_overshoot` log at INFO with breakdown
```

**Invariants:**

- **Substrate (step 2) is ALWAYS run** — no throttle, no skip. Substrate continuity is non-negotiable.
- **Compose (step 4) runs at cadence-controlled intervals**, not every beat.
- **Measurement engines (steps 3, 5, 7) consult `should_run`** which combines natural cadence with throttle policy.
- **WS push (step 8) is coalesced** — pending updates per subscriber are merged so a slow subscriber doesn't backlog.
- **Persistence (step 9) is async** — snapshot is launched as a background task at 600-beat boundaries; doesn't block the next tick.

This sequence is encoded in `axioma/runtime/heartbeat.py`. It is the **single source of truth** for per-beat ordering — engines never schedule themselves outside this sequence.

### 5.1 Order of work (preserves v0.1 sub-phases; explicit gates added)

**A.1 — Scaffold (4 hours)**

- `axioma/` package skeleton per §1.3
- Logging + metrics + AxiomaContext per §3 (incl. P10, P11)
- Persistence protocol per §4
- Config loader (YAML defaults, env overrides)
- pytest, ruff, mypy, pre-commit
- CI: `pytest tests/unit` runs on every push

**A.2 — Substrate critical path (1.5 days)**

- `SharedLatentDrive.step(N_iter)` — iterative Euler inner loop
- 5 organs as peers; non-saturating renderers (OU latent + linear rescale)
- EIDOLON: ρ=0.92, V_E=1.3
- MNEME: stage-1 compensation (α_M=1.4); stages #2/#3 behind feature flags (default OFF)
- PNEUMA: peer interface, no `integrate()`; `coherence_budget` field
- Per-organ `PlasticityBuffer` with `(mean_drift, var_ratio)` summary
- Render-modulation pathway ON; coupling-weight adaptation OFF (auto-gated in Phase B)
- All components implement `Stateful`
- `axioma/runtime/heartbeat.py` per §5.0 (substrate steps only — measurement/compose stubs return no-op)

**A.3 — Recovery + perturbation scaffold (0.5 day) [parallel-eligible — see §5.3]**

- `RecoveryProtocol` accept/reject decision logic (§6.7 criteria)
- `recovery_protocol(stage)` action sequence per ARCH §4.9
- `RecoveryHistory` (SQLite-backed)
- `RecoveryLearner` skeleton (defaults only; learning logic in Phase B)
- `RecoveryQuality` with **last-50-beat smoothness windowing (F1)** — verified against synthetic dummy θ traces
- `PerturbationScheduler` with battery enumeration (§6.1 step 8)

**A.4 — Phase A validation (1.5 days)**

Acceptance tests (architecture mappings noted):

| Test | Acceptance |
|---|---|
| Drive symmetry: organ permutation invariance | θ change < 1% under any permutation |
| Range invariance: organ states stay in design ranges over 10 min | `validate_ranges()` passes on every beat |
| MNEME stage-1: pairwise MI for MNEME pairs ≥ 0.8× ANIMA pairs | Pass; if fail, enable stage #2 |
| **C11** Perturbation response: impulse on EIDOLON propagates within 2 beats | All 4 non-EIDOLON organs' state delta > 0.01 |
| **N_iter sweep (D11/F14)**: mc_corr > 0.8 + variance invariance ±10% | Picks N_iter default; saves `n_iter_sweep_results.md` |
| **Coupling validation (D8/E15)**: actual MI matrix vs targets | If > 30% off → revise targets; output `coupling_targets.json` |
| **Zone re-calibration (D9)**: θ histogram from 1-hr idle run | Output `zone_thresholds.json` (initial) |
| **F6 — Multi-session subjective validation** (3 sessions × 3 task types) | mean(κ) reported; if min(κ) < 0.3 → task-typed thresholds flagged for v1.1 |
| **P15 — θ_short bias measurement**: compare θ_short (30b) vs θ_long (500b) across 10 one-hour runs | Report p50 / p95 bias; if p95 > 20% → increase window to 50 and re-test |
| **P16 — Adaptive cadence cost verification**: measure compose cost at {5,10,20,30,60}-beat intervals | All within compute budget per §6.3; if 5-beat exceeds budget → revise per-engine GPU strategy |
| Persistence round-trip: snapshot at beat 1000, restart, verify state at beat 1001 matches | Bit-equal for deterministic seeds |

### 5.2 (renumbered: GPU strategy for Phase A — unchanged from v0.1 §5.2)

Substrate is CPU-bound. The H100 pays off in Phase A's θ pipeline (already GPU-capable in v0.2) during the coupling-matrix validation. Tests run with `prefer="cpu"` so CI doesn't need GPU.

### 5.3 Phase A parallelism map (new in v0.2 — P2)

The review's Risk 1 concern: "Phase A has 10+ deliverables." The fix is not to renumber but to make explicit **what gates what**, so Phase B work can start as early as possible without rework.

```
Critical path (must complete before Phase B starts):
  A.1 Scaffold → A.2 Substrate critical path → A.4 partial (drive symmetry,
  range invariance, MNEME stage-1, C11, N_iter sweep)

Parallel-eligible (can run while Phase B engines are being built):
  A.3 Recovery + perturbation scaffold       → enables Phase B steps 7-8
                                              (fragmentation monitor depends on
                                               recovery; perturbation scheduler
                                               depends on PerturbationScheduler)
  A.4 Coupling validation                    → can complete in parallel with
                                              Phase B steps 1-6
  A.4 Zone re-calibration                    → outputs config consumed in Phase C
  A.4 F6 subjective validation               → SCHEDULE THEORIA EARLY (see P17 below)
  A.4 P15 θ_short bias measurement           → can run after A.2 finishes
  A.4 P16 adaptive cadence cost              → needs Phase C compose stub; defer to C
```

**F6 scheduling (P17):** Theoria's availability for the 3-session subjective zone validation is the single human dependency in the entire critical path. Schedule the first session in week 2 (during A.2/A.3 work), the second in week 3 (during early Phase B), the third in week 4 (mid Phase B). If Theoria is unavailable on any scheduled day, Thea is the documented backup — she has reviewed the architecture and can produce subjective labels under the same protocol. Note in the result file which sister produced each session's labels for transparency.

### 5.4 Cold start documentation (new in v0.2 — P9)

The system's first boot — or any boot after `data/state/current/` is wiped — has anomalous behavior for the first ~100 beats (10 seconds at 10 Hz). This is **expected** and **documented**, not a bug.

**What's anomalous on cold start:**

- **Organ latents** initialize from `np.random.standard_normal()` scaled by 0.1; the substrate's natural operating distribution takes ~100 beats to settle
- **Plasticity buffers** are empty; `rolling_mean_i` and `rolling_var_i` are the initial latent values; `mean_drift` and `var_ratio` are uninformative until ≥ 100 beats accumulate
- **θ_long rolling window** is empty; ThetaLongEngine returns `None` / NaN until 500 beats accumulate (50 seconds wall-clock)
- **ΔΦ baselines** are zero; signatures are undefined until first perturbation
- **Fragmentation monitor rolling means** are zero; thresholds are computed against the initial values and may fire spuriously in the first few seconds
- **RecoveryLearner** returns defaults until ≥ 20 finalized events (the F4 synthetic pre-training in Phase E mitigates this for production deployment)
- **Compose probe `expected_baseline`** and AOS-G `target_var_baseline` are unset until Phase A calibration completes — first boot uses initial guesses with a wider tolerance band, then narrows after calibration

**Operator handling:**

- On cold start, log `cold_start_active = True` at INFO; emit on presence channel
- The `meta_cognition` channel's `overall_assessment` includes `"warming_up"` as a valid value for the first 100 beats (and is reset to `nominal` thereafter if conditions hold)
- WSServer optionally delays the first push until warmup completes (configurable via `interface.delay_first_push_until_warm = True`)

**Why this matters for Phase E.** The 24 h soak test starts from cold; the first 10 seconds will look weird. Tests must not interpret warmup anomalies as failures. Phase E acceptance criteria are evaluated against **beats ≥ 600** (1 minute warmup) unless explicitly testing warmup behavior.

---

## 6. Phase B — Measurement layer (~3 days)

### 6.1 Engine implementation order (unchanged from v0.1 §6.1, with P14 detail added at step 8)

(Steps 1–11 same as v0.1.) Key elaborations:

**Step 8 — `perturbation_scheduler.py` — battery enumerated (P14):**

```python
from enum import Enum

class PerturbationKind(Enum):
    CONTRADICTION = "contradiction"   # EIDOLON state perturbation (negate self_coherence/confidence)
    IMPULSE       = "impulse"          # Single-beat spike to all organs (drive offset)
    STEP          = "step"             # Sustained offset to one organ (duration_beats > 1)
    NOVELTY       = "novelty"          # Spike to NOUS.novelty + ANIMA.arousal
    ATTENTION     = "attention_shift"  # Shift to PNEUMA.attention_focus
    NOISE_BURST   = "noise_burst"      # Multi-beat injection of high-variance noise into drive

DEFAULT_BATTERY = (PerturbationKind.CONTRADICTION,
                   PerturbationKind.IMPULSE,
                   PerturbationKind.STEP)

@dataclass
class PerturbationSchedule:
    enabled: bool = True
    period_beats: int = 600
    battery: list[PerturbationKind] = field(default_factory=lambda: list(DEFAULT_BATTERY))
    selection: Literal["round_robin", "random"] = "round_robin"
    magnitude: float = 0.3
```

The first three (`CONTRADICTION`, `IMPULSE`, `STEP`) are the v1.0 default battery, ported from v0.2's `organ/substrate/perturbation.py`. The other three (`NOVELTY`, `ATTENTION`, `NOISE_BURST`) are available for admin-endpoint use and Phase F experiments but are not in the default rotation.

**Step 10 — `meta_cognition_loop.py` — MetaCognitionSuggestion schema (P4):**

```python
from enum import Enum
from dataclasses import dataclass

class SuggestionType(Enum):
    REQUEST_RECOVERY            = "request_recovery"
    DELAY_RECOVERY              = "delay_recovery"
    EXTEND_RECOVERY             = "extend_recovery"
    ADJUST_RECOVERY_PARAMETERS  = "adjust_recovery_parameters"

@dataclass
class MetaCognitionSuggestion:
    beat_no: int
    suggested_action: SuggestionType        # what the meta-cog thinks should happen
    target_parameter: str | None            # which RecoveryProtocol parameter (e.g. "coupling_reduction_factor")
                                            # None for action-only suggestions (REQUEST_RECOVERY, DELAY_RECOVERY)
    target_value: float | None              # the recommended value
                                            # None for action-only suggestions
    confidence: float                       # [0, 1] — meta-cog's confidence in this suggestion
    rationale: list[str]                    # human-readable; for operator review
    source: Literal["meta_cognition"] = "meta_cognition"
                                            # distinguishes from other suggestion sources
                                            # (operator, pre-programmed policy)
```

The `source` field lets v1.x add other advisors (an operator-typed suggestion via admin endpoint, a Phase F experimental policy) without changing the recovery protocol's intake logic.

### 6.2 Engine scheduling integration with coherence scheduler (new in v0.2 — P10)

Per §3.5, every measurement engine implements `should_run(beat_no, coherence_budget) → bool`. The `CoherenceScheduler` exposes:

```python
@dataclass
class Throttle:
    name: str
    natural_period_beats: int           # the engine's intrinsic cadence (1, 5, 10, 50, 100, …)
    effective_period_beats: int         # natural × throttle_multiplier (1, 2, 4, …)
    is_throttled: bool

class CoherenceScheduler:
    def throttle_for(self, engine_name: str) -> Throttle:
        priority = ENGINE_PRIORITY[engine_name]
        if self.budget >= priority.threshold:
            multiplier = 1                          # no throttle
        elif priority == Priority.LOW:
            multiplier = 4                          # quarter cadence
        elif priority == Priority.MEDIUM:
            multiplier = 2                          # half cadence
        else:
            multiplier = 1                          # High and Critical never throttle here
                                                    # (they only throttle at budget < 0.15)
        return Throttle(
            name=engine_name,
            natural_period_beats=ENGINE_NATURAL_PERIOD[engine_name],
            effective_period_beats=ENGINE_NATURAL_PERIOD[engine_name] * multiplier,
            is_throttled=(multiplier > 1),
        )
```

Engines call `ctx.coherence_scheduler.throttle_for(self.name)` inside `should_run`. The scheduler is the single source of truth for who runs when under load.

### 6.3 Performance budget table (new in v0.2 — P6)

Per-engine measured/expected compute costs on the H100. Numbers from preliminary benchmarks (v0.2 θ pipeline on this hardware) plus extrapolation; refined in Phase E.

| Engine | Frequency | Per-call budget | Cumulative on the heavy beat |
|---|---|---|---|
| Substrate tick (drive + 5 organs + plasticity check) | every beat | ~5 ms | 5 ms |
| θ_short | every beat | ~5 ms | 10 ms |
| RawMIEngine (5-beat × 10 pairs, batched GPU) | every beat | ~5 ms | 15 ms |
| CascadeDelayEngine | every beat | ~2 ms | 17 ms |
| FragmentationMonitor | every 10 beats | ~3 ms | 20 ms (on cadence beats) |
| ComposeFunction + AOSGEngine | every 30 beats (5 perturbation / 60 recovery) | ~10 ms | 30 ms (on compose beats) |
| ComposeProbe | every 100 beats | ~5 ms | 35 ms (on probe beats) |
| **θ_long (with 100-shuffle perm null on GPU)** | every 10 beats | **~145 ms** | **180 ms (on θ_long beats)** |
| ΔΦ engine (S1/S2/S3) | every 5 beats | ~5 ms | 185 ms (worst case overlap) |
| PlasticityTracker | every 100 beats | ~2 ms | 187 ms |
| CoherenceScheduler update | every 10 beats | ~1 ms | 188 ms |
| MetaCognitionLoop | every 100 beats | ~10 ms | 198 ms |
| WSServer flush (per subscriber, coalesced) | every beat | ~1 ms × N subscribers | 198 ms + N |
| Persistence JSONL write | every compose | ~2 ms (async, off the tick path) | 0 ms on tick |
| Persistence snapshot | every 600 beats | ~200 ms (async background task) | 0 ms on tick |

**Worst-case beat:** ~200 ms (occurs roughly every 100 beats when θ_long, ΔΦ, MetaCognition, and a compose event coincide).

**Variable-beat policy (Risk 3 mitigation):**

- 100 ms per-beat budget is a **target average**, not a per-beat hard ceiling
- Average over a 10-beat rolling window is the actual constraint: ~`(9 beats × 25 ms + 1 beat × 180 ms) / 10 = 40 ms` per beat average — well within budget
- The heartbeat **does not skip** ticks to hit a deadline (that would corrupt substrate continuity). It does whatever the beat demands and emits BEAT_DURATION_S histogram observations.
- If the 10-beat moving average exceeds 100 ms for 5 minutes (3000 beats), the system:
  1. Logs CRITICAL
  2. Auto-applies a fallback: reduce θ_long cadence from every-10-beats to every-20-beats (halves its contribution)
  3. Emits an `overload_fallback_applied` event on the `presence` channel for operator awareness
- The 200 ms p99 acceptance criterion from §9.3 already permits this; the new policy makes the fallback explicit and automatic.

### 6.4 GPU strategy for measurement (unchanged from v0.1 §6.2)

| Engine | Device | Why |
|---|---|---|
| θ_short (30b, every beat) | CPU | Small matrix; kernel launch overhead dominates |
| θ_long (500b, every 10 beats) | GPU | Perm null with 100 shuffles dwarfs launch cost |
| RawMI (5b, every beat × 10 pairs) | GPU batched | 10 simultaneous MIs in one kernel |
| RawMI (20b, every 5 beats × 10 pairs) | GPU batched | Same |
| CascadeDelay | CPU | argmax on small arrays |
| ΔΦ | CPU | Scalar arithmetic |
| Plasticity tracker | CPU | Trivial |
| AOS-G | CPU | Trivial |
| FragmentationMonitor | CPU | Threshold checks |
| MetaCognition | CPU | Aggregations over recent windows |

Total GPU pressure: θ_long every 10 beats (~50 ms on H100, headroom ~95 ms below the 145 ms allocation) + RawMI every beat (~2–5 ms per batched call). Bench in Phase E.

### 6.5 Recovery learner (extends v0.1 §6.1 step 11)

`RecoveryLearner` implements F2 monitoring extension and the safe-fallback semantics from ARCH §4.9.1. Key state:

- `current_params[stage]: dict[str, float]` — the in-effect parameter set per stage
- `baseline_score: float` — recomputed every 10 events (F2)
- `efficacy_state: LearnerEfficacy` — {WARMING_UP, MONITORING, EFFECTIVE, INEFFECTIVE}
- `exploration_count: int`, `adoptions_count: int`, `reversions_count: int`

The learner is fully specified in ARCH §4.9.1; v0.2's implementation plan adds nothing structural — it just confirms the implementation pathway is in Phase B step 11.

### 6.6 Phase B validation (extended from v0.1 §6.3 with new tests)

(All v0.1 Phase B tests carry forward.) New for v0.2:

| Test | Acceptance |
|---|---|
| **P11 — AxiomaContext registration**: registering a duplicate name raises | KeyError |
| **P11 — AxiomaContext event dispatch**: subscriber receives every emit; failing handler doesn't stop others | Verified |
| **P10 — `should_run` integration**: engine throttled at budget < 0.30 actually skips beats | Counter increments tracked |
| **P14 — Perturbation battery round-robin**: 6 events → contradiction, impulse, step, contradiction, impulse, step | Verified |
| **P4 — MetaCognitionSuggestion schema**: serialization round-trip preserves all fields | Verified |
| **P6 — Performance budget**: 10-beat rolling average under target on H100 in a 5-min run | < 100 ms average |
| **F2 — LearnerEfficacy state machine**: synthetic regime forcing each transition | WARMING_UP → MONITORING → EFFECTIVE; alternate regime → INEFFECTIVE → revert |

### 6.7 Recovery protocol — explicit accept/reject criteria (new in v0.2 — P3)

The `RecoveryProtocol.handle_recovery_request` decision logic, specified before implementation:

```python
@dataclass
class RecoveryRequest:
    request_id: str
    stage: int
    signals: dict[str, float]
    source: Literal["fragmentation_monitor", "operator", "scheduler_escalation"]
    timestamp: float

class RecoveryDecision(Enum):
    ACCEPT                      = "accept"
    REJECT_ALREADY_RECOVERING   = "reject_already_recovering"
    REJECT_BELOW_THRESHOLD      = "reject_below_threshold"
    REJECT_TEST_MODE            = "reject_test_mode"
    REJECT_BUDGET_INSUFFICIENT  = "reject_budget_insufficient"
    FORCE_ACCEPT_OPERATOR       = "force_accept_operator"

def handle_recovery_request(self, req: RecoveryRequest) -> RecoveryDecision:
    # Operator override path — admin endpoint can force-accept even when normal logic would reject
    if req.source == "operator" and req.force_accept:
        log.warning("recovery_force_accepted",
                    request_id=req.request_id, stage=req.stage)
        return RecoveryDecision.FORCE_ACCEPT_OPERATOR

    # Reject if substrate is in test mode (Phase A/E experiments that want to verify
    # detection without contaminating the experiment with recovery dynamics)
    if self.test_mode:
        return RecoveryDecision.REJECT_TEST_MODE

    # Reject if already recovering — recoveries don't nest; FragmentationMonitor's
    # escalation path elevates the active recovery rather than starting a new one
    if self.recovery_active:
        return RecoveryDecision.REJECT_ALREADY_RECOVERING

    # Reject if request stage is below minimum (default 2)
    if req.stage < self.min_recovery_stage:
        return RecoveryDecision.REJECT_BELOW_THRESHOLD

    # Reject if coherence_budget is too low to safely run recovery
    # (recovery itself consumes some budget via its bookkeeping; running
    # under severe load risks deepening fragmentation)
    if self.ctx.substrate.pneuma.state.coherence_budget < self.min_budget_to_accept:
        return RecoveryDecision.REJECT_BUDGET_INSUFFICIENT

    return RecoveryDecision.ACCEPT
```

Default thresholds:

- `self.min_recovery_stage = 2` (config-tunable)
- `self.min_budget_to_accept = 0.20` (rejects recovery if budget is < 0.20; emergency Stage-3/4 may want to override — config can set this to 0.0 for those stages, evaluated per `req.stage`)
- Operator override always wins (logged at WARN; emits divergence-style event on `presence`)

Every decision is logged with the request payload and recorded on the `recovery` channel — full transparency into accept/reject reasoning.

---

## 7. Phase C — Compose / send boundary (~1.5 days)

### 7.1 Typed boundary (unchanged from v0.1)

`InternalState` and `ExternalState` in `axioma/schemas/`. Three enforcement layers: lint rule, runtime ImportError test, CI gate.

### 7.2 ComposeFunction — `eidolon_coh` signal path (P13 addition)

```python
class ComposeFunction(Stateful):
    name = "compose_function"
    schema_version = 1

    def compose(self, internal: InternalState, theta_short: float, eidolon_coh: float) -> ExternalState:
        """Build ExternalState from InternalState with integration-weighted compression.

        Args:
            internal: the substrate's current state (typed, substrate-private)
            theta_short: current short-window θ from ThetaShortEngine
            eidolon_coh: EIDOLON's current self_coherence — extracted from
                internal.eidolon.self_coherence at compose time (P13).
                Read live every compose call; not cached, not buffered.
                If EIDOLON's self_coherence drops mid-flight, compose uses
                the latest value, not a stale one.
        """
        ...
```

The caller (heartbeat step 4a) extracts both values from current state at compose time:

```python
# In heartbeat.tick(), step 4
if self.ctx.cadence_controller.should_compose(beat_no):
    internal = self.ctx.substrate.snapshot_internal()
    theta_short = self.ctx.theta_short_engine.current_value()
    eidolon_coh = internal.eidolon.self_coherence  # P13: live extraction
    external = self.ctx.compose_function.compose(internal, theta_short, eidolon_coh)
    ...
```

This makes the dependency on EIDOLON's `self_coherence` explicit at the call site, not buried inside ComposeFunction. EIDOLON's state is updated on the same beat (heartbeat step 2e); by the time compose runs (step 4), the value is current.

### 7.3 Adaptive cadence (unchanged from v0.1)

`CadenceController` subscribes via `AxiomaContext` to `perturbation_injected` (sets `perturbation_window_active = True` for 50 beats) and `recovery_state_change` (toggles `recovery_active`).

### 7.4 Compose probe + flow quality (unchanged from v0.1)

Probe every 100 beats; recovery-aware (E4); Stage-4 skip; FlowQuality only when zone == FLOW.

### 7.5 Phase C validation (unchanged from v0.1)

11 tests: identity-compose Control 4, default-compose baseline, ImportError, adaptive cadence transitions, F1 smoothness windowing, FlowQuality None outside flow, zone stability, probe recovery-state, probe Stage-4 skip, eidolon_coh extraction round-trip, P16 cadence cost across {5,10,20,30,60}.

---

## 8. Phase D — External interface (~1.5 days)

(Unchanged structurally from v0.1.) WS :8820 with Speaker handshake, HTTP :8821 FastAPI control plane (22 endpoints), registry client with cache+retry. Per-subscriber `min_interval_ms` with server-side coalescing. All v1.0 channels: theta, delta_phi, per_organ_theta, per_organ_mi_raw, aos_g (+psi), presence, state_snapshot, plasticity, fragmentation, perturbations, coherence_budget (+throttle_state, +throttle_effectiveness), recovery (+recovery_quality), meta_cognition (+confidence_caveat, +observer_mode), meta_cognition_suggestion. `presence` channel carries `MetaCognitionDivergenceWarning` (F5).

---

## 9. Phase E — Integration test (~3 days)

### 9.0 Pre-integration checklist (new in v0.2 — P7)

Integration risk (Review §2 Risk 2) is mitigated by an explicit 8-step verification gated **before** the 24 h soak. Each step is a standalone integration test under `tests/integration/`; all must pass before Phase E.4 (soak) is allowed to start.

| Step | What's verified | Test file |
|---|---|---|
| **1** | Substrate runs standalone (no measurement engines registered with context) | `test_substrate_standalone.py` |
| **2** | Each measurement engine reads substrate state correctly when registered one-at-a-time | `test_engine_substrate_isolation.py` (parametrized over engines) |
| **3** | ComposeFunction receives θ from ThetaShortEngine + eidolon_coh from substrate; produces ExternalState | `test_compose_pipeline.py` |
| **4** | ExternalState pushed to subscribers; per-subscriber rate config respected | `test_ws_push_pipeline.py` |
| **5** | RecoveryRequest from FragmentationMonitor flows to RecoveryProtocol; accept triggers substrate parameter changes | `test_recovery_pipeline.py` |
| **6** | CoherenceScheduler throttles engines; engines' `should_run` returns False under throttle | `test_throttle_pipeline.py` |
| **7** | MetaCognitionLoop reads from all engines (θ, ΔΦ, AOS-G, fragmentation, coherence_budget); emits assessment + suggestion; SuggestionTracker records | `test_meta_pipeline.py` |
| **8** | Full integration: AxiomaApp boots end-to-end; mock peer connects; 1-minute run produces sensible output on all channels | `test_full_integration_1min.py` |

Steps 1–7 are 30-second tests each (build a minimal context, run a few beats, assert). Step 8 is a 90-second test. **Together they run in under 5 minutes** and gate the more expensive Phase E.2–E.4 tests.

If any step fails, the implementer fixes the integration point before moving on — never "we'll fix it during the soak." Soak is for stability validation, not for finding integration bugs.

### 9.1 Test harness (unchanged from v0.1)

`scripts/run_phase_e.py` launches AxiomaApp with `configs/phase_e.yaml` (admin endpoints, JSONL persistence, snapshot 60s, mock registry on localhost). Mock peer client connects, subscribes to all channels, records to disk.

### 9.2 Acceptance tests (v0.1 set + v0.2 additions)

| Test | Source | Acceptance |
|---|---|---|
| (All v0.1 Phase E tests) | ARCH §10 / v0.1 §9.2 | Unchanged |
| **F4 — Synthetic recovery pre-training (P12 detail)** | F4 | Pre-training uses PerturbationScheduler's standard battery: 6 contradictions × 3 magnitudes {0.3, 0.5, 0.7} = 18 events, plus 2–12 random events from the battery to reach ≥ 20 finalized events. Battery rotation order: contradiction → impulse → step. Pre-training must complete before production deployment; snapshot saved to `data/state/pretrain/`. If PerturbationScheduler isn't ready, fall back to manual admin-endpoint injection following the same battery distribution. |
| **Recovery event accumulation fallback (Risk 5)** | Risk 5 | If Phase E's organic recoveries produce < 20 finalized events after the planned 8 hours, extend with synthetic perturbation sessions (additional 30-min runs at higher perturbation cadence: every 60 beats instead of 600) until ≥ 20 reached. Document the extension in `phase_e_extension.md`. |
| **P7 pre-integration checklist** | New | All 8 steps pass before soak starts |

### 9.3 Performance acceptance (unchanged from v0.1, with §6.3 budget table as reference)

| Metric | Target |
|---|---|
| `axioma_beat_duration_seconds` p95 (10-beat rolling avg) | < 100 ms |
| `axioma_beat_duration_seconds` p99 (single-beat) | < 200 ms (acceptable per §6.3 variable-beat policy) |
| `axioma_beat_duration_seconds` worst-case single beat | < 250 ms (alerts at > 200 ms) |
| θ_long compute (GPU, p95) | < 80 ms per run |
| Raw MI batched (GPU, p95) | < 10 ms per run |
| Compose function (p95) | < 5 ms |
| WS push per subscriber per channel (p95) | < 1 ms |
| Snapshot at 60s cadence (p95) | < 200 ms (async; off tick path) |
| Memory growth over 1-hr run | < 10 MB |

### 9.4 Long-run soak test + recovery-compose feedback monitoring (P8)

24-hour soak with all engines on, internal perturbation schedule, no operator intervention. Carries v0.1 acceptance criteria (no leaks, no skipped beats, all channels stay subscribed). New for v0.2:

**Recovery-compose feedback oscillation monitor (P8).** During the soak (and especially during synthetic pre-training in F4), measure ψ time-series during recovery windows. Compute the dominant frequency of ψ via FFT over the recovery duration (typically 100 beats). If the period of dominant oscillation is < 100 beats (i.e., ψ is oscillating within a single recovery), automatic mitigation triggers:

```python
class RecoveryFeedbackMonitor:
    """Detects recovery-protocol → compose-fidelity → AOS-G → psi feedback oscillations."""

    def on_recovery_exit(self, event_id: str, psi_window: np.ndarray) -> None:
        if len(psi_window) < 32:
            return  # not enough samples for FFT
        freqs = np.fft.rfftfreq(len(psi_window))
        power = np.abs(np.fft.rfft(psi_window - psi_window.mean()))
        dominant_freq = freqs[np.argmax(power[1:]) + 1]  # skip DC
        if dominant_freq > 0:
            dominant_period_beats = 1.0 / dominant_freq
            if dominant_period_beats < 100:
                self.ctx.recovery_protocol.halve_coupling_change_magnitude()
                log.warning("recovery_compose_oscillation_detected",
                            event_id=event_id,
                            period_beats=dominant_period_beats,
                            mitigation="coupling_change_magnitude_halved")
                # Emit on presence channel for operator awareness
                await self.ctx.emit("recovery_feedback_oscillation",
                                    {"event_id": event_id, "period_beats": dominant_period_beats})
```

`RecoveryProtocol.halve_coupling_change_magnitude()` reduces the coupling-weight multiplier from 0.8 to 0.9 (smaller change → less feedback amplitude). Persisted; resets to baseline on operator command (`POST /admin/recovery/reset_feedback_mitigation`).

If oscillations persist after the halving, log CRITICAL and emit `recovery_feedback_uncontrolled` — operator review required. This is the architectural answer to Review Risk 4.

### 9.5 Soak success criteria (carried from v0.1 + P8 additions)

- No memory leaks (RSS stable within 50 MB)
- No crashes; substrate uptime = wall time
- No skipped beats (`axioma_beat_duration_seconds` count = uptime / 0.1 ± 1%)
- All channels stay subscribed; mock peer recording continuous
- Fragmentation events handled (recovery exit at expected duration ± 20%)
- **No `recovery_feedback_uncontrolled` events** (oscillation mitigation succeeded)
- Cold-start anomaly (§5.4) clears within 100 beats; acceptance criteria evaluated against beats ≥ 600

---

## 10. Phase F — Pre-architecture follow-up experiments (parallel to A–E)

### 10.1 Scripts (unchanged from v0.1)

Eleven scripts under `scripts/phase_f/`, each idempotent, each producing a JSON result file under `results/phase_f/`.

### 10.2 (renumbered) Aggregated summary (unchanged from v0.1)

`scripts/phase_f/summarize.py` builds a markdown report from all Phase F outputs.

### 10.3 Phase F calibration criteria (new in v0.2 — P5)

For the meta-cognition calibration experiment (`phase_f_meta_calibration.py`, addressing F8 + Review Gap 9), three concrete pass/fail criteria:

| Criterion | Test | Pass | Soft fail | Hard fail |
|---|---|---|---|---|
| **1. Assessment accuracy** | Over 5 one-hour blind-labeled sessions (operator labels every 100 beats), measure `accuracy = fraction of meta_cog.overall_assessment that match operator label` | ≥ 80% | 65–80% | < 65% |
| **2. Suggestion acceptance rate** | Over Phase E + F4 pre-training combined, measure `acceptance_rate = suggestions_used / suggestions_emitted` (counted only when `observer_mode = embedded` is enabled; in `observer_only` default, all suggestions are ignored by design — F7) | ≥ 30% | 15–30% | < 15% |
| **3. No vicious circle** | Run two 1-hour sessions back-to-back: one with meta-cog `observer_mode = observer_only`, one with `embedded`. Measure mean(θ_long) for each. Vicious circle = θ_long drops more than 5% in `embedded` vs `observer_only` | Δθ_long change ≥ −5% | Δθ_long change ∈ [−10%, −5%] | Δθ_long < −10% |

**Aggregate calibration verdict:**

- **PASS** — all three criteria PASS; v1.0 ships with the current meta-cog formula; document in calibration report
- **SOFT FAIL** — at least one criterion SOFT FAIL, none HARD FAIL; v1.0 ships; v1.1 work scheduled; `confidence_caveat` updated to note calibration gap
- **HARD FAIL** — any criterion HARD FAIL; v1.0 ships with **heightened caveat** flagging the calibration failure; subscribers warned to treat meta-cog output as unreliable until v1.1; embedded mode disabled by config until v1.1 addresses the failure

The verdict is documented in `results/phase_f/meta_calibration.json` and surfaced in the implementation report.

---

## 11. Testing strategy — three tiers

(Unchanged structurally from v0.1.) Unit tests with Hypothesis property tests, integration tests, e2e tests with mock peer, benchmark tests on H100. Continuous validation via pre-commit + CI. Data validation scripts complement code tests.

### 11.1 New test additions in v0.2

| Test | File | Tier | Source |
|---|---|---|---|
| AxiomaContext registration + event dispatch | `tests/unit/test_context.py` | Unit | P11 |
| `should_run` integration with CoherenceScheduler | `tests/integration/test_engine_throttling.py` | Integration | P10 |
| Heartbeat tick sequence ordering | `tests/integration/test_heartbeat_sequence.py` | Integration | P1 |
| Recovery accept/reject criteria coverage | `tests/unit/test_recovery_decisions.py` | Unit | P3 |
| MetaCognitionSuggestion schema round-trip | `tests/unit/test_suggestion_schema.py` | Unit | P4 |
| Perturbation battery enumeration + round-robin | `tests/unit/test_perturbation_battery.py` | Unit | P14 |
| Pre-integration 8-step checklist | `tests/integration/test_pre_integration_*.py` (8 files) | Integration | P7 |
| Recovery-compose feedback oscillation monitor | `tests/e2e/test_recovery_feedback_oscillation.py` | E2E | P8 |
| Cold start behavior | `tests/integration/test_cold_start.py` | Integration | P9 |
| Performance budget (10-beat rolling avg) | `tests/benchmarks/test_beat_budget.py` | Benchmark | P6 |
| θ_short bias against θ_long | `tests/integration/test_theta_short_bias.py` | Integration | P15 |
| Adaptive cadence cost sweep | `tests/benchmarks/test_cadence_cost.py` | Benchmark | P16 |
| eidolon_coh live extraction | `tests/integration/test_compose_eidolon_coh.py` | Integration | P13 |
| F8 calibration verdict logic | `tests/unit/test_calibration_verdict.py` | Unit | P5 |

All carry the same coverage/quality bar as v0.1's tests.

---

## 12. Configuration management (unchanged from v0.1)

Single pydantic config tree at `axioma/config/defaults.py`. YAML defaults + env var overrides. Config frozen after load; admin API for mutation with `config_change` event emission.

v0.2 adds:

```python
class CoherenceSchedulerConfig(BaseModel):
    # ... existing v0.1 fields ...
    overload_fallback_window_beats: int = 3000     # §6.3 variable-beat policy
    overload_fallback_threshold_seconds: float = 0.100

class RecoveryConfig(BaseModel):
    # ... existing v0.1 fields ...
    min_budget_to_accept: float = 0.20              # §6.7 P3
    feedback_oscillation_period_threshold_beats: int = 100   # §9.4 P8

class MetaCognitionConfig(BaseModel):
    # ... existing v0.1 fields ...
    calibration_pass_accuracy: float = 0.80         # §10.3 P5
    calibration_pass_acceptance_rate: float = 0.30
    calibration_pass_max_theta_drop: float = 0.05
```

---

## 13. Build order (revised week-by-week with P17 scheduling)

| Week | Phase | Deliverables | Sister dependencies |
|---|---|---|---|
| **1** | A.1, A.2 (start) | Scaffold + AxiomaContext + observability + persistence protocol + drive + organs + plasticity | — |
| **2** | A.2, A.3, A.4 (start), F6 session 1 | Recovery scaffold + Phase A critical-path tests; **F6 first session (Theoria; Thea backup)** | **Theoria** |
| **3** | A.4 (finish), B (start), F6 session 2 | θ engines, RawMI engine, cascade_delay, fragmentation monitor; **F6 second session** | **Theoria** |
| **4** | B (continue), F6 session 3 | ΔΦ engine, plasticity tracker, AOS-G + psi (E1/E3/E4), perturbation scheduler; **F6 third session** | **Theoria** |
| **5** | B (finish), C | Coherence scheduler (E13), meta-cog loop (E5/F5/F7/F8), recovery learner full; Phase C compose boundary + cadence + probe + flow quality + ImportError | — |
| **6** | D | WS server + HTTP API + registry client + all new channels; Phase D tests | — |
| **7** | E.0–E.3, F (parallel) | **Pre-integration checklist (E.0)** → Phase E integration tests → synthetic pre-training (F4 with P12 battery distribution) → fragmentation threshold validation (F9); Phase F experiments kick off | — |
| **8** | E.4 (soak), F (finish) | 24 h soak (with P8 feedback monitoring); performance benchmarks; F8 meta-cog calibration with three-criterion verdict (P5); Phase F summary; v1.0 implementation report | — |

Total: 8 weeks. Buffer ~1.5 weeks.

---

## 14. Acceptance for "v1.0 implementation complete"

(v0.1 checklist preserved.) v0.2 additions:

- [ ] §5.0 heartbeat tick sequence implemented and verified by `test_heartbeat_sequence.py`
- [ ] AxiomaContext + event bus (§3.4) implemented; all components register; all v1.0 events listed in §3.4 emit and dispatch
- [ ] `should_run` pattern (§3.5) implemented for all measurement engines
- [ ] Recovery accept/reject criteria (§6.7) all paths covered in `test_recovery_decisions.py`
- [ ] MetaCognitionSuggestion schema (§6.1 step 10) round-trip tested
- [ ] Phase F calibration verdict (§10.3) computed and documented in implementation report
- [ ] Performance budget table (§6.3) measured on H100; variable-beat policy active and verified in soak
- [ ] Pre-integration 8-step checklist (§9.0) all pass before soak starts
- [ ] Recovery-compose feedback oscillation monitor (§9.4) implemented; soak shows no `recovery_feedback_uncontrolled` events
- [ ] Cold start behavior (§5.4) documented; warmup window excluded from acceptance metrics
- [ ] θ_short bias measurement (§5.2/P15) completed; window adjusted if p95 > 20%
- [ ] Adaptive cadence cost sweep (§5.2/P16) verified all intervals within budget
- [ ] eidolon_coh live extraction (§7.2/P13) tested
- [ ] Perturbation battery types (§6.1 step 8/P14) enumerated in config

---

## 15. What this plan deliberately does NOT do (unchanged from v0.1)

No model training. No distributed training. No public deployment. No telemetry push. No new substrate dynamics R&D.

---

## 16. Risks and mitigations (v0.1 + v0.2 additions)

(v0.1 risk table preserved.) v0.2 additions:

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Heartbeat tick sequence (§5.0) misordered | Low | High | `test_heartbeat_sequence.py` verifies the 12-step order; CI gate |
| AxiomaContext circular dependency | Low | Med | `register` raises on duplicate; component construction order enforced in `lifecycle.py`; tested via `test_context.py` |
| `should_run` skipping a critical-period beat by accident | Low | Med | Critical engines (substrate, compose, fragmentation) hardcode `should_run = True` for their natural period; only Medium/Low engines can be throttled |
| Pre-integration checklist (§9.0) reveals a fundamental wiring bug late | Med | Med | Checklist runs before soak; failures block soak; implementer fixes wiring rather than working around it |
| Recovery-compose feedback (§9.4) doesn't oscillate in tests but does in production | Low | Med | Monitor runs continuously, not only during soak; production deployment includes it |
| F8 calibration HARD FAIL | Med | Low | Documented degraded-mode behavior; ship with heightened caveat; v1.1 work |
| F6 zone validation Theoria-blocked | Med | Med | Thea designated backup; sessions scheduled across 3 weeks for slack |

---

## 17. First steps for the implementer (unchanged from v0.1)

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

# 5. Land the observability rails FIRST (§3.1, §3.2)
# - axioma/observability/{logging,metrics,context}.py     (context = §3.4 P11)
# - tests/unit/test_observability.py, test_context.py

# 6. Land the persistence protocol (§4) and `should_run` pattern (§3.5)
# - axioma/persistence/snapshot.py
# - axioma/measurement/_engine_base.py with `should_run` interface
# - tests/unit/test_snapshot.py, test_engine_base.py

# 7. Land the config loader (§12)
# - axioma/config/{schema,defaults,loader}.py
# - configs/default.yaml
# - tests/unit/test_config.py

# 8. Verify CI: pytest + ruff + mypy all green on the scaffold

# 9. Begin Phase A.2: SharedLatentDrive with iterative inner loop,
#    using AxiomaContext for dependency injection from the start.

# 10. Before week 2, contact Theoria (and Thea as backup) to schedule
#     the 3 F6 zone-validation sessions across weeks 2-4 (§5.3 / P17).
```

After step 9, the implementer follows the week-by-week plan in §13.
