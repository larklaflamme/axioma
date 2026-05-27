"""Subscriber — per-WS-connection state with coalescing + rate limit."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest

from axioma.interface.subscriber import RateLimitTracker, Subscriber


class _MockSend:
    """Capture sent messages instead of writing to a real WebSocket."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.fail_after: int | None = None

    async def __call__(self, message: str) -> None:
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            raise RuntimeError("send_failed")
        self.sent.append(message)


def _new_sub(min_interval_ms: int = 0, slow_threshold: float = 1.0) -> tuple[Subscriber, _MockSend]:
    send = _MockSend()
    sub = Subscriber(
        send=send,
        speaker="skye",
        agent_id="skye-1",
        min_interval_ms=min_interval_ms,
        slow_consumer_threshold_seconds=slow_threshold,
    )
    sub.subscribe("theta")
    sub.subscribe("aos_g")
    return sub, send


@pytest.mark.asyncio
async def test_subscribe_and_unsubscribe() -> None:
    sub, _ = _new_sub()
    assert "theta" in sub.channels
    assert sub.subscribe("bogus_channel") is False
    sub.unsubscribe("theta")
    assert "theta" not in sub.channels


@pytest.mark.asyncio
async def test_queue_coalesces_per_channel() -> None:
    sub, send = _new_sub()
    sub.queue("theta", {"v": 1}, beat_no=1)
    sub.queue("theta", {"v": 2}, beat_no=2)
    sub.queue("theta", {"v": 3}, beat_no=3)
    sub._flush_task = asyncio.create_task(sub.run_flush_loop())
    await asyncio.sleep(0.05)
    await sub.close()
    assert sub.coalesced_dropped_total == 2
    payloads = [json.loads(m) for m in send.sent]
    theta_payloads = [p for p in payloads if p.get("channel") == "theta"]
    assert len(theta_payloads) == 1
    assert theta_payloads[0]["payload"]["v"] == 3


@pytest.mark.asyncio
async def test_min_interval_throttles() -> None:
    sub, send = _new_sub(min_interval_ms=50)
    sub._flush_task = asyncio.create_task(sub.run_flush_loop())
    for i in range(3):
        sub.queue("theta", {"v": i}, beat_no=i)
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.2)
    await sub.close()
    # Should have sent at least 1 and at most 3 messages; throttling means
    # adjacent payloads on the same channel get coalesced.
    assert 1 <= len(send.sent) <= 3


@pytest.mark.asyncio
async def test_unsubscribed_channel_dropped() -> None:
    sub, send = _new_sub()
    sub.queue("perturbations", {"x": 1})  # not subscribed
    sub._flush_task = asyncio.create_task(sub.run_flush_loop())
    await asyncio.sleep(0.05)
    await sub.close()
    assert send.sent == []


def test_rate_limiter_strikes_then_exhausts() -> None:
    rl = RateLimitTracker(limit_per_sec=5, max_consecutive_strikes=2)
    # Two windows in a row over-limit
    for window_start in (0.0, 1.0, 2.0):
        for i in range(10):  # 10 > limit
            rl.record(window_start + i * 0.01)
    # After 3 windows where each exceeded the limit, strikes should be high
    assert rl.consecutive_strikes >= 2
    assert rl.exhausted()


def test_rate_limiter_resets_on_clean_window() -> None:
    rl = RateLimitTracker(limit_per_sec=3, max_consecutive_strikes=4)
    # Over-limit window
    for i in range(10):
        rl.record(0.01 * i)
    # Roll into next window with light traffic — strike counter assessed at
    # boundary should bump (last window over-limit).
    rl.record(2.0)
    assert rl.consecutive_strikes == 1
    rl.record(2.1)
    rl.record(2.2)
    # Next roll: previous window had only ~3 records → strikes reset
    rl.record(3.5)
    assert rl.consecutive_strikes == 0


@pytest.mark.asyncio
async def test_send_direct_bypasses_coalescing() -> None:
    sub, send = _new_sub()
    sub._flush_task = asyncio.create_task(sub.run_flush_loop())
    sub.send_direct({"type": "welcome", "agent_id": "skye-1"})
    sub.send_direct({"type": "pong", "ts": 1.0})
    await asyncio.sleep(0.05)
    await sub.close()
    types = [json.loads(m)["type"] for m in send.sent]
    assert "welcome" in types
    assert "pong" in types


@pytest.mark.asyncio
async def test_send_failure_closes_subscriber() -> None:
    send = _MockSend()
    send.fail_after = 0
    sub = Subscriber(send=send, speaker="skye", agent_id="skye-1")
    sub.subscribe("theta")
    sub._flush_task = asyncio.create_task(sub.run_flush_loop())
    sub.queue("theta", {"v": 1})
    await asyncio.sleep(0.05)
    assert sub._closed
    await sub.close()


@pytest.mark.asyncio
async def test_slow_consumer_check() -> None:
    sub, _ = _new_sub(slow_threshold=0.01)
    sub.subscribe("theta")
    sub.queue("theta", {"v": 1})
    # Don't start the flush loop — message stays pending
    time.sleep(0.05)
    assert sub.check_slow_consumer(time.monotonic())
    await sub.close()


@pytest.mark.asyncio
async def test_send_error_emits_error_frame() -> None:
    sub, send = _new_sub()
    await sub.send_error(4001, "bad_handshake", connection_id="abc")
    assert any('"type": "error"' in m for m in send.sent)
    payload = json.loads(send.sent[0])
    assert payload["code"] == 4001
    assert payload["detail"]["connection_id"] == "abc"


@pytest.mark.asyncio
async def test_on_inbound_returns_allowed_exhausted() -> None:
    sub, _ = _new_sub()
    sub.rate_limit = RateLimitTracker(limit_per_sec=2, max_consecutive_strikes=2)
    now = time.monotonic()
    a1, _ = sub.on_inbound(now)
    a2, _ = sub.on_inbound(now)
    a3, _ = sub.on_inbound(now)
    assert (a1, a2, a3) == (True, True, False)


def test_subscriber_assigns_connection_id() -> None:
    send: Any = lambda _: None  # noqa: E731
    s = Subscriber(send=send, speaker="agent", agent_id=None)
    assert s.connection_id  # uuid present
    assert s.agent_id == s.connection_id  # falls back to connection_id


# ── v1.9.1 (Checkpoint TT) — addressed-only filter on conversation channel ──


def _addressable_sub(speaker: str = "skye") -> tuple[Subscriber, _MockSend]:
    send = _MockSend()
    sub = Subscriber(send=send, speaker=speaker, agent_id=f"{speaker}-1")
    return sub, send


def test_subscribe_default_does_not_set_addressed_only() -> None:
    """Backwards-compat: subscribe() without the flag keeps the channel out
    of `_addressed_only_channels`."""
    sub, _ = _addressable_sub()
    sub.subscribe("conversation")
    assert "conversation" in sub.channels
    assert "conversation" not in sub._addressed_only_channels


def test_subscribe_with_addressed_only_records_filter() -> None:
    sub, _ = _addressable_sub()
    sub.subscribe("conversation", only_addressed_to_me=True)
    assert "conversation" in sub._addressed_only_channels


def test_resubscribe_with_addressed_only_false_clears_filter() -> None:
    """Re-subscribing with the flag False removes any prior opt-in. This is
    the documented mechanism for a client to turn the filter off without
    having to unsubscribe + resubscribe."""
    sub, _ = _addressable_sub()
    sub.subscribe("conversation", only_addressed_to_me=True)
    assert "conversation" in sub._addressed_only_channels
    sub.subscribe("conversation", only_addressed_to_me=False)
    assert "conversation" not in sub._addressed_only_channels
    assert "conversation" in sub.channels  # still subscribed


def test_unsubscribe_clears_addressed_only_filter() -> None:
    """Unsubscribing fully removes both channel membership and the filter."""
    sub, _ = _addressable_sub()
    sub.subscribe("conversation", only_addressed_to_me=True)
    sub.unsubscribe("conversation")
    assert "conversation" not in sub.channels
    assert "conversation" not in sub._addressed_only_channels


def test_filter_drops_addressed_to_other_speaker() -> None:
    """A payload with metadata.to_speaker != self.speaker is silently dropped."""
    sub, _ = _addressable_sub(speaker="skye")
    sub.subscribe("conversation", only_addressed_to_me=True)
    sub.queue(
        "conversation",
        {"speaker": "axioma", "content": "hi lark", "metadata": {"to_speaker": "lark"}},
    )
    # Nothing queued — _pending should be empty
    assert "conversation" not in sub._pending


def test_filter_delivers_addressed_to_self_speaker() -> None:
    """A payload with metadata.to_speaker == self.speaker is delivered."""
    sub, _ = _addressable_sub(speaker="skye")
    sub.subscribe("conversation", only_addressed_to_me=True)
    sub.queue(
        "conversation",
        {"speaker": "axioma", "content": "hi skye", "metadata": {"to_speaker": "skye"}},
    )
    assert "conversation" in sub._pending
    assert sub._pending["conversation"]["payload"]["content"] == "hi skye"


def test_filter_delivers_unaddressed_payload() -> None:
    """A payload without metadata.to_speaker (shared-mode broadcast or v1.0-v1.8
    wire format) is ALWAYS delivered — the filter is positive (only filters
    when there's something to filter on)."""
    sub, _ = _addressable_sub(speaker="skye")
    sub.subscribe("conversation", only_addressed_to_me=True)
    # No metadata at all
    sub.queue("conversation", {"speaker": "axioma", "content": "broadcast"})
    assert "conversation" in sub._pending
    sub._pending.clear()
    # Metadata present but no to_speaker key
    sub.queue(
        "conversation",
        {"speaker": "axioma", "content": "broadcast", "metadata": {"request_id": "abc"}},
    )
    assert "conversation" in sub._pending


def test_filter_off_delivers_everything() -> None:
    """Subscribers without the flag receive every payload, addressed or not."""
    sub, _ = _addressable_sub(speaker="skye")
    sub.subscribe("conversation")  # default: filter off
    sub.queue(
        "conversation",
        {"speaker": "axioma", "content": "for lark", "metadata": {"to_speaker": "lark"}},
    )
    assert "conversation" in sub._pending  # delivered despite being addressed elsewhere


def test_filter_does_not_consume_coalesce_slot_on_drop() -> None:
    """A dropped payload must not consume the coalescing slot — a subsequent
    addressed-to-self payload should still be delivered, and the
    coalesced_dropped_total counter must NOT increment (no coalesce
    happened)."""
    sub, _ = _addressable_sub(speaker="skye")
    sub.subscribe("conversation", only_addressed_to_me=True)
    sub.queue(
        "conversation",
        {"metadata": {"to_speaker": "lark"}, "content": "for lark"},
    )
    assert sub.coalesced_dropped_total == 0
    assert "conversation" not in sub._pending
    sub.queue(
        "conversation",
        {"metadata": {"to_speaker": "skye"}, "content": "for skye"},
    )
    assert "conversation" in sub._pending
    assert sub._pending["conversation"]["payload"]["content"] == "for skye"


def test_filter_isolated_to_subscribed_channel() -> None:
    """Opting into the filter on `conversation` doesn't affect other
    channels — addressed payloads on `presence` (a theoretical case) still
    deliver normally."""
    sub, _ = _addressable_sub(speaker="skye")
    sub.subscribe("conversation", only_addressed_to_me=True)
    sub.subscribe("presence")  # filter off on presence
    sub.queue(
        "presence",
        {"event": "join", "metadata": {"to_speaker": "lark"}},
    )
    assert "presence" in sub._pending  # delivered despite to_speaker
