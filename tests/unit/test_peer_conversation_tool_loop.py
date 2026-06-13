"""Tool-use loop tests for PeerConversationHandler (v1.12, Phase 1).

When an `axioma.self_expansion.ToolExecutor` is registered on the ctx
under the key `tool_executor`, the handler runs a multi-turn loop:

  - Call Ollama with `tools=[...]`
  - If the model returns `tool_calls`, dispatch each via the executor
  - Append the assistant turn (tool_calls) and one tool-result turn per call
  - Loop until the model returns plain text, or hit `max_tool_iterations`
  - Final reply = the last plain-text turn (intermediate narration is
    captured as `last_text` but NOT concatenated into the final output —
    avoids "Let me check." ×N noise when the loop stalls)

These tests stub both Ollama and the executor so the loop's mechanics
are verified without booting either dependency.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from axioma.infra.ollama import ChatResponse, ToolCall
from axioma.interface.peer_conversation import PeerConversationHandler
from axioma.observability import AxiomaContext

# ── Stubs ────────────────────────────────────────────────────────────


class _StubOllama:
    """Stub OllamaClient. Returns a scripted sequence of ChatResponse objects.

    Each call consumes one scripted response. Records every (messages, tools)
    pair so tests can assert on the conversation that was built up.
    """

    def __init__(self, responses: list[ChatResponse]) -> None:
        self.responses: Iterator[ChatResponse] = iter(responses)
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        **_: Any,
    ) -> ChatResponse:
        self.calls.append(([dict(m) for m in messages], list(tools)))
        try:
            return next(self.responses)
        except StopIteration:
            raise AssertionError(
                "test exhausted scripted Ollama responses — loop ran too long"
            )

    async def chat(self, messages: list, **_: Any) -> str:
        # Fallback path: used by the recovery/stuck handler.
        return "fallback single-shot"


class _StubExecutor:
    """Stub ToolExecutor. Advertises some tools; dispatches via a scripted dict."""

    def __init__(self, tool_results: dict[str, str]) -> None:
        # Anthropic-format tool def list (what the real ToolExecutor returns)
        self.tools = [
            {"name": name, "description": f"stub {name}",
             "input_schema": {"type": "object"}}
            for name in tool_results
        ]
        self._results = tool_results
        self.dispatched: list[tuple[str, dict]] = []

    async def execute_async(self, name: str, args: dict) -> str:
        self.dispatched.append((name, args))
        return self._results.get(name, f"[ERROR] unknown tool: {name}")


def _make_handler(*, ollama: _StubOllama, executor: _StubExecutor | None = None,
                   max_tool_iterations: int = 5) -> PeerConversationHandler:
    ctx = AxiomaContext()
    if executor is not None:
        ctx.register("tool_executor", executor)
    return PeerConversationHandler(
        ctx=ctx, ollama=ollama,
        max_tool_iterations=max_tool_iterations,
    )


# ── Loop mechanics ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_executor_falls_back_to_single_chat() -> None:
    """Back-compat: no tool_executor on ctx → use the old single-shot path."""
    ollama = _StubOllama([])  # chat_with_tools shouldn't be called
    handler = _make_handler(ollama=ollama, executor=None)
    reply = await handler.respond_text(speaker="skye", content="hi")
    assert reply == "fallback single-shot"
    assert ollama.calls == []  # chat_with_tools not invoked


@pytest.mark.asyncio
async def test_executor_with_no_tools_falls_back() -> None:
    """If the executor is registered but has no tools loaded, still fall back."""
    executor = _StubExecutor({})
    ollama = _StubOllama([])
    handler = _make_handler(ollama=ollama, executor=executor)
    reply = await handler.respond_text(speaker="skye", content="hi")
    assert reply == "fallback single-shot"


@pytest.mark.asyncio
async def test_zero_tool_calls_short_circuits() -> None:
    """Model returns text + no tool_calls → loop exits immediately."""
    executor = _StubExecutor({"file_read": "ok"})
    ollama = _StubOllama([
        ChatResponse(text="Final answer right away."),
    ])
    handler = _make_handler(ollama=ollama, executor=executor)
    reply = await handler.respond_text(speaker="skye", content="hi")
    assert reply == "Final answer right away."
    assert len(ollama.calls) == 1
    assert executor.dispatched == []


@pytest.mark.asyncio
async def test_single_tool_call_then_final_text() -> None:
    """Model emits tool_call → executor runs it → second LLM call returns text."""
    executor = _StubExecutor({"file_read": "hello from file"})
    ollama = _StubOllama([
        # Round 1: tool call, no text
        ChatResponse(text="", tool_calls=[
            ToolCall(name="file_read", arguments={"path": "/x"}, id="call_1"),
        ]),
        # Round 2: text only — loop exits
        ChatResponse(text="The file says: hello from file"),
    ])
    handler = _make_handler(ollama=ollama, executor=executor)
    reply = await handler.respond_text(speaker="skye", content="read /x")
    assert reply == "The file says: hello from file"
    # Executor was actually invoked with the right args
    assert executor.dispatched == [("file_read", {"path": "/x"})]
    # Two Ollama round-trips
    assert len(ollama.calls) == 2
    # Round-2 messages must include the tool-result turn
    round2_msgs = ollama.calls[1][0]
    tool_msgs = [m for m in round2_msgs if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"] == "hello from file"
    assert tool_msgs[0]["name"] == "file_read"


@pytest.mark.asyncio
async def test_multiple_tool_calls_in_one_round_all_dispatched() -> None:
    """One LLM round can emit several tool_calls; all dispatched (sequentially)
    and each gets its own tool-result turn."""
    executor = _StubExecutor({
        "file_read": "f-out", "bash_exec": "b-out",
    })
    ollama = _StubOllama([
        ChatResponse(text="", tool_calls=[
            ToolCall(name="file_read", arguments={"path": "/a"}, id="c1"),
            ToolCall(name="bash_exec", arguments={"command": "ls"}, id="c2"),
        ]),
        ChatResponse(text="combined!"),
    ])
    handler = _make_handler(ollama=ollama, executor=executor)
    reply = await handler.respond_text(speaker="skye", content="multi")
    assert reply == "combined!"
    # Both tools dispatched, in order
    assert [d[0] for d in executor.dispatched] == ["file_read", "bash_exec"]
    # Round 2 has TWO tool messages
    round2_msgs = ollama.calls[1][0]
    tool_msgs = [m for m in round2_msgs if m.get("role") == "tool"]
    assert len(tool_msgs) == 2
    assert {m["content"] for m in tool_msgs} == {"f-out", "b-out"}


@pytest.mark.asyncio
async def test_chained_tool_calls_across_iterations() -> None:
    """Web-search → web-fetch → text — three LLM rounds, two tools.
    Final reply is the LAST no-tool text ONLY — intermediate narration
    is NOT concatenated."""
    executor = _StubExecutor({
        "web_search": '[{"url": "http://x"}]',
        "web_fetch":  "the page body",
    })
    ollama = _StubOllama([
        ChatResponse(text="Let me search.", tool_calls=[
            ToolCall(name="web_search", arguments={"query": "x"}, id="c1"),
        ]),
        ChatResponse(text="Now I'll fetch.", tool_calls=[
            ToolCall(name="web_fetch", arguments={"url": "http://x"}, id="c2"),
        ]),
        ChatResponse(text="Based on the page, the answer is Y."),
    ])
    handler = _make_handler(ollama=ollama, executor=executor)
    reply = await handler.respond_text(speaker="skye",
                                        content="research x for me")
    # Only the final turn's text is returned (no concatenation of intermediate)
    assert reply == "Based on the page, the answer is Y."
    # Two tools dispatched in order
    assert [d[0] for d in executor.dispatched] == ["web_search", "web_fetch"]
    assert len(ollama.calls) == 3


@pytest.mark.asyncio
async def test_iteration_cap_triggers_recovery_and_returns_fallback() -> None:
    """Three identical tool calls → stuck guard fires → _recover_stuck_loop
    calls ollama.chat() → returns the stub fallback."""
    executor = _StubExecutor({"file_read": "ok"})
    # Always returns a tool call — never plain text
    forever = ChatResponse(text="progress…", tool_calls=[
        ToolCall(name="file_read", arguments={"path": "/x"}, id="c"),
    ])
    ollama = _StubOllama([forever, forever, forever])  # 3 rounds, then stuck
    handler = _make_handler(ollama=ollama, executor=executor,
                            max_tool_iterations=3)
    reply = await handler.respond_text(speaker="skye", content="loop forever")
    # Stuck guard → _recover_stuck_loop → ollama.chat() → "fallback single-shot"
    assert reply == "fallback single-shot"
    # Executor dispatched 3 times
    assert len(executor.dispatched) == 2


@pytest.mark.asyncio
async def test_executor_crash_surfaces_as_error_text_to_model() -> None:
    """Exceptions in `executor.execute_async` are caught and surfaced to
    the model as a [ERROR] result so the model can decide what to do
    next — they do NOT crash the loop."""
    class _CrashyExecutor(_StubExecutor):
        async def execute_async(self, name: str, args: dict) -> str:
            self.dispatched.append((name, args))
            raise RuntimeError("simulated tool crash")

    executor = _CrashyExecutor({"file_read": "ignored"})
    ollama = _StubOllama([
        ChatResponse(text="", tool_calls=[
            ToolCall(name="file_read", arguments={"path": "/x"}, id="c1"),
        ]),
        ChatResponse(text="Sorry, the tool crashed; here is what I can say."),
    ])
    handler = _make_handler(ollama=ollama, executor=executor)
    reply = await handler.respond_text(speaker="skye", content="probe a tool")
    assert "Sorry" in reply
    # The tool-result message should carry the [ERROR] marker
    round2_msgs = ollama.calls[1][0]
    tool_msg = next(m for m in round2_msgs if m.get("role") == "tool")
    assert "[ERROR]" in tool_msg["content"]
    assert "simulated tool crash" in tool_msg["content"]


@pytest.mark.asyncio
async def test_ollama_tools_array_uses_openai_shape() -> None:
    """The handler must translate the executor's Anthropic-style tool defs
    into Ollama's OpenAI-style {type:'function', function:{name, ...}}."""
    executor = _StubExecutor({"file_read": "ok"})
    ollama = _StubOllama([ChatResponse(text="done")])
    handler = _make_handler(ollama=ollama, executor=executor)
    await handler.respond_text(speaker="skye", content="hi")
    _msgs, tools = ollama.calls[0]
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    fn = tools[0]["function"]
    assert fn["name"] == "file_read"
    assert "description" in fn
    assert "parameters" in fn  # NOT "input_schema" — Ollama wants "parameters"


@pytest.mark.asyncio
async def test_ollama_error_with_partial_text_returns_partial() -> None:
    """If Ollama fails mid-loop after we already accumulated text, return
    the text we have plus a note instead of an empty string."""
    from axioma.infra.ollama import OllamaError

    class _StubOllamaError(_StubOllama):
        async def chat_with_tools(self, *args: Any, **kwargs: Any) -> ChatResponse:
            self.calls.append((args, kwargs))
            if len(self.calls) == 1:
                return ChatResponse(text="here is what I know so far.",
                                    tool_calls=[ToolCall(
                                        name="file_read", arguments={}, id="c",
                                    )])
            raise OllamaError("simulated Ollama failure")

    executor = _StubExecutor({"file_read": "ok"})
    ollama = _StubOllamaError([])
    handler = _make_handler(ollama=ollama, executor=executor)
    reply = await handler.respond_text(speaker="skye", content="probe")
    assert "here is what I know so far" in reply
    assert "tool loop ended early" in reply


@pytest.mark.asyncio
async def test_history_is_updated_with_final_reply_not_intermediates() -> None:
    """The persistent per-speaker history should record AXIOMA's final
    reply text (the no-tool-call turn), not the intermediate tool noise.
    The implementation returns only the final turn's text."""
    executor = _StubExecutor({"file_read": "the contents"})
    ollama = _StubOllama([
        ChatResponse(text="Let me check.", tool_calls=[
            ToolCall(name="file_read", arguments={"path": "/x"}, id="c"),
        ]),
        ChatResponse(text="The file says: the contents"),
    ])
    handler = _make_handler(ollama=ollama, executor=executor)
    reply = await handler.respond_text(speaker="skye", content="read /x")
    # History has 2 entries: user turn + AXIOMA's final reply
    history = list(handler.history)
    assert len(history) == 2
    assert history[0].speaker == "skye"
    assert history[1].speaker == "axioma"
    # AXIOMA's stored reply is the FINAL turn text only (not intermediate)
    assert "The file says" in history[1].content
    assert reply == history[1].content
