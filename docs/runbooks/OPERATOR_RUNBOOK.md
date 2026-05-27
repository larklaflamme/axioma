# AXIOMA Operator Runbook

**For:** ops teams running AXIOMA in production
**Version:** v1.3 (post-Checkpoint P)
**Scope:** deployment, configuration, monitoring, common operations, failure recovery

This runbook consolidates everything a new operator needs to run AXIOMA in production. Per-release notes are at [RELEASE_v1.0.md](../../RELEASE_v1.0.md), [RELEASE_v1.2.md](../../RELEASE_v1.2.md), [RELEASE_v1.3.md](../../RELEASE_v1.3.md), [RELEASE_v1.4.md](../../RELEASE_v1.4.md), [RELEASE_v1.5.md](../../RELEASE_v1.5.md), [RELEASE_v1.6.md](../../RELEASE_v1.6.md), [RELEASE_v1.7.md](../../RELEASE_v1.7.md), [RELEASE_v1.8.md](../../RELEASE_v1.8.md), [RELEASE_v1.9.md](../../RELEASE_v1.9.md). Full implementation history is in [design/IMPLEMENTATION_SCHEDULE.md](../../design/IMPLEMENTATION_SCHEDULE.md).

---

## 1. Quickstart (5 minutes)

```bash
# 1. Activate env
conda activate axioma

# 2. Run AXIOMA with v1.3 defaults (PNEUMA-weighted AOS-G)
python -m axioma
```

That's it for a development run. The substrate boots, the heartbeat ticks at 10 Hz, the WebSocket server binds at `127.0.0.1:8820`, the HTTP API binds at `127.0.0.1:8821`. Ctrl-C triggers graceful shutdown.

**Verify it's alive:**

```bash
curl http://localhost:8821/health
# {"status": "ok", "shutting_down": false, "components": [...]}

curl http://localhost:8821/status | jq .data.theta_short
# 1.0734
```

---

## 2. Production deployment

### 2.1 Minimum config

For a real deployment, override the host/port to bind on a public interface:

```yaml
# configs/production.yaml
interface:
  ws_host: 0.0.0.0       # or specific bind address
  ws_port: 8820
  http_host: 0.0.0.0
  http_port: 8821
  admin_api_key: "${AXIOMA_ADMIN_KEY}"   # set via env var

persistence:
  snapshot_root: /var/lib/axioma/state
  jsonl_root: /var/lib/axioma/jsonl

observability:
  log_level: INFO
  log_json: true   # structlog → JSON for log aggregation
```

```bash
AXIOMA_CONFIG=configs/production.yaml \
AXIOMA_ADMIN_KEY=$(cat /etc/axioma/admin-key) \
python -m axioma
```

### 2.2 systemd unit (recommended)

```ini
# /etc/systemd/system/axioma.service
[Unit]
Description=AXIOMA consciousness substrate
After=network.target

[Service]
Type=simple
User=axioma
WorkingDirectory=/opt/axioma
Environment="AXIOMA_CONFIG=/opt/axioma/configs/production.yaml"
EnvironmentFile=/etc/axioma/secrets.env  # AXIOMA_ADMIN_KEY etc.
ExecStart=/opt/axioma/.venv/bin/python -m axioma
Restart=on-failure
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=30   # AxiomaApp.shutdown() needs ~5s for HTTP server tearndown

[Install]
WantedBy=multi-user.target
```

`SIGTERM` triggers `app.shutdown()` via the signal handler wired in [src/axioma/__main__.py](../../src/axioma/__main__.py); the `TimeoutStopSec=30` gives the heartbeat + HTTP/WS servers room to drain.

### 2.3 CLI flags reference

```
python -m axioma [OPTIONS]

  --seconds N          Run for N wall-clock seconds (default: until SIGINT)
  --beats N            Run for N beats (mutually exclusive with --seconds)
  --seed N             Substrate RNG seed (default 42)
  --no-ws              Disable WebSocket server
  --no-http            Disable HTTP API server
  --no-registry        Disable registry client
  --with-peer-conversation   Enable Ollama-backed peer chat handler
  --pretrain PATH      Path to learner pretrain snapshot
                       (default: data/state/recovery_learner_pretrain.json)
```

Env vars (any of `AXIOMA_<SECTION>__<FIELD>` override the corresponding YAML field):

```bash
AXIOMA_RUNTIME__HEARTBEAT_HZ=10
AXIOMA_INTERFACE__WS_PORT=8820
AXIOMA_INTERFACE__HTTP_PORT=8821
AXIOMA_COMPOSE__AOS_G_ALERT_THRESHOLD=0.152
AXIOMA_OBSERVABILITY__LOG_LEVEL=INFO
```

Special env vars:

- `AXIOMA_CONFIG=path/to.yaml` — extra YAML overlay (loaded after `configs/default.yaml` and `configs/local.yaml`)

### 2.4 Bootstrapping the recovery learner (recommended)

Without pretraining, the substrate's recovery learner starts cold and takes 20+ events (~30 min of operation) to enter MONITORING state. Pre-train it offline:

```bash
python scripts/phase_e_pretrain.py --scorer substrate -n 50 \
    -o data/state/recovery_learner_pretrain.json
# Wall-clock: ~2.5 seconds for 50 events per stage
```

Subsequent boots pick up the snapshot automatically (the default path is `data/state/recovery_learner_pretrain.json`).

---

## 3. Configuration reference

### 3.1 Layered resolution

The config loader applies layers in this order (later wins):

1. Pydantic schema defaults (see [src/axioma/config/schema.py](../../src/axioma/config/schema.py))
2. `configs/default.yaml`
3. `configs/local.yaml` (gitignored — for per-host secrets / overrides)
4. `AXIOMA_CONFIG=<path>` env var (if set)
5. `.env` infra vars (`OLLAMA_URL`, `QDRANT_URL`, `EMBED_MODEL`, `REDIS_URL`, etc.)
6. `AXIOMA_*` env vars (per-field overrides, double-underscore for nesting)

### 3.2 Key fields

#### Compose / AOS-G (v1.5 defaults)

```yaml
compose:
  baseline_period_beats: 30           # ARCH §4.6 baseline cadence
  perturbation_period_beats: 5        # adaptive cadence during perturbation window
  recovery_period_beats: 60           # cadence during active recovery
  aos_g_alert_threshold: 0.152        # initial value (auto-tuned after warmup)
  psi_alert_threshold: 0.3
  aos_g_gap_weights:                  # v1.3 default — PNEUMA-weighted
    anima: 0.5
    eidolon: 0.75
    mneme: 0.75
    nous: 0.5
    pneuma: 2.5
  # v1.5 default-flip: balanced per-organ metric + self-calibrating threshold.
  aos_g_normalize_per_organ: true     # was False in v1.4
  aos_g_alert_threshold_auto_tune: true  # was False in v1.4
```

To revert to v1.0/v1.1/v1.2 uniform AOS-G:

```bash
AXIOMA_CONFIG=configs/v1_0_backwards_compat.yaml python -m axioma
```

To revert to v1.4 metric surface (unnormalized weighted L2 + static threshold):

```bash
AXIOMA_CONFIG=configs/v1_4_backwards_compat.yaml python -m axioma
```

#### Alert auto-tune (v1.5 default — was opt-in in v1.4.2)

```yaml
compose:
  # v1.5 default ON. Measures the substrate's own gap distribution during the
  # warmup window, then sets aos_g_alert_threshold to ratio × mean(observed_gap).
  # Recomputes every recompute_period_beats to track drift.
  aos_g_alert_threshold_auto_tune: true                        # v1.5 default
  aos_g_alert_threshold_auto_tune_ratio: 0.014                 # 1.4% of typical magnitude
  aos_g_alert_threshold_auto_tune_warmup_beats: 3000           # v1.4.4: outlasts normalize warmup (60 × 30 = 1800 beats)
  aos_g_alert_threshold_auto_tune_recompute_period_beats: 36000  # ~1h @ 10 Hz
```

Operators on bespoke `aos_g_gap_weights` (anything other than uniform / PNEUMA-weighted) benefit most — no need to run `scripts/phase_f/alert_threshold_calibration.py` manually.

The auto-tuner fires the first set after warmup completes AND ≥20 gap samples accumulate. Watch the `aos_g_alert_threshold_auto_tuned` log event for visibility.

**v1.4.4 warmup-coordination note**: when `aos_g_normalize_per_organ` is also on, `auto_tune_warmup_beats` must be at least `normalize_min_samples × 30` (the AOS-G natural period) — otherwise the first auto-tune fires against partly-normalized gaps and overshoots by ~2× before converging on the second recompute. The default (3000) satisfies this for the default `normalize_min_samples` (60). Operators who increase `normalize_min_samples` should bump `auto_tune_warmup_beats` proportionally; the engine logs a `aos_g_auto_tune_warmup_below_normalize_warmup` warning at boot if the two are misaligned.

#### Per-component ψ thresholds (v1.4.3 — opt-in)

```yaml
compose:
  psi_alert_threshold: 0.3   # fallback for any unspecified component
  # When set, alert fires if ANY component drops below ITS threshold.
  # Missing keys fall back to psi_alert_threshold.
  psi_per_component_thresholds:
    structural_health: 0.95   # tight — catches architectural regressions early
    gap_variance_health: 0.2  # loose — substrate dynamics vary naturally
    # compose_probe_health unspecified → 0.3 fallback
```

Default behavior (the field unset): all three components use `psi_alert_threshold`. Same as v1.0..v1.3.

#### Per-organ gap normalization (v1.5 default — was opt-in in v1.4.1)

```yaml
compose:
  # v1.5 default ON. Each organ's raw gap is divided by its rolling mean before
  # the weighted sum. Equalizes per-organ contribution to the aggregate gap
  # regardless of natural magnitude (under raw L2 + PNEUMA-weighted, PNEUMA
  # contributes ~84% of the gap signal; with normalization, ~45%).
  aos_g_normalize_per_organ: true             # v1.5 default
  aos_g_normalize_per_organ_window_beats: 600 # rolling mean window
  aos_g_normalize_per_organ_min_samples: 60   # warmup before normalization activates
```

During warmup (`< min_samples` observations) the path falls back to the unnormalized contribution, so behavior matches v1.0..v1.4 bit-for-bit until enough samples accumulate. The per-organ raw gap stays exposed in `AOSGReading.per_organ_gap` for diagnostics — normalization only affects the aggregate.

**v1.5 pairs this with auto-tune by default.** Normalization shifts `aos_g_gap` mean by ~75-78% (3 seeds × 50K beats sweep: gap_mean drops from ~10.5 to ~2.5 across all seeds), so a static `aos_g_alert_threshold` calibrated for the unnormalized regime becomes too loose. v1.5's default config pairs normalization with `aos_g_alert_threshold_auto_tune: true`, which recalibrates after warmup. Operators wanting unnormalized weighted L2 + static threshold should load `configs/v1_4_backwards_compat.yaml`.

This combination gives a balanced, self-calibrating AOS-G measurement with no manual threshold tuning. Multi-seed validation (3 seeds × 10K beats) confirmed all V11/V13 ship-gates pass with normalize=ON.

#### Recovery + learner

```yaml
recovery:
  min_recovery_stage: 2               # fragmentation stage triggering recovery
  default_duration_beats: 100         # how long Stage-2 recovery lasts
  min_budget_to_accept: 0.20          # below this coherence_budget → reject
  require_pretrain: true              # refuse to start without pretrain snapshot
  learner_exploration_rate: 0.15      # F2 — 15% of recoveries explore new params
  learner_clean_baseline_events: 100  # post-INEFFECTIVE clean window
  rejection_escalation_consecutive: 3 # Q1 — N rejects → presence warning
  durability_watchdog_beats: 3000     # how long without re-fragmentation = durable
```

#### Meta-cognition

```yaml
meta_cognition:
  enabled: true                       # Q8 scope-reduction toggle
  observer_mode: observer_only        # F7 — embedded mode is v0.7+ work
  suggestion_confidence_threshold: 0.7
  divergence_warning_threshold: 5     # F5 — 5 ignored suggestions → warn
```

#### Interface (WS + HTTP)

```yaml
interface:
  ws_host: 127.0.0.1
  ws_port: 8820
  http_host: 127.0.0.1
  http_port: 8821
  admin_api_key: "${AXIOMA_ADMIN_KEY}"      # required for /admin/* endpoints
  ws_rate_limit_msgs_per_second: 100        # V1 inbound rate limit
  ws_rate_limit_consecutive_strikes: 3      # close after N strikes
  http_default_retry_after_seconds: 5       # 503 + Retry-After
```

---

## 4. WebSocket channels (15 channels)

Connect: `ws://<host>:<ws_port>/`

### 4.1 Handshake

```json
{"type": "handshake", "speaker": "skye", "min_interval_ms": 100}
```

For agents not in the Speaker enum, use `"speaker": "agent", "name": "your_agent_id"`. If `admin_api_key` is configured, AGENT speakers must also send `"auth_key": "..."`.

### 4.2 Subscribe

```json
{"type": "subscribe", "channels": ["theta", "fragmentation", "aos_g"]}
```

### 4.3 Channel reference

| Channel | Push rate | Purpose |
|---|---|---|
| `conversation` | on message | peer-to-peer text |
| `theta` | every 10 beats | θ_short + θ_long + p_value + significant flag |
| `per_organ_theta` | every 10 beats | per-organ-pair MI |
| `per_organ_mi_raw` | every 5 beats | raw MI traces (high-resolution) |
| `delta_phi` | on event | S1/S2/S3 perturbation responses |
| `aos_g` | every 10 beats | gap + psi + per-component health + alert |
| `plasticity` | on event | adaptation_delta per organ |
| `fragmentation` | on event | 4-stage detector state changes |
| `perturbations` | on event | injected perturbations (internal + admin) |
| `coherence_budget` | every 10 beats | budget + throttle_state |
| `recovery` | on event | request/decision/state_change/finalized |
| `meta_cognition` | every 100 beats | overall_assessment + confidence + caveat |
| `meta_cognition_suggestion` | on emission | suggestion + target_param + target_value |
| `presence` | on event | join/leave/rejection_warning/divergence_warning |
| `state_snapshot` | every beat | full ExternalState |

### 4.4 Per-subscriber rate limiting

Set `min_interval_ms` in handshake to coalesce server-side updates (e.g., `min_interval_ms: 500` for ≤ 2 Hz subscriber bandwidth).

---

## 5. HTTP API (34 endpoints)

Base URL: `http://<host>:<http_port>`

### 5.1 Read endpoints (no auth required)

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness + components list |
| `GET /metrics` | Prometheus scrape format |
| `GET /status` | Latest ExternalState snapshot (`warmup_active=true` before first compose) |
| `GET /capabilities` | Agent capabilities + supported channels |
| `GET /connections` | Live WS subscribers + their stats |
| `GET /organs` | Per-organ external state subset |
| `GET /theta/history?minutes=60` | θ trajectory |
| `GET /delta_phi/history` | ΔΦ event history |
| `GET /perturbations` | Recent perturbation events |
| `GET /fragmentation` | Current fragmentation stage + signals |
| `GET /fragmentation/history?limit=200` | Stage history |
| `GET /recovery/history?limit=100` | Recovery event history with quality scores |
| `GET /recovery/learner/efficacy` | Current learner state (WARMING_UP/MONITORING/EFFECTIVE/INEFFECTIVE) |
| `GET /recovery/pretrain/status` | Pretrain snapshot availability + readiness |
| `GET /meta_cognition/history?limit=50` | Recent assessments |
| `GET /meta_cognition/suggestions?limit=20` | Recent suggestions + decisions |
| `GET /meta_cognition/calibration` | F8 calibration measurements |
| `GET /scheduler/effectiveness` | Throttle effectiveness + budget |
| `GET /integrity` | ψ + per-component breakdown |
| `GET /aos_g/self_check` | v1.5 self-check: config + auto-tune state + per-organ contribution share + checks (see §5.3) |
| `GET /dashboard` | v1.8.3 HTML dashboard for `/aos_g/self_check` — single-page, polls every 3s (see §6.4) |
| `GET /presence/divergence_warnings?limit=20` | F5 meta-cog divergence warnings |
| `GET /presence/rejection_warnings?limit=20` | Q1 recovery rejection warnings |

### 5.2 Admin endpoints (require `Authorization: Bearer <admin_api_key>`)

| Endpoint | Purpose |
|---|---|
| `POST /admin/perturb` | Inject perturbation. Body: `{"kind": "contradiction", "magnitude": 0.5, "tag": "..."}` |
| `POST /admin/recovery/force` | Force recovery request. Body: `{"stage": 2, "force": true}` |
| `POST /admin/recovery/learner/pretrain` | Run F4 synthetic pretrain sweep. Body: `{"target_events_per_stage": 50}` |
| `POST /admin/recovery/learner/reset` | Reset learner to default params |
| `POST /admin/meta_cognition/mode` | Set observer_mode. Body: `{"mode": "observer_only" \| "embedded"}` |
| `POST /admin/heartbeat/pause` | Pause heartbeat N beats. Body: `{"beats": 1}` |
| `POST /admin/shutdown` | Trigger graceful shutdown (returns 200, then app exits) |
| `POST /admin/calibration/session/start` | F6/F8 live session. Body: `{"kind": "zone" \| "meta_cog", "task_type": "analytical", "duration_minutes": 60}` |
| `POST /admin/calibration/label` | Submit operator label. Body: `{"kind": "zone", "beat_no": 12500, "label": "focus"}` |
| `POST /admin/calibration/session/end` | End session + write summary JSON. Body: `{"kind": "zone"}` |
| `GET /admin/calibration/active` | List active calibration sessions |

### 5.3 v1.5 self-check endpoint

`GET /aos_g/self_check` answers *"is v1.5 operating as expected on this deployment?"* without grepping structlog. Read-only, no auth required.

**Response shape:**

```json
{
  "data": {
    "version": "v1.5",
    "config": {
      "aos_g_normalize_per_organ": true,
      "aos_g_normalize_per_organ_window_beats": 600,
      "aos_g_normalize_per_organ_min_samples": 60,
      "aos_g_alert_threshold_auto_tune": true,
      "aos_g_alert_threshold_auto_tune_ratio": 0.014,
      "aos_g_alert_threshold_auto_tune_warmup_beats": 3000,
      "aos_g_alert_threshold_auto_tune_recompute_period_beats": 36000,
      "gap_weights": {"anima": 0.5, "eidolon": 0.75, "mneme": 0.75, "nous": 0.5, "pneuma": 2.5}
    },
    "engine_state": {
      "current_threshold": 0.0425,
      "initial_threshold": 0.152,
      "auto_tune_first_set": true,
      "auto_tune_n_tunes": 2,
      "last_tune_beat": 39000,
      "normalize_ready": true,
      "normalize_samples_per_organ": {"anima": 600, "eidolon": 600, "mneme": 600, "nous": 600, "pneuma": 600},
      "last_reading_beat": 50000
    },
    "per_organ_contribution_share_pct": {
      "anima": 8.5, "eidolon": 11.0, "mneme": 18.5, "nous": 17.0, "pneuma": 45.0
    },
    "checks": [
      {"name": "normalize_enabled", "status": "ok", "detail": "..."},
      {"name": "normalize_stabilized", "status": "ok", "detail": "..."},
      {"name": "auto_tune_enabled", "status": "ok", "detail": "..."},
      {"name": "auto_tune_first_set_fired", "status": "ok", "detail": "..."},
      {"name": "per_organ_contribution_balanced", "status": "ok", "detail": "PNEUMA share 45.0% — balanced (target < 60%)"}
    ],
    "overall_status": "ok"
  }
}
```

**Status semantics:**

| `overall_status` | Meaning |
|---|---|
| `ok` | All checks passing — v1.5 operating as expected |
| `warmup` | Substrate hasn't reached stabilization yet (normalize warmup or auto-tune warmup pending). Expected during the first ~3000 beats (5 min @ 10 Hz) of any deployment. |
| `warning` | Post-stabilization, some check failed (e.g., PNEUMA share > 60%). Investigate: gap_weights misconfigured, or substrate dynamics drifted into a regime where normalization isn't equalizing as expected. |

**Recommended operator wire-in:**

After a deploy, wait for warmup then assert `overall_status == "ok"`:

```bash
# After 5 minutes of uptime
curl -sf "$HOST/aos_g/self_check" | jq -e '.data.overall_status == "ok"'
```

For continuous monitoring, alert on `overall_status == "warning"`. The `warmup` status is expected post-boot and self-resolves; it's not actionable on its own.

### 5.4 V1 error policy (per ARCH §8.6)

| Failure | Status | Body |
|---|---|---|
| Internal exception | 503 + `Retry-After: 5` | `{"error": "internal_error", "request_id": "...", "retry_after_seconds": 5}` |
| Missing auth on admin | 401 | `{"error": "auth_required"}` |
| Bad auth on admin | 403 | `{"error": "auth_invalid"}` |
| Admin during shutdown | 503 | `{"error": "shutting_down"}` |
| Invalid params | 422 | (FastAPI default) |
| Warmup state (no data yet) | 200 + `warmup_active: true` | `{"data": null, "warmup_active": true}` |

---

## 6. Monitoring

### 6.1 Prometheus metrics (scrape from `/metrics`)

| Metric | Type | Purpose |
|---|---|---|
| `axioma_beat_duration_seconds` | Histogram | Per-beat wall-clock. **V11 gate: 10-beat rolling p95 < 100 ms.** |
| `axioma_engine_duration_seconds{engine}` | Histogram | Per-engine compute time |
| `axioma_theta_short` | Gauge | Current θ_short |
| `axioma_theta_long` | Gauge | Current θ_long |
| `axioma_aos_g_gap` | Gauge | Current AOS-G gap |
| `axioma_psi` | Gauge | Boundary integrity field [0,1] |
| `axioma_coherence_budget` | Gauge | PNEUMA coherence_budget [0,1] |
| `axioma_fragmentation_stage` | Gauge | 0-4 |
| `axioma_recovery_active` | Gauge | 1 if recovering, 0 otherwise |
| `axioma_meta_cognition_period_beats` | Gauge | Meta-cog cadence (100 default; raised on Q7 fallback) |
| `axioma_recovery_learner_exploration_rate` | Gauge | Current learner exploration rate |
| `axioma_perturbations_total{source, kind}` | Counter | Perturbations injected |
| `axioma_recoveries_total{stage, decision}` | Counter | Recovery decisions |
| `axioma_meta_suggestions_total{decision}` | Counter | Meta-cog suggestions handled |
| `axioma_divergence_warnings_total` | Counter | F5 warnings |
| `axioma_rejection_run_warnings_total` | Counter | Q1 warnings |
| `axioma_persistence_writes_total{target}` | Counter | Snapshot/JSONL writes |
| `axioma_persistence_write_seconds{target}` | Histogram | Persistence write latency |
| `axioma_disk_bytes_used` | Gauge | data/ subtree disk usage |
| `axioma_ws_connections_total` | Counter | WS connections opened |
| `axioma_ws_disconnects_total` | Counter | WS disconnects |
| `axioma_ws_messages_sent_total` | Counter | WS messages sent across all subscribers |
| `axioma_http_requests_total{method, path, status}` | Counter | HTTP requests |
| `axioma_registry_heartbeat_failures_total` | Counter | Registry outage events |

### 6.2 Recommended dashboards

**Substrate health:**
- `axioma_theta_short` and `axioma_theta_long` (lines, last 1h)
- `axioma_psi` with alert threshold line at 0.3
- `axioma_aos_g_gap` with alert threshold line at 0.152 (v1.3) or 0.1 (v1.0 backwards-compat)
- `axioma_coherence_budget` (line, last 1h)

**Recovery health:**
- `axioma_fragmentation_stage` (gauge, 0-4 colour-coded)
- `axioma_recovery_active` (0/1 indicator)
- `rate(axioma_recoveries_total[5m])` by `decision` (stacked bar)
- `rate(axioma_rejection_run_warnings_total[1h])` (should be near 0)

**Performance:**
- `histogram_quantile(0.95, rate(axioma_beat_duration_seconds_bucket[5m]))` — V11 watchdog
- `axioma_engine_duration_seconds` by engine (find the heavy engines)
- `axioma_disk_bytes_used` (storage growth)

**Interface:**
- `axioma_ws_connections_total - axioma_ws_disconnects_total` (active WS subscribers)
- `rate(axioma_http_requests_total[5m])` by status (4xx + 5xx spikes)

### 6.3 Alerting rules (suggested)

```yaml
# Prometheus rules
- alert: AxiomaBeatBudgetExceeded
  expr: histogram_quantile(0.95, rate(axioma_beat_duration_seconds_bucket[5m])) > 0.1
  for: 10m
  annotations:
    summary: "V11 perf gate violated — investigate engine durations"

- alert: AxiomaPsiBelowThreshold
  expr: axioma_psi < 0.3
  for: 1m
  annotations:
    summary: "Boundary integrity ψ has dropped — compose-time integrity at risk"

- alert: AxiomaUncontrolledFeedback
  expr: increase(axioma_recovery_feedback_uncontrolled_total[24h]) > 0
  annotations:
    summary: "V13 uncontrolled-feedback event — recovery-compose oscillation"

- alert: AxiomaRecoveryRejectionRun
  expr: increase(axioma_rejection_run_warnings_total[1h]) > 0
  annotations:
    summary: "Q1 — substrate refusing recoveries; check coherence_budget"
```

### 6.4 HTML dashboard (v1.8.3)

For at-a-glance status without grepping logs or scripting `curl`, browse to `http://<host>:<http_port>/dashboard`. The page is self-contained (no external assets, no CDN dependency, no build step) and polls `/aos_g/self_check` every 3 seconds.

**What it shows:**
- **Overall status pill** (top right of header) — `ok` / `warmup` / `warning` / `off`, color-coded
- **Config** block — current MNEME compensations, normalize/auto-tune state, gap_weights
- **Engine state** block — current threshold, auto-tune fired count, normalize-ready flag, last reading beat
- **Per-organ contribution share** bar chart — visual confirmation the substrate is balanced (no organ dominating >60%)
- **Checks** list — every self-check check with its status pill + name + detail

Recommended use:
- Live monitoring during early operation: keep it open in a browser tab while the substrate warms up; the status pill flips from `warmup` to `ok` automatically once normalization stabilizes (~3000 beats).
- Post-deploy smoke check: visit once after a deploy to confirm `ok` status before declaring rollout complete.
- Incident triage: when an alert fires, the dashboard's checks list tells you which specific check failed without needing to parse JSON.

If the page shows `fetch failed`, the HTTP server is unreachable; check the AXIOMA process is running and the port is bound. If it shows `warmup` persistently past beat 3000, normalization isn't stabilizing — investigate `cfg.compose.aos_g_normalize_per_organ_*` settings or use `python -m axioma.tools.snapshot_inspect --current --component aos_g` to drill into the engine state.

### 6.5 Peer-conversation multi-peer mode (v1.9.0)

When multiple peers talk to AXIOMA simultaneously, `cfg.interface.peer_conversation_multi_peer_mode` controls how history is partitioned and how outbound replies are addressed.

| Mode | Behavior | When to use |
|---|---|---|
| `shared` (default) | One global conversation history across all peers. Outbound replies have no `to_speaker` field (v1.0–v1.8 wire format preserved). | Default — preserves prior behavior. Use when AXIOMA should participate in a single "town square" conversation visible to all peers, with each turn influencing every subsequent reply. |
| `per_peer` | Per-speaker history dict; each peer's turns only enter that peer's bucket. Outbound metadata always includes `to_speaker: <inbound_speaker>` for client-side filtering. | Use when peers should have isolated conversation contexts (peer A's question shouldn't influence AXIOMA's reply to peer B). Operators or downstream tools subscribing to the `conversation` channel can filter on `to_speaker`. |

**The `conversation` WS channel stays a public broadcast in both modes** — every subscriber receives every reply. In `per_peer` mode, the `to_speaker` field is a routing hint clients can use to filter their own UI. Server-side filtering (peers only receive messages addressed to them) is planned for v1.9.1.

**Configuration (YAML):**

```yaml
interface:
  peer_conversation_multi_peer_mode: per_peer  # or "shared" (default)
```

Unknown values raise `ValueError` at boot per the v1.6 boot-time-error idiom (no late failures during the first inbound message).

### 6.6 Subscribe options: `only_addressed_to_me` (v1.9.1)

When `peer_conversation_multi_peer_mode = per_peer` is configured, AXIOMA stamps outbound replies with `metadata.to_speaker = <inbound_speaker>`. v1.9.1 extends the WS `subscribe` message with an optional per-channel `options` block so subscribers can opt into **server-side filtering** of un-addressed messages — they receive only their own addressed replies plus any unaddressed broadcasts. This is the complement to v1.9.0's client-side filter approach.

**Wire format (extends the v1.0–v1.8 subscribe message):**

```json
{
  "type": "subscribe",
  "channels": ["conversation", "presence"],
  "options": {
    "conversation": {"only_addressed_to_me": true}
  }
}
```

The `options` field is optional and per-channel. Channels not mentioned in `options` (or sent by pre-v1.9.1 clients without an `options` field at all) behave as before — no filtering. Unknown flags within a channel's option dict are silently ignored (forward-compatible).

**Filter semantics:**

| Payload `metadata.to_speaker` value | With filter ON | With filter OFF (default) |
|---|---|---|
| Matches subscriber's `speaker` (handshake field) | ✓ delivered | ✓ delivered |
| Set, but matches a different speaker | ✗ dropped server-side | ✓ delivered |
| Absent (shared-mode broadcast / v1.0–v1.8 wire format) | ✓ delivered | ✓ delivered |

**Properties:**
- **Positive filter** — only drops when there's something to filter on. Subscribers using the filter still receive all unaddressed broadcasts, so they don't miss `shared`-mode replies when a deployment runs mixed-mode.
- **Toggleable without unsubscribe** — re-subscribing to the same channel with `only_addressed_to_me: false` clears the filter; the channel membership is unaffected.
- **Server-side drop is silent** — no rate-limit or coalescing slot is consumed; the dropped payload doesn't reach the subscriber's pending queue at all.

**When to use:**
- Operator dashboards monitoring a specific peer's conversation thread without seeing every peer's traffic.
- Multi-tenant peer wrappers that want clean per-tenant isolation at the wire level rather than client-side filtering.
- High-volume deployments where dropped payloads at the server save the subscriber's WS bandwidth.

**When NOT to use:**
- If you need to *audit* all conversation traffic, don't filter — subscribe without the option.
- If `peer_conversation_multi_peer_mode = shared` is configured, the filter is a no-op (no payload has `to_speaker`); leave the option off.

---

## 7. Common operations

### 7.1 Snapshot / restore

Snapshots fire automatically every `cfg.persistence.snapshot_period_beats` (default 600). They land under `cfg.persistence.snapshot_root` (default `data/state`).

**Force a snapshot:**

```python
# In an embedded use case
await app.take_snapshot()
```

**Restore on boot:** if the snapshot dir has a `current` symlink, the SnapshotManager picks it up automatically.

**Inspect snapshots from the command line (v1.8.0):**

```bash
# List all snapshots in the default root, sorted by name (timestamp-prefixed)
python -m axioma.tools.snapshot_inspect data/state/snapshots

# Inspect the `current` (latest) snapshot — manifest + component breakdown
python -m axioma.tools.snapshot_inspect data/state/snapshots --current

# Inspect a specific snapshot by name (e.g., after a `--list` shows it)
python -m axioma.tools.snapshot_inspect data/state/snapshots \
    --target 20260527_120000_beat_5000

# Dump a specific component's saved state (decoded JSON, pretty-printed)
python -m axioma.tools.snapshot_inspect data/state/snapshots \
    --current --component recovery_protocol

# Same drill-down on a specific snapshot
python -m axioma.tools.snapshot_inspect data/state/snapshots \
    --target 20260527_120000_beat_5000 --component aos_g
```

The CLI is read-only and does NOT boot the substrate — safe to run against in-flight or stopped-deployment snapshot directories. Exit codes: 0 = ok, 2 = error (missing root, missing manifest, corrupted manifest, missing component).

**Inspect recovery history + learner state (v1.8.1):**

The companion `recovery_inspect` CLI dives into the `recovery_protocol` component specifically — list events, drill into one by ID, or print the learner's current state:

```bash
# List the 20 most recent recovery events in the current snapshot
python -m axioma.tools.recovery_inspect data/state/snapshots

# Show only stage-3 events
python -m axioma.tools.recovery_inspect data/state/snapshots --stage 3

# Show only real (non-synthetic) events from a specific snapshot
python -m axioma.tools.recovery_inspect data/state/snapshots \
    --target 20260527_120000_beat_5000 --real

# Show full detail for an event by event_id prefix (first 8 chars usually unique)
python -m axioma.tools.recovery_inspect data/state/snapshots --event 2d81eebf

# Show learner state: current_params per stage + adoption/reversion counts
python -m axioma.tools.recovery_inspect data/state/snapshots --learner
```

If ROOT itself contains `recovery_protocol.json` (e.g., operator extracted a single snapshot dir), the CLI treats ROOT as the snapshot dir directly without needing `--current`. Same read-only / no-substrate-boot guarantees as `snapshot_inspect`.

**Inspect calibration session results (v1.8.2):**

After F6 / F8 calibration sessions complete (`POST /admin/calibration/session/end`), session results land at `results/phase_f/calibration_session_<id>.json`. The `calibration_inspect` CLI summarises and drills into them:

```bash
# List all calibration sessions (default action), most-recent first
python -m axioma.tools.calibration_inspect

# Show only zone (F6) sessions
python -m axioma.tools.calibration_inspect --kind zone

# Drill into one session by session_id prefix
python -m axioma.tools.calibration_inspect --session zone-abc

# Aggregate metric summary across all sessions (mean kappa for zone,
# mean accuracy for meta_cog, verdict distribution, task-type histogram)
python -m axioma.tools.calibration_inspect --summary

# Aggregate over zone-only sessions
python -m axioma.tools.calibration_inspect --summary --kind zone
```

ROOT defaults to `results/phase_f`; override with a positional argument. Read-only; safe to run during or after a live calibration cycle.

### 7.2 Pretrain the recovery learner

```bash
# F4 substrate-driven pretrain (recommended)
python scripts/phase_e_pretrain.py --scorer substrate -n 50 \
    -o data/state/recovery_learner_pretrain.json

# Or the lighter smooth-bell scorer for fast smoke
python scripts/phase_e_pretrain.py --scorer smooth-bell -n 50

# Then either restart AXIOMA (it auto-loads) or hit the admin endpoint:
curl -X POST http://localhost:8821/admin/recovery/learner/pretrain \
    -H "Authorization: Bearer ${AXIOMA_ADMIN_KEY}" \
    -d '{"target_events_per_stage": 50}'
```

### 7.3 Run a calibration session (F6 zone validation / F8 meta-cog)

```bash
# Start session
SESSION=$(curl -X POST http://localhost:8821/admin/calibration/session/start \
    -H "Authorization: Bearer ${AXIOMA_ADMIN_KEY}" \
    -d '{"kind": "zone", "task_type": "analytical", "duration_minutes": 60}' \
    | jq -r .data.session_id)

# Operator subscribes to WS channels they want to label from
# (theta, fragmentation, aos_g — but NOT meta_cognition for blind F8)

# Every 100 beats (~10s), operator submits a label
curl -X POST http://localhost:8821/admin/calibration/label \
    -H "Authorization: Bearer ${AXIOMA_ADMIN_KEY}" \
    -d '{"kind": "zone", "beat_no": 12500, "label": "focus"}'

# End session — writes results/phase_f/calibration_session_<id>.json
curl -X POST http://localhost:8821/admin/calibration/session/end \
    -H "Authorization: Bearer ${AXIOMA_ADMIN_KEY}" \
    -d '{"kind": "zone"}'
```

### 7.4 Manual perturbation (debug)

```bash
curl -X POST http://localhost:8821/admin/perturb \
    -H "Authorization: Bearer ${AXIOMA_ADMIN_KEY}" \
    -d '{"kind": "contradiction", "magnitude": 0.5, "tag": "manual_debug"}'
```

Perturbation kinds (full table in [src/axioma/measurement/perturbation_scheduler.py](../../src/axioma/measurement/perturbation_scheduler.py)):
- `contradiction` — EIDOLON negate
- `impulse` — drive spike (1-beat)
- `step` — ANIMA valence offset (20 beats)
- `novelty` — NOUS+ANIMA spike
- `attention` — PNEUMA offset
- `noise_burst` — drive Gaussian noise

### 7.5 Force recovery (testing only)

```bash
curl -X POST http://localhost:8821/admin/recovery/force \
    -H "Authorization: Bearer ${AXIOMA_ADMIN_KEY}" \
    -d '{"stage": 2, "force": true}'
```

### 7.6 Graceful shutdown via API

```bash
curl -X POST http://localhost:8821/admin/shutdown \
    -H "Authorization: Bearer ${AXIOMA_ADMIN_KEY}"
# Returns 200; subsequent admin requests get 503 "shutting_down"; process exits.
```

Or `kill -TERM <pid>` / `systemctl stop axioma` — same effect.

---

## 8. Failure modes

### 8.1 V11 perf gate violated (`beat_duration p95 > 100 ms`)

**Likely causes:**
- θ_long engine on CPU (should be GPU; check `nvidia-smi` for CUDA availability)
- raw MI batching disabled
- substrate spending too long in the iterative inner loop (N_iter too high)

**Action:**
- `GET /metrics` to identify the heavy engine via `axioma_engine_duration_seconds{engine}`
- Lower `cfg.substrate.n_iter` from 3 → 2
- Verify GPU presence: `python -c "from axioma.infra.gpu import gpu_info; print(gpu_info())"`

### 8.2 ψ drops below 0.3

**Likely causes:**
- Compose function returning degenerate output (gap variance near 0)
- structural_health failed (architectural violation — should never happen in production)
- compose_probe disagrees with current compose

**Action:**
- `GET /integrity` to see per-component breakdown
- Check WS handler imports (lint-imports should catch this at build time)
- If `gap_variance_health` is the dominator and the substrate is producing real diversity, check if `cfg.compose.aos_g_gap_weights` was set to all-zero (unlikely)

### 8.3 Recovery loop oscillation (`recovery_feedback_oscillation_detected`)

**Likely causes:**
- RecoveryLearner adopted aggressive params that destabilize the substrate
- coherence_budget thrashing between accept/reject

**Action:**
```bash
# Reset learner to safe defaults
curl -X POST http://localhost:8821/admin/recovery/learner/reset \
    -H "Authorization: Bearer ${AXIOMA_ADMIN_KEY}"

# Inspect learner state
curl http://localhost:8821/recovery/learner/efficacy
```

### 8.4 Q1 rejection-run warning (`recovery_rejected_run`)

**Cause:** RecoveryProtocol rejected 3 consecutive recovery_requests for the same fragmentation episode. Usually `REJECT_BUDGET_INSUFFICIENT` (coherence_budget too low).

**Action:**
- `GET /presence/rejection_warnings` to see the warning context
- `GET /fragmentation` to confirm substrate is still degraded
- Consider operator override: `POST /admin/recovery/force` with `{"force": true}`

### 8.5 Registry outage

**Action:** none required. AXIOMA continues in degraded mode (caches peer list from disk). When the registry returns, the heartbeat loop auto-reconnects with exponential backoff.

### 8.6 Snapshot write failure

**Cause:** disk full, permissions issue.

**Action:**
- Check `axioma_persistence_writes_total{target}` for stalled increments
- Check disk: `df -h $(grep snapshot_root configs/production.yaml | awk '{print $2}')`
- Verify perms: `ls -la /var/lib/axioma/state`

---

## 9. v1.3 migration (for existing v1.0/v1.1/v1.2 deployments)

v1.3 flipped two defaults — `aos_g_gap_weights` (None → PNEUMA_WEIGHTED) and `aos_g_alert_threshold` (0.1 → 0.152). For deployments that don't explicitly set these:

**Option A: Keep v1.0/v1.1/v1.2 behavior (zero risk)**

```bash
AXIOMA_CONFIG=configs/v1_0_backwards_compat.yaml python -m axioma
```

**Option B: Adopt v1.3 defaults (recommended for new deployments)**

Update downstream consumers/dashboards that have hardcoded `aos_g_gap` thresholds. The new PNEUMA-weighted gap baseline is ~1.52× larger (mean 10.89 vs 7.17 under uniform), so absolute thresholds need to scale.

Validate with a short soak first:
```bash
python scripts/phase_e_soak.py --beats 20000  # ~3.5 min
```

Full empirical justification + per-seed data in [RELEASE_v1.3.md](../../RELEASE_v1.3.md).

---

## 10. Troubleshooting

### `pydantic.ValidationError: Extra inputs are not permitted [config]`

You set `AXIOMA_CONFIG=path` and the loader interpreted it as a field. This was fixed in Checkpoint M; if you see it, update to v1.2.5+.

### `OllamaError: Ollama /api/chat 4xx` (peer conversation)

Check `OLLAMA_URL` env var and that the model name matches what's actually pulled:

```bash
ollama list   # should show deepseek-v4-flash:cloud + nomic-embed-text-v2-moe
```

### `RuntimeError: heartbeat tick failed: substrate must be initialised`

`AxiomaApp.start_services()` was called before `setup()`. Always:

```python
app = AxiomaApp(cfg)
await app.setup()
await app.start_services()
await app.run(...)
await app.shutdown()
```

`run()` calls `setup()` automatically if not already called.

### Heartbeat lags (`beat_overshoot` log entries)

Normal for the first 3-5 beats after boot (warmup latency). If persistent, see §8.1 V11 perf gate.

### HTTP server doesn't bind (`OSError: [Errno 98] Address already in use`)

Another instance is running, or a previous run didn't release the port. Find it:

```bash
ss -ltnp | grep 8821
# kill the stale process
```

The port-release-on-shutdown test ([test_http_server_shutdown_clean](../../tests/unit/test_axioma_app.py)) covers this — clean shutdowns release ports immediately.

### WebSocket subscriber stops receiving messages

Two likely causes:
1. **Slow consumer cutoff** — server force-closed after 5s of pending coalesced messages. Check WS server logs for `ws_slow_consumer`. Subscriber should reduce `min_interval_ms` or increase processing speed.
2. **Rate-limit exhaustion** — subscriber sent >100 inbound msgs/sec for 3 consecutive 1-second windows. Subscriber should batch its sends.

---

## 11. Where to find more

- **Per-release notes:** [RELEASE_v1.0.md](../../RELEASE_v1.0.md), [RELEASE_v1.2.md](../../RELEASE_v1.2.md), [RELEASE_v1.3.md](../../RELEASE_v1.3.md), [RELEASE_v1.4.md](../../RELEASE_v1.4.md), [RELEASE_v1.5.md](../../RELEASE_v1.5.md), [RELEASE_v1.6.md](../../RELEASE_v1.6.md), [RELEASE_v1.7.md](../../RELEASE_v1.7.md), [RELEASE_v1.8.md](../../RELEASE_v1.8.md), [RELEASE_v1.9.md](../../RELEASE_v1.9.md)
- **Architecture:** [design/ARCH_DESIGN_v1.0.md](../../design/ARCH_DESIGN_v1.0.md)
- **Implementation plan:** [design/IMPLEMENTATION_PLAN_v1.0.md](../../design/IMPLEMENTATION_PLAN_v1.0.md)
- **Per-session checkpoint history:** [design/IMPLEMENTATION_SCHEDULE.md](../../design/IMPLEMENTATION_SCHEDULE.md)
- **Phase F experiment results:** [results/phase_f/phase_f_summary.md](../../results/phase_f/phase_f_summary.md)
- **Multi-seed validation:** [results/phase_f/multi_seed_50k_summary.md](../../results/phase_f/multi_seed_50k_summary.md)

---

**Document version:** Generated at Checkpoint Q (2026-05-25). Update on each new release.
