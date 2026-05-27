"""v1.4.3 — per-component ψ alert thresholds.

Verifies:
  - Default (None) preserves v1.0..v1.3 single-threshold behavior
  - Per-component dict overrides individual sub-signals
  - Alert fires when ANY component < its threshold
  - Missing keys fall back to psi_alert_threshold
  - Out-of-range values rejected (negative, >1)
"""
from __future__ import annotations

import pytest

from axioma.config import ComposeConfig
from axioma.measurement.aos_g_engine import (
    AOSGEngine,
    _resolve_per_component_thresholds,
)
from axioma.observability import AxiomaContext


def test_config_default_is_none() -> None:
    cfg = ComposeConfig()
    assert cfg.psi_per_component_thresholds is None


def test_resolver_fills_all_keys_with_fallback() -> None:
    out = _resolve_per_component_thresholds(None, fallback=0.3)
    assert out == {
        "gap_variance_health": 0.3,
        "structural_health": 0.3,
        "compose_probe_health": 0.3,
    }


def test_resolver_overrides_specified_keys() -> None:
    out = _resolve_per_component_thresholds(
        {"gap_variance_health": 0.2, "structural_health": 0.5},
        fallback=0.3,
    )
    assert out["gap_variance_health"] == 0.2
    assert out["structural_health"] == 0.5
    assert out["compose_probe_health"] == 0.3  # fallback


def test_resolver_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="in \\[0,1\\]"):
        _resolve_per_component_thresholds(
            {"gap_variance_health": 1.5}, fallback=0.3,
        )
    with pytest.raises(ValueError, match="in \\[0,1\\]"):
        _resolve_per_component_thresholds(
            {"structural_health": -0.1}, fallback=0.3,
        )


def test_resolver_ignores_unknown_keys() -> None:
    """Unknown keys silently ignored — keeps the resolver tolerant of typos
    without surfacing as crashes at boot."""
    out = _resolve_per_component_thresholds(
        {"unknown_key": 0.5, "gap_variance_health": 0.2},
        fallback=0.3,
    )
    assert out["gap_variance_health"] == 0.2
    assert "unknown_key" not in out


def test_engine_default_uses_single_threshold() -> None:
    """Backwards compat: AOSGEngine() with no per-component arg → single threshold for all."""
    ctx = AxiomaContext()
    engine = AOSGEngine(ctx, psi_alert_threshold=0.35)
    assert engine.psi_per_component_thresholds == {
        "gap_variance_health": 0.35,
        "structural_health": 0.35,
        "compose_probe_health": 0.35,
    }


def test_engine_per_component_args() -> None:
    ctx = AxiomaContext()
    engine = AOSGEngine(
        ctx,
        psi_alert_threshold=0.3,
        psi_per_component_thresholds={
            "gap_variance_health": 0.2,
            "structural_health": 0.5,
        },
    )
    assert engine.psi_per_component_thresholds["gap_variance_health"] == 0.2
    assert engine.psi_per_component_thresholds["structural_health"] == 0.5
    assert engine.psi_per_component_thresholds["compose_probe_health"] == 0.3  # fallback


def _compute_alert(*, gv: float, sh: float, cp: float, thresholds: dict[str, float]) -> bool:
    """Replicate the alert logic for direct testing."""
    return (
        gv < thresholds["gap_variance_health"]
        or sh < thresholds["structural_health"]
        or cp < thresholds["compose_probe_health"]
    )


def test_alert_fires_when_any_component_below_threshold() -> None:
    # Uniform threshold 0.3
    thresholds = _resolve_per_component_thresholds(None, fallback=0.3)
    # All above → no alert
    assert _compute_alert(gv=0.9, sh=0.9, cp=0.9, thresholds=thresholds) is False
    # gv below → alert
    assert _compute_alert(gv=0.2, sh=0.9, cp=0.9, thresholds=thresholds) is True
    # sh below → alert
    assert _compute_alert(gv=0.9, sh=0.2, cp=0.9, thresholds=thresholds) is True
    # cp below → alert
    assert _compute_alert(gv=0.9, sh=0.9, cp=0.2, thresholds=thresholds) is True


def test_per_component_thresholds_independent_alerts() -> None:
    """Tight on structural, loose on compose_probe → different alert behavior."""
    thresholds = _resolve_per_component_thresholds(
        {"structural_health": 0.95, "compose_probe_health": 0.1},
        fallback=0.3,
    )
    # gv=0.5, sh=0.94 (just below tight structural), cp=0.5 → alert (structural)
    assert _compute_alert(gv=0.5, sh=0.94, cp=0.5, thresholds=thresholds) is True
    # gv=0.5, sh=0.96 (above tight), cp=0.15 (above loose compose_probe) → no alert
    assert _compute_alert(gv=0.5, sh=0.96, cp=0.15, thresholds=thresholds) is False


@pytest.mark.asyncio
async def test_axioma_app_wires_per_component_thresholds() -> None:
    from axioma.config import AxiomaConfig
    from axioma.runtime.app import AxiomaApp

    cfg = AxiomaConfig()
    object.__setattr__(
        cfg.compose, "psi_per_component_thresholds",
        {"structural_health": 0.95, "gap_variance_health": 0.2},
    )
    app = AxiomaApp(cfg, with_ws_server=False, with_registry=False, with_http_api=False)
    await app.setup()
    try:
        aos_g = app.ctx.get("aos_g")  # type: ignore[union-attr]
        assert aos_g.psi_per_component_thresholds["structural_health"] == 0.95
        assert aos_g.psi_per_component_thresholds["gap_variance_health"] == 0.2
        # Unspecified key falls back to psi_alert_threshold
        assert aos_g.psi_per_component_thresholds["compose_probe_health"] == cfg.compose.psi_alert_threshold
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_axioma_app_default_preserves_single_threshold_behavior() -> None:
    """v1.3 backwards compat: default config → all 3 components use psi_alert_threshold."""
    from axioma.config import AxiomaConfig
    from axioma.runtime.app import AxiomaApp

    cfg = AxiomaConfig()
    app = AxiomaApp(cfg, with_ws_server=False, with_registry=False, with_http_api=False)
    await app.setup()
    try:
        aos_g = app.ctx.get("aos_g")  # type: ignore[union-attr]
        for k in ("gap_variance_health", "structural_health", "compose_probe_health"):
            assert aos_g.psi_per_component_thresholds[k] == cfg.compose.psi_alert_threshold
    finally:
        await app.shutdown()
