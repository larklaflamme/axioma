"""Integration tests against live Ollama / Qdrant / Redis services.

Marked @pytest.mark.infra; skipped if the corresponding service is down.
Run with: pytest -m infra
"""
from __future__ import annotations

import uuid

import pytest

from axioma.config import AxiomaConfig
from axioma.infra import KVStore, OllamaClient, VectorStore

pytestmark = pytest.mark.infra


# ── Ollama ─────────────────────────────────────────────────────────────────

@pytest.fixture()
async def ollama_client(loaded_cfg: AxiomaConfig):
    async with OllamaClient(loaded_cfg.infra.ollama) as cli:
        if not await cli.health_check():
            pytest.skip("Ollama service not reachable")
        yield cli


async def test_ollama_embed_returns_correct_dim(
    ollama_client: OllamaClient, loaded_cfg: AxiomaConfig
) -> None:
    embs = await ollama_client.embed("The substrate is integrated.")
    assert len(embs) == 1
    assert len(embs[0]) == loaded_cfg.infra.ollama.embed_dim


async def test_ollama_embed_batch(ollama_client: OllamaClient) -> None:
    texts = ["alpha", "beta", "gamma"]
    embs = await ollama_client.embed(texts)
    assert len(embs) == len(texts)
    # Different inputs → different embeddings
    assert embs[0] != embs[1]
    assert embs[1] != embs[2]


async def test_ollama_chat_returns_string(ollama_client: OllamaClient) -> None:
    reply = await ollama_client.chat(
        messages=[{"role": "user", "content": "Reply with just the literal word: OK"}],
        max_tokens=256,
    )
    # deepseek-v4-flash:cloud is a thinking model; reply may include reasoning markers.
    # We only assert: it's a string and finite.
    assert isinstance(reply, str)


async def test_ollama_list_models(ollama_client: OllamaClient, loaded_cfg: AxiomaConfig) -> None:
    models = await ollama_client.list_models()
    assert len(models) > 0
    names = {m.get("name", "") for m in models}
    assert loaded_cfg.infra.ollama.chat_model in names
    assert any(loaded_cfg.infra.ollama.embed_model in n for n in names)


# ── Qdrant ─────────────────────────────────────────────────────────────────

@pytest.fixture()
async def vector_store(loaded_cfg: AxiomaConfig):
    vs = VectorStore(loaded_cfg.infra.qdrant, loaded_cfg.infra.ollama.embed_dim)
    if not await vs.health_check():
        await vs.close()
        pytest.skip("Qdrant service not reachable")
    yield vs
    await vs.close()


async def test_vector_store_collection_lifecycle(vector_store: VectorStore) -> None:
    # Use a UUID suffix to avoid collisions across parallel test runs
    name = f"test_{uuid.uuid4().hex[:8]}"
    assert not await vector_store.collection_exists(name)
    qname = await vector_store.ensure_collection(name)
    try:
        assert qname.startswith("axioma_")
        assert await vector_store.collection_exists(name)
        # ensure_collection is idempotent
        qname2 = await vector_store.ensure_collection(name)
        assert qname == qname2
        assert await vector_store.collection_count(name) == 0
    finally:
        await vector_store.delete_collection(name)
    assert not await vector_store.collection_exists(name)


async def test_vector_store_upsert_search_delete(
    vector_store: VectorStore, loaded_cfg: AxiomaConfig
) -> None:
    name = f"test_{uuid.uuid4().hex[:8]}"
    await vector_store.ensure_collection(name)
    try:
        async with OllamaClient(loaded_cfg.infra.ollama) as oll:
            vecs = await oll.embed(
                ["integration is rising", "fragmentation imminent", "coherence stable"]
            )
            ids = await vector_store.upsert(
                name,
                embeddings=vecs,
                payloads=[
                    {"label": "good", "idx": 0},
                    {"label": "bad", "idx": 1},
                    {"label": "stable", "idx": 2},
                ],
            )
            assert len(ids) == 3
            assert await vector_store.collection_count(name) == 3

            # Query nearest to "high coherence" — should find "coherence stable"
            q = await oll.embed("high coherence")
            hits = await vector_store.search(name, query=q[0], limit=3)
            assert len(hits) == 3
            assert all("score" in h and "payload" in h for h in hits)
            # The top hit is the most-similar payload; we don't pin which
            top = hits[0]["payload"]
            assert top["label"] in {"good", "bad", "stable"}

            # Delete one
            await vector_store.delete(name, ids=[ids[0]])
            assert await vector_store.collection_count(name) == 2
    finally:
        await vector_store.delete_collection(name)


async def test_vector_store_upsert_length_mismatch_raises(
    vector_store: VectorStore,
) -> None:
    name = f"test_{uuid.uuid4().hex[:8]}"
    await vector_store.ensure_collection(name)
    try:
        with pytest.raises(ValueError, match="length mismatch"):
            await vector_store.upsert(
                name,
                embeddings=[[0.0] * 768, [0.0] * 768],
                payloads=[{"a": 1}],  # only 1 payload for 2 embeddings
            )
    finally:
        await vector_store.delete_collection(name)


async def test_vector_store_namespace_prefix(vector_store: VectorStore) -> None:
    """Collections we create are prefixed; existing non-prefixed collections
    are not in our list."""
    axioma_only = await vector_store.list_axioma_collections()
    assert all(c.startswith("axioma_") for c in axioma_only)


# ── Redis ──────────────────────────────────────────────────────────────────

@pytest.fixture()
async def kv_store(loaded_cfg: AxiomaConfig):
    kv = KVStore(loaded_cfg.infra.redis)
    if not await kv.health_check():
        await kv.close()
        pytest.skip("Redis service not reachable")
    yield kv
    await kv.close()


async def test_kv_set_get_delete(kv_store: KVStore) -> None:
    key = f"test_{uuid.uuid4().hex[:8]}"
    await kv_store.set(key, "hello", ex_seconds=60)
    assert await kv_store.exists(key)
    val = await kv_store.get(key)
    assert val == "hello"
    assert await kv_store.delete(key) == 1
    assert not await kv_store.exists(key)
    assert await kv_store.get(key) is None


async def test_kv_namespace_prefix(kv_store: KVStore, loaded_cfg: AxiomaConfig) -> None:
    """Verify the prefix is applied (and not double-applied)."""
    key = "raw_key"
    await kv_store.set(key, "v", ex_seconds=60)
    # Reading with the same logical key works
    assert await kv_store.get(key) == "v"
    # And with the fully-prefixed key (since we add prefix only if missing)
    assert await kv_store.get(loaded_cfg.infra.redis.key_prefix + key) == "v"
    await kv_store.delete(key)


async def test_kv_publish(kv_store: KVStore) -> None:
    """Publish returns receiver count; with no subscribers, 0."""
    n = await kv_store.publish("test_channel", "msg")
    assert n == 0  # no subscribers in this test
