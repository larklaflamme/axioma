"""Unit tests for OllamaClient.chat() options forwarding.

The behaviour under test: every config sampling parameter (temperature,
max_tokens / num_predict, num_ctx, top_p, top_k, min_p, repeat_penalty)
must be forwarded to Ollama as part of the request body's `options`
dict. Per-call kwargs override config defaults; `extra_options` overrides
both. Without this forwarding, deepseek-v4-flash:cloud (a thinking model
that benefits from large num_ctx) ran with model-default sampling
regardless of what `.env` said.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from axioma.config import OllamaConfig
from axioma.infra.ollama import OllamaClient


def _make_client(**cfg_overrides: Any) -> OllamaClient:
    cfg = OllamaConfig(**cfg_overrides)
    return OllamaClient(cfg)


def _capture_post(client: OllamaClient) -> tuple[OllamaClient, AsyncMock]:
    """Replace _post_json with a mock so we can inspect the body."""
    mock = AsyncMock(return_value={"message": {"content": "ok"}})
    client._post_json = mock  # type: ignore[method-assign]
    return client, mock


# ── Defaults from cfg flow through ─────────────────────────────────────


def test_chat_forwards_all_sampling_params_from_config() -> None:
    client = _make_client(
        temperature=0.4, max_tokens=4096, num_ctx=131072,
        top_p=0.95, top_k=64, min_p=0.05, repeat_penalty=1.0,
    )
    client, mock = _capture_post(client)
    asyncio.run(client.chat([{"role": "user", "content": "hi"}]))
    _, body = mock.call_args.args
    opts = body["options"]
    assert opts["temperature"] == 0.4
    assert opts["num_predict"] == 4096
    assert opts["num_ctx"] == 131072
    assert opts["top_p"] == 0.95
    assert opts["top_k"] == 64
    assert opts["min_p"] == 0.05
    assert opts["repeat_penalty"] == 1.0


def test_chat_omits_num_predict_when_max_tokens_is_unlimited() -> None:
    """max_tokens=-1 (the .env default for 'unlimited') must be OMITTED
    from the request — the deepseek-v4-flash:cloud endpoint rejects
    `max_tokens: -1` with HTTP 400 'must be positive'. Omitting lets the
    upstream use its own default."""
    client = _make_client(max_tokens=-1)
    client, mock = _capture_post(client)
    asyncio.run(client.chat([{"role": "user", "content": "hi"}]))
    assert "num_predict" not in mock.call_args.args[1]["options"]


def test_chat_omits_num_predict_when_max_tokens_is_zero() -> None:
    client = _make_client(max_tokens=0)
    client, mock = _capture_post(client)
    asyncio.run(client.chat([{"role": "user", "content": "hi"}]))
    assert "num_predict" not in mock.call_args.args[1]["options"]


def test_chat_omits_num_ctx_when_zero() -> None:
    """num_ctx=0 means 'let the model decide' — don't send it at all so
    Ollama uses the model's default context (vs forcing 0)."""
    client = _make_client(num_ctx=0)
    client, mock = _capture_post(client)
    asyncio.run(client.chat([{"role": "user", "content": "hi"}]))
    _, body = mock.call_args.args
    assert "num_ctx" not in body["options"]


# ── Per-call kwargs override config ────────────────────────────────────


def test_chat_explicit_temperature_overrides_config() -> None:
    client = _make_client(temperature=0.4)
    client, mock = _capture_post(client)
    asyncio.run(client.chat(
        [{"role": "user", "content": "hi"}], temperature=0.9,
    ))
    assert mock.call_args.args[1]["options"]["temperature"] == 0.9


def test_chat_explicit_max_tokens_overrides_config() -> None:
    client = _make_client(max_tokens=-1)
    client, mock = _capture_post(client)
    asyncio.run(client.chat(
        [{"role": "user", "content": "hi"}], max_tokens=256,
    ))
    assert mock.call_args.args[1]["options"]["num_predict"] == 256


def test_chat_max_tokens_none_falls_back_to_config_default() -> None:
    """max_tokens=None (PeerConversationHandler's default) → use cfg.max_tokens.
    The old hardcoded 512 in PeerConversationHandler was the truncation."""
    client = _make_client(max_tokens=2048)
    client, mock = _capture_post(client)
    asyncio.run(client.chat(
        [{"role": "user", "content": "hi"}], max_tokens=None,
    ))
    assert mock.call_args.args[1]["options"]["num_predict"] == 2048


def test_chat_explicit_max_tokens_negative_omits_num_predict() -> None:
    """Per-call max_tokens=-1 also omits the field (matches the config path)."""
    client = _make_client(max_tokens=4096)  # cfg has a positive cap
    client, mock = _capture_post(client)
    asyncio.run(client.chat(
        [{"role": "user", "content": "hi"}], max_tokens=-1,
    ))
    assert "num_predict" not in mock.call_args.args[1]["options"]


# ── extra_options is final-say ────────────────────────────────────────


def test_chat_extra_options_override_everything() -> None:
    """extra_options is the operator's emergency hatch — beats both
    per-call kwargs and config defaults."""
    client = _make_client(temperature=0.4)
    client, mock = _capture_post(client)
    asyncio.run(client.chat(
        [{"role": "user", "content": "hi"}],
        temperature=0.9,
        extra_options={"temperature": 0.1, "seed": 42},
    ))
    opts = mock.call_args.args[1]["options"]
    assert opts["temperature"] == 0.1  # extra_options wins over explicit kwarg
    assert opts["seed"] == 42


def test_chat_model_kwarg_overrides_config() -> None:
    client = _make_client(chat_model="default-model")
    client, mock = _capture_post(client)
    asyncio.run(client.chat(
        [{"role": "user", "content": "hi"}], model="other-model",
    ))
    assert mock.call_args.args[1]["model"] == "other-model"


# ── OllamaConfig new fields are present ────────────────────────────────


def test_ollama_config_has_all_new_sampling_fields() -> None:
    """Regression guard: if someone removes a sampling field from the
    schema, this test fails immediately with a clear name."""
    cfg = OllamaConfig()
    for field in ("temperature", "max_tokens", "num_ctx",
                   "top_p", "top_k", "min_p", "repeat_penalty"):
        assert hasattr(cfg, field), f"OllamaConfig missing {field!r}"


def test_ollama_config_default_max_tokens_is_unlimited() -> None:
    """The hard cap that was causing truncation lived in
    PeerConversationHandler (512); OllamaConfig itself is -1 = unlimited.
    Confirm the config default still means 'no cap'."""
    assert OllamaConfig().max_tokens == -1


def test_ollama_config_streaming_is_disabled() -> None:
    """Sanity: stream=True still raises NotImplementedError; the chat
    endpoint is non-streaming for this version."""
    client = _make_client()
    with pytest.raises(NotImplementedError):
        asyncio.run(client.chat(
            [{"role": "user", "content": "hi"}], stream=True,
        ))
