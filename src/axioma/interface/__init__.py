"""axioma.interface — external surface (WS + HTTP + registry + peer conversation).

★ ARCHITECTURAL KEYSTONE — modules in this package MUST NOT import
`InternalState`. The C12 test enforces this at runtime; the import-linter
rule in pyproject.toml enforces it at lint time. Per ARCH §5 + §8.6.

Phase D builds:
  - protocol.py            : Speaker, Channel, message envelope types
  - subscriber.py          : per-WS-connection state + rate limit
  - ws_server.py           : WebSocket multiplexer (replaces ws_handlers stub)
  - registry_client.py     : agent registry registration + cache (best-effort)
  - peer_conversation.py   : Ollama-backed chat handler
  - http_api.py            : FastAPI control plane on :8821
  - ws_handlers.py         : retained as legacy alias (re-exports stub for C12)
"""
from __future__ import annotations

from .http_api import create_app
from .peer_conversation import PeerConversationHandler
from .protocol import (
    Channel,
    ConversationMessage,
    ErrorCode,
    HandshakeRequest,
    Speaker,
)
from .registry_client import AgentRegistration, PeerRecord, RegistryClient
from .subscriber import RateLimitTracker, Subscriber
from .ws_server import AxiomaWSServer

__all__ = [
    "AgentRegistration",
    "AxiomaWSServer",
    "Channel",
    "ConversationMessage",
    "ErrorCode",
    "HandshakeRequest",
    "PeerConversationHandler",
    "PeerRecord",
    "RateLimitTracker",
    "RegistryClient",
    "Speaker",
    "Subscriber",
    "create_app",
]
