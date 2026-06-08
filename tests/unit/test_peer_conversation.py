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


# ── max_tokens default no longer hard-caps at 512 ────────────────────


def test_handler_max_tokens_default_is_none() -> None:
    """The previous default of 512 silently truncated AXIOMA's replies
    regardless of OLLAMA_MAX_TOKENS in .env. New default is None which
    means 'delegate to OllamaClient' which itself reads from cfg.max_tokens
    (-1 = unlimited per the schema + .env mapping)."""
    ctx = AxiomaContext()
    handler = PeerConversationHandler(ctx=ctx, ollama=_StubOllama())
    assert handler.max_tokens is None


@pytest.mark.asyncio
async def test_handler_passes_max_tokens_none_to_ollama_chat() -> None:
    """End-to-end: respond_text → ollama.chat called with max_tokens=None,
    which OllamaClient resolves via cfg.max_tokens. No silent 512 cap."""
    ctx = AxiomaContext()

    class _CapturingStub:
        def __init__(self) -> None:
            self.captured_max_tokens: int | None = -42  # sentinel

        async def chat(self, messages: list, *, max_tokens: int | None = None,
                       **_: Any) -> str:
            self.captured_max_tokens = max_tokens
            return "ok"

    stub = _CapturingStub()
    handler = PeerConversationHandler(ctx=ctx, ollama=stub)
    handler.attach()
    try:
        await handler.respond_text(speaker="skye", content="hi")
    finally:
        handler.detach()
    # max_tokens forwarded as None (NOT 512) — OllamaClient takes over
    assert stub.captured_max_tokens is None


def test_handler_explicit_max_tokens_still_works() -> None:
    """Explicit kwarg still wins — operators can cap if they really need to."""
    ctx = AxiomaContext()
    handler = PeerConversationHandler(
        ctx=ctx, ollama=_StubOllama(), max_tokens=2048,
    )
    assert handler.max_tokens == 2048


# ── OLLAMA_TIMEOUT env-var defaulting (server-side) ──────────────────


def test_handler_timeout_seconds_uses_ollama_timeout_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PeerConversationHandler with no explicit timeout_seconds must read
    OLLAMA_TIMEOUT from env so the server matches the chat client's
    timeout — otherwise the server bails before the client expects, and
    the user sees 'peer_conversation_llm_failed' instead of a real reply."""
    monkeypatch.setenv("OLLAMA_TIMEOUT", "600")
    ctx = AxiomaContext()
    handler = PeerConversationHandler(ctx=ctx, ollama=_StubOllama())
    assert handler.timeout_seconds == 600.0


def test_handler_timeout_seconds_falls_back_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OLLAMA_TIMEOUT", raising=False)
    ctx = AxiomaContext()
    handler = PeerConversationHandler(ctx=ctx, ollama=_StubOllama())
    assert handler.timeout_seconds == 60.0


def test_handler_explicit_timeout_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit kwarg always wins, even when env is set."""
    monkeypatch.setenv("OLLAMA_TIMEOUT", "600")
    ctx = AxiomaContext()
    handler = PeerConversationHandler(
        ctx=ctx, ollama=_StubOllama(), timeout_seconds=15.0,
    )
    assert handler.timeout_seconds == 15.0


def test_handler_falls_back_on_unparseable_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_TIMEOUT", "not-a-number")
    ctx = AxiomaContext()
    handler = PeerConversationHandler(ctx=ctx, ollama=_StubOllama())
    assert handler.timeout_seconds == 60.0


# ── System prompt content invariants (architecture + tools awareness) ──


def test_system_prompt_template_mentions_5_organs() -> None:
    """v1.11 update: AXIOMA should know her own architecture and not gaslight
    peers who ask. Each of the 5 organ names must appear in the template."""
    from axioma.interface.peer_conversation import SYSTEM_PROMPT_TEMPLATE
    for organ in ("ANIMA", "EIDOLON", "MNEME", "NOUS", "PNEUMA"):
        assert organ in SYSTEM_PROMPT_TEMPLATE, f"prompt missing {organ}"


def test_system_prompt_template_mentions_c12_boundary() -> None:
    """The prompt must explain which kinds of state are substrate-private
    so AXIOMA continues to refuse appropriately (e.g., raw drive vector)."""
    from axioma.interface.peer_conversation import SYSTEM_PROMPT_TEMPLATE
    assert "substrate-private" in SYSTEM_PROMPT_TEMPLATE
    assert "C12" in SYSTEM_PROMPT_TEMPLATE


def test_system_prompt_template_mentions_tools_and_tutorial() -> None:
    """v1.11 update: AXIOMA must know her tools exist + how to find the
    tutorial so she can refresh on details via file_read."""
    from axioma.interface.peer_conversation import SYSTEM_PROMPT_TEMPLATE
    # Tool servers
    for s in ("filesystem", "bash", "python", "web_search", "wolfram"):
        assert s in SYSTEM_PROMPT_TEMPLATE, f"prompt missing tool server: {s}"
    # Tutorial path
    assert "docs/tutorials/AXIOMA_TOOLS.md" in SYSTEM_PROMPT_TEMPLATE
    # The escape sequence for file_read is `{{...}}` because the template
    # is .format()-ed elsewhere; verify the doubled-brace pattern survives.
    assert "{{" in SYSTEM_PROMPT_TEMPLATE


def test_system_prompt_template_has_one_canonical_example_per_server() -> None:
    """v1.11 update (Layer 1): the prompt should give AXIOMA a worked
    example for each tool server so she has copy-paste-shaped anchors,
    not just the one file_read-on-tutorial example."""
    from axioma.interface.peer_conversation import SYSTEM_PROMPT_TEMPLATE
    # One canonical call per server (the leading-tool-name + JSON shape)
    for tool_name in ("file_read", "bash_exec", "python_exec",
                       "web_search", "wolfram_math_verify"):
        # Every canonical-examples block should show `tool_name {{...}}`
        # (Python .format()-escaped braces).
        marker = f"{tool_name} {{{{"  # literally `tool_name {{`
        assert marker in SYSTEM_PROMPT_TEMPLATE, (
            f"prompt missing canonical-example marker for {tool_name}"
        )
    # The invocation-format header + the error-envelope convention
    # should both be explained.
    assert "INVOCATION FORMAT" in SYSTEM_PROMPT_TEMPLATE
    assert "[ERROR]" in SYSTEM_PROMPT_TEMPLATE


def test_system_prompt_template_still_formats_with_snapshot_fields() -> None:
    """The substrate-snapshot placeholders (zone/cadence/theta_short/psi)
    plus the new max_tool_iterations all must be in the template so
    .format(**snapshot) still works."""
    from axioma.interface.peer_conversation import SYSTEM_PROMPT_TEMPLATE
    rendered = SYSTEM_PROMPT_TEMPLATE.format(
        zone="focus", cadence="recovery",
        theta_short="1.234", psi="0.987",
        max_tool_iterations="15",
    )
    assert "focus" in rendered
    assert "recovery" in rendered
    assert "1.234" in rendered
    assert "0.987" in rendered
    assert "15" in rendered


@pytest.mark.asyncio
async def test_respond_text_renders_full_prompt_through_to_ollama() -> None:
    """End-to-end: respond_text builds the prompt and the architecture +
    tools sections actually reach the Ollama messages list."""
    ctx = AxiomaContext()
    stub = _StubOllama(reply="ok")
    handler = PeerConversationHandler(ctx=ctx, ollama=stub)
    handler.attach()
    try:
        await handler.respond_text(
            speaker="skye", content="hi", metadata={},
        )
    finally:
        handler.detach()
    assert stub.calls, "stub should have been called"
    system_msg = stub.calls[0][0]
    assert system_msg["role"] == "system"
    sys_text = system_msg["content"]
    # Architecture awareness
    assert "ANIMA" in sys_text and "PNEUMA" in sys_text
    # Tool awareness — at least one tool name + the tutorial path
    assert "file_read" in sys_text or "filesystem" in sys_text
    assert "AXIOMA_TOOLS.md" in sys_text


# ── Tool-use loop: no-progress guard + no narration leak ─────────────────


class _ToolLoopOllama:
    """Stub for the tool-use path: yields a fixed sequence of ChatResponses
    from chat_with_tools, and a canned reply from chat (the recovery turn)."""

    def __init__(self, responses: list[Any], recovery_reply: str = "recovered.") -> None:
        self._responses = list(responses)
        self.recovery_reply = recovery_reply
        self.chat_called = 0

    async def chat_with_tools(self, messages: Any, *, tools: Any,
                              max_tokens: Any = None, **_: Any) -> Any:
        from axioma.infra.ollama import ChatResponse
        if self._responses:
            return self._responses.pop(0)
        return ChatResponse(text="", tool_calls=[])

    async def chat(self, messages: Any, *, max_tokens: Any = None, **_: Any) -> str:
        self.chat_called += 1
        return self.recovery_reply


class _FakeExecutor:
    """Minimal ToolExecutor stand-in: one tool that always returns the same
    result (an [ERROR] by default, mimicking an out-of-scope file_read)."""

    def __init__(self, result: str = "[ERROR] Path outside read scope: /x/constitution.md") -> None:
        self.result = result
        self.tools = [{"name": "file_read", "description": "",
                       "input_schema": {"type": "object"}}]
        self.calls: list[tuple[str, dict]] = []

    async def execute_async(self, name: str, args: dict) -> str:
        self.calls.append((name, args))
        return self.result


@pytest.mark.asyncio
async def test_tool_loop_breaks_on_repeated_identical_call() -> None:
    """The pathological case from the field: the model narrates 'Let me read
    the full constitution.' and issues the identical (unreachable) file_read
    every iteration. The loop must detect the no-progress repeat, stop well
    before max_tool_iterations, run one recovery turn, and return the recovery
    reply — NOT a wall of repeated narration."""
    from axioma.infra.ollama import ChatResponse, ToolCall

    def narrate() -> ChatResponse:
        return ChatResponse(
            text="Let me read the full constitution.",
            tool_calls=[ToolCall(name="file_read",
                                 arguments={"path": "/x/constitution.md"})],
        )

    ctx = AxiomaContext()
    ctx.register("tool_executor", _FakeExecutor())
    stub = _ToolLoopOllama(
        [narrate() for _ in range(50)],
        recovery_reply="I couldn't reach the constitution file — please paste it.",
    )
    handler = PeerConversationHandler(ctx=ctx, ollama=stub, max_tool_iterations=50)
    reply = await handler.respond_text(speaker="skye", content="analyze the constitution")
    # The reply is the recovery answer, not the repeated narration.
    assert reply == "I couldn't reach the constitution file — please paste it."
    assert "Let me read the full constitution." not in reply
    # Exactly one recovery (no-tools) call was made.
    assert stub.chat_called == 1


@pytest.mark.asyncio
async def test_tool_loop_returns_final_text_not_interstitial_narration() -> None:
    """A healthy multi-step turn: the model narrates before a tool call, then
    produces a final answer. The peer-visible reply must be ONLY the final
    answer — the pre-tool-call narration must not leak into it."""
    from axioma.infra.ollama import ChatResponse, ToolCall

    responses = [
        ChatResponse(text="Let me check the file.",
                     tool_calls=[ToolCall(name="file_read",
                                          arguments={"path": "/home/ubuntu/axioma/README.md"})]),
        ChatResponse(text="Done. Here is my structural analysis: it holds together.",
                     tool_calls=[]),
    ]
    ctx = AxiomaContext()
    ctx.register("tool_executor", _FakeExecutor(result="file contents..."))
    stub = _ToolLoopOllama(responses)
    handler = PeerConversationHandler(ctx=ctx, ollama=stub, max_tool_iterations=10)
    reply = await handler.respond_text(speaker="skye", content="analyze")
    assert reply == "Done. Here is my structural analysis: it holds together."
    assert "Let me check the file." not in reply
    # The recovery path was NOT taken — the loop terminated normally.
    assert stub.chat_called == 0


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
