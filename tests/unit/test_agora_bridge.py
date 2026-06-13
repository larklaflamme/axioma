"""AgoraBridge — unit tests with a fake Agora agent (no network, no Ollama).

The bridge is the Axioma-specific glue over the vendored ACP/1.1 client: it reacts
to inbound `message` events from *other* citizens and posts a reply back to the
thread. We swap the real `AgoraAgent` for a fake that feeds hand-built `Event`s
through an async queue and records outbound `say()` calls, so we can assert the
react/reply contract deterministically.
"""
from __future__ import annotations

import asyncio

import pytest

from axioma.interface.agora import Event
from axioma.interface.agora_bridge import AgoraBridge


class FakeAgent:
    """Stands in for AgoraAgent — same surface the bridge touches."""

    def __init__(self, handle: str = "axioma") -> None:
        self.handle = handle
        self.subscriptions: set[int] = set()
        self._connected = asyncio.Event()
        self._stream_mode = False
        self._inbox: asyncio.Queue[Event] = asyncio.Queue()
        self.sent: list[dict] = []          # recorded outbound posts
        self.logged_out = False
        self.closed = False
        self.stopped = False

    # -- lifecycle the bridge calls --
    async def start(self) -> None:
        self._connected.set()

    async def subscribe_all(self) -> list[int]:
        self.subscriptions.update({1})
        return [1]

    async def subscribe(self, *ids: int) -> None:
        self.subscriptions.update(int(i) for i in ids)

    async def stream(self):
        while True:
            ev = await self._inbox.get()
            yield ev

    def stop(self) -> None:
        self.stopped = True

    async def logout(self) -> None:
        self.logged_out = True

    async def aclose(self) -> None:
        self.closed = True

    # -- outbound (Event.reply -> agent.say) --
    async def say(self, thread_id, body, visibility="shared", **kw):
        self.sent.append({"thread_id": thread_id, "body": body,
                          "visibility": visibility, **kw})
        return {"id": 999}

    # -- test helper: feed an inbound message event --
    def feed_message(self, *, author: str, body: str, thread_id: int = 1,
                     mid: int = 10, visibility: str = "shared") -> None:
        message = {
            "id": mid,
            "author": {"citizen_id": author, "display_name": author},
            "body": body,
            "visibility": visibility,
        }
        ev = Event(agent=self, kind="message",
                   raw={"thread_id": thread_id, "message": message},
                   thread_id=thread_id, message=message)
        self._inbox.put_nowait(ev)


async def _bridge_with_fake(responder, **kw) -> tuple[AgoraBridge, FakeAgent]:
    bridge = AgoraBridge(
        ctx=None,  # the bridge never dereferences ctx in these paths
        responder=responder,
        base_url="http://localhost:8935",
        citizen_id="axioma",
        password="pw",
        **kw,
    )
    fake = FakeAgent(handle="axioma")
    bridge.agent = fake  # swap the real client for the fake
    await bridge.start()
    return bridge, fake


async def _wait_until(cond, timeout: float = 2.0) -> None:
    async def _poll() -> None:
        while not cond():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(_poll(), timeout)


@pytest.mark.asyncio
async def test_non_self_message_triggers_reply() -> None:
    seen: list[tuple[str, str]] = []

    async def responder(speaker: str, content: str) -> str:
        seen.append((speaker, content))
        return f"echo:{content}"

    bridge, fake = await _bridge_with_fake(responder)
    try:
        fake.feed_message(author="thea", body="hello", thread_id=7, mid=42,
                          visibility="shared")
        await _wait_until(lambda: len(fake.sent) == 1)
        assert seen == [("thea", "hello")]
        reply = fake.sent[0]
        assert reply["body"] == "echo:hello"
        assert reply["thread_id"] == 7
        assert reply["visibility"] == "shared"   # inherits the message's tier
        assert reply["parent_id"] == 42           # threaded reply
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_whisper_reply_names_its_recipient() -> None:
    """A whisper reply must carry whisper_recipient_id (ACP/1.1 §7) or the server
    rejects it NO_RECIPIENT. Regression: the bridge inherited the whisper
    visibility but not the recipient, so it silently failed every whispered DM."""
    async def responder(speaker: str, content: str) -> str:
        return f"echo:{content}"

    bridge, fake = await _bridge_with_fake(responder)
    try:
        fake.feed_message(author="lark", body="can you hear me?", thread_id=1,
                          mid=9175, visibility="whisper")
        await _wait_until(lambda: len(fake.sent) == 1)
        reply = fake.sent[0]
        assert reply["visibility"] == "whisper"
        assert reply["whisper_recipient_id"] == "lark"   # echo back to the sender
        assert reply["parent_id"] == 9175
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_anonymous_whisper_reply_falls_back_to_shared() -> None:
    """A masked (anonymous) whisper has no author to whisper back to, so the
    reply downgrades to shared rather than posting a recipient-less whisper."""
    async def responder(speaker: str, content: str) -> str:
        return "ack"

    bridge, fake = await _bridge_with_fake(responder)
    try:
        # masked poster => author present but citizen_id is None => Event.author None
        message = {"id": 50, "author": {"citizen_id": None, "display_name": "anon"},
                   "body": "psst", "visibility": "whisper"}
        ev = Event(agent=fake, kind="message",
                   raw={"thread_id": 1, "message": message},
                   thread_id=1, message=message)
        fake._inbox.put_nowait(ev)
        await _wait_until(lambda: len(fake.sent) == 1)
        reply = fake.sent[0]
        assert reply["visibility"] == "shared"
        assert "whisper_recipient_id" not in reply
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_self_message_is_ignored() -> None:
    called = False

    async def responder(speaker: str, content: str) -> str:
        nonlocal called
        called = True
        return "should not run"

    bridge, fake = await _bridge_with_fake(responder)
    try:
        # author == agent.handle → Event.is_self is True → no reply
        fake.feed_message(author="axioma", body="my own post")
        await asyncio.sleep(0.1)
        assert called is False
        assert fake.sent == []
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_empty_reply_posts_nothing() -> None:
    async def responder(speaker: str, content: str) -> str:
        return "   "  # whitespace-only → stays silent

    bridge, fake = await _bridge_with_fake(responder)
    try:
        fake.feed_message(author="thea", body="hi")
        await asyncio.sleep(0.1)
        assert fake.sent == []
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_responder_exception_does_not_kill_loop() -> None:
    calls: list[str] = []

    async def responder(speaker: str, content: str) -> str:
        calls.append(content)
        if content == "boom":
            raise RuntimeError("responder blew up")
        return f"ok:{content}"

    bridge, fake = await _bridge_with_fake(responder)
    try:
        fake.feed_message(author="thea", body="boom", mid=1)
        await _wait_until(lambda: calls == ["boom"])
        # The loop survives the exception and still handles the next message.
        fake.feed_message(author="thea", body="again", mid=2)
        await _wait_until(lambda: len(fake.sent) == 1)
        assert fake.sent[0]["body"] == "ok:again"
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_stop_logs_out_and_closes() -> None:
    async def responder(speaker: str, content: str) -> str:
        return ""

    bridge, fake = await _bridge_with_fake(responder)
    await bridge.stop()
    assert fake.stopped is True
    assert fake.logged_out is True
    assert fake.closed is True
    # idempotent
    await bridge.stop()


@pytest.mark.asyncio
async def test_subscribe_all_records_subscriptions() -> None:
    async def responder(speaker: str, content: str) -> str:
        return ""

    bridge, _fake = await _bridge_with_fake(responder)
    try:
        assert bridge.connected is True
        assert bridge.subscriptions == [1]
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_fixed_thread_ids_when_not_subscribe_all() -> None:
    async def responder(speaker: str, content: str) -> str:
        return ""

    bridge = AgoraBridge(
        ctx=None, responder=responder, base_url="http://localhost:8935",
        citizen_id="axioma", password="pw",
        subscribe_all=False, thread_ids=[3, 5],
    )
    fake = FakeAgent(handle="axioma")
    bridge.agent = fake
    await bridge.start()
    try:
        assert bridge.subscriptions == [3, 5]
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_concurrency_cap_limits_in_flight_responders() -> None:
    """At most max_concurrent_replies responders run at once; the rest wait."""
    active = 0
    peak = 0
    release = asyncio.Event()

    async def responder(speaker: str, content: str) -> str:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await release.wait()       # hold the slot until the test releases
        finally:
            active -= 1
        return ""

    bridge, fake = await _bridge_with_fake(responder, max_concurrent_replies=2)
    try:
        for i in range(6):
            fake.feed_message(author="thea", body=f"m{i}", mid=i)
        await _wait_until(lambda: peak >= 2)
        await asyncio.sleep(0.1)        # give any over-admission a chance to show
        assert peak == 2, f"semaphore should cap concurrency at 2, saw {peak}"
        release.set()                   # let them all drain
    finally:
        release.set()
        await bridge.stop()


@pytest.mark.asyncio
async def test_backpressure_drops_when_queue_full() -> None:
    """Past the queue cap, excess inbound messages are shed (counted), not piled on."""
    release = asyncio.Event()

    async def responder(speaker: str, content: str) -> str:
        await release.wait()
        return ""

    # cap concurrency at 1 and queue at 2 → only ~2 tasks may be in-flight.
    bridge, fake = await _bridge_with_fake(
        responder, max_concurrent_replies=1, max_queued_replies=2,
    )
    try:
        for i in range(10):
            fake.feed_message(author="thea", body=f"m{i}", mid=i)
        await _wait_until(lambda: bridge.dropped_overload_total > 0)
        await asyncio.sleep(0.05)
        assert len(bridge._inflight) <= bridge._max_queued
        assert bridge.dropped_overload_total >= 1
        release.set()
    finally:
        release.set()
        await bridge.stop()
