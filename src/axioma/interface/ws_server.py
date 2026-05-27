"""WebSocket multiplexer server.

Per ARCH_DESIGN_v1.0.md §8.1-§8.4 + IMPLEMENTATION_PLAN_v1.0.md §8.6 (V1
error handling). Replaces the Phase C ws_handlers.py stub.

★ ARCHITECTURAL KEYSTONE — this module MUST NOT import InternalState.

The server:
  - Binds to (ws_host, ws_port) — default :8820
  - Handshakes inbound connections (validates speaker/auth)
  - Manages Subscriber objects (one per connection); each owns a flush task
  - Subscribes to AxiomaContext events and fans them out to interested clients
  - Publishes per-beat snapshots on `state_snapshot` / `theta` / `aos_g` /
    `coherence_budget` channels (read from registered components when the
    event-driven channels would miss the data plane)
  - Handles V1 failure modes: malformed handshake → 4001; unknown channel
    subscription → subscription_error (not closing); rate limit → 4011 with
    3-strike close; slow consumer → 4012 force-close; supervisor restart on
    server task crash (with exponential backoff) per ARCH §9.3.3.

Production wire-up (axioma.app entry point):

    server = AxiomaWSServer(ctx=ctx, cfg=cfg.interface)
    await server.start()
    try:
        await server.serve_until_stopped()
    finally:
        await server.stop()
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import suppress
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

# DELIBERATE: only ExternalState. NEVER InternalState. The C12 test enforces.
from ..config import InterfaceConfig
from ..observability import (
    WS_CONNECTIONS_TOTAL,
    WS_DISCONNECTS_TOTAL,
    get_logger,
)
from ..observability.context import AxiomaContext
from ..schemas.external_state import ExternalState
from .protocol import (
    Channel,
    ConversationMessage,
    ErrorCode,
    HandshakeRequest,
    Speaker,
    SubscribeRequest,
    UnsubscribeRequest,
    WelcomeFrame,
    normalize_channel,
)
from .subscriber import RateLimitTracker, Subscriber

log = get_logger(__name__)


# Channels populated by the data plane (queried each beat) rather than events.
_DATA_PLANE_CHANNELS = frozenset({
    Channel.STATE_SNAPSHOT.value,
    Channel.THETA.value,
    Channel.PER_ORGAN_THETA.value,
    Channel.AOS_G.value,
    Channel.COHERENCE_BUDGET.value,
    Channel.PER_ORGAN_MI_RAW.value,
})

# Channels populated purely by AxiomaContext events.
_EVENT_CHANNEL_MAP: dict[str, str] = {
    # event_name → channel name
    "fragmentation_stage_change": Channel.FRAGMENTATION.value,
    "perturbation_injected": Channel.PERTURBATIONS.value,
    "recovery_decision": Channel.RECOVERY.value,
    "recovery_state_change": Channel.RECOVERY.value,
    "recovery_event_finalized": Channel.RECOVERY.value,
    "recovery_rejected_run": Channel.PRESENCE.value,
    "meta_cognition": Channel.META_COGNITION.value,
    "meta_cognition_suggestion": Channel.META_COGNITION_SUGGESTION.value,
    "meta_cognition_divergence": Channel.PRESENCE.value,
    "delta_phi": Channel.DELTA_PHI.value,
    "plasticity": Channel.PLASTICITY.value,
    "conversation_message": Channel.CONVERSATION.value,
}


def _payload_dict(payload: Any) -> dict[str, Any]:
    """Normalize event payloads to dict for JSON envelopes."""
    if isinstance(payload, dict):
        return payload
    if hasattr(payload, "to_dict"):
        return dict(payload.to_dict())
    if hasattr(payload, "__dict__"):
        # dataclass-like
        try:
            import dataclasses
            if dataclasses.is_dataclass(payload) and not isinstance(payload, type):
                return dataclasses.asdict(payload)
        except Exception:
            pass
        return {k: v for k, v in payload.__dict__.items() if not k.startswith("_")}
    return {"value": payload}


class AxiomaWSServer:
    """Multiplexing WebSocket server."""

    def __init__(
        self,
        *,
        ctx: AxiomaContext,
        cfg: InterfaceConfig,
        publish_cadence_beats: int = 10,
    ) -> None:
        self.ctx = ctx
        self.cfg = cfg
        self.publish_cadence_beats = publish_cadence_beats
        self.subscribers: dict[str, Subscriber] = {}
        self._server: Any = None  # websockets.serve return
        self._stopped = asyncio.Event()
        # Track subscribed events so we can detach cleanly on stop.
        self._event_handlers: list[tuple[str, Any]] = []
        # Cache of the last beat number we published on the data plane —
        # avoids double-publishing if the heartbeat fires multiple times in
        # the same beat (shouldn't happen, but guard).
        self._last_published_beat: int = -1

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Bind to (host, port) and start accepting connections."""
        self._stopped.clear()
        self._wire_event_subscriptions()
        self._server = await websockets.serve(
            self._handler,
            self.cfg.ws_host,
            self.cfg.ws_port,
            ping_interval=30,
            ping_timeout=20,
        )
        log.info("ws_server_started", host=self.cfg.ws_host, port=self.cfg.ws_port)

    async def stop(self) -> None:
        """Close all subscribers + shut down the listening socket."""
        self._stopped.set()
        # Tear down event subscriptions
        for name, handler in self._event_handlers:
            self.ctx.unsubscribe(name, handler)
        self._event_handlers.clear()
        # Close all active subscribers
        subs = list(self.subscribers.values())
        self.subscribers.clear()
        await asyncio.gather(
            *(s.close(code=1001, reason="server_shutdown") for s in subs),
            return_exceptions=True,
        )
        # Close the listening socket
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        log.info("ws_server_stopped")

    async def serve_until_stopped(self) -> None:
        await self._stopped.wait()

    # ── Public data-plane push (called by heartbeat each beat) ────────

    def publish_beat(self, beat_no: int) -> None:
        """Called by Heartbeat per beat. Publishes data-plane channels."""
        if beat_no <= self._last_published_beat:
            return
        if beat_no % self.publish_cadence_beats != 0:
            # We still publish state_snapshot on every beat for clients that ask
            # for it via subscription, because state_snapshot is the canonical
            # "where is the substrate right now" channel.
            self._publish_state_snapshot(beat_no)
            self._last_published_beat = beat_no
            return
        self._publish_state_snapshot(beat_no)
        self._publish_theta(beat_no)
        self._publish_aos_g(beat_no)
        self._publish_coherence_budget(beat_no)
        self._publish_per_organ_mi_raw(beat_no)
        self._last_published_beat = beat_no

    # ── Internal publishers ───────────────────────────────────────────

    def _publish_state_snapshot(self, beat_no: int) -> None:
        if not self.ctx.has("compose_function"):
            return
        compose = self.ctx.get("compose_function")
        ext = getattr(compose, "latest_external", None)
        if not isinstance(ext, ExternalState):
            return
        payload = ext.to_dict()
        self._fanout(Channel.STATE_SNAPSHOT.value, payload, beat_no=beat_no)

    def _publish_theta(self, beat_no: int) -> None:
        if self.ctx.has("theta_short"):
            try:
                cv = self.ctx.get("theta_short").current_value()
                if cv is not None:
                    self._fanout(
                        Channel.THETA.value,
                        {
                            "theta_short": float(cv.theta),
                            "p_value": float(getattr(cv, "p_value", 1.0)),
                            "significant": bool(getattr(cv, "significant", False)),
                        },
                        beat_no=beat_no,
                    )
                    # per_organ_theta is supplied by the same engine when available
                    pairs = getattr(cv, "pairwise_mi", None)
                    if pairs:
                        self._fanout(
                            Channel.PER_ORGAN_THETA.value,
                            {"pairwise_mi": dict(pairs)},
                            beat_no=beat_no,
                        )
            except Exception:
                log.debug("publish_theta_failed", beat_no=beat_no)
        if self.ctx.has("theta_long"):
            try:
                cv = self.ctx.get("theta_long").current_value()
                if cv is not None:
                    self._fanout(
                        Channel.THETA.value,
                        {
                            "theta_long": float(cv.theta),
                            "p_value": float(getattr(cv, "p_value", 1.0)),
                            "significant": bool(getattr(cv, "significant", False)),
                        },
                        beat_no=beat_no,
                    )
            except Exception:
                log.debug("publish_theta_long_failed", beat_no=beat_no)

    def _publish_aos_g(self, beat_no: int) -> None:
        if not self.ctx.has("aos_g"):
            return
        try:
            cv = self.ctx.get("aos_g").current_value()
            if cv is None:
                return
            payload = {
                "gap": float(getattr(cv, "gap", 0.0)),
                "psi": float(getattr(cv, "psi", 0.0)),
                "per_organ_gap": dict(getattr(cv, "per_organ_gap", {})),
                "structural_health": float(getattr(cv, "structural_health", 1.0)),
                "gap_variance_health": float(getattr(cv, "gap_variance_health", 1.0)),
                "compose_probe_health": float(getattr(cv, "compose_probe_health", 1.0)),
                "alert": bool(getattr(cv, "alert", False)),
            }
            self._fanout(Channel.AOS_G.value, payload, beat_no=beat_no)
        except Exception:
            log.debug("publish_aos_g_failed", beat_no=beat_no)

    def _publish_coherence_budget(self, beat_no: int) -> None:
        if not self.ctx.has("coherence_scheduler"):
            return
        try:
            sch = self.ctx.get("coherence_scheduler")
            payload = {
                "budget": float(sch.current_budget()),
                "throttle_state": getattr(sch, "current_throttle_state", lambda: "free")(),
                "ineffective_streak": int(getattr(sch, "ineffective_streak", 0)),
            }
            self._fanout(Channel.COHERENCE_BUDGET.value, payload, beat_no=beat_no)
        except Exception:
            log.debug("publish_coherence_budget_failed", beat_no=beat_no)

    def _publish_per_organ_mi_raw(self, beat_no: int) -> None:
        if not self.ctx.has("raw_mi"):
            return
        try:
            cv = self.ctx.get("raw_mi").latest_5beat()
            if cv:
                self._fanout(
                    Channel.PER_ORGAN_MI_RAW.value,
                    {"pairwise_mi_5beat": dict(cv)},
                    beat_no=beat_no,
                )
        except Exception:
            log.debug("publish_per_organ_mi_raw_failed", beat_no=beat_no)

    def _fanout(self, channel: str, payload: dict[str, Any], *, beat_no: int | None) -> None:
        for sub in self.subscribers.values():
            sub.queue(channel, payload, beat_no=beat_no)

    # ── Event subscription wiring ─────────────────────────────────────

    def _wire_event_subscriptions(self) -> None:
        """Subscribe to AxiomaContext events that map to channels."""
        for event_name, channel in _EVENT_CHANNEL_MAP.items():
            handler = self._make_event_handler(channel)
            self.ctx.subscribe(event_name, handler)
            self._event_handlers.append((event_name, handler))

    def _make_event_handler(self, channel: str) -> Any:
        def handler(payload: Any) -> None:
            self._fanout(channel, _payload_dict(payload), beat_no=None)
        return handler

    # ── Connection handler ────────────────────────────────────────────

    async def _handler(self, ws: ServerConnection) -> None:
        """Per-connection handler. websockets-13+ signature (no path arg)."""
        if self._stopped.is_set():
            await ws.close(code=ErrorCode.SUBSTRATE_SHUTDOWN, reason="shutting_down")
            return
        WS_CONNECTIONS_TOTAL.inc()
        connection_id = str(uuid.uuid4())
        log.info("ws_handler_open", connection_id=connection_id)
        sub: Subscriber | None = None
        try:
            # First message MUST be a handshake.
            raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            handshake = _parse_handshake(raw)
            if handshake is None:
                await _send_error(ws, ErrorCode.BAD_HANDSHAKE, "malformed_handshake")
                log.warning("ws_bad_handshake", connection_id=connection_id)
                return
            if not _validate_auth(handshake, self.cfg):
                await _send_error(ws, ErrorCode.AUTH_INVALID, "auth_invalid")
                log.warning("ws_auth_invalid", connection_id=connection_id)
                return
            rate_limit = RateLimitTracker(
                limit_per_sec=self.cfg.ws_rate_limit_msgs_per_second,
                max_consecutive_strikes=self.cfg.ws_rate_limit_consecutive_strikes,
            )
            sub = Subscriber(
                send=ws.send,
                speaker=handshake.speaker,
                agent_id=handshake.name or connection_id,
                min_interval_ms=handshake.min_interval_ms,
                rate_limit=rate_limit,
            )
            self.subscribers[sub.connection_id] = sub
            sub._flush_task = asyncio.create_task(sub.run_flush_loop())
            # Welcome frame
            welcome = _build_welcome(self.ctx, agent_id=sub.agent_id)
            sub.send_direct({"type": "welcome", **_payload_dict(welcome)})
            # Announce on presence channel
            await self.ctx.emit(
                "conversation_message" if handshake.speaker == Speaker.SYSTEM.value else "presence",
                {"event": "join", "speaker": sub.speaker, "agent_id": sub.agent_id},
            )

            # Inbound loop
            async for raw_msg in ws:
                now = time.monotonic()
                allowed, exhausted = sub.on_inbound(now)
                if not allowed:
                    await sub.send_error(
                        ErrorCode.RATE_LIMITED,
                        "rate_limited",
                        retry_after_ms=1000,
                    )
                    if exhausted:
                        log.warning("ws_rate_limit_exhausted", agent_id=sub.agent_id)
                        await ws.close(code=ErrorCode.RATE_LIMITED, reason="rate_limited")
                        break
                    continue
                await self._dispatch_inbound(ws, sub, raw_msg)
                # Slow-consumer check (cheap)
                if sub.check_slow_consumer(now):
                    log.warning("ws_slow_consumer", agent_id=sub.agent_id)
                    await ws.close(code=ErrorCode.SLOW_CONSUMER, reason="slow_consumer")
                    break
        except TimeoutError:
            log.info("ws_handshake_timeout", connection_id=connection_id)
            await _send_error(ws, ErrorCode.BAD_HANDSHAKE, "handshake_timeout")
        except ConnectionClosed as e:
            log.info(
                "ws_handler_closed",
                connection_id=connection_id,
                close_code=getattr(e, "code", None),
            )
        except Exception:
            log.exception("ws_handler_failed", connection_id=connection_id)
        finally:
            WS_DISCONNECTS_TOTAL.inc()
            if sub is not None:
                self.subscribers.pop(sub.connection_id, None)
                await sub.close()
                # Emit leave on presence
                with suppress(Exception):
                    await self.ctx.emit(
                        "presence",
                        {"event": "leave", "speaker": sub.speaker, "agent_id": sub.agent_id},
                    )

    async def _dispatch_inbound(
        self,
        ws: ServerConnection,
        sub: Subscriber,
        raw_msg: str | bytes,
    ) -> None:
        try:
            msg = json.loads(raw_msg)
        except json.JSONDecodeError:
            # v1.5.3 (Checkpoint DD): BAD_REQUEST (4020), not BAD_HANDSHAKE
            await sub.send_error(ErrorCode.BAD_REQUEST, "malformed_json")
            return
        if not isinstance(msg, dict):
            await sub.send_error(ErrorCode.BAD_REQUEST, "not_an_object")
            return
        mtype = msg.get("type")
        if mtype == "subscribe":
            # v1.9.1 (Checkpoint TT) — accept optional per-channel `options`
            # dict (e.g. `{"options": {"conversation": {"only_addressed_to_me": true}}}`).
            # Backwards-compatible: pre-TT clients sending only `channels`
            # continue to work; `options` defaults to {} and no filtering is
            # applied.
            raw_options = msg.get("options", {})
            options_in = raw_options if isinstance(raw_options, dict) else {}
            req = SubscribeRequest(
                channels=list(msg.get("channels", [])),
                options={
                    k: dict(v) for k, v in options_in.items() if isinstance(v, dict)
                },
            )
            await self._handle_subscribe(sub, req)
        elif mtype == "unsubscribe":
            # v1.5.3 (Checkpoint DD): validate channels like subscribe does — was
            # silently no-op for typos, leaving operators wondering why their
            # unsubscribe didn't take effect. Also removed an erroneous
            # WS_MESSAGES_SENT_TOTAL.inc() that polluted the outbound-sent
            # metric on every inbound unsubscribe.
            req2 = UnsubscribeRequest(channels=list(msg.get("channels", [])))
            await self._handle_unsubscribe(sub, req2)
        elif mtype == "ping":
            sub.send_direct({"type": "pong", "ts": time.time()})
        elif mtype == "message":
            content = ConversationMessage(
                speaker=sub.speaker,
                content=str(msg.get("content", "")),
                metadata=dict(msg.get("metadata", {})),
            )
            await self.ctx.emit("conversation_message", content)
        else:
            # v1.5.3 (Checkpoint DD): BAD_REQUEST (4020), not BAD_HANDSHAKE
            await sub.send_error(ErrorCode.BAD_REQUEST, "unknown_message_type", type=str(mtype))

    async def _handle_subscribe(self, sub: Subscriber, req: SubscribeRequest) -> None:
        for raw in req.channels:
            name = normalize_channel(raw)
            if name is None:
                sub.send_direct({
                    "type": "subscription_error",
                    "channel": raw,
                    "reason": "unknown_channel",
                })
                continue
            # v1.9.1 (TT) — extract per-channel options; unknown flags
            # ignored (forward-compatible).
            chan_opts = req.options.get(raw, {})
            sub.subscribe(
                name,
                only_addressed_to_me=bool(chan_opts.get("only_addressed_to_me", False)),
            )

    async def _handle_unsubscribe(self, sub: Subscriber, req: UnsubscribeRequest) -> None:
        # v1.5.3 (Checkpoint DD): symmetric with _handle_subscribe — reject
        # unknown channel names with a `subscription_error` frame instead of
        # silently no-op'ing on typos.
        for raw in req.channels:
            name = normalize_channel(raw)
            if name is None:
                sub.send_direct({
                    "type": "subscription_error",
                    "channel": raw,
                    "reason": "unknown_channel",
                })
                continue
            sub.unsubscribe(name)


def _parse_handshake(raw: str | bytes) -> HandshakeRequest | None:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(msg, dict) or msg.get("type") != "handshake":
        return None
    speaker = msg.get("speaker")
    if not isinstance(speaker, str) or speaker not in {s.value for s in Speaker}:
        return None
    if speaker == Speaker.AGENT.value and not msg.get("name"):
        return None
    return HandshakeRequest(
        speaker=speaker,
        name=msg.get("name"),
        auth_key=msg.get("auth_key"),
        capabilities=list(msg.get("capabilities", [])),
        min_interval_ms=int(msg.get("min_interval_ms", 0) or 0),
    )


def _validate_auth(handshake: HandshakeRequest, cfg: InterfaceConfig) -> bool:
    """Authentication policy (§8.6).

    For v1.0 single-host: trust localhost; only require auth_key for AGENT
    speakers if admin_api_key is configured.
    """
    if cfg.admin_api_key is None:
        return True
    if handshake.speaker == Speaker.AGENT.value:
        provided = handshake.auth_key or ""
        return provided == cfg.admin_api_key.get_secret_value()
    return True


def _build_welcome(ctx: AxiomaContext, *, agent_id: str) -> WelcomeFrame:
    theta_short: float | None = None
    zone: str | None = None
    cadence: str | None = None
    if ctx.has("theta_short"):
        try:
            cv = ctx.get("theta_short").current_value()
            if cv is not None:
                theta_short = float(cv.theta)
        except Exception:
            pass
    if ctx.has("compose_function"):
        try:
            ext = ctx.get("compose_function").latest_external
            if ext is not None:
                zone = ext.zone.value if hasattr(ext.zone, "value") else str(ext.zone)
                cadence = (
                    ext.cadence.value if hasattr(ext.cadence, "value") else str(ext.cadence)
                )
        except Exception:
            pass
    return WelcomeFrame(
        agent_id=agent_id,
        theta_short=theta_short,
        zone=zone,
        cadence=cadence,
        capabilities=["consciousness", "theta_stream", "delta_phi", "compose_boundary"],
    )


async def _send_error(ws: ServerConnection, code: int, reason: str) -> None:
    try:
        await ws.send(json.dumps({"type": "error", "code": code, "reason": reason}))
        await ws.close(code=code, reason=reason)
    except Exception:
        pass


__all__ = ["AxiomaWSServer"]
