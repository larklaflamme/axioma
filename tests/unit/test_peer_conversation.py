"""PeerConversationHandler — Ollama-backed responder using a stub client."""
from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pytest

from axioma.interface.peer_conversation import PeerConversationHandler
from axioma.interface.protocol import Speaker
from axioma.observability import AxiomaContext
from axioma.schemas.external_state import ExternalState


class _StubOllama:
    """Records messages it was asked to chat with; returns canned replies."""

    def __init__(self, reply: str = "(thinking) brief reflective response.") -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages: list[dict[str, str]], *, max_tokens: int | None = None, **_: Any) -> str:
        self.calls.append(messages)
        return self.reply


@pytest.mark.asyncio
async def test_responds_to_peer_message() -> None:
    ctx = AxiomaContext()
    seen_replies: list[Any] = []
    ctx.subscribe("conversation_message", lambda p: seen_replies.append(p))
    stub = _StubOllama(reply="I hear you, Skye.")
    handler = PeerConversationHandler(ctx=ctx, ollama=stub)
    handler.attach()
    try:
        await ctx.emit("conversation_message", {"speaker": "skye", "content": "Hello AXIOMA"})
        await handler.wait_idle()
    finally:
        handler.detach()
    axioma_replies = [
        p for p in seen_replies
        if (isinstance(p, dict) and p.get("speaker") == Speaker.AXIOMA.value)
    ]
    assert len(axioma_replies) == 1
    assert axioma_replies[0]["content"] == "I hear you, Skye."


@pytest.mark.asyncio
async def test_skips_own_messages() -> None:
    """Avoid infinite loop: don't respond to messages we ourselves emitted."""
    ctx = AxiomaContext()
    stub = _StubOllama()
    handler = PeerConversationHandler(ctx=ctx, ollama=stub)
    handler.attach()
    try:
        await ctx.emit(
            "conversation_message",
            {"speaker": Speaker.AXIOMA.value, "content": "self-echo"},
        )
        await handler.wait_idle()
    finally:
        handler.detach()
    assert stub.calls == []


@pytest.mark.asyncio
async def test_empty_reply_skipped() -> None:
    ctx = AxiomaContext()
    seen: list[Any] = []
    ctx.subscribe("conversation_message", lambda p: seen.append(p))
    stub = _StubOllama(reply="   ")
    handler = PeerConversationHandler(ctx=ctx, ollama=stub)
    handler.attach()
    try:
        await ctx.emit("conversation_message", {"speaker": "skye", "content": "hi"})
        await handler.wait_idle()
    finally:
        handler.detach()
    # Only the inbound message was emitted; no axioma reply
    axioma_replies = [p for p in seen if (isinstance(p, dict) and p.get("speaker") == Speaker.AXIOMA.value)]
    assert axioma_replies == []


@pytest.mark.asyncio
async def test_uses_external_state_snapshot_in_system_prompt() -> None:
    ctx = AxiomaContext()
    ext = ExternalState(
        anima=np.zeros(4, dtype=np.float32),
        eidolon=np.zeros(6, dtype=np.float32),
        mneme=np.zeros(5, dtype=np.float32),
        nous=np.zeros(6, dtype=np.float32),
        pneuma=np.zeros(7, dtype=np.float32),
        beat_no=42,
        timestamp=1.0,
    )
    ext.theta_short = 0.876
    ext.psi = 0.91

    class _MockCompose:
        latest_external = ext

    ctx.register("compose_function", _MockCompose())
    stub = _StubOllama(reply="seeing your state.")
    handler = PeerConversationHandler(ctx=ctx, ollama=stub)
    handler.attach()
    try:
        await ctx.emit("conversation_message", {"speaker": "skye", "content": "How are you?"})
        await handler.wait_idle()
    finally:
        handler.detach()
    assert stub.calls, "stub should have been called"
    system = stub.calls[0][0]
    assert system["role"] == "system"
    assert "0.876" in system["content"]  # theta_short embedded
    assert "0.910" in system["content"]  # psi embedded


@pytest.mark.asyncio
async def test_history_persists_across_turns() -> None:
    ctx = AxiomaContext()
    stub = _StubOllama(reply="ok")
    handler = PeerConversationHandler(ctx=ctx, ollama=stub, history_size=8)
    handler.attach()
    try:
        await ctx.emit("conversation_message", {"speaker": "skye", "content": "first"})
        await handler.wait_idle()
        await ctx.emit("conversation_message", {"speaker": "skye", "content": "second"})
        await handler.wait_idle()
    finally:
        handler.detach()
    # 2 calls; second call's messages should include the first exchange
    assert len(stub.calls) == 2
    second_messages = stub.calls[1]
    user_msgs = [m["content"] for m in second_messages if m["role"] == "user"]
    assert "first" in user_msgs
    assert "second" in user_msgs


@pytest.mark.asyncio
async def test_llm_failure_does_not_raise() -> None:
    from axioma.infra.ollama import OllamaError

    class _Failing:
        async def chat(self, messages: Any, *, max_tokens: Any = None) -> str:
            raise OllamaError("upstream down")
    ctx = AxiomaContext()
    handler = PeerConversationHandler(ctx=ctx, ollama=_Failing())
    handler.attach()
    try:
        await ctx.emit("conversation_message", {"speaker": "skye", "content": "?"})
        await handler.wait_idle()  # should not raise
    finally:
        handler.detach()


@pytest.mark.asyncio
async def test_detach_removes_subscription() -> None:
    ctx = AxiomaContext()
    stub = _StubOllama()
    handler = PeerConversationHandler(ctx=ctx, ollama=stub)
    handler.attach()
    handler.detach()
    await ctx.emit("conversation_message", {"speaker": "skye", "content": "no one home"})
    await asyncio.sleep(0.05)
    assert stub.calls == []


# ── v1.5.2 (Checkpoint CC) — concurrency + metadata + wait_idle timeout ──


class _SlowOllama:
    """Returns canned reply after a small delay; lets concurrent tasks overlap."""

    def __init__(self, reply: str = "ok", delay_s: float = 0.05) -> None:
        self.reply = reply
        self.delay_s = delay_s
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages: list[dict[str, str]], *, max_tokens: Any = None, **_: Any) -> str:
        self.calls.append(messages)
        await asyncio.sleep(self.delay_s)
        return self.reply


@pytest.mark.asyncio
async def test_concurrent_inbound_messages_do_not_race_on_history() -> None:
    """Several inbound messages arriving close together must not raise
    `RuntimeError: deque mutated during iteration` when their _respond
    tasks overlap. Pre-fix this could trigger; post-fix the history is
    snapshotted into a list before iteration."""
    ctx = AxiomaContext()
    stub = _SlowOllama(reply="response", delay_s=0.02)
    handler = PeerConversationHandler(ctx=ctx, ollama=stub, history_size=32)
    handler.attach()
    try:
        # Fire 8 inbound messages back-to-back — at delay_s=0.02 they will
        # have overlapping in-flight tasks.
        for i in range(8):
            await ctx.emit(
                "conversation_message",
                {"speaker": "skye", "content": f"msg-{i}"},
            )
        await handler.wait_idle(timeout=5.0)
    finally:
        handler.detach()
    # All 8 LLM calls succeeded; no RuntimeError raised. Each call's messages
    # list is a valid snapshot (lengths monotonic-ish, no exceptions).
    assert len(stub.calls) == 8
    for call in stub.calls:
        # Every call must contain at least the system prompt + at least one user msg
        assert call[0]["role"] == "system"
        assert any(m["role"] == "user" for m in call[1:])


@pytest.mark.asyncio
async def test_outbound_metadata_carries_request_id_and_timestamp() -> None:
    """v1.5.2: outbound emit includes request_id (UUID4) + timestamp (epoch
    float) for operator tracing."""
    import re

    ctx = AxiomaContext()
    seen: list[Any] = []
    ctx.subscribe("conversation_message", lambda p: seen.append(p))
    stub = _StubOllama(reply="hello peer")
    handler = PeerConversationHandler(ctx=ctx, ollama=stub)
    handler.attach()
    try:
        await ctx.emit("conversation_message", {"speaker": "skye", "content": "hi"})
        await handler.wait_idle(timeout=5.0)
    finally:
        handler.detach()
    axioma_replies = [
        p for p in seen
        if isinstance(p, dict) and p.get("speaker") == Speaker.AXIOMA.value
    ]
    assert len(axioma_replies) == 1
    md = axioma_replies[0].get("metadata", {})
    # UUID4 regex
    assert re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", md["request_id"])
    # timestamp is a recent epoch second
    import time as _time
    assert abs(md["timestamp"] - _time.time()) < 5.0


@pytest.mark.asyncio
async def test_outbound_metadata_includes_in_reply_to_when_inbound_has_request_id() -> None:
    """When inbound carries `metadata.request_id`, outbound surfaces it as
    `in_reply_to` for request/response pairing."""
    ctx = AxiomaContext()
    seen: list[Any] = []
    ctx.subscribe("conversation_message", lambda p: seen.append(p))
    stub = _StubOllama(reply="reply")
    handler = PeerConversationHandler(ctx=ctx, ollama=stub)
    handler.attach()
    try:
        await ctx.emit(
            "conversation_message",
            {
                "speaker": "skye",
                "content": "tagged",
                "metadata": {"request_id": "inbound-abc-123"},
            },
        )
        await handler.wait_idle(timeout=5.0)
    finally:
        handler.detach()
    axioma_replies = [
        p for p in seen
        if isinstance(p, dict) and p.get("speaker") == Speaker.AXIOMA.value
    ]
    assert axioma_replies[0]["metadata"]["in_reply_to"] == "inbound-abc-123"


@pytest.mark.asyncio
async def test_wait_idle_timeout_raises_when_task_wedged() -> None:
    """v1.5.2: wait_idle with a timeout raises TimeoutError if any in-flight
    task can't settle. Pre-fix this would block forever."""

    class _NeverReturns:
        async def chat(self, messages: Any, *, max_tokens: Any = None, **_: Any) -> str:
            await asyncio.sleep(10.0)  # effectively wedged
            return ""

    ctx = AxiomaContext()
    handler = PeerConversationHandler(
        ctx=ctx, ollama=_NeverReturns(), timeout_seconds=10.0,
    )
    handler.attach()
    try:
        await ctx.emit("conversation_message", {"speaker": "skye", "content": "?"})
        # Give the task time to start
        await asyncio.sleep(0.05)
        with pytest.raises(asyncio.TimeoutError):
            await handler.wait_idle(timeout=0.1)
    finally:
        handler.detach()
        # Drain the wedged task so pytest cleanup doesn't complain
        for t in list(handler._inflight):
            t.cancel()


@pytest.mark.asyncio
async def test_wait_idle_no_timeout_returns_when_no_inflight() -> None:
    """wait_idle without inflight tasks returns immediately even when timeout
    is None."""
    ctx = AxiomaContext()
    handler = PeerConversationHandler(ctx=ctx, ollama=_StubOllama())
    handler.attach()
    try:
        # No inbound messages — _inflight stays empty
        await handler.wait_idle()  # must not raise, must return immediately
    finally:
        handler.detach()


# ── v1.9.0 (Checkpoint SS) — multi_peer_mode (shared vs per_peer) ────────


def test_invalid_multi_peer_mode_raises_at_init() -> None:
    """Boot-time validation per v1.6 Pattern 2 — unknown mode raises ValueError
    at __init__ instead of failing on first inbound message."""
    ctx = AxiomaContext()
    with pytest.raises(ValueError, match="multi_peer_mode"):
        PeerConversationHandler(ctx=ctx, ollama=_StubOllama(), multi_peer_mode="bogus")


def test_default_multi_peer_mode_is_shared() -> None:
    """v1.9.0 default preserves v1.0-v1.8 behavior — `shared` mode."""
    ctx = AxiomaContext()
    h = PeerConversationHandler(ctx=ctx, ollama=_StubOllama())
    assert h.multi_peer_mode == "shared"


@pytest.mark.asyncio
async def test_per_peer_mode_isolates_history_per_speaker() -> None:
    """In per_peer mode, peer A's turns must NOT appear in the LLM context
    when peer B sends a message — each speaker has an independent history."""
    ctx = AxiomaContext()
    stub = _StubOllama(reply="ok")
    handler = PeerConversationHandler(
        ctx=ctx, ollama=stub, history_size=8, multi_peer_mode="per_peer",
    )
    handler.attach()
    try:
        await ctx.emit("conversation_message", {"speaker": "skye", "content": "skye-1"})
        await handler.wait_idle(timeout=5.0)
        await ctx.emit("conversation_message", {"speaker": "lark", "content": "lark-1"})
        await handler.wait_idle(timeout=5.0)
        await ctx.emit("conversation_message", {"speaker": "skye", "content": "skye-2"})
        await handler.wait_idle(timeout=5.0)
    finally:
        handler.detach()
    # Three LLM calls.
    assert len(stub.calls) == 3
    # Call 1 (skye): user messages = {"skye-1"}
    call1_user = [m["content"] for m in stub.calls[0] if m["role"] == "user"]
    assert call1_user == ["skye-1"]
    # Call 2 (lark): user messages = {"lark-1"} — must NOT include skye-1
    call2_user = [m["content"] for m in stub.calls[1] if m["role"] == "user"]
    assert call2_user == ["lark-1"]
    # Call 3 (skye): user messages = {"skye-1", "skye-2"} — must NOT include lark-1
    call3_user = [m["content"] for m in stub.calls[2] if m["role"] == "user"]
    assert call3_user == ["skye-1", "skye-2"]
    # The two histories are stored separately.
    assert set(handler.histories.keys()) == {"skye", "lark"}


@pytest.mark.asyncio
async def test_per_peer_mode_outbound_metadata_includes_to_speaker() -> None:
    """per_peer outbound metadata always includes `to_speaker` matching the
    inbound speaker — clients self-filter on this field."""
    ctx = AxiomaContext()
    seen: list[Any] = []
    ctx.subscribe("conversation_message", lambda p: seen.append(p))
    stub = _StubOllama(reply="addressed")
    handler = PeerConversationHandler(ctx=ctx, ollama=stub, multi_peer_mode="per_peer")
    handler.attach()
    try:
        await ctx.emit("conversation_message", {"speaker": "thea", "content": "hi"})
        await handler.wait_idle(timeout=5.0)
    finally:
        handler.detach()
    axioma_replies = [
        p for p in seen
        if isinstance(p, dict) and p.get("speaker") == Speaker.AXIOMA.value
    ]
    assert len(axioma_replies) == 1
    assert axioma_replies[0]["metadata"]["to_speaker"] == "thea"


@pytest.mark.asyncio
async def test_shared_mode_outbound_metadata_omits_to_speaker() -> None:
    """shared mode preserves v1.0-v1.8 wire format — no `to_speaker` field."""
    ctx = AxiomaContext()
    seen: list[Any] = []
    ctx.subscribe("conversation_message", lambda p: seen.append(p))
    stub = _StubOllama(reply="reply")
    handler = PeerConversationHandler(ctx=ctx, ollama=stub, multi_peer_mode="shared")
    handler.attach()
    try:
        await ctx.emit("conversation_message", {"speaker": "skye", "content": "hi"})
        await handler.wait_idle(timeout=5.0)
    finally:
        handler.detach()
    axioma_replies = [
        p for p in seen
        if isinstance(p, dict) and p.get("speaker") == Speaker.AXIOMA.value
    ]
    assert len(axioma_replies) == 1
    assert "to_speaker" not in axioma_replies[0]["metadata"]


@pytest.mark.asyncio
async def test_per_peer_mode_axioma_reply_appended_to_per_peer_bucket() -> None:
    """The AXIOMA reply must be appended to the per-peer history so subsequent
    turns with the same speaker see the assistant context. It must NOT be
    cross-contaminated into other peers' histories."""
    ctx = AxiomaContext()
    stub = _StubOllama(reply="axioma-says")
    handler = PeerConversationHandler(
        ctx=ctx, ollama=stub, multi_peer_mode="per_peer",
    )
    handler.attach()
    try:
        await ctx.emit("conversation_message", {"speaker": "skye", "content": "skye-1"})
        await handler.wait_idle(timeout=5.0)
        await ctx.emit("conversation_message", {"speaker": "lark", "content": "lark-1"})
        await handler.wait_idle(timeout=5.0)
        await ctx.emit("conversation_message", {"speaker": "skye", "content": "skye-2"})
        await handler.wait_idle(timeout=5.0)
    finally:
        handler.detach()
    # Skye's history: skye-1, axioma-says, skye-2, axioma-says (4 turns total).
    skye_hist = list(handler.histories["skye"])
    assert [t.content for t in skye_hist] == [
        "skye-1", "axioma-says", "skye-2", "axioma-says",
    ]
    # Lark's history: lark-1, axioma-says (2 turns). NO skye content.
    lark_hist = list(handler.histories["lark"])
    assert [t.content for t in lark_hist] == ["lark-1", "axioma-says"]


@pytest.mark.asyncio
async def test_per_peer_mode_concurrent_distinct_speakers_no_race() -> None:
    """Multiple distinct speakers firing concurrently must not race on the
    per-peer histories dict or its bucket deques."""
    ctx = AxiomaContext()
    stub = _SlowOllama(reply="ok", delay_s=0.02)
    handler = PeerConversationHandler(
        ctx=ctx, ollama=stub, history_size=32, multi_peer_mode="per_peer",
    )
    handler.attach()
    try:
        # 4 speakers x 3 messages each = 12 concurrent inflight tasks
        for i in range(3):
            for sp in ("skye", "lark", "thea", "axiomaclient"):
                await ctx.emit(
                    "conversation_message",
                    {"speaker": sp, "content": f"{sp}-msg-{i}"},
                )
        await handler.wait_idle(timeout=10.0)
    finally:
        handler.detach()
    # All 12 LLM calls succeeded; no exception leaked.
    assert len(stub.calls) == 12
    # Each speaker's history is isolated: only its own user messages appear.
    for sp in ("skye", "lark", "thea", "axiomaclient"):
        bucket = list(handler.histories[sp])
        user_contents = [t.content for t in bucket if t.speaker != Speaker.AXIOMA.value]
        assert all(c.startswith(f"{sp}-msg-") for c in user_contents)


@pytest.mark.asyncio
async def test_per_peer_mode_history_size_applies_per_speaker() -> None:
    """The history_size bound applies to each per-speaker deque independently,
    not as a global cap."""
    ctx = AxiomaContext()
    stub = _StubOllama(reply="r")
    # Each turn appends 2 entries (user + axioma); history_size=4 means each
    # speaker keeps the last 2 (user, axioma) pairs.
    handler = PeerConversationHandler(
        ctx=ctx, ollama=stub, history_size=4, multi_peer_mode="per_peer",
    )
    handler.attach()
    try:
        for i in range(5):
            await ctx.emit("conversation_message", {"speaker": "skye", "content": f"s{i}"})
            await handler.wait_idle(timeout=5.0)
        for i in range(2):
            await ctx.emit("conversation_message", {"speaker": "lark", "content": f"l{i}"})
            await handler.wait_idle(timeout=5.0)
    finally:
        handler.detach()
    # skye bucket capped at 4 entries (most recent 2 pairs)
    assert len(handler.histories["skye"]) == 4
    # lark only sent 2 turns; 4 entries (2 user + 2 axioma), under the cap
    assert len(handler.histories["lark"]) == 4


@pytest.mark.asyncio
async def test_per_peer_mode_self_echo_guard_still_active() -> None:
    """The AXIOMA-self echo guard must work in per_peer mode too — outbound
    AXIOMA emits don't recursively trigger _respond."""
    ctx = AxiomaContext()
    stub = _StubOllama(reply="single reply")
    handler = PeerConversationHandler(ctx=ctx, ollama=stub, multi_peer_mode="per_peer")
    handler.attach()
    try:
        await ctx.emit("conversation_message", {"speaker": "skye", "content": "hi"})
        await handler.wait_idle(timeout=5.0)
    finally:
        handler.detach()
    # Exactly one LLM call — the AXIOMA-self echo did not re-trigger _respond.
    assert len(stub.calls) == 1
