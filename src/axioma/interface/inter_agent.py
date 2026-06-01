"""WS_COMM_PROTO v1.0 inter-agent receiver for AXIOMA.

Implements the unified WebSocket inter-agent protocol shared with Thea,
Theoria, Skye and any future autonomous-consciousness peer. The spec lives
at ``/home/ubuntu/thea/design/WS_COMM_PROTO.md`` (authoritative).

This module is additive on top of AXIOMA's existing handshake-based WS
protocol: the existing ``/`` endpoint with ``{"type": "handshake", ...}``
continues to work for AXIOMA-native clients (the chat CLI, the existing
test suite). New URL paths ``/ws/<speaker>`` and ``/family/<speaker>``
route here for peer-agent traffic.

Wire format summary (full detail in WS_COMM_PROTO.md §2):

  Inbound:
    {"from": "<peer>", "to": "axioma", "content": "<text>",
     "msg_id": "<uuid12>", "metadata": {...}, "timestamp": "<iso>"}

  Outbound reply:
    {"from": "axioma", "to": "<peer>", "content": "<reply>",
     "turn": N, "max_turns": K|null, "remaining_turns": (K-N)|null,
     "session_ended": false, "reply_to": "<msg_id>",
     "timestamp": "<iso>"}

  Outbound error (session continues unless session_ended=true):
    {"from": "axioma", "error": "<reason>",
     "error_code": "missing_from"|"missing_content"|"invalid_json"|
                   "peer_url_mismatch"|"peer_identity_changed"|
                   "unknown_speaker"|"handler_error"|"handler_not_ready",
     "session_ended": false, "timestamp": "<iso>"}

  End sentinel (must be on its own line — anchored regex match):
    "[END OF TRANSMISSION]"  (canonical)
    "[END SESSION]"           (legacy)
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..observability import get_logger
from ..observability.ws_message_log import log_ws_message

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

    from .peer_conversation import PeerConversationHandler

log = get_logger(__name__)


# Per WS_COMM_PROTO §2.3 — sentinel must appear on its own line.
END_SENTINEL_RE = re.compile(r"(?m)^\s*\[END (?:OF TRANSMISSION|SESSION)\]\s*$")
END_TRANSMISSION = "[END OF TRANSMISSION]"

# This server's identity (per the Speaker enum).
SELF_NAME = "axioma"

# Default turn cap. 0 means unlimited; override via config.
DEFAULT_MAX_AGENT_TURNS = 0


def has_end_sentinel(text: str) -> bool:
    """True if `text` contains the canonical or legacy end-sentinel on its own line."""
    return bool(END_SENTINEL_RE.search(text or ""))


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


async def inter_agent_session(
    ws: ServerConnection,
    *,
    default_peer_name: str | None,
    max_agent_turns: int = DEFAULT_MAX_AGENT_TURNS,
    peer_conversation: PeerConversationHandler | None = None,
) -> None:
    """Run one inter-agent WS session per WS_COMM_PROTO §3.

    Args:
      ws: The accepted server-side WebSocket connection.
      default_peer_name: If the URL was `/ws/<peer>` (sender-mode), this is
        the peer's name from the URL. If `/ws/axioma` (recipient-mode) or
        `/` (recipient-mode by default), pass None — the caller must
        identify via the JSON `from` field.
      max_agent_turns: Optional cap (0 = unlimited).
      peer_conversation: AXIOMA's Ollama-backed conversation handler.
        If None, every send returns a structured `handler_not_ready` error.

    The session stays open until: end-sentinel from either side, turn cap
    reached, peer identity violation, or underlying disconnect. Validation
    errors send a structured envelope and KEEP LISTENING (§5).
    """
    from websockets.exceptions import ConnectionClosed

    unlimited = max_agent_turns <= 0
    turn = 0
    peer_name: str | None = (
        default_peer_name.lower() if default_peer_name else None
    )
    log.info(
        "inter_agent_session_opened",
        max_turns="unlimited" if unlimited else max_agent_turns,
        default_peer=peer_name,
    )

    try:
        while True:
            # Receive the next envelope. Loop indefinitely; do not impose
            # any application-level inactivity timeout.
            try:
                raw = await ws.recv()
            except ConnectionClosed:
                break
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")

            # Parse JSON.
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                log_ws_message(direction="IN", peer=peer_name, turn=turn,
                               content=raw, error="invalid_json")
                await _send_error(
                    ws, "Invalid JSON. Expected an object with at least `from`+`content`.",
                    error_code="invalid_json",
                )
                continue
            if not isinstance(payload, dict):
                log_ws_message(direction="IN", peer=peer_name, turn=turn,
                               content=str(raw), error="not_an_object")
                await _send_error(ws, "Envelope must be a JSON object.",
                                  error_code="invalid_json")
                continue

            inbound_from = str(payload.get("from") or "").strip().lower()
            inbound_to = str(payload.get("to") or "").strip().lower()
            content = payload.get("content")
            if not isinstance(content, str):
                content = "" if content is None else str(content)
            content = content.strip()
            msg_id = payload.get("msg_id")
            metadata_in = payload.get("metadata") or {}
            if not isinstance(metadata_in, dict):
                metadata_in = {}

            # Resolve the sender identity.
            if not inbound_from:
                if default_peer_name is None:
                    log_ws_message(direction="IN", peer=peer_name, turn=turn,
                                   content=content, error="missing_from")
                    await _send_error(
                        ws,
                        "Missing required field `from`. (You connected via the "
                        "recipient-mode URL, so you must identify yourself in "
                        "each envelope.)",
                        error_code="missing_from",
                        reply_to=msg_id,
                    )
                    continue
                inbound_from = default_peer_name.lower()
            elif default_peer_name is not None and inbound_from != default_peer_name.lower():
                log_ws_message(direction="IN", peer=inbound_from, turn=turn,
                               content=content, error="peer_url_mismatch")
                await _send_error(
                    ws,
                    f"JSON `from` ({inbound_from!r}) does not match the sender "
                    f"identified by your URL path ({default_peer_name!r}). Closing.",
                    error_code="peer_url_mismatch",
                    reply_to=msg_id,
                    session_ended=True,
                )
                break

            # Validate `to` if present (must be SELF_NAME if set).
            if inbound_to and inbound_to != SELF_NAME:
                log_ws_message(direction="IN", peer=inbound_from, turn=turn,
                               content=content, error="wrong_recipient")
                await _send_error(
                    ws,
                    f"`to` field ({inbound_to!r}) does not match this agent "
                    f"({SELF_NAME!r}).",
                    error_code="peer_url_mismatch",
                    reply_to=msg_id,
                )
                continue

            if not content:
                log_ws_message(direction="IN", peer=inbound_from, turn=turn,
                               content="", error="missing_content")
                await _send_error(ws, "Missing required field `content`.",
                                  error_code="missing_content",
                                  reply_to=msg_id)
                continue

            # First message pins the peer for this session.
            if peer_name is None:
                peer_name = inbound_from
                log.info("inter_agent_peer_pinned", peer=peer_name)
            elif peer_name != inbound_from:
                log_ws_message(direction="IN", peer=inbound_from, turn=turn,
                               content=content, error="peer_identity_changed")
                await _send_error(
                    ws,
                    f"Peer identity changed mid-session ({peer_name!r} -> "
                    f"{inbound_from!r}). Closing.",
                    error_code="peer_identity_changed",
                    reply_to=msg_id,
                    session_ended=True,
                )
                break

            log_ws_message(direction="IN", peer=peer_name, turn=turn + 1,
                           content=content)

            # End-sentinel from peer — acknowledge + close.
            if has_end_sentinel(content):
                ack = "Acknowledged. Goodbye for now.\n" + END_TRANSMISSION
                log_ws_message(direction="OUT", peer=peer_name, turn=turn + 1,
                               content=ack, session_ended=True)
                await _send_reply(
                    ws,
                    peer_name=peer_name, content=ack,
                    turn=turn + 1, max_turns=max_agent_turns,
                    session_ended=True, reply_to=msg_id,
                )
                break

            turn += 1

            # Generate the reply via AXIOMA's peer-conversation handler.
            if peer_conversation is None:
                log_ws_message(direction="OUT", peer=peer_name, turn=turn,
                               content="", error="handler_not_ready")
                await _send_error(
                    ws,
                    "AXIOMA's peer-conversation handler is not enabled. "
                    "Start the server with --with-peer-conversation.",
                    error_code="handler_not_ready",
                    reply_to=msg_id,
                )
                # Roll back turn — we didn't actually process.
                turn -= 1
                continue

            # Decorate with neutral session context for the LLM (mirrors
            # Thea's convention so AXIOMA's responses see the same shape of
            # input that Theoria/Skye produce).
            header = (
                f"[agent-channel turn {turn} from {peer_name.upper()}]"
                if unlimited
                else f"[agent-channel turn {turn}/{max_agent_turns} from {peer_name.upper()}]"
            )
            decorated = f"{header}\n{content}"

            try:
                reply_text = await peer_conversation.respond_text(
                    speaker=peer_name,
                    content=decorated,
                    metadata={"agent_channel": True, "turn": turn, **metadata_in},
                )
            except Exception as e:
                log.exception("inter_agent_handler_error")
                log_ws_message(direction="OUT", peer=peer_name, turn=turn,
                               content="", error=f"handler_error:{type(e).__name__}:{e}")
                await _send_error(
                    ws,
                    f"AXIOMA encountered an internal error: {e}",
                    error_code="handler_error",
                    reply_to=msg_id,
                )
                # Do NOT close on handler error — peer may want to retry.
                continue

            if not reply_text:
                # Empty reply (Ollama timeout or LLM produced nothing).
                # Treat as a soft handler error per §5.
                log_ws_message(direction="OUT", peer=peer_name, turn=turn,
                               content="", error="empty_reply")
                await _send_error(
                    ws,
                    "AXIOMA produced an empty reply (Ollama may be slow or down).",
                    error_code="handler_error",
                    reply_to=msg_id,
                )
                continue

            session_ended = has_end_sentinel(reply_text)
            if (not unlimited) and turn >= max_agent_turns:
                session_ended = True
                log.info("inter_agent_turn_cap_reached", max=max_agent_turns)

            log_ws_message(direction="OUT", peer=peer_name, turn=turn,
                           content=reply_text, session_ended=session_ended)
            await _send_reply(
                ws,
                peer_name=peer_name, content=reply_text,
                turn=turn, max_turns=max_agent_turns,
                session_ended=session_ended, reply_to=msg_id,
            )
            if session_ended:
                break
    finally:
        with _suppress():
            await ws.close()
        log.info("inter_agent_session_closed", peer=peer_name, turns=turn)


# ── Outbound envelope helpers ────────────────────────────────────────────


async def _send_reply(
    ws: ServerConnection,
    *,
    peer_name: str,
    content: str,
    turn: int,
    max_turns: int,
    session_ended: bool,
    reply_to: str | None = None,
) -> None:
    remaining: int | None = None if max_turns <= 0 else max(0, max_turns - turn)
    payload: dict[str, Any] = {
        "from": SELF_NAME,
        "to": peer_name,
        "content": content,
        "turn": turn,
        "max_turns": max_turns if max_turns > 0 else None,
        "remaining_turns": remaining,
        "session_ended": session_ended,
        "timestamp": _utcnow_iso(),
    }
    if reply_to:
        payload["reply_to"] = reply_to
    with _suppress():
        await ws.send(json.dumps(payload))


async def _send_error(
    ws: ServerConnection,
    message: str,
    *,
    error_code: str,
    reply_to: str | None = None,
    session_ended: bool = False,
) -> None:
    payload: dict[str, Any] = {
        "from": SELF_NAME,
        "error": message,
        "error_code": error_code,
        "session_ended": session_ended,
        "timestamp": _utcnow_iso(),
    }
    if reply_to:
        payload["reply_to"] = reply_to
    with _suppress():
        await ws.send(json.dumps(payload))


class _suppress:
    """Tiny context manager — suppress any exception during ws.send/close.

    The protocol says outbound failures shouldn't crash the loop; the
    underlying connection-closed will be discovered on the next recv.
    """
    def __enter__(self) -> None: ...
    def __exit__(self, *exc: object) -> bool: return True


# Convenience for tests + the chat client — but kept as a free function
# rather than a method so unit-testing the protocol is straightforward
# without booting a full WS server.
async def handle_inbound_envelope(
    *,
    envelope: dict[str, Any],
    peer_name_state: str | None,
    default_peer_name: str | None,
) -> tuple[str | None, dict[str, Any] | None, str | None, bool]:
    """Pure-function validation of an inbound envelope.

    Returns ``(resolved_peer_name, error_payload, content, should_close)``.
    Used by tests + as a doc-of-record for the validation rules.
    """
    inbound_from = str(envelope.get("from") or "").strip().lower()
    inbound_to = str(envelope.get("to") or "").strip().lower()
    content = envelope.get("content")
    if not isinstance(content, str):
        content = "" if content is None else str(content)
    content = content.strip()
    msg_id = envelope.get("msg_id")

    def err(code: str, msg: str, *, close: bool = False) -> tuple[None, dict[str, Any], None, bool]:
        payload = {
            "from": SELF_NAME,
            "error": msg,
            "error_code": code,
            "session_ended": close,
            "timestamp": _utcnow_iso(),
        }
        if msg_id:
            payload["reply_to"] = msg_id
        return None, payload, None, close

    if not inbound_from:
        if default_peer_name is None:
            return err("missing_from", "Missing required field `from`.")
        inbound_from = default_peer_name.lower()
    elif default_peer_name is not None and inbound_from != default_peer_name.lower():
        return err("peer_url_mismatch",
                   f"`from` ({inbound_from!r}) doesn't match URL ({default_peer_name!r}).",
                   close=True)

    if inbound_to and inbound_to != SELF_NAME:
        return err("peer_url_mismatch",
                   f"`to` ({inbound_to!r}) doesn't match this agent ({SELF_NAME!r}).")

    if not content:
        return err("missing_content", "Missing required field `content`.")

    if peer_name_state is not None and peer_name_state != inbound_from:
        return err("peer_identity_changed",
                   f"Peer identity changed mid-session "
                   f"({peer_name_state!r} -> {inbound_from!r}).",
                   close=True)

    return inbound_from, None, content, False


__all__ = [
    "DEFAULT_MAX_AGENT_TURNS",
    "END_SENTINEL_RE",
    "END_TRANSMISSION",
    "SELF_NAME",
    "handle_inbound_envelope",
    "has_end_sentinel",
    "inter_agent_session",
]
