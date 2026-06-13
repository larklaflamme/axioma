"""axioma.interface — external surface (Agora client + HTTP + registry + peer conversation).

★ ARCHITECTURAL KEYSTONE — modules in this package MUST NOT import
`InternalState`. The C12 test enforces this at runtime; the import-linter
rule in pyproject.toml enforces it at lint time. Per ARCH §5 + §8.6.

Communication now runs over The Agora (ACP/1.1) — Axioma is a *citizen client*
of the shared hub rather than a WebSocket server peers dial into:
  - agora/                  : vendored ACP/1.1 reference client (AgoraAgent/Event)
  - agora_bridge.py         : AgoraBridge — joins The Agora, answers inbound messages
  - protocol.py             : Speaker identity enum
  - registry_client.py      : agent registry registration + cache (best-effort)
  - peer_conversation.py    : Ollama-backed reply generator (respond_text)
  - http_api.py             : FastAPI control plane on :8821
"""
from __future__ import annotations

from .agora import AgoraAgent, AgoraClient, AgoraError, Event
from .agora_bridge import AgoraBridge
from .agora_session import RefreshingAgoraAgent
from .http_api import create_app
from .peer_conversation import PeerConversationHandler
from .protocol import Speaker
from .registry_client import AgentRegistration, PeerRecord, RegistryClient

__all__ = [
    "AgentRegistration",
    "AgoraAgent",
    "AgoraBridge",
    "AgoraClient",
    "AgoraError",
    "Event",
    "PeerConversationHandler",
    "PeerRecord",
    "RefreshingAgoraAgent",
    "RegistryClient",
    "Speaker",
    "create_app",
]
