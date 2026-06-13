"""HTTP API — endpoint shapes + V1 error policy (no live network)."""
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr

from axioma.config import AxiomaConfig, InterfaceConfig
from axioma.interface import create_app
from axioma.observability import AxiomaContext


def _client(ctx: AxiomaContext, cfg: AxiomaConfig | None = None) -> TestClient:
    if cfg is None:
        cfg = AxiomaConfig()
    app = create_app(ctx, cfg)
    return TestClient(app)


def test_health_ok_no_components() -> None:
    ctx = AxiomaContext()
    client = _client(ctx)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["shutting_down"] is False


def test_metrics_returns_prometheus_text() -> None:
    ctx = AxiomaContext()
    client = _client(ctx)
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "axioma_beat_duration_seconds" in r.text


def test_capabilities_reports_agora_comms() -> None:
    ctx = AxiomaContext()
    client = _client(ctx)
    r = client.get("/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert "theta_stream" in body["capabilities"]
    # Communication now runs over The Agora (ACP/1.1), not an in-house channel
    # multiplexer — /capabilities advertises the hub instead of a channel list.
    assert body["comms"] == {"hub": "agora", "protocol": "ACP/1.1"}


def test_status_warmup_when_no_compose() -> None:
    ctx = AxiomaContext()
    client = _client(ctx)
    r = client.get("/status")
    assert r.status_code == 200
    body = r.json()
    assert body["warmup_active"] is True
    assert body["data"] is None


def test_status_full_when_compose_warm() -> None:
    """Wire a mock compose_function with a latest_external; expect full data."""
    import numpy as np

    from axioma.schemas.external_state import ExternalState
    ctx = AxiomaContext()

    class _MockCompose:
        def __init__(self) -> None:
            self.latest_external = ExternalState(
                anima=np.zeros(4, dtype=np.float32),
                eidolon=np.zeros(6, dtype=np.float32),
                mneme=np.zeros(5, dtype=np.float32),
                nous=np.zeros(6, dtype=np.float32),
                pneuma=np.zeros(7, dtype=np.float32),
                beat_no=100,
                timestamp=1.0,
            )
            self.latest_external.theta_short = 1.23

    ctx.register("compose_function", _MockCompose())
    client = _client(ctx)
    r = client.get("/status")
    assert r.status_code == 200
    body = r.json()
    assert body["warmup_active"] is False
    assert body["data"]["theta_short"] == 1.23
    assert body["data"]["beat_no"] == 100


def test_perturb_admin_requires_kind() -> None:
    """422 if `kind` missing — V1 invalid params policy."""
    ctx = AxiomaContext()

    class _MockSched:
        def inject_now(self, *a: Any, **kw: Any) -> Any:
            return None
    ctx.register("perturbation_scheduler", _MockSched())
    client = _client(ctx)
    r = client.post("/admin/perturb", json={})
    assert r.status_code == 422
    assert r.json()["detail"] == {"error": "kind_required"}


def test_perturb_admin_dispatches() -> None:
    ctx = AxiomaContext()
    seen: list[Any] = []

    class _MockSched:
        def inject_now(self, kind: str, magnitude: Any = None, *, tag: Any = None) -> Any:
            seen.append((kind, magnitude, tag))
            return {"event_id": "evt1", "kind": kind, "magnitude": magnitude}
    ctx.register("perturbation_scheduler", _MockSched())
    client = _client(ctx)
    r = client.post("/admin/perturb", json={"kind": "contradiction", "magnitude": 0.5})
    assert r.status_code == 200
    assert r.json()["data"]["event_id"] == "evt1"
    assert seen == [("contradiction", 0.5, None)]


def test_admin_auth_required_when_configured() -> None:
    ctx = AxiomaContext()

    class _MockSched:
        def inject_now(self, *a: Any, **kw: Any) -> Any:
            return {"event_id": "x"}
    ctx.register("perturbation_scheduler", _MockSched())
    cfg = AxiomaConfig(interface=InterfaceConfig(admin_api_key=SecretStr("hush")))
    client = _client(ctx, cfg)
    # No header → 401
    r = client.post("/admin/perturb", json={"kind": "step"})
    assert r.status_code == 401
    # Wrong header → 403
    r = client.post(
        "/admin/perturb",
        json={"kind": "step"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 403
    # Correct → 200
    r = client.post(
        "/admin/perturb",
        json={"kind": "step"},
        headers={"Authorization": "Bearer hush"},
    )
    assert r.status_code == 200


def test_shutdown_then_admin_returns_503() -> None:
    ctx = AxiomaContext()

    class _MockSched:
        def inject_now(self, *a: Any, **kw: Any) -> Any:
            return {"event_id": "x"}
    ctx.register("perturbation_scheduler", _MockSched())
    client = _client(ctx)
    r = client.post("/admin/shutdown")
    assert r.status_code == 200
    assert r.json()["data"]["shutting_down"] is True
    r = client.post("/admin/perturb", json={"kind": "step"})
    assert r.status_code == 503
    assert r.json()["error"] == "shutting_down"


def test_internal_error_returns_503_with_retry_after() -> None:
    """V1: unexpected handler exception → 503 + Retry-After: 5."""
    ctx = AxiomaContext()

    class _MockSched:
        def inject_now(self, *a: Any, **kw: Any) -> Any:
            raise RuntimeError("boom")
    ctx.register("perturbation_scheduler", _MockSched())
    cfg = AxiomaConfig()
    app = create_app(ctx, cfg)
    # raise_server_exceptions=False lets the registered Exception handler run
    # in tests (in production starlette's middleware does this automatically).
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/admin/perturb", json={"kind": "step"})
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "5"
    body = r.json()
    assert body["error"] == "internal_error"
    assert "request_id" in body
    assert body["retry_after_seconds"] == 5


def test_meta_cognition_mode_validates_value() -> None:
    ctx = AxiomaContext()

    class _MockMC:
        observer_mode = "observer_only"
        def set_observer_mode(self, m: str) -> None:
            self.observer_mode = m
    ctx.register("meta_cognition_loop", _MockMC())
    client = _client(ctx)
    r = client.post("/admin/meta_cognition/mode", json={"mode": "bogus"})
    assert r.status_code == 422
    r = client.post("/admin/meta_cognition/mode", json={"mode": "embedded"})
    assert r.status_code == 200
    assert r.json()["data"]["mode"] == "embedded"


def test_heartbeat_pause_invokes_method() -> None:
    ctx = AxiomaContext()
    pauses: list[int] = []

    class _MockHB:
        def pause(self, *, beats: int) -> None:
            pauses.append(beats)
    ctx.register("heartbeat", _MockHB())
    client = _client(ctx)
    r = client.post("/admin/heartbeat/pause", json={"beats": 2})
    assert r.status_code == 200
    assert pauses == [2]
    # Bad input
    r = client.post("/admin/heartbeat/pause", json={"beats": 0})
    assert r.status_code == 422


def test_warmup_endpoints_return_warmup_flag() -> None:
    ctx = AxiomaContext()
    client = _client(ctx)
    for path in (
        "/status",
        "/perturbations",
        "/fragmentation",
        "/recovery/history",
        "/meta_cognition/history",
        "/integrity",
    ):
        r = client.get(path)
        assert r.status_code == 200, f"{path} returned {r.status_code}"
        body = r.json()
        assert body.get("warmup_active") is True, f"{path} should be warmup-active"


def test_presence_divergence_warnings_capture_events() -> None:
    ctx = AxiomaContext()
    client = _client(ctx)
    # After create_app subscribed to the bus
    import asyncio
    asyncio.run(ctx.emit("meta_cognition_divergence", {"beat_no": 100, "ignored": 5}))
    r = client.get("/presence/divergence_warnings")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) >= 1
    assert data[-1]["beat_no"] == 100


def test_recovery_force_emits_event() -> None:
    ctx = AxiomaContext()
    seen: list[Any] = []

    class _MockRP:
        class _State:
            value = "baseline"
        state = _State()

    ctx.register("recovery_protocol", _MockRP())
    ctx.register("substrate", type("S", (), {"beat_no": 100})())
    ctx.subscribe("recovery_request", lambda p: seen.append(p))
    client = _client(ctx)
    r = client.post("/admin/recovery/force", json={"stage": 3})
    assert r.status_code == 200
    assert seen and seen[0].stage == 3
    assert seen[0].source == "operator"  # admin uses operator literal


# ── v1.8.3 (Checkpoint QQ) — /dashboard HTML endpoint ────────────────────


def test_v1_8_3_dashboard_returns_html() -> None:
    """GET /dashboard returns HTML with the right content-type."""
    ctx = AxiomaContext()
    client = _client(ctx)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<!DOCTYPE html>" in r.text


def test_v1_8_3_dashboard_html_is_self_contained() -> None:
    """The dashboard HTML must be self-contained: no external <link>/<script src> tags.
    Operators rely on it working offline (no CDN, no npm)."""
    ctx = AxiomaContext()
    client = _client(ctx)
    r = client.get("/dashboard")
    html = r.text
    # No external script/link tags
    assert '<link rel="stylesheet"' not in html
    assert '<script src=' not in html
    # Inline style + script blocks present
    assert "<style>" in html
    assert "<script>" in html


def test_v1_8_3_dashboard_polls_correct_endpoint() -> None:
    """The dashboard JS must reference /aos_g/self_check as its data source.
    A typo or hardcoded wrong endpoint would silently break the dashboard."""
    ctx = AxiomaContext()
    client = _client(ctx)
    r = client.get("/dashboard")
    assert '/aos_g/self_check' in r.text


def test_v1_8_3_dashboard_lists_expected_status_classes() -> None:
    """The CSS must define all 4 status colors (ok / warmup / warning / off)
    that the self-check endpoint can emit."""
    ctx = AxiomaContext()
    client = _client(ctx)
    html = client.get("/dashboard").text
    assert ".status-pill.ok" in html
    assert ".status-pill.warmup" in html
    assert ".status-pill.warning" in html
    assert ".status-pill.off" in html


def test_v1_8_3_dashboard_works_alongside_self_check_endpoint() -> None:
    """Dashboard and self_check live in the same FastAPI app and don't conflict.
    Both should respond independently."""
    ctx = AxiomaContext()
    client = _client(ctx)
    r1 = client.get("/dashboard")
    r2 = client.get("/aos_g/self_check")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.headers["content-type"].startswith("text/html")
    assert r2.headers["content-type"].startswith("application/json")
