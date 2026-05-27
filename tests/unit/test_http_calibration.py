"""HTTP /admin/calibration/* endpoints (v1.1.5)."""
from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from axioma.config import AxiomaConfig
from axioma.interface import create_app
from axioma.observability import AxiomaContext
from axioma.schemas import Zone
from axioma.schemas.external_state import ExternalState


def _client_with_zone(zone: Zone = Zone.FOCUS) -> TestClient:
    ctx = AxiomaContext()
    ext = ExternalState(
        anima=np.zeros(4, dtype=np.float32),
        eidolon=np.zeros(6, dtype=np.float32),
        mneme=np.zeros(5, dtype=np.float32),
        nous=np.zeros(6, dtype=np.float32),
        pneuma=np.zeros(7, dtype=np.float32),
        beat_no=100, timestamp=1.0,
    )
    ext.zone = zone

    class _MockCompose:
        latest_external = ext
    ctx.register("compose_function", _MockCompose())
    ctx.register("heartbeat", type("HB", (), {"beat_no": 100})())
    app = create_app(ctx, AxiomaConfig())
    return TestClient(app)


def test_session_start_returns_session_id() -> None:
    client = _client_with_zone()
    r = client.post(
        "/admin/calibration/session/start",
        json={"kind": "zone", "task_type": "analytical", "duration_minutes": 30},
    )
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["kind"] == "zone"
    assert body["task_type"] == "analytical"
    assert body["duration_minutes"] == 30
    assert body["started_at_beat"] == 100
    assert body["session_id"]


def test_session_start_validates_kind() -> None:
    client = _client_with_zone()
    r = client.post(
        "/admin/calibration/session/start",
        json={"kind": "bogus", "task_type": "x"},
    )
    assert r.status_code == 422


def test_session_start_requires_task_type() -> None:
    client = _client_with_zone()
    r = client.post(
        "/admin/calibration/session/start",
        json={"kind": "zone"},
    )
    assert r.status_code == 422


def test_full_zone_session_flow() -> None:
    client = _client_with_zone(zone=Zone.FOCUS)
    r = client.post(
        "/admin/calibration/session/start",
        json={"kind": "zone", "task_type": "x"},
    )
    assert r.status_code == 200
    # Record a label
    r2 = client.post(
        "/admin/calibration/label",
        json={"kind": "zone", "beat_no": 100, "label": "focus"},
    )
    assert r2.status_code == 200
    body = r2.json()["data"]
    assert body["operator_label"] == "focus"
    assert body["system_label"] == "focus"
    # End session
    r3 = client.post(
        "/admin/calibration/session/end",
        json={"kind": "zone"},
    )
    assert r3.status_code == 200
    summary = r3.json()["data"]
    assert summary["agreements"] == 1
    assert summary["n_pairs"] == 1


def test_double_start_returns_409() -> None:
    client = _client_with_zone()
    client.post("/admin/calibration/session/start",
                json={"kind": "zone", "task_type": "x"})
    r = client.post("/admin/calibration/session/start",
                    json={"kind": "zone", "task_type": "y"})
    assert r.status_code == 409


def test_label_without_session_returns_409() -> None:
    client = _client_with_zone()
    r = client.post("/admin/calibration/label",
                    json={"kind": "zone", "beat_no": 100, "label": "focus"})
    assert r.status_code == 409


def test_label_missing_fields_422() -> None:
    client = _client_with_zone()
    client.post("/admin/calibration/session/start",
                json={"kind": "zone", "task_type": "x"})
    r = client.post("/admin/calibration/label", json={"kind": "zone"})
    assert r.status_code == 422
    r = client.post("/admin/calibration/label",
                    json={"kind": "zone", "beat_no": 1})
    assert r.status_code == 422


def test_active_endpoint_lists_running_sessions() -> None:
    client = _client_with_zone()
    r0 = client.get("/admin/calibration/active")
    assert r0.json()["data"] == []
    client.post("/admin/calibration/session/start",
                json={"kind": "zone", "task_type": "x"})
    client.post("/admin/calibration/session/start",
                json={"kind": "meta_cog", "task_type": "y"})
    r = client.get("/admin/calibration/active")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 2
    kinds = {s["kind"] for s in data}
    assert kinds == {"zone", "meta_cog"}


def test_end_session_without_active_returns_409() -> None:
    client = _client_with_zone()
    r = client.post("/admin/calibration/session/end", json={"kind": "zone"})
    assert r.status_code == 409
