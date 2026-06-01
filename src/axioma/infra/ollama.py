"""Ollama LLM client — chat + embeddings via local Ollama service.

Models used (per .env):
  - chat: deepseek-v4-flash:cloud (default)
  - embeddings: nomic-embed-text-v2-moe (768-dim)

Async HTTP via httpx. Retries on transient network errors per config.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import OllamaConfig
from ..observability.logging import get_logger

log = get_logger(__name__)


class OllamaError(RuntimeError):
    """Wrapper for upstream Ollama HTTP / transport failures."""


@dataclass
class ToolCall:
    """One structured tool call emitted by the model.

    Mirrors the shape of Ollama's `/api/chat` response under
    `message.tool_calls[]`: a function name + parsed arguments dict +
    optional id (some models emit IDs for round-tripping).
    """

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)  # original block for debug


@dataclass
class ChatResponse:
    """Result of `OllamaClient.chat_with_tools` — text + structured tool calls.

    The model may emit either or both: a tool-use turn typically has
    `text=""` and one or more `tool_calls`; a final answer turn has
    text content and `tool_calls=[]`. The caller's tool loop decides
    based on whether `tool_calls` is non-empty.
    """

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    done_reason: str = ""
    raw_message: dict[str, Any] = field(default_factory=dict)


class OllamaClient:
    """Thin async client over Ollama's REST API.

    Endpoints:
      POST /api/chat          — chat completion (model + messages)
      POST /api/embed         — embeddings (model + input)
      POST /api/generate      — single-shot completion (model + prompt)
      GET  /api/tags          — list installed models
    """

    def __init__(self, cfg: OllamaConfig) -> None:
        self.cfg = cfg
        timeout = httpx.Timeout(
            connect=cfg.connect_timeout_seconds,
            read=cfg.timeout_seconds,
            write=cfg.timeout_seconds,
            pool=cfg.timeout_seconds,
        )
        self._client = httpx.AsyncClient(base_url=cfg.url, timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> OllamaClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ── Embeddings ────────────────────────────────────────────────────────

    async def embed(self, text: str | list[str], *, model: str | None = None) -> list[list[float]]:
        """Return embedding(s). Always returns a list of vectors.

        For a single string input, the result has one element.
        """
        single = isinstance(text, str)
        inputs = [text] if single else list(text)
        body = {"model": model or self.cfg.embed_model, "input": inputs}
        data = await self._post_json("/api/embed", body)
        embs = data.get("embeddings")
        if not isinstance(embs, list) or not all(isinstance(e, list) for e in embs):
            raise OllamaError(f"unexpected embedding response shape: {data}")
        if len(embs) != len(inputs):
            raise OllamaError(
                f"expected {len(inputs)} embeddings, got {len(embs)}"
            )
        if embs and len(embs[0]) != self.cfg.embed_dim:
            log.warning(
                "embed_dim_mismatch",
                expected=self.cfg.embed_dim,
                actual=len(embs[0]),
                model=model or self.cfg.embed_model,
            )
        return embs

    # ── Chat completion ───────────────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        extra_options: dict[str, Any] | None = None,
    ) -> str:
        """Chat completion (non-streaming by default). Returns assistant text.

        Sampling parameters (`temperature`, `num_predict`, `num_ctx`, `top_p`,
        `top_k`, `min_p`, `repeat_penalty`) are sourced from `self.cfg` —
        which in turn reads OLLAMA_* env vars at boot. Explicit kwargs
        (`temperature`, `max_tokens`) override the config defaults per-call.
        Any keys in `extra_options` win over both — useful for ad-hoc tuning.

        For streaming use chat_stream().
        """
        if stream:
            raise NotImplementedError("Use chat_stream() for streaming.")
        body = self._build_chat_body(
            messages=messages, model=model, temperature=temperature,
            max_tokens=max_tokens, extra_options=extra_options,
        )
        data = await self._post_json("/api/chat", body)
        msg = data.get("message", {})
        return str(msg.get("content", ""))

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_options: dict[str, Any] | None = None,
    ) -> ChatResponse:
        """Chat completion with tools, returning structured (text, tool_calls).

        Wraps Ollama's `/api/chat` with the `tools` parameter. Each entry
        in `tools` follows the OpenAI-style schema:
            {"type": "function", "function": {"name": ..., "description": ...,
             "parameters": <jsonschema>}}

        AXIOMA's `axioma.self_expansion.ToolExecutor` produces Anthropic-style
        tool defs by default; convert with `_executor_tools_to_ollama_tools`
        in the caller, or pass the Anthropic shape directly — Ollama is
        lenient about whether `function` wrapping is present, but the
        canonical form is the OpenAI one.

        Returns a `ChatResponse` with:
            text         — model's text content (often empty when emitting
                            tool calls)
            tool_calls   — list of `ToolCall` (name + parsed arguments)
            done_reason  — Ollama's done_reason (e.g. "stop", "tool_calls",
                            "length")
            raw_message  — the full response.message dict for debugging
        """
        body = self._build_chat_body(
            messages=messages, model=model, temperature=temperature,
            max_tokens=max_tokens, extra_options=extra_options,
        )
        if tools:
            body["tools"] = tools
        data = await self._post_json("/api/chat", body)
        msg = data.get("message", {}) or {}
        text = str(msg.get("content", "") or "")
        raw_calls = msg.get("tool_calls") or []
        tool_calls: list[ToolCall] = []
        for raw in raw_calls:
            fn = (raw or {}).get("function") or {}
            args = fn.get("arguments") or {}
            # Ollama returns args as a dict; if a model emits a JSON-string,
            # parse it tolerantly.
            if isinstance(args, str):
                import json as _json
                try:
                    args = _json.loads(args)
                except Exception:
                    args = {"_raw": args}
            tool_calls.append(ToolCall(
                name=str(fn.get("name") or ""),
                arguments=dict(args) if isinstance(args, dict) else {},
                id=str(raw.get("id")) if raw.get("id") else None,
                raw=dict(raw),
            ))
        return ChatResponse(
            text=text,
            tool_calls=tool_calls,
            done_reason=str(data.get("done_reason") or ""),
            raw_message=dict(msg),
        )

    def _build_chat_body(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        extra_options: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Shared body-builder for `chat()` and `chat_with_tools()`."""
        options: dict[str, Any] = {
            "temperature":    temperature if temperature is not None else self.cfg.temperature,
            "top_p":          self.cfg.top_p,
            "top_k":          self.cfg.top_k,
            "min_p":          self.cfg.min_p,
            "repeat_penalty": self.cfg.repeat_penalty,
        }
        # Only set num_predict when bounded. max_tokens <= 0 means "no cap"
        # — local Ollama accepts num_predict=-1 as unlimited, but the
        # `:cloud` endpoints (e.g. deepseek-v4-flash:cloud) reject it with
        # "max_tokens must be positive". Omitting the option entirely makes
        # both paths use their own defaults safely.
        resolved_max_tokens = max_tokens if max_tokens is not None else self.cfg.max_tokens
        if resolved_max_tokens and resolved_max_tokens > 0:
            options["num_predict"] = resolved_max_tokens
        # Only set num_ctx if explicitly configured (0 = let the model decide).
        if self.cfg.num_ctx and self.cfg.num_ctx > 0:
            options["num_ctx"] = self.cfg.num_ctx
        if extra_options:
            options.update(extra_options)
        return {
            "model": model or self.cfg.chat_model,
            "messages": messages,
            "stream": False,
            "options": options,
        }

    async def list_models(self) -> list[dict[str, Any]]:
        resp = await self._client.get("/api/tags")
        resp.raise_for_status()
        return list(resp.json().get("models", []))

    async def health_check(self) -> bool:
        """Returns True if Ollama service is reachable."""
        try:
            await self.list_models()
            return True
        except Exception as e:
            log.warning("ollama_health_check_failed", error=str(e))
            return False

    # ── Internals ─────────────────────────────────────────────────────────

    async def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        attempts = 0
        last_exc: Exception | None = None
        while attempts <= self.cfg.retries:
            attempts += 1
            try:
                resp = await self._client.post(path, json=body)
                resp.raise_for_status()
                return dict(resp.json())
            except httpx.HTTPStatusError as e:
                # 4xx errors are user errors; don't retry
                if 400 <= e.response.status_code < 500:
                    raise OllamaError(
                        f"Ollama {path} {e.response.status_code}: {e.response.text}"
                    ) from e
                last_exc = e
            except (httpx.RequestError, httpx.TimeoutException) as e:
                last_exc = e
                log.warning(
                    "ollama_request_retry",
                    path=path,
                    attempt=attempts,
                    max_attempts=self.cfg.retries + 1,
                    error=str(e),
                )
        raise OllamaError(
            f"Ollama {path} failed after {attempts} attempts: {last_exc}"
        ) from last_exc
