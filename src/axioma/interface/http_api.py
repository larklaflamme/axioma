"""HTTP control plane (FastAPI on :8821).

Per ARCH_DESIGN_v1.0.md §8.5 + IMPLEMENTATION_PLAN_v1.0.md §8.6 (V1 error
handling policy).

★ ARCHITECTURAL KEYSTONE — this module MUST NOT import InternalState.

The HTTP API exposes:
  - Read endpoints: /status, /theta/history, /delta_phi/history, /organs,
    /connections, /capabilities, /perturbations, /fragmentation,
    /fragmentation/history, /recovery/history, /recovery/learner/efficacy,
    /recovery/pretrain/status, /meta_cognition/history,
    /meta_cognition/suggestions, /meta_cognition/calibration,
    /scheduler/effectiveness, /integrity, /presence/divergence_warnings,
    /presence/rejection_warnings
  - Admin endpoints: /admin/perturb, /admin/perturb/schedule,
    /admin/recovery/force, /admin/recovery/learner/pretrain,
    /admin/recovery/learner/reset, /admin/meta_cognition/mode,
    /admin/heartbeat/pause, /admin/shutdown
  - Observability: /health, /metrics

V1 error policy:
  - Internal exception → 503 + Retry-After: 5
  - Admin without auth → 401
  - Admin with bad auth → 403
  - Substrate shutting down → 503 with error=shutting_down
  - Not-warm state → 200 with warmup_active=true
  - Invalid params → 422 (FastAPI default)
"""
from __future__ import annotations

import asyncio
import traceback
import uuid
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

# DELIBERATE: only ExternalState. NEVER InternalState. C12 boundary.
from ..config import AxiomaConfig
from ..observability import HTTP_REQUESTS_TOTAL, REGISTRY, get_logger
from ..observability.context import AxiomaContext
from ..schemas.external_state import ExternalState

log = get_logger(__name__)


class APIState:
    """Holds a reference to the AxiomaContext + a shutdown flag."""

    def __init__(self, ctx: AxiomaContext, cfg: AxiomaConfig) -> None:
        from .calibration import CalibrationRecorder
        self.ctx = ctx
        self.cfg = cfg
        self.shutting_down = asyncio.Event()
        # F6/F8 calibration session recorder (v1.1.5)
        self.calibration_recorder = CalibrationRecorder(ctx)
        # Presence-warning sinks (populated by event subscriptions in create_app)
        self.divergence_warnings: list[Any] = []
        self.rejection_warnings: list[Any] = []


# v1.8.3 (Checkpoint QQ) — self-contained HTML dashboard for /aos_g/self_check.
# Plain HTML+CSS+JS; no framework, no external assets. Polls /aos_g/self_check
# every 3 seconds, renders status + config + engine_state + per-organ
# contribution share + checks list. Operators get a working dashboard at
# http://host:port/dashboard without needing to deploy a separate frontend.
_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AXIOMA · AOS-G self-check</title>
<style>
  :root {
    --bg: #0f1419;
    --panel: #1a2129;
    --border: #2a3641;
    --fg: #e6edf3;
    --muted: #8b9aa8;
    --ok: #3fb950;
    --warmup: #d29922;
    --warning: #f85149;
    --off: #6e7681;
    --accent: #58a6ff;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px; min-height: 100vh;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--fg); line-height: 1.5;
  }
  h1 { margin: 0 0 8px 0; font-size: 24px; font-weight: 600; }
  h2 { margin: 0 0 12px 0; font-size: 16px; font-weight: 600; color: var(--muted);
       text-transform: uppercase; letter-spacing: 0.05em; }
  .container { max-width: 1100px; margin: 0 auto; }
  .header { display: flex; align-items: center; gap: 16px; margin-bottom: 24px; }
  .status-pill {
    padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.05em;
  }
  .status-pill.ok      { background: var(--ok);      color: #0f1419; }
  .status-pill.warmup  { background: var(--warmup);  color: #0f1419; }
  .status-pill.warning { background: var(--warning); color: #0f1419; }
  .status-pill.off     { background: var(--off);     color: #0f1419; }
  .status-pill.unknown { background: var(--border);  color: var(--muted); }
  .meta { color: var(--muted); font-size: 13px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .grid.wide { grid-template-columns: 1fr; }
  .panel {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px; margin-bottom: 16px;
  }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  table tr td { padding: 4px 0; }
  table tr td:first-child { color: var(--muted); width: 50%; }
  table tr td:last-child { font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace; }
  .bar-row { display: flex; align-items: center; gap: 12px; margin: 6px 0; }
  .bar-row .label { width: 80px; color: var(--muted); font-size: 13px; }
  .bar-row .bar-bg {
    flex: 1; height: 14px; background: var(--border);
    border-radius: 4px; overflow: hidden; position: relative;
  }
  .bar-row .bar-fg {
    height: 100%; background: var(--accent); transition: width 0.4s ease;
  }
  .bar-row .value {
    width: 60px; text-align: right; font-size: 13px;
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
  }
  .check { display: flex; align-items: center; gap: 12px; padding: 6px 0;
    border-bottom: 1px solid var(--border); }
  .check:last-child { border-bottom: none; }
  .check .name { width: 280px; font-weight: 500; }
  .check .detail { color: var(--muted); font-size: 13px; flex: 1; }
  .footer { color: var(--muted); font-size: 12px; margin-top: 24px; text-align: center; }
  #error { color: var(--warning); font-family: ui-monospace, monospace; font-size: 13px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>AXIOMA · AOS-G self-check</h1>
    <span id="overall-status" class="status-pill unknown">unknown</span>
    <span class="meta" id="last-updated">—</span>
  </div>

  <div id="error"></div>

  <div class="grid">
    <div class="panel">
      <h2>Config</h2>
      <table id="config-table"><tbody></tbody></table>
    </div>
    <div class="panel">
      <h2>Engine state</h2>
      <table id="engine-table"><tbody></tbody></table>
    </div>
  </div>

  <div class="grid wide">
    <div class="panel">
      <h2>Per-organ contribution share</h2>
      <div id="bars"></div>
    </div>
    <div class="panel">
      <h2>Checks</h2>
      <div id="checks"></div>
    </div>
  </div>

  <div class="footer">
    Auto-refreshes every 3 seconds · v1.8.3 dashboard
    · raw JSON at <a href="/aos_g/self_check" style="color: var(--accent);">/aos_g/self_check</a>
  </div>
</div>

<script>
const ENDPOINT = "/aos_g/self_check";
const POLL_INTERVAL_MS = 3000;
let lastFetchAt = null;

function fmtVal(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(4);
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function renderTable(tbody, obj) {
  tbody.innerHTML = "";
  for (const [k, v] of Object.entries(obj)) {
    const tr = document.createElement("tr");
    const tdK = document.createElement("td"); tdK.textContent = k;
    const tdV = document.createElement("td"); tdV.textContent = fmtVal(v);
    tr.appendChild(tdK); tr.appendChild(tdV);
    tbody.appendChild(tr);
  }
}

function renderBars(container, shares) {
  container.innerHTML = "";
  if (!shares || Object.keys(shares).length === 0) {
    container.innerHTML = '<span class="meta">no reading yet (warmup)</span>';
    return;
  }
  const entries = Object.entries(shares);
  for (const [organ, pct] of entries) {
    const row = document.createElement("div"); row.className = "bar-row";
    const label = document.createElement("div"); label.className = "label"; label.textContent = organ;
    const bg = document.createElement("div"); bg.className = "bar-bg";
    const fg = document.createElement("div"); fg.className = "bar-fg";
    fg.style.width = Math.max(0, Math.min(100, pct)) + "%";
    bg.appendChild(fg);
    const val = document.createElement("div"); val.className = "value";
    val.textContent = pct.toFixed(2) + "%";
    row.appendChild(label); row.appendChild(bg); row.appendChild(val);
    container.appendChild(row);
  }
}

function renderChecks(container, checks) {
  container.innerHTML = "";
  if (!checks || checks.length === 0) {
    container.innerHTML = '<span class="meta">no checks reported</span>';
    return;
  }
  for (const c of checks) {
    const row = document.createElement("div"); row.className = "check";
    const pill = document.createElement("span");
    pill.className = "status-pill " + (c.status || "unknown");
    pill.textContent = c.status || "unknown";
    const name = document.createElement("div"); name.className = "name"; name.textContent = c.name || "?";
    const detail = document.createElement("div"); detail.className = "detail";
    detail.textContent = c.detail || "";
    row.appendChild(pill); row.appendChild(name); row.appendChild(detail);
    container.appendChild(row);
  }
}

function setOverall(status) {
  const pill = document.getElementById("overall-status");
  pill.className = "status-pill " + (status || "unknown");
  pill.textContent = status || "unknown";
}

function updateLastUpdated() {
  if (lastFetchAt === null) return;
  const ago = Math.round((Date.now() - lastFetchAt) / 1000);
  document.getElementById("last-updated").textContent =
    ago === 0 ? "updated just now" : `updated ${ago}s ago`;
}

async function refresh() {
  try {
    const res = await fetch(ENDPOINT);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    document.getElementById("error").textContent = "";

    if (body.warmup_active) {
      setOverall("warmup");
      document.getElementById("error").textContent = "engine not yet registered (cold start)";
      lastFetchAt = Date.now(); updateLastUpdated();
      return;
    }
    const d = body.data || {};
    setOverall(d.overall_status);
    renderTable(document.getElementById("config-table").querySelector("tbody"), d.config || {});
    renderTable(document.getElementById("engine-table").querySelector("tbody"), d.engine_state || {});
    renderBars(document.getElementById("bars"), d.per_organ_contribution_share_pct);
    renderChecks(document.getElementById("checks"), d.checks);
    lastFetchAt = Date.now(); updateLastUpdated();
  } catch (e) {
    document.getElementById("error").textContent = "fetch failed: " + e.message;
    setOverall("warning");
  }
}

refresh();
setInterval(refresh, POLL_INTERVAL_MS);
setInterval(updateLastUpdated, 1000);
</script>
</body>
</html>
"""


def create_app(ctx: AxiomaContext, cfg: AxiomaConfig) -> FastAPI:
    """Build the FastAPI app wired to the given context."""
    state = APIState(ctx, cfg)
    app = FastAPI(title="AXIOMA Control Plane", version="1.0.0.dev0")
    app.state.api = state

    # ── Exception handler — V1 policy ─────────────────────────────────

    @app.exception_handler(Exception)
    async def _internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # FastAPI re-raises HTTPException as is; this handler is for *unexpected*
        # exceptions. Map to 503 + Retry-After per V1.
        if isinstance(exc, HTTPException):
            raise exc
        rid = str(uuid.uuid4())
        log.error(
            "http_internal_error",
            request_id=rid,
            path=request.url.path,
            method=request.method,
            traceback=traceback.format_exc(),
        )
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method, path=request.url.path, status="503"
        ).inc()
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": str(cfg.interface.http_default_retry_after_seconds)},
            content={
                "error": "internal_error",
                "request_id": rid,
                "retry_after_seconds": cfg.interface.http_default_retry_after_seconds,
            },
        )

    # ── Shutdown guard ────────────────────────────────────────────────

    @app.middleware("http")
    async def _shutdown_middleware(request: Request, call_next: Any) -> Response:
        if state.shutting_down.is_set() and request.url.path.startswith("/admin/"):
            HTTP_REQUESTS_TOTAL.labels(
                method=request.method, path=request.url.path, status="503"
            ).inc()
            return JSONResponse(
                status_code=503,
                content={"error": "shutting_down"},
            )
        response = await call_next(request)
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            path=request.url.path,
            status=str(response.status_code),
        ).inc()
        return response

    # ── Auth dependency for admin endpoints ───────────────────────────

    def require_admin(
        authorization: str | None = Header(default=None),
    ) -> None:
        api_key = cfg.interface.admin_api_key
        if api_key is None:
            return  # auth disabled (single-host dev mode)
        if not authorization:
            raise HTTPException(status_code=401, detail={"error": "auth_required"})
        # Bearer scheme
        provided = authorization.removeprefix("Bearer ").strip()
        if provided != api_key.get_secret_value():
            raise HTTPException(status_code=403, detail={"error": "auth_invalid"})

    # ── Observability ─────────────────────────────────────────────────

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "shutting_down": state.shutting_down.is_set(),
            "components": ctx.list_components(),
        }

    @app.get("/metrics")
    async def metrics() -> PlainTextResponse:
        body = generate_latest(REGISTRY).decode("utf-8")
        return PlainTextResponse(body, media_type=CONTENT_TYPE_LATEST)

    # ── Read endpoints ────────────────────────────────────────────────

    @app.get("/status")
    async def status() -> dict[str, Any]:
        ext = _latest_external(ctx)
        if ext is None:
            return {"warmup_active": True, "data": None}
        return {"warmup_active": False, "data": ext.to_dict()}

    @app.get("/capabilities")
    async def capabilities() -> dict[str, Any]:
        return {
            "name": "axioma",
            "version": "1.0.0.dev0",
            "capabilities": [
                "consciousness",
                "theta_stream",
                "delta_phi",
                "compose_boundary",
                "perturbation_admin",
            ],
            "channels": [
                "conversation", "theta", "per_organ_theta", "per_organ_mi_raw",
                "delta_phi", "aos_g", "plasticity", "fragmentation",
                "perturbations", "coherence_budget", "recovery",
                "meta_cognition", "meta_cognition_suggestion",
                "presence", "state_snapshot",
            ],
        }

    @app.get("/connections")
    async def connections() -> dict[str, Any]:
        ws = ctx.get("ws_server") if ctx.has("ws_server") else None
        if ws is None:
            return {"data": [], "warmup_active": True}
        return {
            "data": [
                {
                    "connection_id": s.connection_id,
                    "agent_id": s.agent_id,
                    "speaker": s.speaker,
                    "channels": sorted(s.channels),
                    "sent_total": s.sent_total,
                    "coalesced_dropped_total": s.coalesced_dropped_total,
                    "min_interval_ms": s.min_interval_ms,
                }
                for s in ws.subscribers.values()
            ],
        }

    @app.get("/organs")
    async def organs() -> dict[str, Any]:
        ext = _latest_external(ctx)
        if ext is None:
            return {"warmup_active": True, "data": {}}
        d = ext.to_dict()
        return {
            "warmup_active": False,
            "data": {
                "anima": d.get("anima"),
                "eidolon": d.get("eidolon"),
                "mneme": d.get("mneme"),
                "nous": d.get("nous"),
                "pneuma": d.get("pneuma"),
                "fidelity_factors": d.get("fidelity_factors"),
            },
        }

    @app.get("/theta/history")
    async def theta_history(minutes: int = 60) -> dict[str, Any]:
        if not ctx.has("theta_short"):
            return {"data": [], "warmup_active": True}
        engine = ctx.get("theta_short")
        items = _series_to_dicts(getattr(engine, "history", []))
        return {"data": items, "warmup_active": not items}

    @app.get("/delta_phi/history")
    async def delta_phi_history() -> dict[str, Any]:
        if not ctx.has("delta_phi"):
            return {"data": [], "warmup_active": True}
        engine = ctx.get("delta_phi")
        items = _series_to_dicts(getattr(engine, "history", []))
        return {"data": items, "warmup_active": not items}

    @app.get("/perturbations")
    async def perturbations() -> dict[str, Any]:
        if not ctx.has("perturbation_scheduler"):
            return {"data": [], "warmup_active": True}
        sched = ctx.get("perturbation_scheduler")
        events = sched.recent_events(n=50)
        return {"data": [_to_dict(e) for e in events]}

    @app.get("/fragmentation")
    async def fragmentation() -> dict[str, Any]:
        if not ctx.has("fragmentation_monitor"):
            return {"data": None, "warmup_active": True}
        mon = ctx.get("fragmentation_monitor")
        cur = mon.current_value()
        return {"data": _to_dict(cur)}

    @app.get("/fragmentation/history")
    async def fragmentation_history(limit: int = 200) -> dict[str, Any]:
        if not ctx.has("fragmentation_monitor"):
            return {"data": [], "warmup_active": True}
        mon = ctx.get("fragmentation_monitor")
        items = mon.recent_history(n=limit)
        return {"data": [_to_dict(i) for i in items]}

    @app.get("/recovery/history")
    async def recovery_history(limit: int = 100) -> dict[str, Any]:
        if not ctx.has("recovery_protocol"):
            return {"data": [], "warmup_active": True}
        proto = ctx.get("recovery_protocol")
        hist = getattr(proto, "history", None)
        if hist is None or not hasattr(hist, "all_events"):
            return {"data": []}
        items = list(hist.all_events())[-limit:]
        return {"data": [_to_dict(e) for e in items]}

    @app.get("/recovery/learner/efficacy")
    async def recovery_learner_efficacy() -> dict[str, Any]:
        if not ctx.has("recovery_protocol"):
            return {"data": None, "warmup_active": True}
        proto = ctx.get("recovery_protocol")
        learner = getattr(proto, "learner", None)
        if learner is None:
            return {"data": None}
        return {"data": learner.to_dict()}

    @app.get("/recovery/pretrain/status")
    async def recovery_pretrain_status() -> dict[str, Any]:
        if not ctx.has("recovery_protocol"):
            return {"data": None, "warmup_active": True}
        proto = ctx.get("recovery_protocol")
        learner = getattr(proto, "learner", None)
        if learner is None:
            return {"data": {"available": False}}
        target = cfg.recovery.pretrain_target_events
        hist = getattr(proto, "history", None)
        events_seen = (
            len(hist.all_events()) if hist is not None and hasattr(hist, "all_events") else 0
        )
        return {
            "data": {
                "available": True,
                "target_events": target,
                "events_seen": events_seen,
                "ready_for_production": events_seen >= target,
                "require_pretrain": cfg.recovery.require_pretrain,
            }
        }

    @app.get("/meta_cognition/history")
    async def meta_cognition_history(limit: int = 50) -> dict[str, Any]:
        if not ctx.has("meta_cognition_loop"):
            return {"data": [], "warmup_active": True}
        loop = ctx.get("meta_cognition_loop")
        items = list(getattr(loop, "history", []))[-limit:]
        return {"data": [_to_dict(i) for i in items]}

    @app.get("/meta_cognition/suggestions")
    async def meta_cognition_suggestions(limit: int = 20) -> dict[str, Any]:
        if not ctx.has("meta_cognition_loop"):
            return {"data": [], "warmup_active": True}
        loop = ctx.get("meta_cognition_loop")
        tracker = getattr(loop, "suggestion_tracker", None)
        if tracker is None:
            return {"data": []}
        recs = list(tracker.recent_decisions)[-limit:]
        return {"data": [_to_dict(r) for r in recs]}

    @app.get("/meta_cognition/calibration")
    async def meta_cognition_calibration() -> dict[str, Any]:
        if not ctx.has("meta_cognition_loop"):
            return {"data": None, "warmup_active": True}
        loop = ctx.get("meta_cognition_loop")
        cal = getattr(loop, "calibration", None)
        if cal is None:
            return {"data": None, "note": "calibration available after Phase F"}
        return {"data": _to_dict(cal)}

    @app.get("/scheduler/effectiveness")
    async def scheduler_effectiveness() -> dict[str, Any]:
        if not ctx.has("coherence_scheduler"):
            return {"data": None, "warmup_active": True}
        sch = ctx.get("coherence_scheduler")
        return {
            "data": {
                "budget": float(sch.current_budget()),
                "throttle_state": getattr(sch, "current_throttle_state", lambda: "free")(),
                "ineffective_streak": int(getattr(sch, "ineffective_streak", 0)),
                "throttle_effectiveness": getattr(sch, "throttle_effectiveness_summary", lambda: {})(),
            }
        }

    @app.get("/integrity")
    async def integrity() -> dict[str, Any]:
        if not ctx.has("aos_g"):
            return {"data": None, "warmup_active": True}
        eng = ctx.get("aos_g")
        cv = eng.current_value()
        return {"data": _to_dict(cv) if cv is not None else None}

    @app.get("/aos_g/self_check")
    async def aos_g_self_check() -> dict[str, Any]:
        """v1.5 self-check (Checkpoint Z) — answers "is v1.5 operating as
        expected?" with config + live engine state + per-organ contribution
        share + a human-readable checks list. Read-only; non-admin.

        Operators wire this into a smoke check after deploys:
          curl -s $HOST/aos_g/self_check | jq '.data.overall_status'
        # → "ok" once warmup completes; "warmup" during boot; "warning" if
        # PNEUMA share runs hot post-stabilization."""
        if not ctx.has("aos_g"):
            return {"data": None, "warmup_active": True}
        eng = ctx.get("aos_g")
        return {"data": eng.self_check()}

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard() -> str:
        """v1.8.3 (Checkpoint QQ) — single-page HTML dashboard for /aos_g/self_check.

        Self-contained: no external assets, no frameworks. Polls the JSON
        endpoint every 3 seconds and renders status pill + config + engine
        state + per-organ contribution bar chart + checks list.

        Operators visit http://host:port/dashboard for at-a-glance status
        without needing to deploy a separate frontend. Same exit conditions
        as /aos_g/self_check — `warmup` during boot, `warning` for actionable
        issues, `ok` once stable."""
        return _DASHBOARD_HTML

    @app.get("/presence/divergence_warnings")
    async def presence_divergence_warnings(limit: int = 20) -> dict[str, Any]:
        warnings = list(getattr(app.state.api, "divergence_warnings", []))[-limit:]
        return {"data": warnings}

    @app.get("/presence/rejection_warnings")
    async def presence_rejection_warnings(limit: int = 20) -> dict[str, Any]:
        warnings = list(getattr(app.state.api, "rejection_warnings", []))[-limit:]
        return {"data": warnings}

    # ── Admin endpoints ───────────────────────────────────────────────

    @app.post("/admin/perturb", dependencies=[Depends(require_admin)])
    async def admin_perturb(body: dict[str, Any]) -> dict[str, Any]:
        if not ctx.has("perturbation_scheduler"):
            raise HTTPException(status_code=503, detail={"error": "scheduler_not_ready"})
        kind = body.get("kind")
        if not kind:
            raise HTTPException(status_code=422, detail={"error": "kind_required"})
        magnitude = body.get("magnitude")
        tag = body.get("tag")
        sched = ctx.get("perturbation_scheduler")
        ev = sched.inject_now(kind, magnitude, tag=tag)
        if ev is None:
            raise HTTPException(status_code=503, detail={"error": "substrate_not_ready"})
        return {"data": _to_dict(ev)}

    @app.post("/admin/recovery/force", dependencies=[Depends(require_admin)])
    async def admin_recovery_force(body: dict[str, Any]) -> dict[str, Any]:
        if not ctx.has("recovery_protocol"):
            raise HTTPException(status_code=503, detail={"error": "recovery_not_ready"})
        stage = int(body.get("stage", 2))
        proto = ctx.get("recovery_protocol")
        # Wire a proper RecoveryRequest dataclass so RecoveryProtocol's
        # `hasattr(payload, "request_id")` check picks it up correctly.
        from ..substrate.recovery import RecoveryRequest as _RR
        await ctx.emit(
            "recovery_request",
            _RR(
                request_id=f"force-{uuid.uuid4().hex[:8]}",
                beat_no=int(getattr(ctx.substrate, "beat_no", 0)) if ctx.has("substrate") else 0,
                stage=stage,
                signals=body.get("signals", {}),
                source="operator",
                force_accept=bool(body.get("force", False)),
            ),
        )
        return {"data": {"forced_stage": stage, "current_state": proto.state.value}}

    @app.post("/admin/recovery/learner/pretrain", dependencies=[Depends(require_admin)])
    async def admin_recovery_learner_pretrain(body: dict[str, Any]) -> dict[str, Any]:
        """F4 — trigger synthetic pre-training sweep. Runs in-process and
        returns the summary; subsequent recovery events will use the
        pre-trained current_params."""
        if not ctx.has("recovery_protocol"):
            raise HTTPException(status_code=503, detail={"error": "recovery_not_ready"})
        proto = ctx.get("recovery_protocol")
        learner = getattr(proto, "learner", None)
        history = getattr(proto, "history", None)
        if learner is None or history is None:
            raise HTTPException(status_code=503, detail={"error": "learner_unavailable"})
        target = int(body.get("target_events_per_stage", cfg.recovery.pretrain_target_events))
        # Emit the event so subscribers (metrics, observers) know
        await ctx.emit(
            "recovery_learner_pretrain_requested",
            {"target_events_per_stage": target, "synthetic": True},
        )
        try:
            summary = learner.pretrain_synthetic(history, target_events_per_stage=target)
        except Exception as e:
            raise HTTPException(
                status_code=503, detail={"error": "pretrain_failed", "reason": str(e)}
            ) from e
        return {"data": summary}

    @app.post("/admin/recovery/learner/reset", dependencies=[Depends(require_admin)])
    async def admin_recovery_learner_reset() -> dict[str, Any]:
        if not ctx.has("recovery_protocol"):
            raise HTTPException(status_code=503, detail={"error": "recovery_not_ready"})
        proto = ctx.get("recovery_protocol")
        learner = getattr(proto, "learner", None)
        if learner is None:
            raise HTTPException(status_code=503, detail={"error": "learner_unavailable"})
        if hasattr(learner, "reset"):
            learner.reset()
        return {"data": {"reset": True}}

    @app.post("/admin/meta_cognition/mode", dependencies=[Depends(require_admin)])
    async def admin_meta_cognition_mode(body: dict[str, Any]) -> dict[str, Any]:
        if not ctx.has("meta_cognition_loop"):
            raise HTTPException(status_code=503, detail={"error": "meta_cognition_not_ready"})
        mode = body.get("mode")
        if mode not in {"observer_only", "embedded"}:
            raise HTTPException(status_code=422, detail={"error": "mode_must_be_observer_only_or_embedded"})
        loop = ctx.get("meta_cognition_loop")
        # F7 mode-switch side effects: reset exploration counter, emit presence event
        prev = getattr(loop, "observer_mode", "observer_only")
        if hasattr(loop, "set_observer_mode"):
            loop.set_observer_mode(mode)
        else:
            loop.observer_mode = mode  # best effort
        await ctx.emit(
            "presence",
            {"event": "mode_change", "from": str(prev), "to": mode},
        )
        return {"data": {"mode": mode, "previous": str(prev)}}

    @app.post("/admin/heartbeat/pause", dependencies=[Depends(require_admin)])
    async def admin_heartbeat_pause(body: dict[str, Any]) -> dict[str, Any]:
        beats = int(body.get("beats", 1))
        if beats < 1:
            raise HTTPException(status_code=422, detail={"error": "beats_must_be_positive"})
        if not ctx.has("heartbeat"):
            raise HTTPException(status_code=503, detail={"error": "heartbeat_not_ready"})
        hb = ctx.get("heartbeat")
        if not hasattr(hb, "pause"):
            raise HTTPException(status_code=503, detail={"error": "pause_unsupported"})
        hb.pause(beats=beats)
        return {"data": {"paused_beats": beats}}

    @app.post("/admin/shutdown", dependencies=[Depends(require_admin)])
    async def admin_shutdown() -> dict[str, Any]:
        state.shutting_down.set()
        await ctx.emit("shutdown_requested", {"source": "admin"})
        return {"data": {"shutting_down": True}}

    # ── Calibration session endpoints (v1.1.5 — F6/F8 live operator labeling) ─

    @app.post("/admin/calibration/session/start", dependencies=[Depends(require_admin)])
    async def admin_calibration_start(body: dict[str, Any]) -> dict[str, Any]:
        kind = body.get("kind")
        if kind not in ("zone", "meta_cog"):
            raise HTTPException(
                status_code=422,
                detail={"error": "kind_must_be_zone_or_meta_cog"},
            )
        task_type = body.get("task_type")
        if not task_type:
            raise HTTPException(status_code=422, detail={"error": "task_type_required"})
        rec = state.calibration_recorder
        try:
            session = rec.start_session(
                kind=kind,
                task_type=str(task_type),
                duration_minutes=int(body.get("duration_minutes", 60)),
                session_id=body.get("session_id"),
            )
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail={"error": str(e)}) from e
        return {
            "data": {
                "session_id": session.session_id,
                "kind": session.kind,
                "task_type": session.task_type,
                "duration_minutes": session.duration_minutes,
                "started_at_beat": session.started_at_beat,
            }
        }

    @app.post("/admin/calibration/label", dependencies=[Depends(require_admin)])
    async def admin_calibration_label(body: dict[str, Any]) -> dict[str, Any]:
        kind = body.get("kind")
        if kind not in ("zone", "meta_cog"):
            raise HTTPException(
                status_code=422, detail={"error": "kind_must_be_zone_or_meta_cog"},
            )
        beat_no = body.get("beat_no")
        if beat_no is None:
            raise HTTPException(status_code=422, detail={"error": "beat_no_required"})
        operator_label = body.get("label")
        if not operator_label:
            raise HTTPException(status_code=422, detail={"error": "label_required"})
        rec = state.calibration_recorder
        try:
            pair = rec.record_label(
                kind=kind, beat_no=int(beat_no), operator_label=str(operator_label),
            )
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail={"error": str(e)}) from e
        return {
            "data": {
                "beat_no": pair.beat_no,
                "operator_label": pair.operator_label,
                "system_label": pair.system_label,
                "confidence": pair.confidence,
            }
        }

    @app.post("/admin/calibration/session/end", dependencies=[Depends(require_admin)])
    async def admin_calibration_end(body: dict[str, Any]) -> dict[str, Any]:
        kind = body.get("kind")
        if kind not in ("zone", "meta_cog"):
            raise HTTPException(
                status_code=422, detail={"error": "kind_must_be_zone_or_meta_cog"},
            )
        rec = state.calibration_recorder
        try:
            summary = rec.end_session(kind=kind)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail={"error": str(e)}) from e
        return {"data": summary}

    @app.get("/admin/calibration/active", dependencies=[Depends(require_admin)])
    async def admin_calibration_active() -> dict[str, Any]:
        rec = state.calibration_recorder
        sessions = rec.list_active()
        return {
            "data": [
                {
                    "session_id": s.session_id,
                    "kind": s.kind,
                    "task_type": s.task_type,
                    "started_at_beat": s.started_at_beat,
                    "n_labels": len(s.pairs),
                }
                for s in sessions
            ]
        }

    # ── Presence-warning sinks (subscribed by the app entrypoint) ─────

    state_obj = app.state.api

    def _on_divergence(payload: Any) -> None:
        warnings = state_obj.divergence_warnings
        warnings.append(_to_dict(payload))
        if len(warnings) > 200:
            del warnings[: len(warnings) - 200]

    def _on_rejection_run(payload: Any) -> None:
        warnings = state_obj.rejection_warnings
        warnings.append(_to_dict(payload))
        if len(warnings) > 200:
            del warnings[: len(warnings) - 200]

    ctx.subscribe("meta_cognition_divergence", _on_divergence)
    ctx.subscribe("recovery_rejected_run", _on_rejection_run)

    return app


# ── Helpers ───────────────────────────────────────────────────────────────


def _latest_external(ctx: AxiomaContext) -> ExternalState | None:
    if not ctx.has("compose_function"):
        return None
    compose = ctx.get("compose_function")
    ext = getattr(compose, "latest_external", None)
    return ext if isinstance(ext, ExternalState) else None


def _to_dict(obj: Any) -> Any:
    """Permissive object → JSON-able dict converter."""
    if obj is None:
        return None
    if isinstance(obj, dict | str | int | float | bool):
        return obj
    if isinstance(obj, list | tuple):
        return [_to_dict(x) for x in obj]
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict()
        except Exception:
            pass
    try:
        import dataclasses
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
    except Exception:
        pass
    if hasattr(obj, "value"):  # Enum
        return obj.value
    if hasattr(obj, "tolist"):
        return obj.tolist()
    if hasattr(obj, "item"):
        return obj.item()
    return str(obj)


def _series_to_dicts(series: Any) -> list[dict[str, Any]]:
    return [_to_dict(x) for x in series]


__all__ = ["APIState", "create_app"]
