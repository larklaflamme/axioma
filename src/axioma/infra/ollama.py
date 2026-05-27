"""Ollama LLM client — chat + embeddings via local Ollama service.

Models used (per .env):
  - chat: deepseek-v4-flash:cloud (default)
  - embeddings: nomic-embed-text-v2-moe (768-dim)

Async HTTP via httpx. Retries on transient network errors per config.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import OllamaConfig
from ..observability.logging import get_logger

log = get_logger(__name__)


class OllamaError(RuntimeError):
    """Wrapper for upstream Ollama HTTP / transport failures."""


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

        For streaming use chat_stream().
        """
        if stream:
            raise NotImplementedError("Use chat_stream() for streaming.")
        body: dict[str, Any] = {
            "model": model or self.cfg.chat_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature if temperature is not None else self.cfg.temperature,
                "num_predict": max_tokens if max_tokens is not None else self.cfg.max_tokens,
                **(extra_options or {}),
            },
        }
        data = await self._post_json("/api/chat", body)
        msg = data.get("message", {})
        return str(msg.get("content", ""))

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
