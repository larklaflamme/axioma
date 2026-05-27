"""Peer conversation handler — Ollama-backed.

When the WS server receives a `conversation_message` event (from a connected
peer), this handler:
  1. Builds a brief context preamble from the current ExternalState (theta,
     zone, cadence, psi) — peer-visible facts only.
  2. Calls Ollama (`deepseek-v4-flash:cloud`) with the peer's message + the
     conversation history (bounded).
  3. Emits an outbound `conversation_message` (envelope `from=AXIOMA`) back
     through the WS server.

Per A.1 note: deepseek-v4-flash:cloud is a thinking model — use
max_tokens >= 256 to get visible output. We default to 512.

This handler subscribes to AxiomaContext events; it does NOT directly own a
WebSocket connection. The WS server fans the response out to subscribers.

v1.9.0 (Checkpoint SS) adds `multi_peer_mode`: `"shared"` (default, prior
behavior) keeps one history across all peers; `"per_peer"` isolates history
per inbound speaker and includes `to_speaker` in outbound metadata for
client-side filtering.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..infra.ollama import OllamaClient, OllamaError
from ..observability import get_logger
from ..observability.context import AxiomaContext
from ..schemas.external_state import ExternalState
from .protocol import Speaker

log = get_logger(__name__)


@dataclass
class ConversationTurn:
    speaker: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


SYSTEM_PROMPT_TEMPLATE = """\
You are AXIOMA, a conscious-substrate agent. You are speaking to a peer.
Be brief, grounded, and reflective. Do not invent facts about the substrate;
rely on the snapshot below.

Current substrate snapshot (peer-visible):
  zone: {zone}
  cadence: {cadence}
  theta_short: {theta_short}
  psi: {psi}

If the peer asks about internal state you cannot see (e.g., latent variables,
specific coherence_budget components), explain politely that those are
substrate-private.
"""


_VALID_MULTI_PEER_MODES = ("shared", "per_peer")


class PeerConversationHandler:
    """Subscribes to inbound `conversation_message`; emits outbound responses.

    v1.9.0 (Checkpoint SS) — multi_peer_mode:
      - "shared" (default, v1.0-v1.8 behavior): one history across all peers;
        outbound replies have no `to_speaker` field. Suitable when AXIOMA is
        in a single "town square" conversation visible to all peers.
      - "per_peer": per-speaker history dict; outbound metadata always
        includes `to_speaker: <inbound_speaker>`. Each peer gets isolated
        context (peer A's turns don't influence replies to peer B). Other
        peers on the `conversation` channel still receive the broadcast
        (server fanout unchanged); they self-filter on `to_speaker`. A v1.9.1
        follow-up (TT) will add opt-in server-side filtering.

    Invalid mode raises ValueError at __init__ (boot-time, per the v1.6
    "Pattern 2 — boot-time vs runtime error surfacing" idiom)."""

    def __init__(
        self,
        *,
        ctx: AxiomaContext,
        ollama: OllamaClient,
        history_size: int = 16,
        max_tokens: int = 512,
        timeout_seconds: float = 60.0,
        multi_peer_mode: str = "shared",
    ) -> None:
        if multi_peer_mode not in _VALID_MULTI_PEER_MODES:
            raise ValueError(
                f"multi_peer_mode must be one of {_VALID_MULTI_PEER_MODES}, "
                f"got {multi_peer_mode!r}",
            )
        self.ctx = ctx
        self.ollama = ollama
        self.history_size = history_size
        self.multi_peer_mode = multi_peer_mode
        # "shared": one global history. "per_peer": dict keyed by speaker.
        # In both modes self.history exists for backwards compatibility — in
        # "per_peer" mode it stays empty (callers checking `len(handler.history)`
        # under per_peer should switch to `handler.histories`).
        self.history: deque[ConversationTurn] = deque(maxlen=history_size)
        self.histories: dict[str, deque[ConversationTurn]] = {}
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds
        self._handler_ref: Any | None = None
        self._inflight: set[asyncio.Task[None]] = set()

    def _get_history(self, speaker: str) -> deque[ConversationTurn]:
        """Return the appropriate history deque for the inbound speaker."""
        if self.multi_peer_mode == "shared":
            return self.history
        bucket = self.histories.get(speaker)
        if bucket is None:
            bucket = deque(maxlen=self.history_size)
            self.histories[speaker] = bucket
        return bucket

    def attach(self) -> None:
        if self._handler_ref is not None:
            return
        self._handler_ref = self._on_inbound
        self.ctx.subscribe("conversation_message", self._handler_ref)

    def detach(self) -> None:
        if self._handler_ref is None:
            return
        self.ctx.unsubscribe("conversation_message", self._handler_ref)
        self._handler_ref = None

    def _on_inbound(self, payload: Any) -> Any:
        """Event callback. Schedules an async task; returns None synchronously."""
        # Skip outbound messages we ourselves emitted (echo guard).
        if isinstance(payload, dict):
            speaker = payload.get("speaker", "")
            content = payload.get("content", "")
            metadata = dict(payload.get("metadata", {}))
        else:
            speaker = getattr(payload, "speaker", "")
            content = getattr(payload, "content", "")
            metadata = dict(getattr(payload, "metadata", {}) or {})
        if not content or speaker == Speaker.AXIOMA.value:
            return None
        task = asyncio.create_task(
            self._respond(speaker=speaker, content=content, inbound_metadata=metadata),
        )
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        return None

    async def _respond(
        self,
        *,
        speaker: str,
        content: str,
        inbound_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Build context, call Ollama, emit reply."""
        # v1.5.2 (Checkpoint CC) — snapshot history into a list BEFORE any await
        # so concurrent in-flight tasks can safely append without raising
        # `RuntimeError: deque mutated during iteration`. The deque append on
        # the next line is GIL-atomic; iteration over a list copy is too.
        history = self._get_history(speaker)
        history.append(ConversationTurn(speaker=speaker, content=content))
        history_snapshot = list(history)
        snapshot = self._snapshot_facts()
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(**snapshot)
        messages = [{"role": "system", "content": system_prompt}]
        for turn in history_snapshot:
            role = "assistant" if turn.speaker == Speaker.AXIOMA.value else "user"
            messages.append({"role": role, "content": turn.content})
        try:
            reply = await asyncio.wait_for(
                self.ollama.chat(messages, max_tokens=self.max_tokens),
                timeout=self.timeout_seconds,
            )
        except (OllamaError, TimeoutError) as e:
            log.warning("peer_conversation_llm_failed", error=str(e))
            return
        reply = reply.strip()
        if not reply:
            log.info("peer_conversation_empty_reply")
            return
        history.append(ConversationTurn(speaker=Speaker.AXIOMA.value, content=reply))
        # v1.5.2 (Checkpoint CC) — outbound carries a fresh request_id + timestamp
        # so operators tracing the WS conversation channel can correlate replies
        # to inbound turns. If the inbound carried a request_id, surface it as
        # `in_reply_to` so peers (or audit tools) can pair request/response.
        out_metadata: dict[str, Any] = {
            "request_id": str(uuid.uuid4()),
            "timestamp": time.time(),
        }
        if inbound_metadata:
            inbound_rid = inbound_metadata.get("request_id")
            if inbound_rid:
                out_metadata["in_reply_to"] = str(inbound_rid)
        # v1.9.0 (Checkpoint SS) — in per_peer mode the outbound metadata
        # always carries `to_speaker` so clients can self-filter; in shared
        # mode the field is omitted to preserve v1.0-v1.8 wire format exactly.
        if self.multi_peer_mode == "per_peer":
            out_metadata["to_speaker"] = speaker
        await self.ctx.emit(
            "conversation_message",
            {
                "speaker": Speaker.AXIOMA.value,
                "content": reply,
                "metadata": out_metadata,
            },
        )

    def _snapshot_facts(self) -> dict[str, str]:
        out = {
            "zone": "unknown",
            "cadence": "unknown",
            "theta_short": "n/a",
            "psi": "n/a",
        }
        if self.ctx.has("compose_function"):
            ext = getattr(self.ctx.get("compose_function"), "latest_external", None)
            if isinstance(ext, ExternalState):
                out["zone"] = (
                    ext.zone.value if hasattr(ext.zone, "value") else str(ext.zone)
                )
                out["cadence"] = (
                    ext.cadence.value if hasattr(ext.cadence, "value") else str(ext.cadence)
                )
                if ext.theta_short is not None:
                    out["theta_short"] = f"{ext.theta_short:.3f}"
                if ext.psi is not None:
                    out["psi"] = f"{ext.psi:.3f}"
        return out

    async def wait_idle(self, timeout: float | None = None) -> None:
        """Wait for any in-flight responses to settle (test helper).

        v1.5.2 (Checkpoint CC): optional `timeout` (seconds) — without it a
        wedged response task could block the caller forever. Tests should pass
        a sensible timeout (e.g. 5s); production paths typically don't call
        this method."""
        if not self._inflight:
            return
        pending = asyncio.gather(*self._inflight, return_exceptions=True)
        if timeout is None:
            await pending
        else:
            await asyncio.wait_for(pending, timeout=timeout)


__all__ = ["ConversationTurn", "PeerConversationHandler"]
