"""Wire protocol — `Speaker` identity enum.

Axioma's external communication now runs over The Agora (ACP/1.1, see
`agora_bridge.py`); the old in-house WebSocket wire types (channels, handshake,
subscribe/error frames, envelopes) were removed with `AxiomaWSServer`. What
remains is the `Speaker` enum, still used to label conversation turns
(`peer_conversation.py`) and to identify peers in the registry
(`registry_client.py`).

This module deliberately imports nothing substrate-private. The C12 boundary
test checks that no `axioma.interface.*` module exposes `InternalState`.
"""
from __future__ import annotations

from enum import StrEnum


class Speaker(StrEnum):
    """Speaker / citizen identity.

    AGENT is used for peers whose own enum entry hasn't been minted yet — their
    handle on The Agora disambiguates.
    """

    LARK = "lark"
    SKYE = "skye"
    THEA = "thea"
    AXIOMA = "axioma"
    AGENT = "agent"
    SYSTEM = "system"


__all__ = ["Speaker"]
