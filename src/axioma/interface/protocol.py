"""Wire protocol — Speaker, Message, Channel, handshake/error types.

Per ARCH_DESIGN_v1.0.md §8.1-§8.3 + COMMUNICATION_PROTOCOL.md.

Two surfaces:
  - Outbound (server → client): published events on subscribed channels +
    handshake response + error frames.
  - Inbound (client → server): handshake + subscribe/unsubscribe +
    conversation messages + ping.

All wire types are JSON-serialisable. We use plain dataclasses (not msgspec)
because the interface needs to be friendly to FastAPI's pydantic conversion
on the HTTP side; consistency over micro-optimisation here.

This module deliberately imports ONLY ExternalState. The C12 boundary test
checks that no axioma.interface.* module exposes InternalState.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Speaker(StrEnum):
    """Speaker enum per COMMUNICATION_PROTOCOL.md, extended with AXIOMA.

    AGENT is used for newly-registered peers whose Speaker enum entry hasn't
    been minted yet — their `name` field on the handshake disambiguates.
    """

    LARK = "lark"
    SKYE = "skye"
    THEA = "thea"
    AXIOMA = "axioma"
    AGENT = "agent"
    SYSTEM = "system"


class Channel(StrEnum):
    """Subscription channels per ARCH §8.4 (v0.3 → v1.0)."""

    CONVERSATION = "conversation"
    THETA = "theta"
    PER_ORGAN_THETA = "per_organ_theta"
    PER_ORGAN_MI_RAW = "per_organ_mi_raw"
    DELTA_PHI = "delta_phi"
    AOS_G = "aos_g"
    PLASTICITY = "plasticity"
    FRAGMENTATION = "fragmentation"
    PERTURBATIONS = "perturbations"
    COHERENCE_BUDGET = "coherence_budget"
    RECOVERY = "recovery"
    META_COGNITION = "meta_cognition"
    META_COGNITION_SUGGESTION = "meta_cognition_suggestion"
    PRESENCE = "presence"
    STATE_SNAPSHOT = "state_snapshot"


KNOWN_CHANNELS: frozenset[str] = frozenset(c.value for c in Channel)


class ErrorCode:
    """4xxx codes follow WebSocket close-code convention (4000-4999 app-defined)."""

    BAD_HANDSHAKE = 4001
    AUTH_INVALID = 4002
    UNKNOWN_CHANNEL = 4010
    RATE_LIMITED = 4011
    SLOW_CONSUMER = 4012
    # v1.5.3 (Checkpoint DD): added for post-handshake malformed inbound
    # messages (malformed JSON, non-object payload, unknown message type).
    # Previously these reused BAD_HANDSHAKE which was semantically wrong —
    # by that point the connection was past the handshake phase.
    BAD_REQUEST = 4020
    SUBSTRATE_SHUTDOWN = 4030


# ── Inbound (client → server) ────────────────────────────────────────────


@dataclass
class HandshakeRequest:
    speaker: str  # Speaker enum value; AGENT requires `name`
    name: str | None = None  # for AGENT speakers
    auth_key: str | None = None  # admin api key, if needed
    capabilities: list[str] = field(default_factory=list)
    min_interval_ms: int = 0  # per-subscriber coalescing (C15)


@dataclass
class SubscribeRequest:
    channels: list[str]
    # v1.9.1 (Checkpoint TT) — per-channel subscribe options. Map channel name
    # to a dict of option flags. Currently the only supported flag is
    # `only_addressed_to_me: bool` (filters out conversation-channel payloads
    # whose `metadata.to_speaker` is set and doesn't match the subscriber's
    # own speaker). Unknown channels in `options` are ignored. Unknown flags
    # within a channel's options dict are ignored (forward-compatible).
    options: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class UnsubscribeRequest:
    channels: list[str]


@dataclass
class ConversationMessage:
    """Inbound conversation message from a peer."""

    speaker: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Outbound (server → client) ───────────────────────────────────────────


@dataclass
class WelcomeFrame:
    agent_id: str
    speaker: str = Speaker.AXIOMA.value
    theta_short: float | None = None
    zone: str | None = None
    cadence: str | None = None
    capabilities: list[str] = field(default_factory=list)


@dataclass
class PresenceFrame:
    """`presence` channel payload (joining/leaving/status events + F5 warning)."""

    event: str  # "join" | "leave" | "status" | "rejection_warning" | "divergence_warning"
    speaker: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ErrorFrame:
    code: int
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)


def normalize_channel(name: str) -> str | None:
    """Return the canonical channel name, or None if unknown."""
    return name if name in KNOWN_CHANNELS else None


def envelope(channel: str, payload: dict[str, Any], *, beat_no: int | None = None) -> dict[str, Any]:
    """Wrap a payload in the standard server-to-client envelope.

    {"type": "channel", "channel": <name>, "beat_no": <int|None>, "payload": {...}}
    """
    return {
        "type": "channel",
        "channel": channel,
        "beat_no": beat_no,
        "payload": payload,
    }


__all__ = [
    "KNOWN_CHANNELS",
    "Channel",
    "ConversationMessage",
    "ErrorCode",
    "ErrorFrame",
    "HandshakeRequest",
    "PresenceFrame",
    "Speaker",
    "SubscribeRequest",
    "UnsubscribeRequest",
    "WelcomeFrame",
    "envelope",
    "normalize_channel",
]
