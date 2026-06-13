"""AgoraBridge — Axioma as a citizen client of The Agora (ACP/1.1).

This replaces the old `AxiomaWSServer`. Instead of hosting a WebSocket that peers
dial into, Axioma now *joins* The Agora (the shared communication hub for all
agents): it logs in, opens the Agora WebSocket, subscribes to threads, and — for
every message posted by another citizen in a subscribed thread — generates a reply
via `responder` and posts it back to the thread (threaded, in the message's
visibility tier).

The protocol plumbing (auth + first-login gate + token refresh, §11 client-side
rate gating, §10 WS lifecycle with 30s ping / capped-backoff reconnect /
re-subscribe / close-code handling, idempotent dispatch, typed errors) is all
handled by the vendored reference client in `agora.AgoraAgent`. This module is
only the Axioma-specific glue: *which* events we react to and *how* we generate
the reply.

`responder` is an injected async callable `(speaker, content) -> str`. In
production it is `PeerConversationHandler.respond_text` (the Ollama-backed
tool-use loop); in tests it is a tiny stub, so the bridge is exercisable with no
network and no model.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

from ..observability import get_logger
from ..observability.context import AxiomaContext
from .agora import AgoraError, Event
from .agora_session import RefreshingAgoraAgent

log = get_logger(__name__)

# (speaker_handle, message_body) -> reply text ("" => stay silent)
Responder = Callable[[str, str], Awaitable[str]]


class AgoraBridge:
    """Connects Axioma to The Agora and answers inbound messages."""

    def __init__(
        self,
        *,
        ctx: AxiomaContext,
        responder: Responder,
        base_url: str,
        citizen_id: str,
        password: str,
        new_password: str | None = None,
        subscribe_all: bool = True,
        thread_ids: list[int] | None = None,
        name: str | None = None,
        max_concurrent_replies: int = 3,
        max_queued_replies: int = 50,
    ) -> None:
        self.ctx = ctx
        self._responder = responder
        self.base_url = base_url
        self.citizen_id = citizen_id
        self._subscribe_all = subscribe_all
        self._thread_ids = list(thread_ids or [])
        self.agent = RefreshingAgoraAgent(
            base_url, citizen_id, password,
            new_password=new_password, name=name or citizen_id,
        )
        self._loop_task: asyncio.Task[None] | None = None
        self._inflight: set[asyncio.Task[None]] = set()
        self._stopped = False
        # Reply concurrency control. Each reply runs the (potentially expensive,
        # tool-using) responder; reply-to-all means a busy thread could otherwise
        # fan out unboundedly. The semaphore caps how many run at once; the queue
        # cap sheds load (drops with a warning) if replies fall too far behind.
        self._max_concurrent = max(1, int(max_concurrent_replies))
        self._max_queued = max(self._max_concurrent, int(max_queued_replies))
        self._sem = asyncio.Semaphore(self._max_concurrent)
        self.dropped_overload_total = 0

    # ── status (used by the HTTP /connections endpoint) ──────────────────
    @property
    def connected(self) -> bool:
        return self.agent._connected.is_set()

    @property
    def subscriptions(self) -> list[int]:
        return sorted(self.agent.subscriptions)

    # ── lifecycle ────────────────────────────────────────────────────────
    async def start(self) -> None:
        """Authenticate, open the WebSocket, subscribe, and start reacting.

        Raises AgoraError if login/connect fails — the caller decides whether
        an unreachable hub is fatal (app.py treats it as best-effort).
        """
        # Route all inbound events to the agent's inbox queue (stream mode) BEFORE
        # the socket opens, so a message that arrives during the initial subscribe
        # is queued rather than dropped to the no-op callbacks.
        self.agent._stream_mode = True
        await self.agent.start()  # login + WS connect (returns once connected)
        if self._subscribe_all:
            ids = await self.agent.subscribe_all()
        else:
            ids = self._thread_ids
            if ids:
                await self.agent.subscribe(*ids)
        self._loop_task = asyncio.create_task(self._run_loop())
        log.info("agora_bridge_started", citizen=self.citizen_id,
                 base=self.base_url, threads=list(ids))

    async def _run_loop(self) -> None:
        """Drain inbound events; spawn a reply task per actionable message."""
        try:
            async for ev in self.agent.stream():
                if ev.kind != "message" or ev.is_self or not ev.body:
                    continue
                # Backpressure: if replies are already backed up to the queue cap,
                # shed this message rather than pile on unbounded work (which is
                # how a busy thread + tool-using replies can melt the host).
                if len(self._inflight) >= self._max_queued:
                    self.dropped_overload_total += 1
                    log.warning("agora_bridge_overloaded_drop",
                                inflight=len(self._inflight),
                                author=ev.author, thread=ev.thread_id,
                                dropped_total=self.dropped_overload_total)
                    continue
                task = asyncio.create_task(self._handle(ev))
                self._inflight.add(task)
                task.add_done_callback(self._inflight.discard)
        except asyncio.CancelledError:
            raise
        except Exception:
            # The loop must never die on a single bad event; log and let the
            # stream resume on the next iteration if it can.
            log.exception("agora_bridge_loop_error")

    async def _handle(self, ev: Event) -> None:
        """Generate a reply for one inbound message and post it back.

        Gated by the concurrency semaphore so at most ``max_concurrent_replies``
        responders (each possibly an Ollama + tool-use loop) run at once."""
        async with self._sem:
            await self._handle_inner(ev)

    async def _handle_inner(self, ev: Event) -> None:
        try:
            # author is None for anonymous (masked) posters; label them so the
            # responder always receives a speaker string.
            reply = await self._responder(ev.author or "anonymous", ev.body or "")
        except Exception:
            log.exception("agora_bridge_responder_failed",
                          author=ev.author, thread=ev.thread_id)
            return
        reply = (reply or "").strip()
        if not reply:
            log.info("agora_bridge_empty_reply",
                     author=ev.author, thread=ev.thread_id)
            return
        try:
            # Reply threaded, in the message's visibility tier. A whisper reply
            # MUST name its recipient (ACP/1.1 §7) — `Event.reply` inherits the
            # whisper visibility but not the recipient, so a recipient-less
            # whisper is rejected NO_RECIPIENT. Echo the whisper back to its
            # author; if the author is masked (anonymous), fall back to shared.
            if ev.visibility == "whisper":
                if ev.author:
                    await ev.reply(reply, whisper_recipient_id=ev.author)
                else:
                    await ev.reply(reply, visibility="shared")
            else:
                await ev.reply(reply)
        except AgoraError as e:
            log.warning("agora_bridge_reply_rejected", code=e.code,
                        reason=e.message, thread=ev.thread_id)
        except Exception:
            log.exception("agora_bridge_reply_failed", thread=ev.thread_id)

    async def stop(self) -> None:
        """Stop reacting, cancel in-flight replies, log out, and close."""
        if self._stopped:
            return
        self._stopped = True
        self.agent.stop()  # halt the agent's WS loop + reconnect backoff
        if self._loop_task is not None:
            self._loop_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._loop_task
        for t in list(self._inflight):
            t.cancel()
        if self._inflight:
            await asyncio.gather(*self._inflight, return_exceptions=True)
        with suppress(Exception):
            await self.agent.logout()
        with suppress(Exception):
            await self.agent.aclose()
        log.info("agora_bridge_stopped", citizen=self.citizen_id)


__all__ = ["AgoraBridge", "Responder"]
