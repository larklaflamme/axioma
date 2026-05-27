"""Redis KV store adapter.

Per IMPLEMENTATION_PLAN_v1.0.md §2 — Redis is used for ephemeral KV +
pub/sub (e.g., registry cache, lightweight event distribution to external
processes). The substrate does NOT depend on Redis to run; loss of Redis
degrades but doesn't break.

Namespace: all keys prefixed `axioma:` to avoid collision with other apps
sharing the Redis instance.
"""
from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis

from ..config import RedisConfig
from ..observability.logging import get_logger

log = get_logger(__name__)


class KVStoreError(RuntimeError):
    pass


class KVStore:
    """Async Redis client with AXIOMA prefix conventions."""

    def __init__(self, cfg: RedisConfig) -> None:
        self.cfg = cfg
        self._client = aioredis.from_url(
            cfg.url,
            socket_timeout=cfg.socket_timeout_seconds,
            decode_responses=True,
        )

    @property
    def prefix(self) -> str:
        return self.cfg.key_prefix

    def _k(self, key: str) -> str:
        """Apply namespace prefix if not already applied."""
        return key if key.startswith(self.prefix) else f"{self.prefix}{key}"

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> KVStore:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ── KV operations ─────────────────────────────────────────────────────

    async def get(self, key: str) -> str | None:
        v = await self._client.get(self._k(key))
        return v if v is None else str(v)

    async def set(self, key: str, value: str, *, ex_seconds: int | None = None) -> None:
        await self._client.set(self._k(key), value, ex=ex_seconds)

    async def delete(self, key: str) -> int:
        return int(await self._client.delete(self._k(key)))

    async def exists(self, key: str) -> bool:
        return bool(await self._client.exists(self._k(key)))

    # ── Pub/Sub ───────────────────────────────────────────────────────────

    async def publish(self, channel: str, message: str) -> int:
        """Publish to a channel; returns number of subscribers that received."""
        return int(await self._client.publish(self._k(channel), message))

    async def health_check(self) -> bool:
        try:
            # redis.asyncio always returns awaitable; the stub union with sync
            # bool confuses mypy, so cast.
            result = self._client.ping()
            if hasattr(result, "__await__"):
                result = await result
            return bool(result)
        except Exception as e:
            log.warning("redis_health_check_failed", error=str(e))
            return False
