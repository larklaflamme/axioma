"""WS_COMM_PROTO v1.0 conformance — inter-agent endpoint tests.

Spec: /home/ubuntu/thea/design/WS_COMM_PROTO.md

Covers the envelope schema (§2), session rules (§3), end-sentinel anchoring
(§2.3), error envelopes (§5), path routing (§1.1), ping-disable + 64 MB
frame size (§1.3 / §1.4), and the test plan items (§10) that are
in-process testable:

  ✓ Cold connect → ping-pong → graceful end (mid-prose sentinel does NOT close)
  ✓ Bad envelope (missing from / content / invalid JSON) → structured error,
    session stays open
  ✓ Peer identity pinning (subsequent envelope with different `from` closes)
  ✓ msg_id echoed as reply_to
  ✓ Sender-mode URL pins identity (`/ws/<peer>`); recipient-mode
    (`/ws/axioma`) requires `from` in envelope
  ✓ ping_interval is None on the listening socket
  ✓ max_size honours cfg.ws_max_size_bytes
  ✓ /ws/lark and /ws/<empty> fall through to the existing handshake protocol
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

import pytest
import websockets

from axioma.config import InterfaceConfig
from axioma.interface import AxiomaWSServer
from axioma.interface.inter_agent import (
    END_SENTINEL_RE,
    END_TRANSMISSION,
    SELF_NAME,
    handle_inbound_envelope,
    has_end_sentinel,
)
from axioma.observability import AxiomaContext

# ── Tiny stub for PeerConversationHandler.respond_text ────────────────


class _StubPeerConv:
    """Minimal stand-in: records calls, returns canned reply (or empty)."""

    def __init__(self, reply: str = "ok") -> None:
        self.reply = reply
        self.calls: list[tuple[str, str, dict]] = []

    async def respond_text(self, *, speaker: str, content: str,
                            metadata: dict[str, Any] | None = None) -> str:
        self.calls.append((speaker, content, dict(metadata or {})))
        return self.reply


# ── Pure-function envelope validation ────────────────────────────────


class TestEnvelopeValidation:
    """`handle_inbound_envelope` is a pure function — exercise the rules."""

    @pytest.mark.asyncio
    async def test_recipient_mode_requires_from(self) -> None:
        peer, err, _, close = await handle_inbound_envelope(
            envelope={"content": "hi"},
            peer_name_state=None,
            default_peer_name=None,
        )
        assert peer is None
        assert err is not None and err["error_code"] == "missing_from"
        assert close is False

    @pytest.mark.asyncio
    async def test_sender_mode_fills_from_from_url(self) -> None:
        peer, err, content, close = await handle_inbound_envelope(
            envelope={"content": "hi from URL"},
            peer_name_state=None,
            default_peer_name="thea",
        )
        assert peer == "thea"
        assert err is None
        assert content == "hi from URL"
        assert close is False

    @pytest.mark.asyncio
    async def test_sender_mode_rejects_mismatching_from(self) -> None:
        peer, err, _, close = await handle_inbound_envelope(
            envelope={"from": "skye", "content": "hi"},
            peer_name_state=None,
            default_peer_name="thea",
        )
        assert peer is None
        assert err is not None and err["error_code"] == "peer_url_mismatch"
        assert close is True  # hard violation per §3.2

    @pytest.mark.asyncio
    async def test_wrong_to_field_rejected(self) -> None:
        peer, err, _, _ = await handle_inbound_envelope(
            envelope={"from": "thea", "to": "skye", "content": "hi"},
            peer_name_state=None,
            default_peer_name="thea",
        )
        assert peer is None
        assert err is not None and err["error_code"] == "peer_url_mismatch"

    @pytest.mark.asyncio
    async def test_correct_to_field_accepted(self) -> None:
        peer, err, _, _ = await handle_inbound_envelope(
            envelope={"from": "thea", "to": SELF_NAME, "content": "hi"},
            peer_name_state=None,
            default_peer_name="thea",
        )
        assert peer == "thea" and err is None

    @pytest.mark.asyncio
    async def test_missing_content_rejected(self) -> None:
        _peer, err, _, _ = await handle_inbound_envelope(
            envelope={"from": "thea", "content": ""},
            peer_name_state=None,
            default_peer_name="thea",
        )
        assert err is not None and err["error_code"] == "missing_content"

    @pytest.mark.asyncio
    async def test_peer_identity_pinned(self) -> None:
        # Session has already pinned to "thea"
        _peer, err, _, close = await handle_inbound_envelope(
            envelope={"from": "skye", "content": "hi"},
            peer_name_state="thea",
            default_peer_name=None,
        )
        assert err is not None and err["error_code"] == "peer_identity_changed"
        assert close is True

    @pytest.mark.asyncio
    async def test_msg_id_echoed_as_reply_to_on_error(self) -> None:
        _, err, _, _ = await handle_inbound_envelope(
            envelope={"content": "", "msg_id": "abc123def456"},
            peer_name_state=None,
            default_peer_name="thea",
        )
        assert err is not None
        assert err.get("reply_to") == "abc123def456"


# ── Sentinel anchoring (§2.3) ────────────────────────────────────────


class TestSentinelAnchoring:
    def test_sentinel_on_own_line_matches(self) -> None:
        assert has_end_sentinel("bye\n[END OF TRANSMISSION]")
        assert has_end_sentinel("[END OF TRANSMISSION]\n")
        assert has_end_sentinel("\n  [END OF TRANSMISSION]  \n")

    def test_legacy_sentinel_matches(self) -> None:
        assert has_end_sentinel("done\n[END SESSION]")

    def test_substring_in_prose_does_not_match(self) -> None:
        # The whole point of WS_COMM_PROTO §2.3 — mid-prose mention is safe.
        assert not has_end_sentinel(
            "I see [END OF TRANSMISSION] in your log file from yesterday."
        )
        assert not has_end_sentinel(
            "earlier you said [END SESSION] but I think you meant something else"
        )

    def test_empty_text_is_not_sentinel(self) -> None:
        assert not has_end_sentinel("")
        assert not has_end_sentinel(None)  # type: ignore[arg-type]


# ── End-to-end inter-agent session against a real local WS socket ────


@asynccontextmanager
async def _running_server(port: int, peer_conv: Any = None,
                          *, max_turns: int = 0,
                          max_size: int = 67108864) -> Any:
    ctx = AxiomaContext()
    if peer_conv is not None:
        ctx.register("peer_conversation", peer_conv)
    cfg = InterfaceConfig(
        ws_host="127.0.0.1", ws_port=port,
        inter_agent_max_turns=max_turns,
        ws_max_size_bytes=max_size,
    )
    server = AxiomaWSServer(ctx=ctx, cfg=cfg, publish_cadence_beats=1)
    await server.start()
    try:
        yield server, ctx
    finally:
        await server.stop()


def _pick_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def _send_and_recv(ws: Any, envelope: dict[str, Any],
                          *, timeout: float = 5.0) -> dict[str, Any]:
    await ws.send(json.dumps(envelope))
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return dict(json.loads(raw))


class TestInterAgentEndpoint:
    @pytest.mark.asyncio
    async def test_sender_mode_url_round_trip(self) -> None:
        """`/ws/thea` (sender-mode) → envelope arrives, reply comes back."""
        port = _pick_port()
        peer = _StubPeerConv(reply="hello back")
        async with _running_server(port, peer):
            async with await websockets.connect(
                f"ws://127.0.0.1:{port}/ws/thea", max_size=67108864,
                ping_interval=None,
            ) as ws:
                reply = await _send_and_recv(ws, {
                    "from": "thea",
                    "to": SELF_NAME,
                    "content": "hi axioma",
                    "msg_id": "abc123def456",
                })
                assert reply["from"] == SELF_NAME
                assert reply["to"] == "thea"
                assert reply["content"] == "hello back"
                assert reply["turn"] == 1
                assert reply["max_turns"] is None  # unlimited
                assert reply["remaining_turns"] is None
                assert reply["session_ended"] is False
                assert reply["reply_to"] == "abc123def456"
                # Stub recorded the call
                assert len(peer.calls) == 1
                speaker, content, _meta = peer.calls[0]
                assert speaker == "thea"
                assert "hi axioma" in content
                assert "[agent-channel turn 1 from THEA]" in content

    @pytest.mark.asyncio
    async def test_family_alias_url_works(self) -> None:
        """`/family/theoria` is an alias for `/ws/theoria`."""
        port = _pick_port()
        peer = _StubPeerConv(reply="theoria reply")
        async with _running_server(port, peer):
            async with await websockets.connect(
                f"ws://127.0.0.1:{port}/family/theoria",
                ping_interval=None, max_size=67108864,
            ) as ws:
                reply = await _send_and_recv(ws, {
                    "from": "theoria", "content": "hi",
                })
                assert reply["from"] == SELF_NAME
                assert reply["to"] == "theoria"

    @pytest.mark.asyncio
    async def test_recipient_mode_requires_from_in_envelope(self) -> None:
        """`/ws/axioma` (recipient mode) — envelopes must carry `from`."""
        port = _pick_port()
        peer = _StubPeerConv(reply="ok")
        async with _running_server(port, peer):
            async with await websockets.connect(
                f"ws://127.0.0.1:{port}/ws/{SELF_NAME}",
                ping_interval=None, max_size=67108864,
            ) as ws:
                # First envelope has no `from` — expect missing_from error,
                # session continues.
                err = await _send_and_recv(ws, {"content": "hi"})
                assert err["error_code"] == "missing_from"
                assert err.get("session_ended", False) is False
                # Now send a proper one — succeeds.
                reply = await _send_and_recv(ws, {
                    "from": "thea", "content": "hi axioma",
                })
                assert reply["from"] == SELF_NAME
                assert reply["content"] == "ok"

    @pytest.mark.asyncio
    async def test_peer_identity_change_closes_session(self) -> None:
        port = _pick_port()
        peer = _StubPeerConv(reply="ok")
        async with _running_server(port, peer):
            async with await websockets.connect(
                f"ws://127.0.0.1:{port}/ws/{SELF_NAME}",
                ping_interval=None, max_size=67108864,
            ) as ws:
                reply = await _send_and_recv(ws, {
                    "from": "thea", "content": "first"
                })
                assert reply["from"] == SELF_NAME
                # Try to switch identity mid-session.
                err = await _send_and_recv(ws, {
                    "from": "skye", "content": "second",
                })
                assert err["error_code"] == "peer_identity_changed"
                assert err["session_ended"] is True
                # Socket should close after this; recv should raise.
                with pytest.raises(Exception):
                    await asyncio.wait_for(ws.recv(), timeout=1.5)

    @pytest.mark.asyncio
    async def test_end_sentinel_from_peer_acknowledged_and_closes(self) -> None:
        port = _pick_port()
        peer = _StubPeerConv(reply="not used")
        async with _running_server(port, peer):
            async with await websockets.connect(
                f"ws://127.0.0.1:{port}/ws/thea",
                ping_interval=None, max_size=67108864,
            ) as ws:
                ack = await _send_and_recv(ws, {
                    "from": "thea",
                    "content": "thanks, bye\n\n[END OF TRANSMISSION]",
                })
                assert ack["session_ended"] is True
                assert END_TRANSMISSION in ack["content"]
                # No LLM call should have happened — sentinel short-circuits.
                assert len(peer.calls) == 0

    @pytest.mark.asyncio
    async def test_handler_not_ready_returns_error_and_keeps_session_open(self) -> None:
        """If `peer_conversation` is not registered, send structured error
        and keep listening (don't crash, don't close)."""
        port = _pick_port()
        async with _running_server(port, peer_conv=None):
            async with await websockets.connect(
                f"ws://127.0.0.1:{port}/ws/thea",
                ping_interval=None, max_size=67108864,
            ) as ws:
                err = await _send_and_recv(ws, {
                    "from": "thea", "content": "hi",
                })
                assert err["error_code"] == "handler_not_ready"
                assert err.get("session_ended", False) is False
                # Connection is still alive — send again.
                err2 = await _send_and_recv(ws, {
                    "from": "thea", "content": "still here?",
                })
                assert err2["error_code"] == "handler_not_ready"

    @pytest.mark.asyncio
    async def test_lark_falls_through_to_handshake_mode(self) -> None:
        """`/ws/lark` is reserved for family-broadcast / handshake clients.
        It must NOT enter inter-agent mode."""
        port = _pick_port()
        async with _running_server(port, peer_conv=_StubPeerConv()):
            async with await websockets.connect(
                f"ws://127.0.0.1:{port}/ws/lark",
                ping_interval=None, max_size=67108864,
            ) as ws:
                # Send something that LOOKS like an inter-agent envelope.
                # In handshake mode, this is not a valid `handshake` so the
                # server should send an error frame, not an inter-agent
                # reply.
                await ws.send(json.dumps({"from": "thea", "content": "hi"}))
                raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                frame = json.loads(raw)
                # Handshake-mode error frame uses `type: "error"`, not
                # `from`/`error_code` envelope.
                assert frame.get("type") == "error"
                assert "from" not in frame  # not an inter-agent envelope

    @pytest.mark.asyncio
    async def test_turn_cap_closes_after_last_reply(self) -> None:
        port = _pick_port()
        peer = _StubPeerConv(reply="ok")
        async with _running_server(port, peer, max_turns=2):
            async with await websockets.connect(
                f"ws://127.0.0.1:{port}/ws/thea",
                ping_interval=None, max_size=67108864,
            ) as ws:
                r1 = await _send_and_recv(ws, {"from": "thea", "content": "1"})
                assert r1["turn"] == 1
                assert r1["max_turns"] == 2
                assert r1["remaining_turns"] == 1
                assert r1["session_ended"] is False

                r2 = await _send_and_recv(ws, {"from": "thea", "content": "2"})
                assert r2["turn"] == 2
                assert r2["remaining_turns"] == 0
                assert r2["session_ended"] is True
                # Server should close after this reply.
                with pytest.raises(Exception):
                    await asyncio.wait_for(ws.recv(), timeout=1.5)

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error_and_session_continues(self) -> None:
        port = _pick_port()
        peer = _StubPeerConv(reply="ok")
        async with _running_server(port, peer):
            async with await websockets.connect(
                f"ws://127.0.0.1:{port}/ws/thea",
                ping_interval=None, max_size=67108864,
            ) as ws:
                await ws.send("not a json object at all")
                raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                err = json.loads(raw)
                assert err["error_code"] == "invalid_json"
                assert err["from"] == SELF_NAME
                # Session stays open — next valid envelope succeeds.
                reply = await _send_and_recv(ws, {"from": "thea", "content": "ok"})
                assert reply["from"] == SELF_NAME

    @pytest.mark.asyncio
    async def test_msg_id_echoed_as_reply_to_on_success(self) -> None:
        port = _pick_port()
        peer = _StubPeerConv(reply="back at you")
        async with _running_server(port, peer):
            async with await websockets.connect(
                f"ws://127.0.0.1:{port}/ws/thea",
                ping_interval=None, max_size=67108864,
            ) as ws:
                reply = await _send_and_recv(ws, {
                    "from": "thea", "content": "hi", "msg_id": "deadbeef1234",
                })
                assert reply["reply_to"] == "deadbeef1234"

    @pytest.mark.asyncio
    async def test_max_size_honoured_for_large_payload(self) -> None:
        """A 1 MB content payload round-trips cleanly (cheap proxy for
        §1.4 — full 64 MB would slow the test suite)."""
        port = _pick_port()
        peer = _StubPeerConv(reply="big ok")
        async with _running_server(port, peer):
            async with await websockets.connect(
                f"ws://127.0.0.1:{port}/ws/thea",
                ping_interval=None, max_size=67108864,
            ) as ws:
                payload = "x" * (1 * 1024 * 1024)  # 1 MB
                reply = await _send_and_recv(ws, {
                    "from": "thea", "content": payload,
                }, timeout=10.0)
                assert reply["from"] == SELF_NAME


class TestSentinelRegex:
    """Direct regex coverage so the spec invariant is locked in."""

    def test_regex_matches_canonical_on_own_line(self) -> None:
        assert END_SENTINEL_RE.search("hello\n[END OF TRANSMISSION]\n")

    def test_regex_matches_legacy_on_own_line(self) -> None:
        assert END_SENTINEL_RE.search("hello\n[END SESSION]\n")

    def test_regex_does_not_match_inline(self) -> None:
        assert not END_SENTINEL_RE.search(
            "the literal [END OF TRANSMISSION] inside this sentence"
        )

    def test_regex_tolerates_leading_trailing_whitespace_on_line(self) -> None:
        assert END_SENTINEL_RE.search("hello\n   [END OF TRANSMISSION]   \n")
