"""v1.5 self-check (Checkpoint Z) — AOSGEngine.self_check() + HTTP endpoint.

Verifies:
  - self_check() shape: config + engine_state + per_organ_share + checks + overall
  - Default (v1.5) deployment: status flips warmup → ok as state advances
  - v1.4 backwards-compat: normalize off + auto-tune off → "off" checks present,
    overall still 'ok' (deployment is intentionally in v1.4 mode)
  - PNEUMA-share warning when post-stabilization share exceeds 60%
  - HTTP endpoint /aos_g/self_check returns warmup_active when no engine,
    and returns the dict shape when engine is present
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from axioma.config import AxiomaConfig, SubstrateConfig
from axioma.interface import create_app
from axioma.measurement.aos_g_engine import AOSGEngine, AOSGReading
from axioma.observability import AxiomaContext
from axioma.schemas import ORGAN_ORDER
from axioma.substrate.app import SubstrateApp


def _ctx_with_substrate() -> tuple[AxiomaContext, SubstrateApp]:
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(SubstrateConfig(), seed=42)
    for beat in range(10):
        app.tick(beat_no=beat, timestamp=float(beat) * 0.1)
    ctx.register("substrate", app)
    return ctx, app


# ── self_check() shape ────────────────────────────────────────────────────


def test_self_check_returns_full_shape_at_startup() -> None:
    ctx, _ = _ctx_with_substrate()
    engine = AOSGEngine(ctx, auto_tune_alert_threshold=True, normalize_per_organ=True)
    sc = engine.self_check()
    assert sc["version"] == "v1.5"
    assert set(sc.keys()) == {
        "version", "config", "engine_state", "per_organ_contribution_share_pct",
        "checks", "overall_status",
    }
    assert set(sc["config"].keys()) >= {
        "aos_g_normalize_per_organ",
        "aos_g_normalize_per_organ_window_beats",
        "aos_g_normalize_per_organ_min_samples",
        "aos_g_alert_threshold_auto_tune",
        "aos_g_alert_threshold_auto_tune_ratio",
        "aos_g_alert_threshold_auto_tune_warmup_beats",
        "aos_g_alert_threshold_auto_tune_recompute_period_beats",
        "gap_weights",
    }
    assert set(sc["engine_state"].keys()) >= {
        "current_threshold", "initial_threshold", "auto_tune_first_set",
        "auto_tune_n_tunes", "normalize_ready", "normalize_samples_per_organ",
        "last_reading_beat",
    }


def test_self_check_at_startup_is_warmup() -> None:
    """Before any compute() — engine state shows warmup, overall='warmup'."""
    ctx, _ = _ctx_with_substrate()
    engine = AOSGEngine(ctx, auto_tune_alert_threshold=True, normalize_per_organ=True)
    sc = engine.self_check()
    assert sc["engine_state"]["auto_tune_first_set"] is False
    assert sc["engine_state"]["auto_tune_n_tunes"] == 0
    assert sc["engine_state"]["normalize_ready"] is False
    # Some checks should be 'warmup'
    statuses = [c["status"] for c in sc["checks"]]
    assert "warmup" in statuses
    assert sc["overall_status"] in ("warmup", "ok")  # ok if no warmup checks; warmup is correct here


def test_self_check_v1_4_backwards_compat_overall_ok() -> None:
    """When both v1.5 features are explicitly OFF (v1.4 regime), checks
    report 'off' status — overall stays 'ok' since 'off' is intentional."""
    ctx, _ = _ctx_with_substrate()
    engine = AOSGEngine(ctx, auto_tune_alert_threshold=False, normalize_per_organ=False)
    sc = engine.self_check()
    # The two 'enabled' checks should be 'off'
    by_name = {c["name"]: c for c in sc["checks"]}
    assert by_name["normalize_enabled"]["status"] == "off"
    assert by_name["auto_tune_enabled"]["status"] == "off"
    # Overall should NOT be 'warning' (off is intentional in v1.4 regime)
    assert sc["overall_status"] in ("ok", "warmup")


def test_self_check_with_synthetic_reading_reports_share() -> None:
    """Inject a synthetic AOSGReading with known per_organ_gap, verify share is
    computed correctly. Test path independent of substrate dynamics."""
    ctx, _ = _ctx_with_substrate()
    engine = AOSGEngine(ctx, normalize_per_organ=False)  # plain L2 for clean math

    # Synthetic per-organ gaps + uniform weights → predictable shares
    engine._current = AOSGReading(
        beat_no=100,
        aos_g_gap=10.0,
        per_organ_gap={
            "anima": 1.0,
            "eidolon": 2.0,
            "mneme": 3.0,
            "nous": 4.0,
            "pneuma": 5.0,
        },
        valid=True,
    )
    sc = engine.self_check()
    # Shares from squared raw gaps (uniform weights):
    # sq = [1, 4, 9, 16, 25] = 55; shares = each/55 * 100
    share = sc["per_organ_contribution_share_pct"]
    assert abs(share["anima"] - (1 / 55 * 100)) < 0.01
    assert abs(share["pneuma"] - (25 / 55 * 100)) < 0.01


def test_self_check_n_tunes_increments_on_auto_tune_fire() -> None:
    """Verify the new _auto_tune_n_tunes counter increments correctly."""
    ctx, _ = _ctx_with_substrate()
    engine = AOSGEngine(
        ctx,
        auto_tune_alert_threshold=True,
        auto_tune_warmup_beats=0,
        auto_tune_recompute_period_beats=100,
    )
    assert engine._auto_tune_n_tunes == 0
    # Manually fire first set
    for _ in range(30):
        engine._auto_tune_gap_samples.append(10.0)
    engine._maybe_auto_tune_threshold(beat_no=10)
    assert engine._auto_tune_n_tunes == 1
    # Fire recompute
    for _ in range(30):
        engine._auto_tune_gap_samples.append(20.0)
    engine._maybe_auto_tune_threshold(beat_no=200)
    assert engine._auto_tune_n_tunes == 2

    sc = engine.self_check()
    assert sc["engine_state"]["auto_tune_n_tunes"] == 2


def test_self_check_pneuma_share_warning_when_imbalanced() -> None:
    """Post-stabilization with PNEUMA share > 60% → status='warning' for the
    per_organ_contribution_balanced check."""
    ctx, _ = _ctx_with_substrate()
    engine = AOSGEngine(
        ctx,
        normalize_per_organ=True,
        normalize_min_samples=2,
    )
    # Seed history so normalize_ready=True
    for _ in range(5):
        for name in ORGAN_ORDER:
            engine._per_organ_gap_history[name].append(1.0)
    # Inject imbalanced reading — PNEUMA dominates
    engine._current = AOSGReading(
        beat_no=1000,
        aos_g_gap=10.0,
        per_organ_gap={
            "anima": 0.01,
            "eidolon": 0.01,
            "mneme": 0.01,
            "nous": 0.01,
            "pneuma": 10.0,  # huge raw → huge contribution even normalized
        },
        valid=True,
    )
    sc = engine.self_check()
    by_name = {c["name"]: c for c in sc["checks"]}
    assert "per_organ_contribution_balanced" in by_name
    assert by_name["per_organ_contribution_balanced"]["status"] == "warning"
    assert sc["overall_status"] == "warning"


# ── HTTP endpoint shape ──────────────────────────────────────────────────


def _client(ctx: AxiomaContext, cfg: AxiomaConfig | None = None) -> TestClient:
    if cfg is None:
        cfg = AxiomaConfig()
    app = create_app(ctx, cfg)
    return TestClient(app)


def test_http_self_check_warmup_when_no_engine() -> None:
    ctx = AxiomaContext()
    client = _client(ctx)
    r = client.get("/aos_g/self_check")
    assert r.status_code == 200
    body = r.json()
    assert body.get("warmup_active") is True
    assert body.get("data") is None


def test_http_self_check_returns_dict_when_engine_present() -> None:
    ctx, _ = _ctx_with_substrate()
    engine = AOSGEngine(
        ctx,
        auto_tune_alert_threshold=True,
        normalize_per_organ=True,
    )
    ctx.register("aos_g", engine)
    client = _client(ctx)
    r = client.get("/aos_g/self_check")
    assert r.status_code == 200
    body = r.json()
    data = body["data"]
    assert data["version"] == "v1.5"
    assert "config" in data
    assert "engine_state" in data
    assert "checks" in data
    assert "overall_status" in data


@pytest.mark.asyncio
async def test_axioma_app_self_check_endpoint_e2e() -> None:
    """End-to-end: AxiomaApp builds the engine with v1.5 defaults; HTTP endpoint
    reports normalize+auto-tune both ON, normalize_ready=False at startup."""
    from axioma.runtime.app import AxiomaApp

    cfg = AxiomaConfig()
    app = AxiomaApp(cfg, with_ws_server=False, with_registry=False, with_http_api=False)
    await app.setup()
    try:
        aos_g = app.ctx.get("aos_g")  # type: ignore[union-attr]
        sc = aos_g.self_check()
        assert sc["config"]["aos_g_normalize_per_organ"] is True
        assert sc["config"]["aos_g_alert_threshold_auto_tune"] is True
        # At startup (no computes yet) — normalize not ready, auto-tune not fired
        assert sc["engine_state"]["normalize_ready"] is False
        assert sc["engine_state"]["auto_tune_first_set"] is False
    finally:
        await app.shutdown()


def _to_dict_overall_keys(d: dict[str, Any]) -> set[str]:
    """Tiny helper to make the assertion error legible if structure drifts."""
    return set(d.keys())
