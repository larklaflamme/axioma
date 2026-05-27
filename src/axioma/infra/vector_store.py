"""Qdrant vector store adapter for AXIOMA.

Namespace: all AXIOMA collections are prefixed with `axioma_` so we don't
collide with the 10 existing collections (theoria_memories, skye_memory, …).

Typical collections:
  - axioma_memories    — MNEME episodic recall
  - axioma_episodes    — full ExternalState snapshots for semantic search
  - axioma_meta        — meta-cognition notes for retrospective analysis

All operations are async (qdrant-client AsyncQdrantClient).
"""
from __future__ import annotations

import uuid
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm

from ..config import QdrantConfig
from ..observability.logging import get_logger

log = get_logger(__name__)


class VectorStoreError(RuntimeError):
    pass


class VectorStore:
    """Wrapper around AsyncQdrantClient with AXIOMA conventions baked in."""

    def __init__(self, cfg: QdrantConfig, embed_dim: int) -> None:
        self.cfg = cfg
        self.embed_dim = embed_dim
        api_key = cfg.api_key.get_secret_value() if cfg.api_key else None
        self._client = AsyncQdrantClient(
            url=cfg.url,
            api_key=api_key,
            timeout=cfg.timeout_seconds,
        )

    @property
    def prefix(self) -> str:
        return self.cfg.collection_prefix

    def _qname(self, name: str) -> str:
        """Apply namespace prefix if not already applied."""
        return name if name.startswith(self.prefix) else f"{self.prefix}{name}"

    async def close(self) -> None:
        await self._client.close()

    async def __aenter__(self) -> VectorStore:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ── Collection management ─────────────────────────────────────────────

    async def ensure_collection(
        self,
        name: str,
        *,
        distance: qm.Distance = qm.Distance.COSINE,
        on_disk: bool = False,
    ) -> str:
        """Create the collection if not present. Returns the namespaced name."""
        qname = self._qname(name)
        existing = {c.name for c in (await self._client.get_collections()).collections}
        if qname in existing:
            return qname
        await self._client.create_collection(
            collection_name=qname,
            vectors_config=qm.VectorParams(
                size=self.embed_dim,
                distance=distance,
                on_disk=on_disk,
            ),
        )
        log.info("vector_collection_created", name=qname, dim=self.embed_dim, distance=str(distance))
        return qname

    async def delete_collection(self, name: str) -> None:
        qname = self._qname(name)
        await self._client.delete_collection(qname)
        log.info("vector_collection_deleted", name=qname)

    async def collection_exists(self, name: str) -> bool:
        qname = self._qname(name)
        existing = {c.name for c in (await self._client.get_collections()).collections}
        return qname in existing

    async def collection_count(self, name: str) -> int:
        qname = self._qname(name)
        info = await self._client.count(collection_name=qname, exact=True)
        return int(info.count)

    async def list_axioma_collections(self) -> list[str]:
        """List only collections in the axioma_ namespace."""
        existing = (await self._client.get_collections()).collections
        return sorted(c.name for c in existing if c.name.startswith(self.prefix))

    # ── Points ────────────────────────────────────────────────────────────

    async def upsert(
        self,
        name: str,
        *,
        embeddings: list[list[float]],
        payloads: list[dict[str, Any]],
        ids: list[str] | None = None,
    ) -> list[str]:
        """Upsert vectors with payloads. Returns the IDs used."""
        if len(embeddings) != len(payloads):
            raise ValueError(
                f"embeddings ({len(embeddings)}) and payloads ({len(payloads)}) length mismatch"
            )
        qname = self._qname(name)
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in embeddings]
        elif len(ids) != len(embeddings):
            raise ValueError(f"ids length {len(ids)} != embeddings length {len(embeddings)}")
        points = [
            qm.PointStruct(id=i, vector=v, payload=p)
            for i, v, p in zip(ids, embeddings, payloads, strict=True)
        ]
        await self._client.upsert(collection_name=qname, points=points, wait=True)
        return ids

    async def search(
        self,
        name: str,
        *,
        query: list[float],
        limit: int = 5,
        score_threshold: float | None = None,
        filter_: qm.Filter | None = None,
    ) -> list[dict[str, Any]]:
        """Vector similarity search. Returns list of {id, score, payload}."""
        qname = self._qname(name)
        # query_points is the modern API (replaces deprecated search())
        result = await self._client.query_points(
            collection_name=qname,
            query=query,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=filter_,
            with_payload=True,
        )
        return [
            {"id": str(p.id), "score": float(p.score), "payload": p.payload}
            for p in result.points
        ]

    async def delete(self, name: str, *, ids: list[str]) -> None:
        qname = self._qname(name)
        await self._client.delete(
            collection_name=qname,
            points_selector=qm.PointIdsList(points=ids),  # type: ignore[arg-type]
            wait=True,
        )

    async def health_check(self) -> bool:
        try:
            await self._client.get_collections()
            return True
        except Exception as e:
            log.warning("qdrant_health_check_failed", error=str(e))
            return False
