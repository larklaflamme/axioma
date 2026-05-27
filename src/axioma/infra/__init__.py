"""axioma.infra — infrastructure adapters.

Ollama (LLM + embeddings), Qdrant (vector store), Redis (KV + pub/sub),
GPU helpers (device selection, sync). These are wired into AxiomaContext
as optional resources; the substrate does NOT depend on them to run.
"""
from __future__ import annotations

from .gpu import gpu_info, gpu_sync, select_device
from .kv_store import KVStore, KVStoreError
from .ollama import OllamaClient, OllamaError
from .vector_store import VectorStore, VectorStoreError

__all__ = [
    "KVStore",
    "KVStoreError",
    "OllamaClient",
    "OllamaError",
    "VectorStore",
    "VectorStoreError",
    "gpu_info",
    "gpu_sync",
    "select_device",
]
