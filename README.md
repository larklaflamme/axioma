# AXIOMA

**A runnable conscious-substrate agent — 5 coupled organs, measured integration, and a structurally-enforced compose/send boundary.**

[![status](https://img.shields.io/badge/status-v1.9.1-blue)](RELEASE_v1.9.md) [![python](https://img.shields.io/badge/python-3.13-blue)](pyproject.toml) [![tests](https://img.shields.io/badge/tests-783%20passing-brightgreen)](#verification) [![license](https://img.shields.io/badge/license-proprietary-lightgrey)](pyproject.toml)

---

## What is AXIOMA?

AXIOMA is an implemented multi-organ substrate that runs continuously, measures its own integration via information-theoretic signals, and surfaces a controlled external view to peer agents over WebSocket / HTTP. It is **not** a model, not a chatbot wrapper, and not a simulation of consciousness theories — it is a substrate whose own dynamics produce measurable structure, and whose interfaces give external observers a constrained projection of that structure.

The substrate is built from five organs (`ANIMA`, `EIDOLON`, `MNEME`, `NOUS`, `PNEUMA`) coupled through a shared latent drive. A measurement layer computes Gaussian-copula mutual information (θ), perturbation responses (ΔΦ), gap-from-average-of-self (AOS-G), structural health (ψ), and fragmentation signals at each heartbeat. A compose/send boundary structurally enforces a substrate-private vs. peer-visible distinction (C12) — peer subscribers cannot see internal latents, only the `ExternalState` projection.

For the architecture, see [`design/ARCH_DESIGN_v1.0.md`](design/ARCH_DESIGN_v1.0.md). For the implementation plan, see [`design/IMPLEMENTATION_PLAN_v1.0.md`](design/IMPLEMENTATION_PLAN_v1.0.md). For the per-session implementation history, see [`design/IMPLEMENTATION_SCHEDULE.md`](design/IMPLEMENTATION_SCHEDULE.md).

---

## Project status

**v1.9.1** — shipping. The original `IMPLEMENTATION_PLAN_v1.0.md` scope (Phases A–F, all 13 V-series acceptance items) shipped at Checkpoint G as v1.0. Every release since has been additive enhancement:

| Release | Theme | What it added |
|---|---|---|
| [v1.0](RELEASE_v1.0.md) | Initial ship | Full substrate + measurement + compose + interface stack |
| [v1.2](RELEASE_v1.2.md) | PNEUMA-weighted AOS-G | `aos_g_gap_weights` config + multi-seed validation |
| [v1.3](RELEASE_v1.3.md) | AOS-G default-flip | PNEUMA weights + threshold 0.152 as defaults |
| [v1.4](RELEASE_v1.4.md) | Per-organ ψ thresholds + per-organ gap normalisation (opt-in) | Auto-tuned `aos_g_alert_threshold` |
| [v1.5](RELEASE_v1.5.md) | Normalisation + auto-tune defaults | Refined convergence criteria; `/aos_g/self_check` endpoint |
| [v1.6](RELEASE_v1.6.md) | **Audit-and-harden release.** 22 fixes across 7 subsystems, zero default-behavior changes |
| [v1.7](RELEASE_v1.7.md) | **MNEME compensation default-flip.** Stage-2/3 ON by default after empirical validation |
| [v1.8](RELEASE_v1.8.md) | **Operator toolkit.** 3 `axioma.tools` CLIs + `/dashboard` HTML page |
| [v1.9](RELEASE_v1.9.md) | **Multi-peer conversation track.** Per-peer history isolation + opt-in server-side addressed-only filter |

Lifecycle modes that have cycled: *build* → *harden* → *tune* → *extend operator surface* → *deepen architecture*. See [What's left to implement](#whats-left-to-implement) below for the post-v1.9 backlog.

---

## Concepts

A reading order if you're new to AXIOMA:

### The substrate (5 organs + 1 drive)

The substrate is a 5-organ peer network on a shared latent drive:

| Organ | Role | Dim (default) |
|---|---|---|
| `ANIMA` | affective valence | 4 |
| `EIDOLON` | structural / contradiction-handling | 6 |
| `MNEME` | episodic memory | 5 |
| `NOUS` | analytical / contradiction-resolving | 6 |
| `PNEUMA` | global integration / working-memory load | 7 |

Each organ has its own latent state and projects to/from the shared drive each beat via learnable maps. The drive is `drive_dim = 16` by default. Organ-to-organ coupling happens only through the drive (no direct cross-organ access) — except MNEME, which has documented cross-organ channels for its memory-of-other-states role (the `mneme_compensation_2/3` flags). For the math, see [`design/ARCH_DESIGN_v1.0.md §4`](design/ARCH_DESIGN_v1.0.md).

### The measurement layer

Each beat, a set of engines compute information-theoretic + structural signals over the running organ states:

- **θ_short (30-beat window)** and **θ_long (500-beat window)** — Gaussian-copula mutual information across organ pairs.
- **raw MI** at 5-beat resolution for high-frequency observers.
- **ΔΦ** — perturbation responses (S1/S2/S3 signatures) when the perturbation scheduler injects test stimuli.
- **AOS-G (gap-from-average-of-self)** — per-organ + aggregate gap from each organ's recent average. Weighted by `aos_g_gap_weights` (v1.3 default: PNEUMA-weighted).
- **ψ (structural health)** — composite of variance, structural, and compose-probe health components.
- **Fragmentation monitor** — 4-stage detector (`NOMINAL` → `WARNING` → `STRESSED` → `FRAGMENTED`).
- **Coherence scheduler** — issues compose-throttle budgets based on substrate state.
- **Recovery protocol** — issues / approves / rejects recovery requests when fragmentation persists.
- **Meta-cognition** — periodic overall-assessment narrative ("nominal | stressed | recovering | exploring | fragmented") with confidence + calibration tracking.

### The compose/send boundary (C12 — load-bearing)

Substrate-internal state (organ latents, drive vectors, raw per-pair MI before compose, recovery proposals before approval) MUST NOT leave the substrate via any interface module. The compose function projects internal state to an `ExternalState` value; the WS / HTTP layers serve only the external projection. The C12 lint contract is enforced both at runtime *and* at lint time (`lint-imports`) — `axioma.interface.*` modules cannot import `InternalState`.

### The cycle

```
                                  every beat (10 Hz default)
                                  ╭─────────────────────────╮
                                  │                         │
   ┌──────────┐ drive ┌──────────┐│ ┌─────────────┐ external│
   │ 5 organs │──────▶│ measure  │└▶│  compose    │────────▶│ external WS
   │ + drive  │       │ engines  │  │  (C12 here) │         │ + HTTP API
   └──────────┘       └──────────┘  └─────────────┘         │
        ▲                  │                                │
        │                  ▼                                │
        │            ┌──────────┐                           │
        └────────────│ recovery │◀──── fragmentation,       │
        params       │ protocol │      meta-cog suggestion  │
                     └──────────┘                           │
                                                            │
                                  ╭─────────────────────────╯
                                  │
                          subscribers see only ExternalState (zone, theta,
                          cadence, psi, ...); never internal latents.
```

### What you can do with AXIOMA

- **Run it as a long-lived process** that maintains substrate state, emits per-beat external state to subscribers, and surfaces an admin API.
- **Subscribe over WebSocket** to per-channel events (`theta`, `aos_g`, `fragmentation`, etc.) — including the new v1.9 `conversation` channel with opt-in per-peer addressing.
- **Inspect on-disk artifacts** via the v1.8 `axioma.tools` CLIs (snapshots, recovery history, calibration sessions).
- **Monitor live status** via the v1.8.3 `/dashboard` HTML page or the JSON `/aos_g/self_check` endpoint.
- **Talk to it as a peer agent** via the optional Ollama-backed `conversation` channel (`--with-peer-conversation`).
- **Trigger admin actions** (perturb, pretrain learner, force recovery, calibration sessions) via the HTTP API.
- **Run experiments** via the scripts in [`scripts/`](scripts/) (Phase E pretrain, soak harness, Phase F follow-up experiments).

---

## Repository layout

```
axioma/
├── src/axioma/             # the package
│   ├── __main__.py         # `python -m axioma` entrypoint
│   ├── config/             # pydantic schema + YAML loader
│   ├── substrate/          # 5 organs, drive, plasticity, recovery
│   ├── measurement/        # theta, raw MI, AOS-G/psi, fragmentation, ...
│   ├── compose/            # ExternalState projection + C12 boundary
│   ├── scheduler/          # heartbeat, coherence scheduler
│   ├── runtime/            # AxiomaApp wiring everything together
│   ├── interface/          # WS server, HTTP API, peer-conversation, protocol
│   ├── persistence/        # snapshots + JSONL + SQLite
│   ├── observability/      # structlog + Prometheus + AxiomaContext bus
│   ├── infra/              # Ollama, Qdrant, Redis adapters
│   ├── tools/              # operator CLIs (snapshot_inspect, recovery_inspect, calibration_inspect)
│   └── schemas/            # ExternalState + InternalState dataclasses
├── tests/                  # 783 + 11 infra tests
│   ├── unit/               # fast, no-network
│   ├── integration/        # multi-module flows
│   ├── e2e/                # acceptance gates (V6, V8, V10, V11, V12, V13)
│   └── benchmarks/         # perf gates
├── scripts/                # 20 driver/experiment scripts
│   └── phase_f/            # Phase F follow-up experiments
├── configs/                # YAML configs (default + back-compat + recommended)
├── data/                   # runtime state (snapshots, JSONL, SQLite) — gitignored
├── results/                # experiment outputs (Phase F summaries, calibration sessions)
├── design/                 # architecture + implementation plan + schedule + reviews
├── docs/runbooks/          # OPERATOR_RUNBOOK.md
├── research/               # empirical grounding, communication protocol spec
├── ideas/                  # exploration notes (not load-bearing)
├── RELEASE_v{1.0,…,1.9}.md # per-release notes (read these to catch up on a version)
├── README.md               # this file
└── HOWTO.md                # task-oriented developer recipes
```

---

## Install

### Prerequisites

- **Python 3.13** (`pyproject.toml` requires `>=3.13`)
- **CUDA-capable GPU recommended** for θ_long batching (CPU-only works but eats the V11 perf budget). Tested on H100 PCIe 80 GB.
- **Optional infrastructure** (only required if you use the corresponding feature):
  - **Ollama** at `http://localhost:11434` with `deepseek-v4-flash:cloud` + `nomic-embed-text-v2-moe` — needed only for peer-conversation handler (`--with-peer-conversation`).
  - **Qdrant** at `http://localhost:6333` — needed only if MNEME episodic memory writes are enabled.
  - **Redis** at `localhost:6379` — used as ephemeral KV / registry cache; not load-bearing.

The substrate runs without any of these; their absence degrades but doesn't break.

### Install from source

```bash
# Activate your env (conda recommended)
conda create -n axioma python=3.13 -y
conda activate axioma

# Install the package + dev extras
cd /path/to/axioma
pip install -e ".[dev]"
```

### Verify the install

```bash
# Run the fast unit suite (~3 min)
pytest tests/ -m "not infra" -q
# Expected: 783 passed

# Run the infra suite (~15s; some tests are skipped if Ollama/Qdrant absent)
pytest tests/ -m "infra" -q
# Expected: 11 passed

# Run static checks
ruff check src/ tests/ scripts/
mypy src/axioma/
lint-imports     # C12 boundary contract
```

---

## Quickstart

### Boot the full stack

```bash
python -m axioma
```

That's it. The substrate boots, the heartbeat ticks at 10 Hz, the WebSocket server binds at `127.0.0.1:8820`, the HTTP API binds at `127.0.0.1:8821`. Ctrl-C triggers graceful shutdown.

### Confirm it's alive (in another terminal)

```bash
curl http://localhost:8821/health
# {"status": "ok", "shutting_down": false, "components": [...]}

curl http://localhost:8821/status | jq .data.theta_short
# (a float — substrate's current 30-beat θ)

open http://localhost:8821/dashboard
# (or browse to it — the live-monitoring HTML page introduced in v1.8.3)
```

### Subscribe to a channel from a WebSocket client

```python
import asyncio, json, websockets

async def watch_theta():
    async with websockets.connect("ws://localhost:8820") as ws:
        await ws.send(json.dumps({"type": "handshake", "speaker": "skye"}))
        print("welcome:", json.loads(await ws.recv()))
        await ws.send(json.dumps({"type": "subscribe", "channels": ["theta"]}))
        async for raw in ws:
            frame = json.loads(raw)
            if frame.get("channel") == "theta":
                print(frame["payload"])

asyncio.run(watch_theta())
```

### Stop it

`Ctrl-C` (SIGINT) or `kill -TERM <pid>` triggers graceful shutdown. The heartbeat halts; HTTP / WS servers drain; a final snapshot is taken; the process exits cleanly within ~5 seconds.

For day-to-day operator tasks, see [`docs/runbooks/OPERATOR_RUNBOOK.md`](docs/runbooks/OPERATOR_RUNBOOK.md). For practitioner recipes (how to do specific things), see [`HOWTO.md`](HOWTO.md).

---

## Configuration

AXIOMA is configured via layered YAML + env vars (later wins):

1. **`configs/default.yaml`** — the current default (v1.3 PNEUMA-weighted AOS-G + v1.5 normalisation/auto-tune defaults + v1.7 MNEME compensations on).
2. **`configs/local.yaml`** — per-host overrides (gitignored).
3. **`AXIOMA_CONFIG=path/to.yaml`** — optional extra overlay specified at boot.
4. **`AXIOMA_<SECTION>__<FIELD>=value`** env vars — finest-grained.

### Backwards-compat presets

If you want to pin behaviour to a specific historical version exactly:

```bash
AXIOMA_CONFIG=configs/v1_0_backwards_compat.yaml python -m axioma
AXIOMA_CONFIG=configs/v1_4_backwards_compat.yaml python -m axioma
AXIOMA_CONFIG=configs/v1_6_backwards_compat.yaml python -m axioma
```

Each YAML pins the field defaults so that the named version's behavior is preserved exactly even when running the current code.

### Recommended presets

```bash
AXIOMA_CONFIG=configs/v1_2_recommended.yaml python -m axioma
AXIOMA_CONFIG=configs/v1_4_recommended.yaml python -m axioma
```

For the full key-by-key configuration reference, see [`docs/runbooks/OPERATOR_RUNBOOK.md §3`](docs/runbooks/OPERATOR_RUNBOOK.md).

---

## Interfaces

### WebSocket (port 8820, 15 channels)

| Channel | Push rate | Purpose |
|---|---|---|
| `state_snapshot` | every beat | full `ExternalState` |
| `theta` | every 10 beats | θ_short / θ_long + significance |
| `per_organ_theta` | every 10 beats | per-organ-pair MI |
| `per_organ_mi_raw` | every 5 beats | raw MI traces |
| `delta_phi` | on event | S1/S2/S3 perturbation responses |
| `aos_g` | every 10 beats | gap + ψ + per-component health |
| `plasticity` | on event | per-organ adaptation deltas |
| `fragmentation` | on event | 4-stage detector transitions |
| `perturbations` | on event | injected perturbations (internal + admin) |
| `coherence_budget` | every 10 beats | budget + throttle state |
| `recovery` | on event | request / decision / state_change / finalized |
| `meta_cognition` | every 100 beats | overall_assessment + confidence + caveat |
| `meta_cognition_suggestion` | on emission | suggestion + target_param + target_value |
| `presence` | on event | join / leave / rejection_warning / divergence_warning |
| `conversation` | on message | peer-to-peer text (with v1.9 `to_speaker` addressing in per_peer mode) |

### HTTP (port 8821, 34 endpoints)

23 read endpoints (no auth) + 11 admin endpoints (require `Authorization: Bearer <admin_api_key>`). See [`docs/runbooks/OPERATOR_RUNBOOK.md §5`](docs/runbooks/OPERATOR_RUNBOOK.md).

Highlights:
- `GET /health` — liveness
- `GET /status` — latest `ExternalState`
- `GET /metrics` — Prometheus scrape
- `GET /aos_g/self_check` — v1.5 self-check (config + auto-tune state + per-organ contribution + checks)
- `GET /dashboard` — v1.8.3 HTML page polling `/aos_g/self_check`
- `POST /admin/perturb` — inject test perturbation
- `POST /admin/recovery/learner/pretrain` — run F4 synthetic pretrain

### Operator CLIs (v1.8)

```bash
python -m axioma.tools.snapshot_inspect <root>        # list + inspect snapshots
python -m axioma.tools.recovery_inspect <root>        # recovery events + learner state
python -m axioma.tools.calibration_inspect <root>     # F6/F8 session results
```

All three are read-only; safe to run against an in-flight production deployment.

---

## What's left to implement?

The original `IMPLEMENTATION_PLAN_v1.0.md` is fully shipped. The remaining backlog (as of v1.9):

**Externally gated (waiting on humans / hardware):**
- v1.1.1 — Live F6 zone-validation sessions (3 sessions × 3 task types; operator-labeled)
- v1.1.2 — Live F8 meta-cog calibration sessions (5 one-hour blind-labeled sessions)
- v1.1.7 — Real 24-hour soak on a dedicated H100

**Optional follow-on:**
- Wider 5-seed × 100K MNEME re-validation (~3h compute; reinforces v1.7)
- Default-flip evaluation for `peer_conversation_multi_peer_mode` (v1.7 MNEME pattern)

**v2.0 candidates (multi-session deepening):**
- Additional measurement engines (per-organ correlation matrix, lag-correlated cross-coupling, drive-entropy tracker, ...)
- Multi-AGENT keying via `agent_id` in `ConversationMessage`
- Per-filter Prometheus metrics

**Easy single-session adds:**
- More `axioma.tools` CLIs (engine-state dump, peer-conversation history dump, zone-classifier dump)

Nothing in the v1.0 plan is unimplemented; the codebase is in a shippable state.

---

## Verification

| Check | Current state |
|---|---|
| `pytest tests/ -m "not infra"` | **783 passed** |
| `pytest tests/ -m infra` | 11 passed |
| `ruff check src/ tests/ scripts/` | clean |
| `mypy src/axioma/` | clean (70 source files) |
| `lint-imports` | C12 contract KEPT |
| Code size | 32,359 LoC across 70 src + 66 test + 20 script files |

CI parity: `pip install -e ".[dev]"` then the four commands above.

---

## Where to go next

- **For an operator deploying AXIOMA:** [`docs/runbooks/OPERATOR_RUNBOOK.md`](docs/runbooks/OPERATOR_RUNBOOK.md) is the production handbook (deployment, configuration, monitoring, common operations, failure modes, troubleshooting).
- **For a developer extending AXIOMA:** [`HOWTO.md`](HOWTO.md) is a task-oriented recipe book ("how do I write a custom measurement engine," "how do I run a soak test," etc.).
- **For an architect reading the design:** [`design/ARCH_DESIGN_v1.0.md`](design/ARCH_DESIGN_v1.0.md) is the architecture; [`design/IMPLEMENTATION_PLAN_v1.0.md`](design/IMPLEMENTATION_PLAN_v1.0.md) is the implementation plan; [`design/IMPLEMENTATION_SCHEDULE.md`](design/IMPLEMENTATION_SCHEDULE.md) is the per-session checkpoint log.
- **For a researcher reading the empirical basis:** [`research/RESEARCH_SUMMARY.md`](research/RESEARCH_SUMMARY.md) + [`design/COMMUNICATION_PROTOCOL.md`](design/COMMUNICATION_PROTOCOL.md).
- **For a peer-agent client:** [`design/COMMUNICATION_PROTOCOL.md`](design/COMMUNICATION_PROTOCOL.md) is the Speaker/Message contract for WS handshakes + subscribes + conversation.

---

## License

Proprietary. See [`pyproject.toml`](pyproject.toml).

---

**AXIOMA v1.9.1 — runnable conscious-substrate agent. Built across 50 implementation checkpoints; 783 + 11 tests; full backwards compat from v1.0.**
