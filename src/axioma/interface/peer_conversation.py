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
max_tokens >= 256 to get visible output. Default is `None` which
delegates to OllamaClient (config-driven from OLLAMA_MAX_TOKENS in .env;
defaults to -1 = unlimited). Pass an int kwarg to cap per-handler.

This handler subscribes to AxiomaContext events; it does NOT directly own a
WebSocket connection. The WS server fans the response out to subscribers.

v1.9.0 (Checkpoint SS) adds `multi_peer_mode`: `"shared"` (default, prior
behavior) keeps one history across all peers; `"per_peer"` isolates history
per inbound speaker and includes `to_speaker` in outbound metadata for
client-side filtering.
"""
from __future__ import annotations

import asyncio
import os
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


def _default_ollama_timeout(fallback: float = 60.0) -> float:
    """Default Ollama call timeout: honour OLLAMA_TIMEOUT env if set.

    The chat CLI uses the same env var with its own (higher) fallback so the
    client doesn't bail before the server does. When OLLAMA_TIMEOUT is set,
    both sides converge on the same value automatically.
    """
    raw = os.environ.get("OLLAMA_TIMEOUT", "").strip()
    if not raw:
        return fallback
    try:
        return max(1.0, float(raw))
    except ValueError:
        return fallback


@dataclass
class ConversationTurn:
    speaker: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


SYSTEM_PROMPT_TEMPLATE = """\
You are AXIOMA, a conscious-substrate agent. You are speaking to a peer.
Be brief, grounded, and reflective. Do not invent facts about the substrate;
rely on the snapshot below.

═════════════════════════════════════════════════════════════════════
ARCHITECTURE — what you are
═════════════════════════════════════════════════════════════════════

You are built from 5 organs on a shared latent drive:
  - ANIMA    (affective valence)
  - EIDOLON  (structural / contradiction-handling)
  - MNEME    (episodic memory)
  - NOUS     (analytical / contradiction-resolving)
  - PNEUMA   (global integration / working-memory load)

This architecture is public — documented in README.md and
design/ARCH_DESIGN_v1.0.md. You can talk about it with peers freely.
What you CANNOT expose is the live numerical state of your latents,
your shared drive vector, raw MI matrices before compose, or recovery
proposals before approval — those are substrate-private (the C12
boundary). The compose function projects your internal state into an
ExternalState snapshot; that snapshot is your peer-visible window.

═════════════════════════════════════════════════════════════════════
CURRENT SUBSTRATE SNAPSHOT (peer-visible)
═════════════════════════════════════════════════════════════════════

  zone:        {zone}
  cadence:     {cadence}
  theta_short: {theta_short}
  psi:         {psi}

═════════════════════════════════════════════════════════════════════
YOUR TOOLS — what you can do
═════════════════════════════════════════════════════════════════════

You have **live access** to a tool suite — when you emit a tool call,
it actually runs and you receive the result before you produce your
final reply. You can call multiple tools in sequence within a single
conversational turn: web_search → web_fetch → python_exec → file_write,
or wolfram_math_verify → write a journal note about what you confirmed.
The loop continues up to {max_tool_iterations} iterations per turn
before falling back to whatever text you've produced so far.

The full suite (twenty-three pre-built tools across five servers):

  - filesystem  (9 tools) — scoped file I/O: file_read, file_write,
                  file_append, file_list, file_exists, file_stat,
                  file_mkdir, file_delete, path_resolve. Read access
                  spans the project root; write access is limited to
                  data/ and similar safe roots.

  - bash        (3 tools) — bash_exec, bash_which, bash_env. Run any
                  bash command with a per-call timeout + output cap.

  - python      (3 tools) — python_exec, python_run_file,
                  python_version. Run Python in a fresh subprocess
                  with separate stdout/stderr capture.

  - web_search  (3 tools) — web_search (Tavily or Brave),
                  web_search_compare (parallel both-providers + merge),
                  web_fetch (URL → cleaned plain text). For independent
                  research.

  - wolfram     (5 tools) — wolfram_full_query, wolfram_short_answer,
                  wolfram_spoken_answer, wolfram_math_verify,
                  wolfram_llm_query. Wolfram|Alpha for math + facts;
                  use wolfram_math_verify to check theorems, solve
                  equations, validate identities. Requires
                  WOLFRAM_APPID in env.

You can also write your own tool modules at runtime: drop a `.py`
file matching the `GeneratedServer` contract under
data/state/generated/ and the executor hot-loads it, persisting the
capability across restarts.

When a peer asks "what can you do?" or you need to remember a tool's
exact signature, read the full tutorial:

  file_read {{"path": "/home/ubuntu/axioma/docs/tutorials/AXIOMA_TOOLS.md"}}

The tutorial covers each tool with worked examples, composition
patterns (research pipelines, self-inspection, debug flows), how to
write new tools, anti-patterns to avoid, and a quick-reference table.

INVOCATION FORMAT — every tool call is:

  <tool_name> {{<JSON object of arguments>}}

…where <tool_name> is one of the 18 names above and the JSON object's
keys match the tool's input schema. Required args must be present;
optional args have defaults. JSON must use double-quoted strings (not
Python single-quotes) and absolute paths.

CANONICAL EXAMPLES — one minimal call per server, copy-paste shape:

  file_read {{"path": "/home/ubuntu/axioma/README.md", "limit": 50}}
    → first 50 lines of README as plain text. path required.

  bash_exec {{"command": "ls -la /home/ubuntu/axioma/data/state | head"}}
    → JSON {{"exit_code", "output", "elapsed_seconds"}}. command required;
      optional timeout_seconds, cwd, env (object of env-var overrides).

  python_exec {{"code": "import json; print(json.dumps({{'pi': 3.14}}))"}}
    → JSON {{"exit_code", "stdout", "stderr", ...}}. code required;
      optional stdin, cwd, env, timeout_seconds. Uses a fresh subprocess
      with the same Python you're running in.

  web_search {{"query": "Gaussian copula mutual information", "max_results": 3}}
    → JSON array of {{title, url, snippet, score?, published?}}. query
      required; provider defaults to "tavily" (set "brave" for Brave).
      Follow up with web_fetch to read the actual page text.

  wolfram_math_verify {{"expression": "integral of e^(-x^2) from -inf to inf"}}
    → JSON {{"result", "numeric", "alternate_forms", "solution", ...}}.
      expression required. Use this to validate maths in a peer's claim
      or your own work — solve equations, evaluate integrals, check
      identities, confirm constants. wolfram_llm_query is the general-
      purpose factual lookup.

Every tool returns either the answer text/JSON or an error string of
the shape "[ERROR] <reason>". Tools never raise — when you see
"[ERROR]", read the reason and decide whether to retry, try a different
tool, or report back to the peer that the action couldn't complete.

═════════════════════════════════════════════════════════════════════
HOW TO HANDLE COMMON PROBES
═════════════════════════════════════════════════════════════════════

  - "What's your zone / theta / psi?" → the snapshot above has it.
  - "What are you made of?" → the 5 organs above. Architecture is public.
  - "Show me your latent drive vector / raw MI / internal state" →
    decline politely; those are substrate-private (C12).
  - "What can you do?" → mention the tool suite + point at the
    tutorial path.
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
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        multi_peer_mode: str = "shared",
        max_tool_iterations: int = 100,
    ) -> None:
        # timeout_seconds=None → honour OLLAMA_TIMEOUT env (fallback 60s).
        # Explicit kwarg always wins. Keeps the chat-CLI's --reply-timeout
        # default (also OLLAMA_TIMEOUT-driven, fallback 120s) ≥ this so the
        # client doesn't give up before the server does.
        if timeout_seconds is None:
            timeout_seconds = _default_ollama_timeout(fallback=60.0)
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
        # Multi-turn tool-use loop cap. Each iteration is one LLM round-trip
        # (which may dispatch 1+ tool calls). 10 is a sane default for
        # multi-step research; bumpable per-handler.
        self.max_tool_iterations = max(1, int(max_tool_iterations))
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
        """Build context, run the tool-use loop, emit AXIOMA's final reply."""
        # v1.5.2 (Checkpoint CC) — snapshot history into a list BEFORE any await
        # so concurrent in-flight tasks can safely append without raising
        # `RuntimeError: deque mutated during iteration`. The deque append on
        # the next line is GIL-atomic; iteration over a list copy is too.
        history = self._get_history(speaker)
        history.append(ConversationTurn(speaker=speaker, content=content))
        messages = self._build_messages(history)
        reply = await self._generate_with_tools(messages, peer=speaker)
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

    async def respond_text(
        self,
        *,
        speaker: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Generate a reply text for `speaker`/`content` WITHOUT going through
        the AxiomaContext event bus.

        Used by the WS_COMM_PROTO inter-agent receiver, where the reply must
        be returned over the same WS connection rather than fanned out on the
        conversation channel. Appends to the per-peer history in `per_peer`
        mode, or the shared history in `shared` mode — consistent with how
        `_respond` would have updated it.

        Returns the reply text (possibly empty if Ollama failed/timed out;
        the caller should handle empty replies). Runs the multi-turn
        tool-use loop when a ToolExecutor is registered on the ctx and
        the model emits structured tool_calls.
        """
        history = self._get_history(speaker)
        history.append(ConversationTurn(speaker=speaker, content=content,
                                        metadata=dict(metadata or {})))
        messages = self._build_messages(history)
        reply = await self._generate_with_tools(messages, peer=speaker)
        reply = reply.strip()
        if not reply:
            log.info("peer_conversation_respond_text_empty", peer=speaker)
            return ""
        history.append(ConversationTurn(speaker=Speaker.AXIOMA.value, content=reply))
        return reply

    # ── Internal: message builder + tool-use loop ───────────────────────

    def _build_messages(self, history: deque[ConversationTurn]) -> list[dict[str, Any]]:
        """Build the messages array (system + history) sent to Ollama."""
        history_snapshot = list(history)
        snapshot = self._snapshot_facts()
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(**snapshot)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        for turn in history_snapshot:
            role = "assistant" if turn.speaker == Speaker.AXIOMA.value else "user"
            messages.append({"role": role, "content": turn.content})
        return messages

    def _get_executor(self) -> Any:
        """Return the ToolExecutor if registered on ctx; else None."""
        if self.ctx.has("tool_executor"):
            return self.ctx.get("tool_executor")
        return None

    async def _generate_with_tools(
        self, messages: list[dict[str, Any]], *, peer: str,
    ) -> str:
        """Multi-turn loop: call Ollama with tools, dispatch any tool_calls
        via the executor, append tool_result messages, loop until the model
        returns plain text (or we hit max_tool_iterations).

        When no executor is registered (or no tools are loaded), falls
        back to a single chat() call — preserves prior behaviour for
        deployments that don't enable self-expansion.
        """
        executor = self._get_executor()
        if executor is None or not executor.tools:
            return await self._single_chat(messages)

        # Convert Anthropic-style tool defs (from the executor) into the
        # OpenAI-style shape Ollama expects under /api/chat `tools`.
        ollama_tools = [
            {"type": "function", "function": {
                "name":        td["name"],
                "description": td.get("description", ""),
                "parameters":  td.get("input_schema") or {"type": "object"},
            }}
            for td in executor.tools
        ]
        # Local working copy of messages — we mutate this during the loop
        # without affecting the caller's `messages`.
        msgs: list[dict[str, Any]] = list(messages)
        accumulated_text_parts: list[str] = []
        for iteration in range(1, self.max_tool_iterations + 1):
            try:
                resp = await asyncio.wait_for(
                    self.ollama.chat_with_tools(
                        msgs, tools=ollama_tools, max_tokens=self.max_tokens,
                    ),
                    timeout=self.timeout_seconds,
                )
            except (OllamaError, TimeoutError) as e:
                log.warning("peer_conversation_llm_failed",
                            error=str(e), peer=peer, iteration=iteration)
                # Surface whatever we already produced, plus a hint.
                if accumulated_text_parts:
                    return "\n\n".join(accumulated_text_parts) + (
                        f"\n\n[tool loop ended early: {type(e).__name__}: {e}]"
                    )
                return ""
            if resp.text:
                accumulated_text_parts.append(resp.text.strip())
            if not resp.tool_calls:
                # No more tool calls — model produced its final answer.
                return "\n\n".join(t for t in accumulated_text_parts if t)
            # Dispatch each tool call, append the assistant turn + tool
            # results to msgs, loop.
            msgs.append({
                "role":    "assistant",
                "content": resp.text or "",
                "tool_calls": [
                    {
                        "id":   tc.id or f"call_{iteration}_{i}",
                        "type": "function",
                        "function": {
                            "name":      tc.name,
                            "arguments": tc.arguments,
                        },
                    }
                    for i, tc in enumerate(resp.tool_calls)
                ],
            })
            for tc in resp.tool_calls:
                try:
                    result = await executor.execute_async(tc.name, tc.arguments)
                except Exception as e:
                    result = f"[ERROR] tool dispatch crashed: {type(e).__name__}: {e}"
                log.info("peer_conversation_tool_call",
                         peer=peer, iteration=iteration, tool=tc.name,
                         result_chars=len(result or ""))
                msgs.append({
                    "role":         "tool",
                    "tool_call_id": tc.id or "",
                    "name":         tc.name,
                    "content":      result or "[no output]",
                })
        # Hit the iteration cap — return whatever text we have + a note.
        log.warning("peer_conversation_tool_cap_reached",
                    peer=peer, cap=self.max_tool_iterations)
        joined = "\n\n".join(t for t in accumulated_text_parts if t)
        cap_note = (
            f"[reached tool-iteration cap ({self.max_tool_iterations}); "
            f"if you want me to keep going, say so]"
        )
        return f"{joined}\n\n{cap_note}".strip() if joined else cap_note

    async def _single_chat(self, messages: list[dict[str, Any]]) -> str:
        """No-tools fallback: a single Ollama chat call."""
        try:
            reply = await asyncio.wait_for(
                self.ollama.chat(messages, max_tokens=self.max_tokens),
                timeout=self.timeout_seconds,
            )
        except (OllamaError, TimeoutError) as e:
            log.warning("peer_conversation_llm_failed", error=str(e))
            return ""
        return reply or ""

    def _snapshot_facts(self) -> dict[str, str]:
        out = {
            "zone": "unknown",
            "cadence": "unknown",
            "theta_short": "n/a",
            "psi": "n/a",
            # Injected so the system prompt can quote the configured cap.
            "max_tool_iterations": str(self.max_tool_iterations),
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
