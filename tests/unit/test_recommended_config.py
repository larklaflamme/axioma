"""v1.2 release — verify the configs/v1_2_recommended.yaml flow works end-to-end.

Tests:
  - Recommended YAML loads via AXIOMA_CONFIG env var
  - Loaded config has the v1.2 PNEUMA-weighted preset + recalibrated threshold
  - Default config (no AXIOMA_CONFIG) keeps v1.0 baseline behavior
  - AXIOMA_CONFIG env var is reserved (doesn't collide with field overrides)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from axioma.config import load_config
from axioma.measurement.aos_g_engine import (
    PNEUMA_WEIGHTED_GAP_WEIGHTS,
    recommended_alert_threshold,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RECOMMENDED_YAML = REPO_ROOT / "configs" / "v1_2_recommended.yaml"


def test_recommended_yaml_exists() -> None:
    assert RECOMMENDED_YAML.exists(), (
        "configs/v1_2_recommended.yaml missing — required for v1.2 release"
    )


def test_recommended_yaml_loads_pneuma_weighted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AXIOMA_CONFIG", str(RECOMMENDED_YAML))
    cfg = load_config()
    assert cfg.compose.aos_g_gap_weights == PNEUMA_WEIGHTED_GAP_WEIGHTS


def test_recommended_yaml_has_recalibrated_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AXIOMA_CONFIG", str(RECOMMENDED_YAML))
    cfg = load_config()
    # Should match the v1.2.2 calibrated value
    expected = recommended_alert_threshold(PNEUMA_WEIGHTED_GAP_WEIGHTS)
    assert abs(cfg.compose.aos_g_alert_threshold - expected) < 0.005


def test_default_config_ships_v1_3_pneuma_weighted(monkeypatch: pytest.MonkeyPatch) -> None:
    """v1.3 default-flip (Checkpoint P): no AXIOMA_CONFIG → PNEUMA-weighted defaults.

    Replaces the v1.0/v1.1/v1.2 backwards-compat invariant. Operators wanting
    v1.0 uniform behavior load configs/v1_0_backwards_compat.yaml explicitly."""
    monkeypatch.delenv("AXIOMA_CONFIG", raising=False)
    cfg = load_config()
    assert cfg.compose.aos_g_gap_weights == PNEUMA_WEIGHTED_GAP_WEIGHTS
    assert cfg.compose.aos_g_alert_threshold == 0.152


def test_v1_0_backwards_compat_yaml_restores_uniform(monkeypatch: pytest.MonkeyPatch) -> None:
    """v1.0/v1.1/v1.2 operators load the backwards-compat YAML to opt back into
    the pre-v1.3 uniform defaults."""
    from axioma.measurement.aos_g_engine import UNIFORM_GAP_WEIGHTS
    bc_yaml = REPO_ROOT / "configs" / "v1_0_backwards_compat.yaml"
    assert bc_yaml.exists(), (
        "configs/v1_0_backwards_compat.yaml missing — required for v1.3 migration path"
    )
    monkeypatch.setenv("AXIOMA_CONFIG", str(bc_yaml))
    cfg = load_config()
    assert cfg.compose.aos_g_gap_weights == UNIFORM_GAP_WEIGHTS
    assert cfg.compose.aos_g_alert_threshold == 0.10


def test_axioma_config_env_var_is_reserved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Bug fix from this checkpoint: AXIOMA_CONFIG must NOT be interpreted as
    setting cfg.config — it's a reserved loader directive (path to extra YAML)."""
    # Set both AXIOMA_CONFIG (the reserved one) AND a sibling AXIOMA_* var.
    fake_yaml = tmp_path / "empty.yaml"
    fake_yaml.write_text("")
    monkeypatch.setenv("AXIOMA_CONFIG", str(fake_yaml))
    monkeypatch.setenv("AXIOMA_RUNTIME__HEARTBEAT_HZ", "5")
    # If AXIOMA_CONFIG were interpreted as a field, this would raise pydantic
    # ValidationError. Should succeed cleanly.
    cfg = load_config()
    assert cfg.runtime.heartbeat_hz == 5  # AXIOMA_RUNTIME__HEARTBEAT_HZ still works


def test_recommended_yaml_inherits_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recommended YAML only overrides compose.* fields; everything else stays at
    v1.0 defaults (substrate, recovery, runtime, etc.)."""
    monkeypatch.setenv("AXIOMA_CONFIG", str(RECOMMENDED_YAML))
    cfg = load_config()
    # Substrate fields untouched
    assert cfg.substrate.n_iter == 3
    assert cfg.substrate.drive_dim == 16
    # Recovery fields untouched
    assert cfg.recovery.min_recovery_stage == 2
    # Runtime untouched
    assert cfg.runtime.heartbeat_hz == 10
