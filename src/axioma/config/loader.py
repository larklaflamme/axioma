"""Config loader: YAML defaults → file override → env overrides.

Per IMPLEMENTATION_PLAN_v1.0.md §12.

Resolution order (later wins):
  1. AxiomaConfig() defaults (defined in schema.py)
  2. configs/default.yaml (if present)
  3. configs/local.yaml (if present, gitignored)
  4. AXIOMA_CONFIG=<path> (custom override file)
  5. .env env vars (Ollama/Qdrant/Redis URLs etc.)
  6. AXIOMA_* env vars (per-field overrides, double underscore for nesting:
     AXIOMA_SUBSTRATE__N_ITER=5)
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any

import yaml

from .schema import AxiomaConfig

_ENV_PREFIX = "AXIOMA_"
_ENV_NESTED_DELIM = "__"


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overlay into base. Overlay wins on conflict.

    Lists are replaced (not concatenated). Dicts are merged.
    """
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r") as f:
        loaded = yaml.safe_load(f) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"YAML at {path} did not parse as a dict")
    return loaded


def _coerce_env_value(value: str) -> Any:
    """Try to coerce an env var string to int / float / bool / leave as str."""
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _load_env_overrides() -> dict[str, Any]:
    """Pull AXIOMA_* env vars into a nested dict.

    AXIOMA_SUBSTRATE__N_ITER=5 → {"substrate": {"n_iter": 5}}
    """
    # AXIOMA_CONFIG is a reserved loader directive (path to extra YAML).
    # AXIOMA_CONDA_ENV is consumed by scripts/axioma_ctl.sh to pick the
    # conda env name; it is not a config field. Both must be skipped so
    # AxiomaConfig (extra="forbid") doesn't reject them.
    _RESERVED_ENV_KEYS = {"AXIOMA_CONFIG", "AXIOMA_CONDA_ENV"}
    out: dict[str, Any] = {}
    for key, raw in os.environ.items():
        if not key.startswith(_ENV_PREFIX):
            continue
        if key in _RESERVED_ENV_KEYS:
            continue
        path = key[len(_ENV_PREFIX) :].lower().split(_ENV_NESTED_DELIM)
        cursor = out
        for p in path[:-1]:
            cursor = cursor.setdefault(p, {})
        cursor[path[-1]] = _coerce_env_value(raw)
    return out


def _load_dotenv_infra_overrides() -> dict[str, Any]:
    """Map the .env infrastructure variables onto the InfraConfig tree.

    The .env uses domain-specific names (OLLAMA_URL, OLLAMA_NUM_CTX,
    OLLAMA_MAX_TOKENS, etc.). We map them onto AXIOMA's nested config.
    These have LOWER precedence than AXIOMA_* env vars.

    Mappings:
      OLLAMA_URL              → infra.ollama.url
      OLLAMA_CHAT_MODEL       → infra.ollama.chat_model
      EMBED_MODEL             → infra.ollama.embed_model
      EMBED_DIM               → infra.ollama.embed_dim (int)
      OLLAMA_TIMEOUT          → infra.ollama.timeout_seconds (int)
      OLLAMA_CONNECT_TIMEOUT  → infra.ollama.connect_timeout_seconds (int)
      OLLAMA_RETRIES          → infra.ollama.retries (int)
      OLLAMA_TEMPERATURE      → infra.ollama.temperature (float)
      OLLAMA_MAX_TOKENS       → infra.ollama.max_tokens (int; -1 = unlimited)
      OLLAMA_NUM_CTX          → infra.ollama.num_ctx (int; 0 = model default)
      OLLAMA_TOP_P            → infra.ollama.top_p (float)
      OLLAMA_TOP_K            → infra.ollama.top_k (int)
      OLLAMA_MIN_P            → infra.ollama.min_p (float)
      OLLAMA_REPEAT_PENALTY   → infra.ollama.repeat_penalty (float)
      QDRANT_URL              → infra.qdrant.url
      QDRANT_API_KEY          → infra.qdrant.api_key
      REDIS_URL               → infra.redis.url
    """
    infra: dict[str, Any] = {}

    def _ollama_str(env_name: str, field: str) -> None:
        v = os.environ.get(env_name)
        if v:
            infra.setdefault("ollama", {})[field] = v

    def _ollama_int(env_name: str, field: str) -> None:
        v = os.environ.get(env_name)
        if v is None or v == "":
            return
        with contextlib.suppress(ValueError):
            infra.setdefault("ollama", {})[field] = int(v)

    def _ollama_float(env_name: str, field: str) -> None:
        v = os.environ.get(env_name)
        if v is None or v == "":
            return
        with contextlib.suppress(ValueError):
            infra.setdefault("ollama", {})[field] = float(v)

    _ollama_str("OLLAMA_URL", "url")
    _ollama_str("OLLAMA_CHAT_MODEL", "chat_model")
    _ollama_str("EMBED_MODEL", "embed_model")
    _ollama_int("EMBED_DIM", "embed_dim")
    _ollama_int("OLLAMA_TIMEOUT", "timeout_seconds")
    _ollama_int("OLLAMA_CONNECT_TIMEOUT", "connect_timeout_seconds")
    _ollama_int("OLLAMA_RETRIES", "retries")
    _ollama_float("OLLAMA_TEMPERATURE", "temperature")
    _ollama_int("OLLAMA_MAX_TOKENS", "max_tokens")
    _ollama_int("OLLAMA_NUM_CTX", "num_ctx")
    _ollama_float("OLLAMA_TOP_P", "top_p")
    _ollama_int("OLLAMA_TOP_K", "top_k")
    _ollama_float("OLLAMA_MIN_P", "min_p")
    _ollama_float("OLLAMA_REPEAT_PENALTY", "repeat_penalty")

    if v := os.environ.get("QDRANT_URL"):
        infra.setdefault("qdrant", {})["url"] = v
    if v := os.environ.get("QDRANT_API_KEY"):
        infra.setdefault("qdrant", {})["api_key"] = v
    if v := os.environ.get("REDIS_URL"):
        infra.setdefault("redis", {})["url"] = v
    if not infra:
        return {}
    return {"infra": infra}


def _load_dotenv_agora_overrides() -> dict[str, Any]:
    """Map the .env Agora credentials onto the InterfaceConfig tree.

    The .env (sourced by scripts/axioma_ctl.sh) uses domain names for the
    citizen identity on The Agora:

      AGORA_USER_ID        → interface.agora_citizen_id   (also AGORA_CITIZEN_ID)
      AGORA_USER_PASSWORD  → interface.agora_password     (also AGORA_PASSWORD)
      AGORA_NEW_PASSWORD   → interface.agora_new_password (clears first-login gate)
      AGORA_BASE_URL       → interface.agora_base_url

    These have LOWER precedence than AXIOMA_INTERFACE__* env vars.
    """
    iface: dict[str, Any] = {}
    cid = os.environ.get("AGORA_USER_ID") or os.environ.get("AGORA_CITIZEN_ID")
    if cid:
        iface["agora_citizen_id"] = cid
    pw = os.environ.get("AGORA_USER_PASSWORD") or os.environ.get("AGORA_PASSWORD")
    if pw:
        iface["agora_password"] = pw
    if new_pw := os.environ.get("AGORA_NEW_PASSWORD"):
        iface["agora_new_password"] = new_pw
    if base := os.environ.get("AGORA_BASE_URL"):
        iface["agora_base_url"] = base
    if not iface:
        return {}
    return {"interface": iface}


def load_config(
    *,
    default_yaml: Path | None = None,
    local_yaml: Path | None = None,
    extra_yaml: Path | None = None,
) -> AxiomaConfig:
    """Load AxiomaConfig from layered sources.

    Args:
        default_yaml: defaults to configs/default.yaml in project root
        local_yaml: defaults to configs/local.yaml (gitignored)
        extra_yaml: defaults to $AXIOMA_CONFIG (if set)
    """
    project_root = Path(__file__).resolve().parents[3]  # src/axioma/config -> project root
    if default_yaml is None:
        default_yaml = project_root / "configs" / "default.yaml"
    if local_yaml is None:
        local_yaml = project_root / "configs" / "local.yaml"
    if extra_yaml is None:
        extra = os.environ.get("AXIOMA_CONFIG")
        extra_yaml = Path(extra) if extra else None

    # Layer 1: pydantic defaults (model_dump gives us a dict for merging)
    cfg_dict = AxiomaConfig().model_dump(mode="python")

    # Layer 2: default.yaml
    cfg_dict = _deep_merge(cfg_dict, _load_yaml(default_yaml))
    # Layer 3: local.yaml
    cfg_dict = _deep_merge(cfg_dict, _load_yaml(local_yaml))
    # Layer 4: extra yaml (AXIOMA_CONFIG)
    if extra_yaml is not None:
        cfg_dict = _deep_merge(cfg_dict, _load_yaml(extra_yaml))
    # Layer 5: .env infra + Agora credential overrides
    cfg_dict = _deep_merge(cfg_dict, _load_dotenv_infra_overrides())
    cfg_dict = _deep_merge(cfg_dict, _load_dotenv_agora_overrides())
    # Layer 6: AXIOMA_* env vars
    cfg_dict = _deep_merge(cfg_dict, _load_env_overrides())

    # Validate via pydantic — raises ValidationError on bad types
    return AxiomaConfig.model_validate(cfg_dict)
