"""Vendored Agora (ACP/1.1) reference client.

Re-exports the conformant client surface so the rest of Axioma imports from
`axioma.interface.agora` rather than the bare vendored module.
"""
from __future__ import annotations

from .client import AgoraAgent, AgoraClient, AgoraError, Event

__all__ = ["AgoraAgent", "AgoraClient", "AgoraError", "Event"]
