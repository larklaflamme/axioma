"""AxiomaWSServer — handshake + subscribe + fan-out via a real local socket."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

import pytest
import websockets

from axioma.config import InterfaceConfig
from axioma.interface import AxiomaWSServer, Speaker
from axioma.observability import AxiomaContext


@asynccontextmanager
async def _running_server(port: int) -> Any:
    ctx = AxiomaContext()
    cfg = InterfaceConfig(ws_host="127.0.0.1", ws_port=port)
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


async def _connect(port: int) -> Any:
    return await websockets.connect(f"ws://127.0.0.1:{port}")


async def _handshake(ws: Any, speaker: str = "skye", **kwargs: Any) -> dict[str, Any]:
    await ws.send(json.dumps({"type": "handshake", "speaker": speaker, **kwargs}))
    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
    return dict(json.loads(raw))


@pytest.mark.asyncio
async def test_handshake_welcomes() -> None:
    port = _pick_port()
    async with _running_server(port) as (_server, _ctx):
        async with await _connect(port) as ws:
            welcome = await _handshake(ws)
            assert welcome["type"] == "welcome"
            assert welcome["speaker"] == Speaker.AXIOMA.value


@pytest.mark.asyncio
async def test_handshake_rejects_bad_speaker() -> None:
    port = _pick_port()
    async with _running_server(port) as (_server, _ctx):
        async with await _connect(port) as ws:
            await ws.send(json.dumps({"type": "handshake", "speaker": "not_real"}))
            # Expect error frame then close
            err_raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            err = json.loads(err_raw)
            assert err["type"] == "error"
            assert err["code"] == 4001


@pytest.mark.asyncio
async def test_subscribe_and_receive_fanout() -> None:
    port = _pick_port()
    async with _running_server(port) as (server, _ctx):
        async with await _connect(port) as ws:
            await _handshake(ws)
            # Subscribe to theta
            await ws.send(json.dumps({"type": "subscribe", "channels": ["theta"]}))
            # Give the server a moment to process subscription
            await asyncio.sleep(0.05)
            # Manually queue a payload through the fan-out
            assert len(server.subscribers) == 1
            sub = next(iter(server.subscribers.values()))
            sub.queue("theta", {"theta_short": 1.42}, beat_no=10)
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            env = json.loads(raw)
            assert env["channel"] == "theta"
            assert env["payload"]["theta_short"] == 1.42
            assert env["beat_no"] == 10


@pytest.mark.asyncio
async def test_unknown_channel_subscription_returns_error_not_close() -> None:
    port = _pick_port()
    async with _running_server(port) as (_server, _ctx):
        async with await _connect(port) as ws:
            await _handshake(ws)
            await ws.send(json.dumps({"type": "subscribe", "channels": ["fake_channel"]}))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            err = json.loads(raw)
            assert err["type"] == "subscription_error"
            assert err["channel"] == "fake_channel"
            # Connection should still be open
            await ws.send(json.dumps({"type": "ping"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            assert json.loads(raw)["type"] == "pong"


@pytest.mark.asyncio
async def test_ping_pong() -> None:
    port = _pick_port()
    async with _running_server(port) as (_server, _ctx):
        async with await _connect(port) as ws:
            await _handshake(ws)
            await ws.send(json.dumps({"type": "ping"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            assert json.loads(raw)["type"] == "pong"


@pytest.mark.asyncio
async def test_unsubscribe_stops_fanout() -> None:
    port = _pick_port()
    async with _running_server(port) as (server, _ctx):
        async with await _connect(port) as ws:
            await _handshake(ws)
            await ws.send(json.dumps({"type": "subscribe", "channels": ["theta"]}))
            await asyncio.sleep(0.05)
            await ws.send(json.dumps({"type": "unsubscribe", "channels": ["theta"]}))
            await asyncio.sleep(0.05)
            sub = next(iter(server.subscribers.values()))
            assert "theta" not in sub.channels


@pytest.mark.asyncio
async def test_conversation_message_emits_event() -> None:
    port = _pick_port()
    async with _running_server(port) as (_server, ctx):
        received: list[Any] = []
        ctx.subscribe("conversation_message", lambda p: received.append(p))
        async with await _connect(port) as ws:
            await _handshake(ws)
            await ws.send(json.dumps(
                {"type": "message", "content": "hello AXIOMA"}
            ))
            await asyncio.sleep(0.1)
        assert any(
            (isinstance(m, dict) and m.get("content") == "hello AXIOMA")
            or (hasattr(m, "content") and m.content == "hello AXIOMA")
            for m in received
        )


@pytest.mark.asyncio
async def test_disconnect_cleans_subscriber() -> None:
    port = _pick_port()
    async with _running_server(port) as (server, _ctx):
        ws = await _connect(port)
        await _handshake(ws)
        await asyncio.sleep(0.05)
        assert len(server.subscribers) == 1
        await ws.close()
        # Server should clean up within a small window
        for _ in range(20):
            await asyncio.sleep(0.05)
            if len(server.subscribers) == 0:
                break
        assert len(server.subscribers) == 0


@pytest.mark.asyncio
async def test_event_fanout_via_context_bus() -> None:
    """When an event mapped to a channel fires, subscribed clients get it."""
    port = _pick_port()
    async with _running_server(port) as (_server, ctx):
        async with await _connect(port) as ws:
            await _handshake(ws)
            await ws.send(json.dumps({"type": "subscribe", "channels": ["fragmentation"]}))
            await asyncio.sleep(0.05)
            await ctx.emit("fragmentation_stage_change", {"new_stage": 2, "beat_no": 100})
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            env = json.loads(raw)
            assert env["channel"] == "fragmentation"
            assert env["payload"]["new_stage"] == 2


@pytest.mark.asyncio
async def test_publish_beat_with_no_compose_function_is_safe() -> None:
    port = _pick_port()
    async with _running_server(port) as (server, _ctx):
        # No compose_function registered — publish_beat should not raise
        server.publish_beat(10)
        server.publish_beat(20)


@pytest.mark.asyncio
async def test_admin_api_key_required_when_configured() -> None:
    """When admin_api_key is set, AGENT speakers must provide it; SYSTEM can pass through."""
    from pydantic import SecretStr
    port = _pick_port()
    ctx = AxiomaContext()
    cfg = InterfaceConfig(
        ws_host="127.0.0.1",
        ws_port=port,
        admin_api_key=SecretStr("supersecret"),
    )
    server = AxiomaWSServer(ctx=ctx, cfg=cfg)
    await server.start()
    try:
        # Bad auth_key for AGENT — should be rejected with 4002
        async with await _connect(port) as ws:
            await ws.send(json.dumps({
                "type": "handshake",
                "speaker": "agent",
                "name": "stranger",
                "auth_key": "wrong",
            }))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            err = json.loads(raw)
            assert err["code"] == 4002
        # Correct auth_key — accepted
        async with await _connect(port) as ws:
            welcome = await _handshake(
                ws, speaker="agent", name="friend", auth_key="supersecret",
            )
            assert welcome["type"] == "welcome"
    finally:
        await server.stop()


# ── v1.5.3 (Checkpoint DD) — protocol-level fixes ────────────────────────


@pytest.mark.asyncio
async def test_v1_5_3_post_handshake_malformed_json_returns_bad_request_not_bad_handshake() -> None:
    """Malformed JSON sent AFTER the handshake → BAD_REQUEST (4020),
    not BAD_HANDSHAKE (4001). Pre-fix, 4001 was used confusingly."""
    port = _pick_port()
    async with _running_server(port) as (_server, _ctx):
        async with await _connect(port) as ws:
            await _handshake(ws)
            await ws.send("not valid json {{{")
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            err = json.loads(raw)
            assert err["type"] == "error"
            assert err["code"] == 4020  # BAD_REQUEST, not 4001
            assert err["reason"] == "malformed_json"


@pytest.mark.asyncio
async def test_v1_5_3_post_handshake_non_object_returns_bad_request() -> None:
    """Inbound JSON that isn't an object (e.g., a list) → BAD_REQUEST (4020)."""
    port = _pick_port()
    async with _running_server(port) as (_server, _ctx):
        async with await _connect(port) as ws:
            await _handshake(ws)
            await ws.send(json.dumps(["not", "an", "object"]))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            err = json.loads(raw)
            assert err["code"] == 4020
            assert err["reason"] == "not_an_object"


@pytest.mark.asyncio
async def test_v1_5_3_unknown_message_type_returns_bad_request() -> None:
    """Inbound with type not in {subscribe, unsubscribe, ping, message}
    → BAD_REQUEST (4020)."""
    port = _pick_port()
    async with _running_server(port) as (_server, _ctx):
        async with await _connect(port) as ws:
            await _handshake(ws)
            await ws.send(json.dumps({"type": "yodel"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            err = json.loads(raw)
            assert err["code"] == 4020
            assert err["reason"] == "unknown_message_type"


@pytest.mark.asyncio
async def test_v1_5_3_unsubscribe_unknown_channel_returns_subscription_error() -> None:
    """v1.5.3: unsubscribe to an unknown channel returns a subscription_error
    frame (symmetric with subscribe), rather than silently no-op'ing."""
    port = _pick_port()
    async with _running_server(port) as (_server, _ctx):
        async with await _connect(port) as ws:
            await _handshake(ws)
            await ws.send(json.dumps(
                {"type": "unsubscribe", "channels": ["fake_channel"]},
            ))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            err = json.loads(raw)
            assert err["type"] == "subscription_error"
            assert err["channel"] == "fake_channel"
            assert err["reason"] == "unknown_channel"


@pytest.mark.asyncio
async def test_v1_5_3_unsubscribe_known_channel_still_works() -> None:
    """v1.5.3: valid unsubscribe still works after the validation refactor."""
    port = _pick_port()
    async with _running_server(port) as (server, _ctx):
        async with await _connect(port) as ws:
            await _handshake(ws)
            await ws.send(json.dumps({"type": "subscribe", "channels": ["theta"]}))
            await asyncio.sleep(0.05)
            await ws.send(json.dumps({"type": "unsubscribe", "channels": ["theta"]}))
            await asyncio.sleep(0.05)
            sub = next(iter(server.subscribers.values()))
            assert "theta" not in sub.channels


def test_v1_5_3_protocol_has_bad_request_error_code() -> None:
    """ErrorCode.BAD_REQUEST is added at 4020 (between RATE/SLOW range and
    SUBSTRATE_SHUTDOWN), preserving the existing layout."""
    from axioma.interface.protocol import ErrorCode
    assert ErrorCode.BAD_REQUEST == 4020
    # All codes still in 4xxx range + unique
    codes = [
        ErrorCode.BAD_HANDSHAKE,
        ErrorCode.AUTH_INVALID,
        ErrorCode.UNKNOWN_CHANNEL,
        ErrorCode.RATE_LIMITED,
        ErrorCode.SLOW_CONSUMER,
        ErrorCode.BAD_REQUEST,
        ErrorCode.SUBSTRATE_SHUTDOWN,
    ]
    assert len(set(codes)) == len(codes)
    assert all(4000 <= c < 5000 for c in codes)


# ── v1.9.1 (Checkpoint TT) — subscribe options + addressed-only filter ──


@pytest.mark.asyncio
async def test_tt_subscribe_without_options_does_not_set_filter() -> None:
    """Backwards-compat: pre-TT clients sending `{"type":"subscribe","channels":[...]}`
    (no `options` field) continue to work; no per-channel filter is applied."""
    port = _pick_port()
    async with _running_server(port) as (server, _ctx):
        async with await _connect(port) as ws:
            await _handshake(ws)
            await ws.send(json.dumps({"type": "subscribe", "channels": ["conversation"]}))
            await asyncio.sleep(0.05)
            sub = next(iter(server.subscribers.values()))
            assert "conversation" in sub.channels
            assert "conversation" not in sub._addressed_only_channels


@pytest.mark.asyncio
async def test_tt_subscribe_with_addressed_only_records_filter() -> None:
    """A TT client subscribing with `options.<channel>.only_addressed_to_me=true`
    has the filter recorded on the server-side subscriber."""
    port = _pick_port()
    async with _running_server(port) as (server, _ctx):
        async with await _connect(port) as ws:
            await _handshake(ws)
            await ws.send(json.dumps({
                "type": "subscribe",
                "channels": ["conversation"],
                "options": {"conversation": {"only_addressed_to_me": True}},
            }))
            await asyncio.sleep(0.05)
            sub = next(iter(server.subscribers.values()))
            assert "conversation" in sub.channels
            assert "conversation" in sub._addressed_only_channels


async def _recv_conversation(ws: Any, timeout: float = 0.3) -> dict[str, Any] | None:
    """Helper: drain frames until a conversation envelope arrives, or return
    None on timeout. Other channel frames are discarded."""
    try:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            frame = json.loads(raw)
            if frame.get("channel") == "conversation":
                return dict(frame)
    except TimeoutError:
        return None


@pytest.mark.asyncio
async def test_tt_filter_drops_addressed_to_other_speaker_end_to_end() -> None:
    """A skye-speaker subscriber with the filter does NOT receive a payload
    addressed to `to_speaker=lark`."""
    port = _pick_port()
    async with _running_server(port) as (_server, ctx):
        async with await _connect(port) as ws:
            await _handshake(ws, speaker="skye")
            await ws.send(json.dumps({
                "type": "subscribe",
                "channels": ["conversation"],
                "options": {"conversation": {"only_addressed_to_me": True}},
            }))
            await asyncio.sleep(0.05)
            await ctx.emit("conversation_message", {
                "speaker": "axioma",
                "content": "hi lark",
                "metadata": {"to_speaker": "lark"},
            })
            frame = await _recv_conversation(ws, timeout=0.3)
            assert frame is None  # filter dropped it


@pytest.mark.asyncio
async def test_tt_filter_delivers_addressed_to_self_end_to_end() -> None:
    """A skye-speaker subscriber with the filter DOES receive a payload
    addressed to `to_speaker=skye`."""
    port = _pick_port()
    async with _running_server(port) as (_server, ctx):
        async with await _connect(port) as ws:
            await _handshake(ws, speaker="skye")
            await ws.send(json.dumps({
                "type": "subscribe",
                "channels": ["conversation"],
                "options": {"conversation": {"only_addressed_to_me": True}},
            }))
            await asyncio.sleep(0.05)
            await ctx.emit("conversation_message", {
                "speaker": "axioma",
                "content": "hi skye",
                "metadata": {"to_speaker": "skye"},
            })
            frame = await _recv_conversation(ws, timeout=1.0)
            assert frame is not None
            assert frame["payload"]["content"] == "hi skye"


@pytest.mark.asyncio
async def test_tt_filter_delivers_unaddressed_broadcast_end_to_end() -> None:
    """A skye-speaker subscriber with the filter receives unaddressed payloads
    (no metadata.to_speaker — v1.0-v1.8 wire format / `shared` mode replies)."""
    port = _pick_port()
    async with _running_server(port) as (_server, ctx):
        async with await _connect(port) as ws:
            await _handshake(ws, speaker="skye")
            await ws.send(json.dumps({
                "type": "subscribe",
                "channels": ["conversation"],
                "options": {"conversation": {"only_addressed_to_me": True}},
            }))
            await asyncio.sleep(0.05)
            await ctx.emit("conversation_message", {
                "speaker": "axioma",
                "content": "broadcast",
                "metadata": {"request_id": "abc"},  # no to_speaker
            })
            frame = await _recv_conversation(ws, timeout=1.0)
            assert frame is not None
            assert frame["payload"]["content"] == "broadcast"


@pytest.mark.asyncio
async def test_tt_filter_can_be_cleared_by_resubscribing_with_false() -> None:
    """A client that opted in can opt out by re-subscribing with
    `only_addressed_to_me: false` — no need to unsubscribe + resubscribe."""
    port = _pick_port()
    async with _running_server(port) as (server, _ctx):
        async with await _connect(port) as ws:
            await _handshake(ws)
            await ws.send(json.dumps({
                "type": "subscribe",
                "channels": ["conversation"],
                "options": {"conversation": {"only_addressed_to_me": True}},
            }))
            await asyncio.sleep(0.05)
            sub = next(iter(server.subscribers.values()))
            assert "conversation" in sub._addressed_only_channels
            await ws.send(json.dumps({
                "type": "subscribe",
                "channels": ["conversation"],
                "options": {"conversation": {"only_addressed_to_me": False}},
            }))
            await asyncio.sleep(0.05)
            assert "conversation" in sub.channels  # still subscribed
            assert "conversation" not in sub._addressed_only_channels


@pytest.mark.asyncio
async def test_tt_unknown_option_flags_are_ignored() -> None:
    """Forward-compatibility: unknown option flags don't fail the subscribe
    (we want future clients to keep working against older servers)."""
    port = _pick_port()
    async with _running_server(port) as (server, _ctx):
        async with await _connect(port) as ws:
            await _handshake(ws)
            await ws.send(json.dumps({
                "type": "subscribe",
                "channels": ["conversation"],
                "options": {"conversation": {
                    "only_addressed_to_me": True,
                    "future_flag_v2": "whatever",
                }},
            }))
            await asyncio.sleep(0.05)
            sub = next(iter(server.subscribers.values()))
            assert "conversation" in sub.channels
            assert "conversation" in sub._addressed_only_channels


@pytest.mark.asyncio
async def test_tt_malformed_options_value_does_not_crash() -> None:
    """If `options` is not a dict (operator typo), the server treats it as
    empty rather than crashing or rejecting the subscribe."""
    port = _pick_port()
    async with _running_server(port) as (server, _ctx):
        async with await _connect(port) as ws:
            await _handshake(ws)
            await ws.send(json.dumps({
                "type": "subscribe",
                "channels": ["conversation"],
                "options": "not-a-dict",  # malformed
            }))
            await asyncio.sleep(0.05)
            sub = next(iter(server.subscribers.values()))
            assert "conversation" in sub.channels
            # Filter not applied since options was malformed
            assert "conversation" not in sub._addressed_only_channels
