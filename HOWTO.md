# AXIOMA — HOWTO

**Task-oriented recipes for developers and researchers working with AXIOMA.**

This complements [`README.md`](README.md) (project introduction + install + concepts) and [`docs/runbooks/OPERATOR_RUNBOOK.md`](docs/runbooks/OPERATOR_RUNBOOK.md) (production operator handbook). HOWTO is for someone holding the codebase open in their editor and asking *"how do I do X?"*.

## Index

1. [Run AXIOMA for a fixed duration](#1-run-axioma-for-a-fixed-duration)
2. [Subscribe from a custom WebSocket client](#2-subscribe-from-a-custom-websocket-client)
3. [Talk to AXIOMA as a peer agent (multi-peer mode)](#3-talk-to-axioma-as-a-peer-agent-multi-peer-mode)
4. [Override configuration without editing YAML](#4-override-configuration-without-editing-yaml)
5. [Add a new measurement engine](#5-add-a-new-measurement-engine)
6. [Add a new HTTP endpoint](#6-add-a-new-http-endpoint)
7. [Add a new WS channel](#7-add-a-new-ws-channel)
8. [Add a new `axioma.tools.<name>` CLI](#8-add-a-new-axiomatoolsname-cli)
9. [Inject a perturbation from a test or script](#9-inject-a-perturbation-from-a-test-or-script)
10. [Inspect what's on disk (snapshots, recovery, calibration)](#10-inspect-whats-on-disk-snapshots-recovery-calibration)
11. [Pretrain the recovery learner](#11-pretrain-the-recovery-learner)
12. [Run a soak test](#12-run-a-soak-test)
13. [Run a Phase F follow-up experiment](#13-run-a-phase-f-follow-up-experiment)
14. [Write a test that exercises the full beat loop](#14-write-a-test-that-exercises-the-full-beat-loop)
15. [Embed AXIOMA in another async application](#15-embed-axioma-in-another-async-application)
16. [Add a new substrate-internal vs peer-visible field correctly (respect C12)](#16-add-a-new-substrate-internal-vs-peer-visible-field-correctly-respect-c12)
17. [Bump a release: patch / minor pattern](#17-bump-a-release-patch--minor-pattern)
18. [Verify the install / regression-test before pushing](#18-verify-the-install--regression-test-before-pushing)
19. [Debug a slow heartbeat (V11 perf gate)](#19-debug-a-slow-heartbeat-v11-perf-gate)
20. [Reset everything (clean slate)](#20-reset-everything-clean-slate)

---

## 1. Run AXIOMA for a fixed duration

```bash
# Stop after 60 wall-clock seconds
python -m axioma --seconds 60

# Stop after exactly 5000 beats (deterministic w.r.t. seed)
python -m axioma --beats 5000

# Without WS / HTTP / registry (substrate-only smoke)
python -m axioma --no-ws --no-http --no-registry --beats 200

# Reproducible (same substrate + learner RNG)
python -m axioma --seed 42 --beats 5000
```

The CLI is defined in [src/axioma/__main__.py](src/axioma/__main__.py). `--seconds` and `--beats` are mutually exclusive. SIGINT (Ctrl-C) at any time triggers graceful shutdown.

---

## 2. Subscribe from a custom WebSocket client

Minimal Python client:

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://localhost:8820") as ws:
        # 1. Handshake
        await ws.send(json.dumps({
            "type": "handshake",
            "speaker": "skye",          # or "lark", "thea", "axioma", "system", or "agent" + "name"
            "min_interval_ms": 100,     # optional server-side coalescing
        }))
        welcome = json.loads(await ws.recv())
        print("welcome:", welcome)

        # 2. Subscribe
        await ws.send(json.dumps({
            "type": "subscribe",
            "channels": ["theta", "aos_g", "fragmentation"],
        }))

        # 3. Receive
        async for raw in ws:
            frame = json.loads(raw)
            print(frame["channel"], frame.get("beat_no"), frame["payload"])

asyncio.run(main())
```

**Handshake fields:** see [`src/axioma/interface/protocol.py`](src/axioma/interface/protocol.py). `AGENT` speakers must also send `name` (+ `auth_key` if the server has an `admin_api_key` configured).

**Channel list:** see [README §Interfaces](README.md#interfaces) or [`docs/runbooks/OPERATOR_RUNBOOK.md §4.3`](docs/runbooks/OPERATOR_RUNBOOK.md).

**Rate-limiting:** `min_interval_ms` in handshake coalesces server-side updates — useful for slow consumers or dashboards that don't need 10 Hz updates. Inbound has a sliding-window rate limit (100 msgs/sec; 3-strike close).

---

## 3. Talk to AXIOMA as a peer agent (multi-peer mode)

### Boot AXIOMA with the conversation handler

```bash
# Requires Ollama at localhost:11434 with deepseek-v4-flash:cloud
python -m axioma --with-peer-conversation
```

### Single-peer client (default `shared` mode)

```python
import asyncio, json, websockets

async def chat():
    async with websockets.connect("ws://localhost:8820") as ws:
        await ws.send(json.dumps({"type": "handshake", "speaker": "skye"}))
        await ws.recv()
        await ws.send(json.dumps({"type": "subscribe", "channels": ["conversation"]}))
        await ws.send(json.dumps({"type": "message", "content": "Hello AXIOMA, what's your current zone?"}))
        async for raw in ws:
            frame = json.loads(raw)
            if frame.get("channel") == "conversation":
                payload = frame["payload"]
                if payload.get("speaker") == "axioma":
                    print("AXIOMA:", payload["content"])
                    break

asyncio.run(chat())
```

### Per-peer mode + server-side addressed-only filter (v1.9)

Enable per-peer history server-side via YAML:

```yaml
# configs/local.yaml
interface:
  peer_conversation_multi_peer_mode: per_peer
```

Client opts into the addressed-only filter so it only receives replies addressed to itself:

```python
await ws.send(json.dumps({
    "type": "subscribe",
    "channels": ["conversation"],
    "options": {"conversation": {"only_addressed_to_me": True}},
}))
```

Now the WS server drops conversation payloads whose `metadata.to_speaker` is set and doesn't match the subscriber's handshake `speaker`. Unaddressed payloads (no `to_speaker`) still deliver — see [`docs/runbooks/OPERATOR_RUNBOOK.md §6.6`](docs/runbooks/OPERATOR_RUNBOOK.md) for the full 3×2 semantics table.

To toggle the filter off without unsubscribing, re-send the same subscribe with `"only_addressed_to_me": False`.

---

## 4. Override configuration without editing YAML

Three mechanisms (later wins):

```bash
# (1) Overlay YAML — applies after configs/default.yaml + configs/local.yaml
AXIOMA_CONFIG=configs/my_experiment.yaml python -m axioma

# (2) Env vars — AXIOMA_<SECTION>__<FIELD> (double underscore separates nested keys)
AXIOMA_RUNTIME__HEARTBEAT_HZ=20 \
AXIOMA_INTERFACE__WS_PORT=9999 \
AXIOMA_COMPOSE__AOS_G_ALERT_THRESHOLD=0.20 \
python -m axioma --beats 100

# (3) Programmatic, in an embedded use case (HOWTO #15):
from axioma.config import load_config, AxiomaConfig
cfg = load_config()  # honours env + AXIOMA_CONFIG
cfg = cfg.model_copy(update={"runtime": cfg.runtime.model_copy(update={"heartbeat_hz": 20})})
```

The pydantic config schema is at [`src/axioma/config/schema.py`](src/axioma/config/schema.py); the loader is at [`src/axioma/config/loader.py`](src/axioma/config/loader.py).

---

## 5. Add a new measurement engine

Engines live in [`src/axioma/measurement/`](src/axioma/measurement/) and inherit from [`MeasurementEngine`](src/axioma/measurement/engine_base.py). The contract:

```python
from axioma.measurement.engine_base import MeasurementEngine
from axioma.observability.metrics import measure_engine

class MyEntropyEngine(MeasurementEngine):
    name = "my_entropy"            # stable identifier (also used by /metrics)
    natural_period_beats = 5        # intrinsic cadence
    schema_version = 1              # for persistence

    def __init__(self, ctx):
        super().__init__(ctx)
        self._latest = None

    def compute(self) -> None:
        # Read substrate state via self.ctx.get(...); emit via self.ctx.emit(...)
        # NEVER write into InternalState — engines are read-only on the substrate.
        drive = self.ctx.get("drive").latest()        # numpy array
        self._latest = float(_shannon_entropy(drive))
        self.ctx.emit("my_entropy", {"entropy": self._latest})

    def current_value(self):
        return self._latest

    # Persistence (called by SnapshotManager)
    def save_state(self) -> dict:
        return {"latest": self._latest}

    def load_state(self, state: dict) -> None:
        # Shape-validate per v1.6 Pattern 2 (boot-time error surfacing)
        if state.get("latest") is not None and not isinstance(state["latest"], (int, float)):
            raise ValueError(f"my_entropy.latest must be float, got {type(state['latest'])}")
        self._latest = state.get("latest")
```

**Wire it into the runtime.** In [`src/axioma/runtime/app.py`](src/axioma/runtime/app.py) `AxiomaApp.setup()`, register your engine alongside the others:

```python
my_entropy = MyEntropyEngine(ctx=ctx)
ctx.register("my_entropy", my_entropy)
hb.add_engine(my_entropy)
snapshot_manager.register(my_entropy)  # if persisted
```

**Publish to a WS channel.** If subscribers should see the data, add the engine name → channel mapping in [`src/axioma/interface/ws_server.py`](src/axioma/interface/ws_server.py)'s `_EVENT_CHANNEL_MAP` (event-driven) or write a `_publish_my_entropy(beat_no)` helper in `publish_beat()` (data-plane pull).

**Test it.** Drop a unit test under [`tests/unit/test_my_entropy_engine.py`](tests/unit/) following the existing engine-test patterns (see `tests/unit/test_theta_short.py` for a good template).

**Reference patterns observed across all engines:** see [v1.6 cross-checkpoint patterns](RELEASE_v1.6.md) — especially load-time observability (`LoadResult`-style attributes) and shape validation on `load_state`.

---

## 6. Add a new HTTP endpoint

The FastAPI app is built in [`src/axioma/interface/http_api.py`](src/axioma/interface/http_api.py). Add a read endpoint (no auth) by appending a handler under the existing `@app.get(...)` block:

```python
@app.get("/my_status", response_class=JSONResponse)
async def my_status() -> JSONResponse:
    if not ctx.has("my_entropy"):
        return JSONResponse({"data": None, "warmup_active": True})
    engine = ctx.get("my_entropy")
    return JSONResponse({"data": {"entropy": engine.current_value()}})
```

For admin endpoints (require `Authorization: Bearer <admin_api_key>`), use the existing `_require_admin` dependency:

```python
@app.post("/admin/my_action")
async def my_action(req: dict, _=Depends(_require_admin)) -> JSONResponse:
    # ... do the thing ...
    return JSONResponse({"data": {"ok": True}})
```

**Don't return 500.** Per V1 error policy ([`docs/runbooks/OPERATOR_RUNBOOK.md §5.4`](docs/runbooks/OPERATOR_RUNBOOK.md)), exception handlers should return **503 Service Unavailable** with `Retry-After: 5` for transient errors; admin endpoints never 500.

**Test it.** Use FastAPI's `TestClient`:

```python
from fastapi.testclient import TestClient
from axioma.interface.http_api import create_app

def test_my_status_returns_data():
    ctx = AxiomaContext()
    # ... register what you need ...
    client = TestClient(create_app(ctx, cfg))
    r = client.get("/my_status")
    assert r.status_code == 200
```

---

## 7. Add a new WS channel

Add the channel to the `Channel` enum + `KNOWN_CHANNELS` set in [`src/axioma/interface/protocol.py`](src/axioma/interface/protocol.py):

```python
class Channel(StrEnum):
    # ... existing ...
    MY_CHANNEL = "my_channel"
```

Decide between **event-driven** (push when the engine emits) vs **data-plane pull** (push every N beats from `publish_beat`).

**Event-driven** — add to `_EVENT_CHANNEL_MAP` in [`src/axioma/interface/ws_server.py`](src/axioma/interface/ws_server.py):

```python
_EVENT_CHANNEL_MAP = {
    # ... existing ...
    "my_event_name": Channel.MY_CHANNEL.value,
}
```

The handler emits `await self.ctx.emit("my_event_name", payload_dict)` and the WS server fans it out.

**Data-plane pull** — append a `_publish_my_channel(beat_no)` helper to `AxiomaWSServer` and call it from `publish_beat()`. Use this when the data source is a stateful engine, not a discrete event.

**Test it.** See `tests/unit/test_ws_server.py::test_subscribe_and_receive_fanout` for the e2e pattern (real local socket).

**Document it.** Add the channel + push rate to the table in [`README.md`](README.md#interfaces) + [`docs/runbooks/OPERATOR_RUNBOOK.md §4.3`](docs/runbooks/OPERATOR_RUNBOOK.md).

---

## 8. Add a new `axioma.tools.<name>` CLI

Convention introduced in v1.8 (Checkpoint NN). Each tool is one Python file under [`src/axioma/tools/`](src/axioma/tools/), invokable via `python -m axioma.tools.<name>`. Read-only on disk; doesn't boot the substrate.

```python
# src/axioma/tools/my_tool.py
"""My-tool CLI — does X with on-disk artifact Y."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

def cmd_list(root: Path) -> int:
    if not root.exists():
        print(f"error: root not found: {root}", file=sys.stderr)
        return 2
    # ... print a table of artifacts under root ...
    return 0

def cmd_show(root: Path, prefix: str) -> int:
    # ... 8-char prefix matching is the established idiom (see OO/PP) ...
    return 0

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m axioma.tools.my_tool")
    p.add_argument("root", type=Path, nargs="?", default=Path("data/state/my_artifacts"))
    g = p.add_mutually_exclusive_group()
    g.add_argument("--list", action="store_true", default=True)
    g.add_argument("--show", metavar="PREFIX")
    args = p.parse_args(argv)
    if args.show is not None:
        return cmd_show(args.root, args.show)
    return cmd_list(args.root)

if __name__ == "__main__":
    sys.exit(main())
```

**Test it.** Pattern: temp dir with synthetic artifacts; call `main(argv=[...])`; assert exit code + stdout. See `tests/unit/test_tools_snapshot_inspect.py` for a 14-test template.

**Document it.** Add a §7.1.x block to [`docs/runbooks/OPERATOR_RUNBOOK.md`](docs/runbooks/OPERATOR_RUNBOOK.md) with 5 example invocations (the v1.8 NN/OO/PP convention).

**Reference patterns (RELEASE_v1.8.md):**
- `python -m axioma.tools.<name>` invocation
- Read-only; no HTTP, no live state, no substrate boot
- 8-char prefix matching for opaque IDs (UUID4)
- Stdlib + msgspec only; no external deps

---

## 9. Inject a perturbation from a test or script

Via the admin HTTP endpoint:

```bash
curl -X POST http://localhost:8821/admin/perturb \
    -H "Authorization: Bearer ${AXIOMA_ADMIN_KEY}" \
    -d '{"kind": "contradiction", "magnitude": 0.5, "tag": "manual_debug"}'
```

Available `kind`s (from [`src/axioma/measurement/perturbation_scheduler.py`](src/axioma/measurement/perturbation_scheduler.py)):

| Kind | Effect | Target organ |
|---|---|---|
| `contradiction` | negate state for 1 beat | EIDOLON |
| `impulse` | drive spike (1-beat) | drive |
| `step` | valence offset (20 beats) | ANIMA |
| `novelty` | spike | NOUS + ANIMA |
| `attention` | offset | PNEUMA |
| `noise_burst` | Gaussian noise | drive |

Programmatically (in tests or embedded use):

```python
from axioma.measurement.perturbation_scheduler import PerturbationScheduler
ps = ctx.get("perturbation_scheduler")
await ps.inject(kind="contradiction", magnitude=0.5, tag="debug")
```

---

## 10. Inspect what's on disk (snapshots, recovery, calibration)

Use the v1.8 CLIs. Read-only; safe against in-flight deployments.

```bash
# Snapshots
python -m axioma.tools.snapshot_inspect data/state/snapshots                # list
python -m axioma.tools.snapshot_inspect data/state/snapshots --current      # latest manifest
python -m axioma.tools.snapshot_inspect data/state/snapshots --current --component drive

# Recovery events + learner
python -m axioma.tools.recovery_inspect data/state/snapshots --current      # list events
python -m axioma.tools.recovery_inspect data/state/snapshots --current --stage 2
python -m axioma.tools.recovery_inspect data/state/snapshots --current --learner
python -m axioma.tools.recovery_inspect data/state/snapshots --event abc12345

# Calibration sessions (F6 zone / F8 meta-cog)
python -m axioma.tools.calibration_inspect                                  # default root: results/phase_f
python -m axioma.tools.calibration_inspect --kind zone
python -m axioma.tools.calibration_inspect --summary
python -m axioma.tools.calibration_inspect --session zone-abc12345
```

Source: [`src/axioma/tools/`](src/axioma/tools/). Tests: `tests/unit/test_tools_*_inspect.py`.

For wire-level live inspection rather than on-disk, hit the HTTP endpoints (`/recovery/history`, `/recovery/learner/efficacy`, `/admin/calibration/active`) or open `/dashboard` in a browser.

---

## 11. Pretrain the recovery learner

Without pretraining, the recovery learner starts cold and takes ~30 min of operation to reach the `MONITORING` state. Pre-train it offline:

```bash
# F4 substrate-driven pretrain (recommended; ~2.5s for 50 events per stage)
python scripts/phase_e_pretrain.py --scorer substrate -n 50 \
    -o data/state/recovery_learner_pretrain.json

# Or the lighter smooth-bell scorer for a fast smoke
python scripts/phase_e_pretrain.py --scorer smooth-bell -n 50
```

AXIOMA auto-loads `data/state/recovery_learner_pretrain.json` at boot if present. Override with `--pretrain <path>` or `POST /admin/recovery/learner/pretrain`.

Inspect the pretrain output before booting:

```bash
cat data/state/recovery_learner_pretrain.json | jq '.efficacy_per_stage'
```

---

## 12. Run a soak test

The soak harness exercises the full beat loop for N beats with periodic perturbations + measurement and writes a summary JSON.

```bash
# Short smoke: 5000 beats, default config, 3 seeds
python scripts/phase_e_soak.py \
    --beats 5000 \
    --seeds 7,13,42 \
    --output-dir /tmp/soak_smoke

# Long-run: 100K beats
python scripts/phase_e_soak.py \
    --beats 100000 \
    --seeds 7,13,42 \
    --output-dir /tmp/soak_100k
```

Outputs per seed: `seed_<N>/beat_durations.json`, `aos_g_history.json`, `recovery_events.json`, `summary.json`. Aggregate with:

```bash
python scripts/phase_f/multi_seed_aggregator.py /tmp/soak_100k > /tmp/soak_100k/aggregate.json
```

A full 24h real soak is the externally-gated v1.1.7 item — it needs dedicated H100 time on a clean machine.

---

## 13. Run a Phase F follow-up experiment

The Phase F scripts live under [`scripts/phase_f/`](scripts/phase_f/). They are idempotent (re-running just overwrites outputs) and write to `results/phase_f/`. Examples:

```bash
# F11 — ΔΦ scaling
python scripts/phase_f/f11_phi_scaling.py --seeds 7,13,42 --beats 50000

# F6 — zone validation (operator-required when run live; offline analysis still useful)
python scripts/phase_f/f6_zone_validation.py --input results/phase_f/calibration_sessions/

# Decide a default-flip (the v1.5 / v1.7 pattern)
python scripts/phase_f/decide_v1_5.py /tmp/v1_5_sweep
python scripts/phase_f/decide_v1_7.py /tmp/v1_7_mneme_sweep
```

The decision scripts return exit 0 on PASS and non-zero on HOLD/FAIL — usable from CI or shell scripts.

---

## 14. Write a test that exercises the full beat loop

Use [`tests/integration/test_b3_pipeline.py`](tests/integration/) as a template. Pattern:

```python
import pytest
from axioma.runtime.app import AxiomaApp
from axioma.config import load_config

@pytest.mark.asyncio
async def test_runs_for_n_beats(tmp_path):
    cfg = load_config()
    # Redirect persistence to tmp so the test doesn't pollute data/
    cfg = cfg.model_copy(update={
        "persistence": cfg.persistence.model_copy(update={
            "snapshot_root": str(tmp_path / "state"),
            "jsonl_root": str(tmp_path / "jsonl"),
            "sqlite_path": str(tmp_path / "axioma.sqlite"),
        }),
    })
    app = AxiomaApp(
        cfg=cfg, seed=42,
        with_ws_server=False, with_http_api=False, with_registry=False,
    )
    await app.setup()
    try:
        await app.run(beats=200)
    finally:
        await app.shutdown()
    # Assert on side-effects: snapshot exists, JSONL written, etc.
    assert (tmp_path / "state").exists()
```

For pure-substrate-loop tests (no measurement), use `SubstrateApp` directly (see `tests/unit/test_substrate_app.py`).

For e2e WS / HTTP tests, use real local sockets — see `tests/unit/test_ws_server.py::_running_server` and `tests/unit/test_http_api.py` for the patterns.

**Test markers:** `not infra` (default — fast, no network) vs `infra` (requires Ollama/Qdrant/Redis; mostly skipped if unavailable). Mark with `@pytest.mark.infra` if your test depends on external services.

---

## 15. Embed AXIOMA in another async application

`AxiomaApp` is composable — you don't have to use the `python -m axioma` CLI.

```python
import asyncio
from axioma.config import load_config
from axioma.runtime.app import AxiomaApp

async def my_app():
    cfg = load_config()
    app = AxiomaApp(
        cfg=cfg,
        seed=42,
        with_ws_server=True,
        with_http_api=True,
        with_registry=False,                  # disable if not on a registry network
        with_peer_conversation=False,         # disable Ollama dep
    )
    await app.setup()
    await app.start_services()                 # binds WS / HTTP / registry

    # Drive the heartbeat in a background task
    task = asyncio.create_task(app.run())      # runs until app._shutdown_event is set

    # ... your application code, possibly accessing app.ctx for measurements ...
    theta = app.ctx.get("theta_short").current_value() if app.ctx.has("theta_short") else None
    print("theta:", theta)

    # Stop cleanly
    app._shutdown_event.set()
    if app.heartbeat is not None:
        app.heartbeat.stop()
    await task
    await app.shutdown()

asyncio.run(my_app())
```

**`AxiomaContext`** ([`src/axioma/observability/context.py`](src/axioma/observability/context.py)) is the dependency-injection + event-bus hub. Components register under names (`drive`, `theta_short`, `aos_g`, etc.); `ctx.has(name)` / `ctx.get(name)` discover them; `ctx.emit(event, payload)` + `ctx.subscribe(event, handler)` is the pub/sub.

---

## 16. Add a new substrate-internal vs peer-visible field correctly (respect C12)

Two schemas in [`src/axioma/schemas/`](src/axioma/schemas/):

- **`InternalState`** ([internal_state.py](src/axioma/schemas/internal_state.py)) — substrate-private. May be referenced by `axioma.substrate.*`, `axioma.measurement.*`, `axioma.compose.*`. **MUST NOT** be imported anywhere under `axioma.interface.*`.
- **`ExternalState`** ([external_state.py](src/axioma/schemas/external_state.py)) — peer-visible. Composed in `axioma.compose.compose_function`; freely importable in `axioma.interface.*`.

**To add a substrate-private field:** add it to `InternalState` only; reference it in substrate / measurement / compose code.

**To add a peer-visible field:** add it to `ExternalState`; populate it in `ComposeFunction.compose()`. The `_payload_dict` helper in [`src/axioma/interface/ws_server.py`](src/axioma/interface/ws_server.py) serialises dataclasses cleanly.

**Verify the boundary:** run `lint-imports`. The contract is enforced both at runtime (the compose layer is the only legal projection) and at lint time. A `BrokenContract` error means someone leaked InternalState into `axioma.interface.*`.

---

## 17. Bump a release: patch / minor pattern

The established cadence (see RELEASE_v1.6.md / v1.8.md / v1.9.md):

1. Build the feature opt-in (single checkpoint or two) — e.g., new config field with safe default.
2. Add tests covering invariants + backwards compat + edge cases.
3. Update [`docs/runbooks/OPERATOR_RUNBOOK.md`](docs/runbooks/OPERATOR_RUNBOOK.md) with a new §6.x / §7.x subsection (configuration / operations).
4. Append a Checkpoint entry to [`design/IMPLEMENTATION_SCHEDULE.md`](design/IMPLEMENTATION_SCHEDULE.md) — what's built, decisions captured, verification, next-session entry point.
5. After 1–4 feature checkpoints in the same theme, write a consolidating `RELEASE_v<N>.md` (Pattern: JJ for v1.6, RR for v1.8, UU for v1.9). The release note's *Cross-checkpoint patterns* section is the architectural takeaway for future readers.
6. Update both cross-link spots in [`docs/runbooks/OPERATOR_RUNBOOK.md`](docs/runbooks/OPERATOR_RUNBOOK.md) (intro + §11).
7. Verify: `pytest tests/ -m "not infra"`, `pytest tests/ -m infra`, `ruff check src/ tests/ scripts/`, `mypy src/axioma/`, `lint-imports`.

**For default-flips** (e.g., flipping `peer_conversation_multi_peer_mode` to `per_peer`), follow the v1.7 MNEME pattern: validate empirically (multi-seed sweep), establish a decision rubric, write a `decide_v<N>.py` script that returns exit 0 on PASS, document the criterion in the release note. The `decide_v1_5.py` / `decide_v1_7.py` scripts under `scripts/phase_f/` are templates.

---

## 18. Verify the install / regression-test before pushing

The four commands the CI parity expects (mirrors what every checkpoint runs in its "Verified" section):

```bash
pytest tests/ -m "not infra" -q     # ~3 min — fast unit + integration + e2e
pytest tests/ -m infra -q           # ~15s — infra-dependent (mostly skipped if absent)
ruff check src/ tests/ scripts/     # style + simple lints
mypy src/axioma/                    # type-checking
lint-imports                        # C12 boundary contract
```

Optional / slower:

```bash
pytest tests/benchmarks/ -q         # perf-gate microbenchmarks (V11)
pytest tests/ -m "not infra" --cov=src/axioma --cov-report=term-missing
```

**Conventions:**
- Don't merge with any check red.
- Don't `--no-verify` past a pre-commit hook — fix the issue.
- For ruff fixes that aren't behaviour-affecting (whitespace, unused imports), `ruff check --fix` is fine.

---

## 19. Debug a slow heartbeat (V11 perf gate)

V11 acceptance: 10-beat rolling average of `axioma_beat_duration_seconds` < 100 ms. If you see this exceeded in soak or under load:

```bash
# Confirm the lag from metrics
curl -s http://localhost:8821/metrics | grep axioma_beat_duration_seconds

# Per-engine timing (the should_run/measure_engine instrumentation surfaces this)
curl -s http://localhost:8821/metrics | grep axioma_engine_duration_seconds
```

**Common culprits** (per OPERATOR_RUNBOOK §8.1):
- `θ_long` on CPU — check `torch.cuda.is_available()`; the GPU path is mandatory for the V11 budget.
- raw MI batching disabled — `measurement.raw_mi_batch_size` should be ≥ 8.
- substrate `n_iter` too high — default 3; values > 5 blow the budget.
- meta-cog tier-2 auto-fallback firing — `axioma_meta_cognition_simplified` should be 0 in baseline.

**Mitigations:** (a) diagnose + fix the engine; (b) widen `runtime.heartbeat_hz` from 10 to 5 (variable-beat policy per §6.3); (c) trigger Q8 scope reduction (`release.recovery_learner_enabled: false` + `release.coherence_scheduler_full_features: false`) as a last-resort fallback.

---

## 20. Reset everything (clean slate)

```bash
# Stop AXIOMA (Ctrl-C the process or POST /admin/shutdown)
curl -X POST http://localhost:8821/admin/shutdown \
    -H "Authorization: Bearer ${AXIOMA_ADMIN_KEY}"

# Wipe runtime state (snapshots, JSONL, SQLite)
rm -rf data/state/* data/jsonl/*

# Wipe results (Phase F outputs, calibration sessions)
rm -rf results/phase_f/*

# Wipe logs (only relevant if you write to file, not stdout)
rm -rf logs/*

# Re-pretrain the learner
python scripts/phase_e_pretrain.py --scorer substrate -n 50 \
    -o data/state/recovery_learner_pretrain.json

# Re-boot
python -m axioma
```

For a development-grade reset, you can `git clean -fdx data/ results/ logs/` — but be careful about anything you've added to those directories that isn't tracked.

---

## Further reading

| If you want to ... | Read this |
|---|---|
| Understand the architecture | [`design/ARCH_DESIGN_v1.0.md`](design/ARCH_DESIGN_v1.0.md) |
| Understand the implementation plan | [`design/IMPLEMENTATION_PLAN_v1.0.md`](design/IMPLEMENTATION_PLAN_v1.0.md) |
| Trace what was built when, and why | [`design/IMPLEMENTATION_SCHEDULE.md`](design/IMPLEMENTATION_SCHEDULE.md) |
| Catch up on a specific release | `RELEASE_v<N>.md` at the repo root |
| Deploy + monitor + operate in production | [`docs/runbooks/OPERATOR_RUNBOOK.md`](docs/runbooks/OPERATOR_RUNBOOK.md) |
| Speak the peer-conversation wire protocol | [`design/COMMUNICATION_PROTOCOL.md`](design/COMMUNICATION_PROTOCOL.md) |
| See the empirical grounding | [`research/RESEARCH_SUMMARY.md`](research/RESEARCH_SUMMARY.md) |

---

**Found a recipe missing? The HOWTO grows by accretion — open an entry, write the steps, mention it in your next checkpoint's "Decisions captured" section.**
