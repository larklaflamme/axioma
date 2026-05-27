"""RegistryClient — best-effort registration + cache fallback.

Per ARCH §9.3.4 + PLAN §8.6: registry outage is NOT fatal at startup.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from axioma.config import AxiomaConfig, InterfaceConfig, PersistenceConfig
from axioma.interface.registry_client import PeerRecord, RegistryClient
from axioma.observability import AxiomaContext


def _cfg(tmp_path: Path, registry_url: str = "http://127.0.0.1:0/registry") -> AxiomaConfig:
    return AxiomaConfig(
        interface=InterfaceConfig(registry_url=registry_url),
        persistence=PersistenceConfig(snapshot_root=str(tmp_path)),
    )


@pytest.mark.asyncio
async def test_start_degrades_on_unreachable(tmp_path: Path) -> None:
    """Unreachable registry → degraded mode + start() still returns."""
    ctx = AxiomaContext()
    cfg = _cfg(tmp_path, registry_url="http://127.0.0.1:1/registry")
    client = RegistryClient(ctx=ctx, cfg=cfg)
    # Avoid the heartbeat loop firing during the test
    cfg = _cfg(tmp_path, registry_url="http://127.0.0.1:1/registry")
    client = RegistryClient(ctx=ctx, cfg=cfg)
    await client.start()
    try:
        assert client.degraded is True
        assert client.agent_id is None
        assert client.peers == []
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_loads_cached_peers_from_disk(tmp_path: Path) -> None:
    cache = tmp_path / "registry_cache.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({
        "saved_at": 0.0,
        "peers": [
            {"name": "skye", "ws_url": "ws://skye:8000", "speaker": "skye"},
        ],
    }))
    ctx = AxiomaContext()
    cfg = _cfg(tmp_path, registry_url="http://127.0.0.1:1/registry")
    client = RegistryClient(ctx=ctx, cfg=cfg, cache_path=cache)
    await client.start()
    try:
        assert any(p.name == "skye" for p in client.peers)
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_corrupt_cache_yields_empty_peers(tmp_path: Path) -> None:
    cache = tmp_path / "registry_cache.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("not_valid_json{")
    ctx = AxiomaContext()
    cfg = _cfg(tmp_path, registry_url="http://127.0.0.1:1/registry")
    client = RegistryClient(ctx=ctx, cfg=cfg, cache_path=cache)
    await client.start()
    try:
        assert client.peers == []
        assert client.degraded is True
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_registration_4xx_emits_rejected_event(tmp_path: Path) -> None:
    """4xx response → register_rejected event + degraded; no crash."""
    ctx = AxiomaContext()
    seen: list[Any] = []
    ctx.subscribe("registry_registration_rejected", lambda p: seen.append(p))
    cfg = _cfg(tmp_path)

    # Monkey-patch httpx.AsyncClient.post to return 409
    class _FakeResp:
        status_code = 409
        text = "agent_id_in_use"
        def raise_for_status(self) -> None:
            raise httpx.HTTPStatusError(
                "409",
                request=httpx.Request("POST", "http://x"),
                response=httpx.Response(409, text=self.text),
            )
        def json(self) -> dict[str, Any]:
            return {}

    client = RegistryClient(ctx=ctx, cfg=cfg)

    async def fake_post(self: Any, url: str, json: Any = None) -> _FakeResp:
        return _FakeResp()
    import httpx as _h
    _h.AsyncClient.post = fake_post  # type: ignore[assignment]
    try:
        await client.start()
        assert client.degraded is True
        assert any(s.get("status") == 409 for s in seen)
    finally:
        await client.stop()
        # restore — pytest test isolation
        delattr(_h.AsyncClient, "post")


@pytest.mark.asyncio
async def test_successful_registration_clears_degraded(tmp_path: Path) -> None:
    ctx = AxiomaContext()
    cfg = _cfg(tmp_path)
    client = RegistryClient(ctx=ctx, cfg=cfg)

    async def fake_post(self: Any, url: str, json: Any = None) -> Any:
        class _OK:
            status_code = 200
            def raise_for_status(self) -> None:
                pass
            def json(self) -> dict[str, Any]:
                return {"agent_id": "axioma-001", "heartbeat_interval_seconds": 30}
        return _OK()

    async def fake_get(self: Any, url: str) -> Any:
        class _OK:
            status_code = 200
            def raise_for_status(self) -> None:
                pass
            def json(self) -> dict[str, Any]:
                return {"agents": [
                    {"name": "skye", "ws_url": "ws://skye:8000", "speaker": "skye"},
                ]}
        return _OK()

    import httpx as _h
    _h.AsyncClient.post = fake_post  # type: ignore[assignment]
    _h.AsyncClient.get = fake_get  # type: ignore[assignment]
    try:
        await client.start()
        assert client.degraded is False
        assert client.agent_id == "axioma-001"
        assert any(p.name == "skye" for p in client.peers)
        # And the disk cache was written
        assert (Path(cfg.persistence.snapshot_root) / "registry_cache.json").exists()
    finally:
        await client.stop()
        delattr(_h.AsyncClient, "post")
        delattr(_h.AsyncClient, "get")


def test_peer_record_dataclass_roundtrip() -> None:
    p = PeerRecord(name="skye", ws_url="ws://x", speaker="skye", capabilities=["chat"])
    from dataclasses import asdict
    d = asdict(p)
    assert d["name"] == "skye"
    assert "chat" in d["capabilities"]
