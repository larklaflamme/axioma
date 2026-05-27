"""Config loader: defaults, YAML, env overrides, frozen invariant."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from axioma.config import AxiomaConfig, load_config


def test_defaults_match_arch_v10() -> None:
    """Verify pydantic defaults match ARCH_DESIGN_v1.0.md §4 organ specs."""
    cfg = AxiomaConfig()
    s = cfg.substrate
    assert s.n_iter == 3
    assert s.organ_specs["eidolon"].rho == 0.92
    assert s.organ_specs["eidolon"].v_scale == 1.3
    assert s.organ_specs["mneme"].v_scale == 1.4  # α_M
    assert s.organ_specs["pneuma"].state_dim == 7  # +1 for coherence_budget
    assert s.organ_specs["anima"].state_dim == 4
    assert s.organ_specs["nous"].state_dim == 6


def test_compose_adaptive_cadences() -> None:
    cfg = AxiomaConfig()
    assert cfg.compose.baseline_period_beats == 30
    assert cfg.compose.perturbation_period_beats == 5
    assert cfg.compose.recovery_period_beats == 60


def test_recovery_q1_defaults() -> None:
    cfg = AxiomaConfig()
    assert cfg.recovery.rejection_escalation_consecutive == 3
    assert cfg.recovery.rejection_warning_cooldown_beats == 600


def test_meta_cognition_observer_only_default() -> None:
    cfg = AxiomaConfig()
    assert cfg.meta_cognition.observer_mode == "observer_only"
    assert cfg.meta_cognition.divergence_warning_threshold == 5


def test_config_is_frozen() -> None:
    cfg = AxiomaConfig()
    with pytest.raises(ValidationError):
        cfg.substrate.n_iter = 99  # type: ignore[misc]


def test_organ_spec_validation() -> None:
    from axioma.config import OrganSpec

    with pytest.raises(ValidationError):
        OrganSpec(latent_dim=0, state_dim=4, rho=0.85, v_scale=1.0)  # latent_dim must be > 0
    with pytest.raises(ValidationError):
        OrganSpec(latent_dim=8, state_dim=4, rho=1.5, v_scale=1.0)  # rho > 1
    with pytest.raises(ValidationError):
        OrganSpec(latent_dim=8, state_dim=4, rho=0.5, v_scale=0.0)  # v_scale not > 0


def test_load_config_with_yaml(tmp_path: Path, monkeypatch) -> None:
    yaml_path = tmp_path / "override.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "substrate": {"n_iter": 7},
                "compose": {"noise_factor": 0.123},
            }
        )
    )
    # Wipe any env vars that might interfere
    for k in list(os.environ):
        if k.startswith("AXIOMA_"):
            monkeypatch.delenv(k, raising=False)
    cfg = load_config(default_yaml=yaml_path, local_yaml=tmp_path / "missing.yaml")
    assert cfg.substrate.n_iter == 7
    assert cfg.compose.noise_factor == 0.123


def test_load_config_env_override_wins(tmp_path: Path, monkeypatch) -> None:
    yaml_path = tmp_path / "default.yaml"
    yaml_path.write_text(yaml.safe_dump({"substrate": {"n_iter": 7}}))
    monkeypatch.setenv("AXIOMA_SUBSTRATE__N_ITER", "11")
    cfg = load_config(default_yaml=yaml_path, local_yaml=tmp_path / "none.yaml")
    assert cfg.substrate.n_iter == 11


def test_load_config_dotenv_infra_mapping(monkeypatch) -> None:
    """OLLAMA_URL / QDRANT_URL / EMBED_MODEL / REDIS_URL from .env map onto InfraConfig."""
    monkeypatch.setenv("OLLAMA_URL", "http://test-ollama:9999")
    monkeypatch.setenv("EMBED_MODEL", "test-embed-model")
    monkeypatch.setenv("EMBED_DIM", "1024")
    monkeypatch.setenv("QDRANT_URL", "http://test-qdrant:6333")
    monkeypatch.setenv("REDIS_URL", "redis://test-redis:6379")
    # Wipe AXIOMA_* overrides
    for k in list(os.environ):
        if k.startswith("AXIOMA_"):
            monkeypatch.delenv(k, raising=False)
    cfg = load_config(
        default_yaml=Path("/nonexistent"),
        local_yaml=Path("/nonexistent"),
    )
    assert cfg.infra.ollama.url == "http://test-ollama:9999"
    assert cfg.infra.ollama.embed_model == "test-embed-model"
    assert cfg.infra.ollama.embed_dim == 1024
    assert cfg.infra.qdrant.url == "http://test-qdrant:6333"
    assert cfg.infra.redis.url == "redis://test-redis:6379"


def test_load_config_axioma_env_overrides_dotenv(monkeypatch) -> None:
    """AXIOMA_INFRA__OLLAMA__URL beats OLLAMA_URL."""
    monkeypatch.setenv("OLLAMA_URL", "http://from-dotenv")
    monkeypatch.setenv("AXIOMA_INFRA__OLLAMA__URL", "http://from-axioma-env")
    cfg = load_config(
        default_yaml=Path("/nonexistent"),
        local_yaml=Path("/nonexistent"),
    )
    assert cfg.infra.ollama.url == "http://from-axioma-env"


def test_load_config_env_value_coercion(monkeypatch) -> None:
    monkeypatch.setenv("AXIOMA_SUBSTRATE__N_ITER", "5")
    monkeypatch.setenv("AXIOMA_RECOVERY__MIN_BUDGET_TO_ACCEPT", "0.42")
    monkeypatch.setenv("AXIOMA_META_COGNITION__ENABLED", "false")
    cfg = load_config(
        default_yaml=Path("/nonexistent"),
        local_yaml=Path("/nonexistent"),
    )
    assert cfg.substrate.n_iter == 5
    assert isinstance(cfg.substrate.n_iter, int)
    assert cfg.recovery.min_budget_to_accept == 0.42
    assert cfg.meta_cognition.enabled is False


def test_load_config_invalid_yaml_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- this is\n- a list, not a dict")
    with pytest.raises(ValueError, match="did not parse as a dict"):
        load_config(default_yaml=bad)
