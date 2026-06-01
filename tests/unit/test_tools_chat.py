"""Tests for axioma.tools.chat — focused on the connection-resilience fix.

When the WS server closes mid-session (e.g., AXIOMA was restarted while
the chat CLI was open), the previous version of `send_chat` would crash
with an unhandled `ConnectionClosedOK` traceback. These tests cover the
new behaviour:

  - `_send_safe` catches the `ConnectionClosed` family + OSError, returns
    False, sets `_connection_closed`, and prints a friendly message.
  - `send_chat` / `cmd_sub` / `cmd_unsub` / `cmd_watch` bail out cleanly
    on a closed connection instead of re-raising.
  - `_reader_loop` sets `_connection_closed` on exit (clean OR error).
  - The REPL short-circuits and returns 0 when `_connection_closed=True`.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from websockets.exceptions import ConnectionClosedOK

from axioma.tools.chat import ChatClient

# ── Stubs ────────────────────────────────────────────────────────────


class _StubConsole:
    """Records printed lines so tests can assert on the friendly-message text."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *args: Any, **_kwargs: Any) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def clear(self) -> None:
        self.lines.append("[CLEAR]")


def _make_close_exc(code: int = 1001, reason: str = "going away") -> ConnectionClosedOK:
    """Build a ConnectionClosedOK like the one in the user's traceback."""
    from websockets.frames import Close
    rcvd = Close(code=code, reason=reason)
    sent = Close(code=code, reason=reason)
    # `rcvd_then_sent` matches what websockets raises in normal close handshakes.
    return ConnectionClosedOK(rcvd, sent, rcvd_then_sent=True)


class _StubWS:
    """Stub websocket. Default: send works; set fail_send_with to raise on next send."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.fail_send_with: BaseException | None = None
        self.closed = False

    async def send(self, payload: str) -> None:
        if self.fail_send_with is not None:
            exc = self.fail_send_with
            self.fail_send_with = None
            raise exc
        if self.closed:
            raise _make_close_exc()
        self.sent.append(payload)

    async def recv(self) -> str:
        # Not used by these tests; if called, the test got the wrong path.
        raise _make_close_exc()

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self) -> Any:
        async def _gen() -> Any:
            # Yields nothing then exits — simulates a connection that closed.
            if False:
                yield ""
        return _gen()


def _make_client() -> ChatClient:
    c = ChatClient(
        ws_url="ws://localhost:8820",
        http_url="http://localhost:8821",
        speaker="skye",
        admin_key=None,
        reply_timeout=10.0,
    )
    c.console = _StubConsole()  # type: ignore[assignment]
    c.ws = _StubWS()
    return c


# ── _send_safe ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_safe_succeeds_on_open_connection() -> None:
    c = _make_client()
    ok = await c._send_safe({"type": "ping"})
    assert ok is True
    assert c._connection_closed is False
    assert c.ws.sent == ['{"type": "ping"}']


@pytest.mark.asyncio
async def test_send_safe_catches_connection_closed_and_marks_flag() -> None:
    """The exact scenario from the user's traceback: server sent 1001;
    next ws.send() raises ConnectionClosedOK. We must catch + flag, not raise."""
    c = _make_client()
    c.ws.fail_send_with = _make_close_exc()
    ok = await c._send_safe({"type": "message", "content": "hi"})
    assert ok is False
    assert c._connection_closed is True
    # User-facing message mentions the close code + suggests next steps.
    joined = "\n".join(c.console.lines)
    assert "connection closed" in joined
    assert "1001" in joined
    assert "axioma_ctl.sh status" in joined


@pytest.mark.asyncio
async def test_send_safe_short_circuits_when_flag_already_set() -> None:
    """Once _connection_closed is True, subsequent calls don't touch ws.send."""
    c = _make_client()
    c._connection_closed = True
    ok = await c._send_safe({"type": "anything"})
    assert ok is False
    # ws.send was NOT called (no entry added)
    assert c.ws.sent == []


@pytest.mark.asyncio
async def test_send_safe_catches_oserror_too() -> None:
    """Broken-pipe / network drops surface as OSError, not ConnectionClosed —
    still must be caught."""
    c = _make_client()
    c.ws.fail_send_with = OSError("broken pipe")
    ok = await c._send_safe({"type": "ping"})
    assert ok is False
    assert c._connection_closed is True
    assert "dropped" in " ".join(c.console.lines)


# ── send_chat resilience ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_chat_returns_cleanly_on_closed_connection() -> None:
    """The exact crash from the traceback: send_chat called on a connection
    that's already closed. Must not raise; transcript stays empty for this turn."""
    c = _make_client()
    c.ws.fail_send_with = _make_close_exc()
    # send_chat needs to handle this without raising
    await c.send_chat("hello")
    assert c._connection_closed is True
    # Nothing added to transcript because the send failed.
    assert c.transcript == []


# ── slash commands resilience ────────────────────────────────────────


@pytest.mark.asyncio
async def test_cmd_sub_bails_on_closed_connection() -> None:
    c = _make_client()
    c.ws.fail_send_with = _make_close_exc()
    ok = await c.cmd_sub(["theta"])
    # Returns True (REPL keeps going), but the subscribe wasn't added to user_subs
    assert ok is True
    assert "theta" not in c.user_subs


@pytest.mark.asyncio
async def test_cmd_unsub_bails_on_closed_connection() -> None:
    c = _make_client()
    c.user_subs.add("theta")
    c.ws.fail_send_with = _make_close_exc()
    ok = await c.cmd_unsub(["theta"])
    assert ok is True
    # user_subs untouched because the unsubscribe didn't send
    assert "theta" in c.user_subs


# ── reader loop marks flag on exit ───────────────────────────────────


@pytest.mark.asyncio
async def test_reader_loop_marks_closed_on_clean_exit() -> None:
    """When `async for raw in self.ws` exits (because the server closed),
    we must mark _connection_closed=True so the REPL knows to bail."""
    c = _make_client()
    # Stub iterator yields nothing then exits — like a closed socket.
    await c._reader_loop()
    assert c._connection_closed is True


@pytest.mark.asyncio
async def test_reader_loop_marks_closed_on_exception() -> None:
    c = _make_client()

    async def _iter_raises() -> Any:
        yield "{not-json"  # not a dict; gets skipped
        raise _make_close_exc()
        yield ""  # unreachable

    c.ws.__aiter__ = _iter_raises  # type: ignore[method-assign,assignment]
    await c._reader_loop()
    assert c._connection_closed is True


# ── REPL short-circuit ────────────────────────────────────────────────


# ── OLLAMA_TIMEOUT env-var defaulting ────────────────────────────────


def test_default_reply_timeout_uses_ollama_timeout_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operator's OLLAMA_TIMEOUT (typically 600s for a thinking model) must
    flow through to the chat CLI's --reply-timeout default. Without this,
    the client reports 'no reply within 120s' while Ollama is still
    legitimately working."""
    from axioma.tools.chat import _default_reply_timeout
    monkeypatch.setenv("OLLAMA_TIMEOUT", "600")
    assert _default_reply_timeout() == 600.0


def test_default_reply_timeout_falls_back_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from axioma.tools.chat import _default_reply_timeout
    monkeypatch.delenv("OLLAMA_TIMEOUT", raising=False)
    assert _default_reply_timeout() == 120.0


def test_default_reply_timeout_falls_back_on_unparseable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from axioma.tools.chat import _default_reply_timeout
    monkeypatch.setenv("OLLAMA_TIMEOUT", "not-a-number")
    assert _default_reply_timeout() == 120.0


def test_default_reply_timeout_clamps_to_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative or zero values get clamped to 1s (you can't sensibly wait
    0 seconds; protects against pathological env settings)."""
    from axioma.tools.chat import _default_reply_timeout
    monkeypatch.setenv("OLLAMA_TIMEOUT", "0")
    assert _default_reply_timeout() == 1.0
    monkeypatch.setenv("OLLAMA_TIMEOUT", "-5")
    assert _default_reply_timeout() == 1.0


@pytest.mark.asyncio
async def test_repl_exits_cleanly_when_connection_already_closed() -> None:
    """If _connection_closed is True at the top of the loop, repl returns 0
    without prompting for input."""
    from axioma.tools.chat import repl
    c = _make_client()
    c._connection_closed = True
    # If repl tried to call input(), this would hang. Patch it to detect.
    called = []
    def _fake_input(prompt: str = "") -> str:
        called.append(prompt)
        return "should never be read"
    with patch("builtins.input", _fake_input):
        rc = await repl(c)
    assert rc == 0
    assert called == [], "REPL should not have asked for input on a closed connection"
    # Friendly message printed
    joined = "\n".join(c.console.lines)
    assert "server connection is closed" in joined
