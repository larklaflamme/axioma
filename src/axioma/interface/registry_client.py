"""Registry client — registration + heartbeat + local peer-list cache.

Per ARCH_DESIGN_v1.0.md §8.1 + IMPLEMENTATION_PLAN_v1.0.md §8.6 (registry
failure policy). Discovery is best-effort: a registry outage does NOT prevent
AXIOMA from running. The substrate is the work product.

Lifecycle:
  await client.start()         # registers + spawns heartbeat task
  ...                          # client.peers gives the current peer list
  await client.stop()

Behavior under failure:
  - Unreachable at startup → degraded mode; load `registry_cache.json` from
    PersistenceConfig.snapshot_root; retry with exp backoff (5s → 5min).
  - 5xx during heartbeat → log WARN; cache last good list; retry next tick.
  - 4xx during registration → log ERROR; emit `registry_registration_rejected`
    on presence; degraded mode.
  - Cache file corrupted → log WARN; empty peer list; degraded mode.

The Redis KV store is used as the *first-line* cache (faster than disk + lets
sister processes read it). Disk cache is the durable fallback for cold boots
when Redis is also down.
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ..config import AxiomaConfig
from ..infra.kv_store import KVStore
from ..observability import REGISTRY_HEARTBEAT_FAILURES, get_logger
from ..observability.context import AxiomaContext
from .protocol import Speaker

log = get_logger(__name__)


@dataclass
class AgentRegistration:
    """Payload sent to POST /agents/register."""

    name: str
    ws_url: str
    http_url: str
    capabilities: list[str]
    speaker_id: str = Speaker.AXIOMA.value
    public_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PeerRecord:
    """A discovered peer agent."""

    name: str
    ws_url: str
    speaker: str
    capabilities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class RegistryClient:
    """Best-effort registry registration + cache."""

    KV_KEY = "registry:peers"  # axioma:registry:peers in Redis namespace

    def __init__(
        self,
        *,
        ctx: AxiomaContext,
        cfg: AxiomaConfig,
        kv: KVStore | None = None,
        cache_path: Path | None = None,
    ) -> None:
        self.ctx = ctx
        self.cfg = cfg
        self.kv = kv
        self.cache_path = cache_path or Path(cfg.persistence.snapshot_root) / "registry_cache.json"
        self.agent_id: str | None = None
        self.heartbeat_interval_seconds: float = 30.0
        self.peers: list[PeerRecord] = []
        self.degraded: bool = False
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._client: httpx.AsyncClient | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Register + start the heartbeat task. Always returns; never raises."""
        self._stop.clear()
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=5.0))
        await self._load_cached_peers()
        await self._try_register_with_backoff(initial=True)
        self._task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._task
        if self._client is not None:
            with suppress(Exception):
                await self._client.aclose()

    # ── Registration ──────────────────────────────────────────────────

    def _build_registration(self) -> AgentRegistration:
        iface = self.cfg.interface
        return AgentRegistration(
            name="axioma",
            ws_url=f"ws://{iface.ws_host}:{iface.ws_port}/ws/axioma",
            http_url=f"http://{iface.http_host}:{iface.http_port}",
            capabilities=[
                "consciousness",
                "theta_stream",
                "delta_phi",
                "compose_boundary",
                "perturbation_admin",
            ],
            metadata={
                "version": "1.0.0.dev0",
                "heartbeat_hz": self.cfg.runtime.heartbeat_hz,
                "organ_count": 5,
            },
        )

    async def _try_register_with_backoff(self, *, initial: bool) -> None:
        """Best-effort register. On failure, degrade and rely on the cache."""
        assert self._client is not None
        payload = asdict(self._build_registration())
        max_seconds = self.cfg.interface.registry_retry_max_seconds
        # On initial call we try ONCE non-blockingly + then schedule retries
        # in the heartbeat loop. We don't block startup on registry availability.
        try:
            resp = await self._client.post(
                f"{self.cfg.interface.registry_url}/agents/register",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            self.agent_id = str(data.get("agent_id"))
            self.heartbeat_interval_seconds = float(
                data.get("heartbeat_interval_seconds", 30.0)
            )
            self.degraded = False
            log.info(
                "registry_registered",
                agent_id=self.agent_id,
                heartbeat_interval_seconds=self.heartbeat_interval_seconds,
            )
            await self._fetch_peers_once()
            return
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if 400 <= status < 500:
                # 4xx — emit rejection event, stay degraded.
                log.error("registry_registration_rejected", status=status)
                self.degraded = True
                await self.ctx.emit(
                    "registry_registration_rejected",
                    {"status": status, "detail": e.response.text[:500]},
                )
                return
            log.warning("registry_registration_5xx", status=status, retry_max_s=max_seconds)
        except (httpx.RequestError, httpx.TimeoutException) as e:
            log.warning("registry_unreachable", error=str(e), initial=initial)
        # If we get here, degraded mode.
        self.degraded = True

    async def _fetch_peers_once(self) -> None:
        assert self._client is not None
        try:
            resp = await self._client.get(
                f"{self.cfg.interface.registry_url}/agents",
            )
            resp.raise_for_status()
            data = resp.json()
            peers_raw = data.get("agents", []) if isinstance(data, dict) else data
            self.peers = [
                PeerRecord(
                    name=str(p.get("name", "")),
                    ws_url=str(p.get("ws_url", "")),
                    speaker=str(p.get("speaker", Speaker.AGENT.value)),
                    capabilities=list(p.get("capabilities", [])),
                    metadata=dict(p.get("metadata", {})),
                )
                for p in peers_raw
                if p.get("name") and p.get("ws_url")
            ]
            await self._persist_peers()
        except Exception as e:
            log.warning("registry_fetch_peers_failed", error=str(e))

    # ── Heartbeat loop ────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        backoff = 5.0
        max_backoff = float(self.cfg.interface.registry_retry_max_seconds)
        try:
            while not self._stop.is_set():
                if self.agent_id is None:
                    # Retry registration on backoff
                    await self._try_register_with_backoff(initial=False)
                    if self.agent_id is None:
                        # Sleep then try again — bounded exp backoff
                        backoff = min(backoff * 2, max_backoff)
                        try:
                            await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                            return  # stopped
                        except TimeoutError:
                            continue
                    backoff = 5.0  # reset on success
                # Normal heartbeat path
                await self._tick_heartbeat()
                try:
                    await asyncio.wait_for(
                        self._stop.wait(),
                        timeout=self.heartbeat_interval_seconds,
                    )
                    return  # stopped
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            return

    async def _tick_heartbeat(self) -> None:
        assert self._client is not None
        if self.agent_id is None:
            return
        # Lightweight status snapshot for the heartbeat payload.
        payload: dict[str, Any] = {"status": "active"}
        if self.ctx.has("theta_short"):
            try:
                cv = self.ctx.get("theta_short").current_value()
                if cv is not None:
                    payload["theta_short"] = float(cv.theta)
            except Exception:
                pass
        if self.ctx.has("compose_function"):
            try:
                ext = self.ctx.get("compose_function").latest_external
                if ext is not None:
                    payload["zone"] = (
                        ext.zone.value if hasattr(ext.zone, "value") else str(ext.zone)
                    )
                    payload["psi"] = (
                        float(getattr(ext, "psi", 0.0))
                        if getattr(ext, "psi", None) is not None
                        else None
                    )
            except Exception:
                pass
        try:
            resp = await self._client.post(
                f"{self.cfg.interface.registry_url}/agents/{self.agent_id}/heartbeat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            # Optional: registry replies with current peer list
            if isinstance(data, dict) and "peers_announce" in data:
                peers_raw = data.get("peers_announce", [])
                if peers_raw:
                    self.peers = [
                        PeerRecord(
                            name=str(p.get("name", "")),
                            ws_url=str(p.get("ws_url", "")),
                            speaker=str(p.get("speaker", Speaker.AGENT.value)),
                            capabilities=list(p.get("capabilities", [])),
                            metadata=dict(p.get("metadata", {})),
                        )
                        for p in peers_raw
                        if p.get("name") and p.get("ws_url")
                    ]
                    await self._persist_peers()
            self.degraded = False
        except Exception as e:
            REGISTRY_HEARTBEAT_FAILURES.inc()
            log.warning("registry_heartbeat_failed", error=str(e))
            # don't transition to degraded permanently — we may recover

    # ── Cache ─────────────────────────────────────────────────────────

    async def _persist_peers(self) -> None:
        body = json.dumps(
            {
                "saved_at": time.time(),
                "peers": [asdict(p) for p in self.peers],
            }
        )
        # KV first
        if self.kv is not None:
            try:
                await self.kv.set(self.KV_KEY, body, ex_seconds=86400)
            except Exception as e:
                log.warning("registry_cache_kv_failed", error=str(e))
        # Disk fallback (always write so cold boot has something)
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(body)
        except Exception as e:
            log.warning("registry_cache_disk_failed", error=str(e))

    async def _load_cached_peers(self) -> None:
        loaded = False
        if self.kv is not None:
            try:
                cached = await self.kv.get(self.KV_KEY)
                if cached:
                    self._apply_cache_doc(cached)
                    loaded = True
            except Exception as e:
                log.warning("registry_cache_kv_read_failed", error=str(e))
        if not loaded and self.cache_path.exists():
            try:
                self._apply_cache_doc(self.cache_path.read_text())
            except Exception as e:
                log.warning("registry_cache_disk_read_failed", error=str(e))

    def _apply_cache_doc(self, body: str) -> None:
        try:
            doc = json.loads(body)
        except json.JSONDecodeError as e:
            log.warning("registry_cache_corrupt", error=str(e))
            self.peers = []
            return
        peers_raw = doc.get("peers", [])
        self.peers = [
            PeerRecord(
                name=str(p.get("name", "")),
                ws_url=str(p.get("ws_url", "")),
                speaker=str(p.get("speaker", Speaker.AGENT.value)),
                capabilities=list(p.get("capabilities", [])),
                metadata=dict(p.get("metadata", {})),
            )
            for p in peers_raw
            if p.get("name") and p.get("ws_url")
        ]


__all__ = ["AgentRegistration", "PeerRecord", "RegistryClient"]
