"""Subscriber — per-WebSocket-connection state.

One Subscriber object per connected client. Owns:
  - The set of subscribed channels
  - Per-channel coalescing buffer (one pending payload per channel)
  - Per-subscriber `min_interval_ms` for rate limiting (server-side coalescing
    per C15)
  - Inbound rate limit (msgs/sec) tracking + strike counter per V1
  - A bounded send queue + flush task

The flush task wakes when (a) a new payload arrives on a subscribed channel,
(b) the min_interval_ms timer elapses. It serialises queued payloads as JSON
and sends them on the websocket.

Slow consumer detection: if more than one payload is coalesced on the same
channel for more than the slow-consumer window, we force-close per V1.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from ..observability import get_logger
from .protocol import KNOWN_CHANNELS, ErrorCode, envelope

log = get_logger(__name__)

# Type for the underlying WS send function — websockets.WebSocketServerProtocol.send
SendCallable = Callable[[str], Awaitable[None]]


@dataclass
class RateLimitTracker:
    """Sliding-window inbound rate limit.

    Counts messages received in the current 1-second window; if the count
    exceeds `limit_per_sec`, the strike counter increments and we emit a
    `rate_limited` frame. Three consecutive strikes (over 3 seconds) closes
    the connection per V1.
    """

    limit_per_sec: int = 100
    max_consecutive_strikes: int = 3
    _window_start: float = 0.0
    _window_count: int = 0
    consecutive_strikes: int = 0

    def record(self, now: float) -> bool:
        """Record a received message; return True if within the limit."""
        # Roll the window every second.
        if now - self._window_start >= 1.0:
            # If we struck the limit in the last full window, mark a strike.
            if self._window_count > self.limit_per_sec:
                self.consecutive_strikes += 1
            else:
                self.consecutive_strikes = 0
            self._window_start = now
            self._window_count = 0
        self._window_count += 1
        return self._window_count <= self.limit_per_sec

    def exhausted(self) -> bool:
        return self.consecutive_strikes >= self.max_consecutive_strikes


class Subscriber:
    """Per-connection state. Async-safe (one owner task per instance)."""

    def __init__(
        self,
        *,
        send: SendCallable,
        speaker: str,
        agent_id: str | None = None,
        min_interval_ms: int = 0,
        rate_limit: RateLimitTracker | None = None,
        slow_consumer_threshold_seconds: float = 5.0,
    ) -> None:
        self.connection_id = str(uuid.uuid4())
        self.agent_id = agent_id or self.connection_id
        self.speaker = speaker
        self.min_interval_ms = max(0, int(min_interval_ms))
        self.channels: set[str] = set()
        # v1.9.1 (Checkpoint TT) — channels for which this subscriber has
        # opted into the addressed-only filter (only_addressed_to_me=True at
        # subscribe time). Payloads queued to one of these channels are
        # dropped if `metadata.to_speaker` is set and doesn't match
        # self.speaker. Payloads without `metadata.to_speaker` (unaddressed
        # broadcasts, including all of v1.0–v1.8 wire format) are always
        # delivered — the filter is positive (only filters when there's
        # something to filter on), so it's safe alongside `multi_peer_mode =
        # "shared"`.
        self._addressed_only_channels: set[str] = set()
        # One pending payload per channel — coalesces stale updates.
        self._pending: dict[str, dict[str, Any]] = {}
        self._pending_since: dict[str, float] = {}
        self._send = send
        self._connected_at = time.monotonic()
        self.last_message_received_at: float | None = None
        self._closed = False
        self.rate_limit = rate_limit or RateLimitTracker()
        self.slow_consumer_threshold_seconds = slow_consumer_threshold_seconds
        self._wake = asyncio.Event()
        self._flush_task: asyncio.Task[None] | None = None
        # Stats
        self.coalesced_dropped_total = 0
        self.sent_total = 0

    # ── Channel management ─────────────────────────────────────────────

    def subscribe(self, channel: str, *, only_addressed_to_me: bool = False) -> bool:
        """Add a channel. Returns False if unknown.

        v1.9.1 (Checkpoint TT): `only_addressed_to_me` opts the subscriber
        into the per-channel addressed-only filter (see queue() for
        semantics). Re-subscribing to the same channel with a different
        value updates the filter state — pass False to clear an existing
        opt-in.
        """
        if channel not in KNOWN_CHANNELS:
            return False
        self.channels.add(channel)
        if only_addressed_to_me:
            self._addressed_only_channels.add(channel)
        else:
            self._addressed_only_channels.discard(channel)
        return True

    def unsubscribe(self, channel: str) -> None:
        self.channels.discard(channel)
        self._addressed_only_channels.discard(channel)
        self._pending.pop(channel, None)
        self._pending_since.pop(channel, None)

    # ── Outbound queue ─────────────────────────────────────────────────

    def queue(self, channel: str, payload: dict[str, Any], *, beat_no: int | None = None) -> None:
        """Queue a payload for delivery on `channel` (coalescing).

        If a payload is already pending on this channel, it's dropped — only
        the latest survives. This is intentional (per ARCH §8.4: peers care
        about *current* state, not the missed snapshots).

        v1.9.1 (Checkpoint TT) — per-channel addressed-only filter: if this
        channel is in `_addressed_only_channels` and the payload's
        `metadata.to_speaker` is set and doesn't match `self.speaker`, the
        payload is silently dropped (does not consume the coalescing slot,
        does not wake the flush loop). Unaddressed payloads (no
        `metadata.to_speaker`, e.g. v1.0–v1.8 wire format or `multi_peer_mode
        = "shared"`) are always delivered.
        """
        if self._closed or channel not in self.channels:
            return
        if channel in self._addressed_only_channels:
            metadata = payload.get("metadata") if isinstance(payload, dict) else None
            if isinstance(metadata, dict):
                to_speaker = metadata.get("to_speaker")
                if to_speaker is not None and to_speaker != self.speaker:
                    return
        now = time.monotonic()
        if channel in self._pending:
            self.coalesced_dropped_total += 1
        else:
            self._pending_since[channel] = now
        self._pending[channel] = envelope(channel, payload, beat_no=beat_no)
        self._wake.set()

    def send_direct(self, frame: dict[str, Any]) -> None:
        """Enqueue a non-coalesced frame (e.g., handshake response, error)."""
        if self._closed:
            return
        # Use a distinct synthetic key so it can't collide with channels.
        key = f"_direct:{uuid.uuid4()}"
        self._pending[key] = frame
        self._pending_since[key] = time.monotonic()
        self._wake.set()

    # ── Flush loop ─────────────────────────────────────────────────────

    async def run_flush_loop(self) -> None:
        """Long-running task that drains pending payloads to the WS.

        Honors min_interval_ms: after sending, waits until that interval has
        elapsed before sending again. While waiting, additional payloads on
        the same channel coalesce.
        """
        try:
            while not self._closed:
                await self._wake.wait()
                self._wake.clear()
                if self._closed:
                    break
                while self._pending and not self._closed:
                    # Pop everything currently pending in one batch.
                    batch = list(self._pending.items())
                    self._pending.clear()
                    self._pending_since.clear()
                    # Slow-consumer guard: if we've been waiting longer than the
                    # threshold to even send any batch, force-close.
                    for _, frame in batch:
                        try:
                            await self._send(json.dumps(frame, default=_json_default))
                            self.sent_total += 1
                        except Exception:
                            log.info("subscriber_send_failed", agent_id=self.agent_id)
                            self._closed = True
                            return
                    if self.min_interval_ms > 0:
                        await asyncio.sleep(self.min_interval_ms / 1000.0)
        except asyncio.CancelledError:
            pass

    def check_slow_consumer(self, now: float) -> bool:
        """Return True if any pending payload has been waiting longer than the threshold."""
        if not self._pending_since:
            return False
        oldest = min(self._pending_since.values())
        return (now - oldest) > self.slow_consumer_threshold_seconds

    async def send_error(self, code: int, reason: str, **detail: Any) -> None:
        frame = {
            "type": "error",
            "code": code,
            "reason": reason,
            "detail": detail,
        }
        try:
            await self._send(json.dumps(frame, default=_json_default))
        except Exception:
            log.info("subscriber_send_error_failed", agent_id=self.agent_id)

    async def close(self, code: int = 1000, reason: str = "ok") -> None:
        """Mark closed and wake the flush loop so it can exit."""
        if self._closed:
            return
        self._closed = True
        self._wake.set()
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._flush_task
        log.info(
            "subscriber_closed",
            agent_id=self.agent_id,
            speaker=self.speaker,
            close_code=code,
            reason=reason,
            sent_total=self.sent_total,
            coalesced_dropped_total=self.coalesced_dropped_total,
        )

    # ── Inbound rate-limit accounting ──────────────────────────────────

    def on_inbound(self, now: float | None = None) -> tuple[bool, bool]:
        """Record an inbound message.

        Returns (allowed, exhausted) — `allowed` is False if THIS message
        exceeds the per-second cap (caller should send a rate_limited frame);
        `exhausted` is True if the consecutive-strike threshold has been hit
        (caller should close per V1).
        """
        now = now if now is not None else time.monotonic()
        allowed = self.rate_limit.record(now)
        self.last_message_received_at = now
        return allowed, self.rate_limit.exhausted()


def _json_default(obj: Any) -> Any:
    """Permissive JSON encoder for dataclasses, enums, numpy scalars."""
    import dataclasses

    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    # Enums
    if hasattr(obj, "value"):
        return obj.value
    # numpy / pydantic / others — fall back to repr
    if hasattr(obj, "tolist"):
        return obj.tolist()
    if hasattr(obj, "item"):
        return obj.item()
    if isinstance(obj, set | frozenset):
        return sorted(obj)
    raise TypeError(f"not JSON-serializable: {type(obj).__name__}")


__all__ = [
    "ErrorCode",
    "RateLimitTracker",
    "Subscriber",
]
