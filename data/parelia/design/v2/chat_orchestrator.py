"""
Multi-agent group chat orchestrator.

Design:
  - Centralized orchestrator owning two explicit FSMs:
      ChatState  : IDLE -> ACTIVE <-> PAUSED, ACTIVE <-> DRAINING -> RESOLVED -> (reset) IDLE
      AgentState : ELIGIBLE <-> SILENCED (per agent, human-controlled)
  - Bid/pass turn protocol: each round, eligible agents are polled in parallel
    with a cheap "bid or pass" call; the highest bidder takes the turn.
  - Epoch-based quiescence: every contribution / human message / async task
    result bumps `epoch` and invalidates recorded passes. The chat quiesces
    when every eligible agent has passed at the *current* epoch AND no async
    tasks are pending.
  - Human-only command channel: [FULL STOP], [PAUSE], [RESUME],
    [SILENCE:<id>], [RESUME:<id>] are parsed only from human-authenticated
    messages. Agent output is sanitized so agents structurally cannot emit
    commands.
  - Safety rails: max rounds, consecutive-speaker cap, sliding-window
    content-hash loop detection, budget circuit breaker.

No external dependencies; Python 3.11+.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Awaitable, Callable, Optional, Protocol

log = logging.getLogger("groupchat")


# --------------------------------------------------------------------------- #
# States and message model
# --------------------------------------------------------------------------- #

class ChatState(Enum):
    IDLE = auto()       # no live conversation
    ACTIVE = auto()     # turn loop running
    PAUSED = auto()     # human [PAUSE]; events buffer, no turns granted
    DRAINING = auto()   # all eligible agents passed, async tasks still pending
    RESOLVED = auto()   # natural end of life reached; about to reset


class AgentState(Enum):
    ELIGIBLE = auto()
    SILENCED = auto()   # human [SILENCE:<id>]; excluded from bidding AND quorum


class Role(Enum):
    HUMAN = auto()
    AGENT = auto()
    SYSTEM = auto()     # orchestrator-injected (task results, notices)


@dataclass(frozen=True)
class Message:
    sender: str
    role: Role
    content: str
    epoch: int
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Bid:
    agent_id: str
    score: int          # 0 == PASS, 1..100 == wants the turn
    intent: str = ""    # one-line statement of what the agent would do


@dataclass(frozen=True)
class TurnResult:
    content: Optional[str]                       # None == PASS at speak time
    # Optional long-running work the agent kicked off this turn (tests, docs).
    # The coroutine's string result is injected back as a SYSTEM message.
    spawned_task: Optional[Awaitable[str]] = None
    task_label: str = ""


class Agent(Protocol):
    """Adapter interface — wrap any LLM stack behind these two calls."""
    id: str

    async def bid(self, transcript: list[Message]) -> Bid:
        """Cheap call: score 0 (pass) .. 100, plus one-line intent."""
        ...

    async def take_turn(self, transcript: list[Message]) -> TurnResult:
        """Full call: produce a contribution, optionally spawn async work.
        May still return content=None (pass) if the bid proved stale."""
        ...


# --------------------------------------------------------------------------- #
# Human command grammar (orchestrator-level; never shown to agents)
# --------------------------------------------------------------------------- #

_CMD_FULL_STOP = re.compile(r"\[FULL STOP\]", re.IGNORECASE)
_CMD_PAUSE = re.compile(r"\[PAUSE\]", re.IGNORECASE)
_CMD_SILENCE = re.compile(r"\[SILENCE:(?P<id>[\w.\-]+)\]", re.IGNORECASE)
_CMD_RESUME_AGENT = re.compile(r"\[RESUME:(?P<id>[\w.\-]+)\]", re.IGNORECASE)
_CMD_RESUME_GLOBAL = re.compile(r"\[RESUME\]", re.IGNORECASE)  # no colon

# Anything that *looks* like a command, for sanitizing agent output.
_CMD_ANY = re.compile(
    r"\[(?:FULL STOP|PAUSE|RESUME(?::[\w.\-]+)?|SILENCE:[\w.\-]+)\]",
    re.IGNORECASE,
)


def sanitize_agent_output(text: str) -> str:
    """Defense in depth: agents can never emit a live command token.
    Matches are neutralized (zero-width-broken) rather than deleted, so the
    transcript still shows what the agent attempted."""
    def neutralize(m: re.Match) -> str:
        log.warning("agent output contained command-like token %r; neutralized", m.group(0))
        return m.group(0).replace("[", "[\u200b")  # '[‍FULL STOP]' renders, never parses
    return _CMD_ANY.sub(neutralize, text)


# --------------------------------------------------------------------------- #
# Safety rails configuration
# --------------------------------------------------------------------------- #

@dataclass
class Limits:
    max_rounds: int = 60                  # hard ceiling on turn-grant rounds
    max_consecutive_turns: int = 3        # per-agent dominance cap
    loop_window: int = 8                  # sliding window for duplicate detection
    loop_dup_threshold: int = 2           # >N near-duplicates in window => loop
    budget_tokens: Optional[int] = None   # circuit breaker (None = unlimited)


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #

class GroupChatOrchestrator:
    def __init__(
        self,
        agents: list[Agent],
        limits: Limits = Limits(),
        on_resolved: Optional[Callable[[list[Message]], Awaitable[None]]] = None,
        silence_survives_reset: bool = True,
    ) -> None:
        self.agents: dict[str, Agent] = {a.id: a for a in agents}
        self.agent_state: dict[str, AgentState] = {
            a.id: AgentState.ELIGIBLE for a in agents
        }
        self.limits = limits
        self.on_resolved = on_resolved          # summary/archival hook
        self.silence_survives_reset = silence_survives_reset

        self.state = ChatState.IDLE
        self.transcript: list[Message] = []
        self.epoch = 0
        # agent_id -> epoch at which it last PASSed (quiescence bookkeeping)
        self._passed_at: dict[str, int] = {}
        self._pending_tasks: set[asyncio.Task] = set()
        self._rounds = 0
        self._last_speaker: Optional[str] = None
        self._consecutive = 0
        self._recent_hashes: deque[str] = deque(maxlen=limits.loop_window)
        self._tokens_spent = 0
        self._wake = asyncio.Event()            # signals the loop on any event
        self._stop = False

    # ------------------------------ events -------------------------------- #

    def post_human_message(self, sender: str, text: str) -> None:
        """Entry point for authenticated human input. Commands are executed
        and stripped; any remaining text becomes a normal chat message."""
        remainder = self._execute_commands(text)
        if remainder.strip():
            self._append(Message(sender, Role.HUMAN, remainder.strip(), self.epoch))
            self._bump_epoch()
            if self.state == ChatState.IDLE:
                self._transition(ChatState.ACTIVE)
            elif self.state == ChatState.DRAINING:
                self._transition(ChatState.ACTIVE)
        self._wake.set()

    def _execute_commands(self, text: str) -> str:
        if _CMD_FULL_STOP.search(text):
            log.info("[FULL STOP] received — aborting and resetting")
            self._stop = True
            text = _CMD_FULL_STOP.sub("", text)

        for m in _CMD_SILENCE.finditer(text):
            aid = self._resolve_agent(m.group("id"))
            if aid:
                self.agent_state[aid] = AgentState.SILENCED
                self._passed_at.pop(aid, None)
                log.info("agent %s silenced", aid)
        text = _CMD_SILENCE.sub("", text)

        for m in _CMD_RESUME_AGENT.finditer(text):
            aid = self._resolve_agent(m.group("id"))
            if aid:
                self.agent_state[aid] = AgentState.ELIGIBLE
                log.info("agent %s resumed", aid)
        text = _CMD_RESUME_AGENT.sub("", text)

        if _CMD_PAUSE.search(text):
            if self.state in (ChatState.ACTIVE, ChatState.DRAINING):
                self._transition(ChatState.PAUSED)
            text = _CMD_PAUSE.sub("", text)

        if _CMD_RESUME_GLOBAL.search(text):   # checked last: [RESUME:<id>] already consumed
            if self.state == ChatState.PAUSED:
                self._transition(ChatState.ACTIVE)
            text = _CMD_RESUME_GLOBAL.sub("", text)

        return text

    def _resolve_agent(self, raw: str) -> Optional[str]:
        if raw in self.agents:
            return raw
        log.warning("command referenced unknown agent id %r — ignored", raw)
        return None

    # --------------------------- async task plumbing ---------------------- #

    def register_task(self, coro: Awaitable[str], label: str) -> None:
        """Track agent-spawned work (tests, document builds...)."""
        task = asyncio.ensure_future(coro)
        self._pending_tasks.add(task)

        def _done(t: asyncio.Task) -> None:
            self._pending_tasks.discard(t)
            try:
                result = t.result()
            except Exception as exc:  # noqa: BLE001 — surface failures to the chat
                result = f"task '{label}' failed: {exc!r}"
            self._append(Message("orchestrator", Role.SYSTEM,
                                 f"[task:{label}] {result}", self.epoch))
            self._bump_epoch()
            if self.state == ChatState.DRAINING:
                self._transition(ChatState.ACTIVE)
            self._wake.set()

        task.add_done_callback(_done)

    # ------------------------------ main loop ----------------------------- #

    async def run(self) -> None:
        """Drive the conversation until RESOLVED (or aborted), then reset."""
        while True:
            if self._stop:
                await self._resolve_and_reset(aborted=True)
                return

            if self.state in (ChatState.IDLE, ChatState.PAUSED):
                await self._wait_for_event()
                continue

            if self.state == ChatState.DRAINING:
                if not self._pending_tasks:
                    await self._resolve_and_reset(aborted=False)
                    return
                await self._wait_for_event()
                continue

            # --- ACTIVE: one round = one bid phase + at most one turn ----- #
            if self._rounds >= self.limits.max_rounds:
                log.warning("max_rounds hit — forcing resolution")
                self._transition(ChatState.DRAINING)
                continue
            if (self.limits.budget_tokens is not None
                    and self._tokens_spent >= self.limits.budget_tokens):
                log.warning("budget exhausted — forcing resolution")
                self._transition(ChatState.DRAINING)
                continue

            winner = await self._bid_phase()
            if winner is None:
                # Every eligible agent passed at the current epoch.
                self._transition(ChatState.DRAINING)
                continue

            await self._speak_phase(winner)

    async def _bid_phase(self) -> Optional[str]:
        eligible = [
            aid for aid, st in self.agent_state.items()
            if st == AgentState.ELIGIBLE
        ]
        if not eligible:
            return None  # everyone silenced => quiescent by definition

        # Skip agents whose PASS is still valid for this epoch.
        to_poll = [a for a in eligible if self._passed_at.get(a) != self.epoch]
        if not to_poll:
            return None

        self._rounds += 1
        bids = await asyncio.gather(
            *(self.agents[a].bid(self.transcript) for a in to_poll),
            return_exceptions=True,
        )

        best: Optional[Bid] = None
        for agent_id, bid in zip(to_poll, bids):
            if isinstance(bid, BaseException):
                log.error("bid from %s raised %r — treating as PASS", agent_id, bid)
                self._passed_at[agent_id] = self.epoch
                continue
            if bid.score <= 0:
                self._passed_at[agent_id] = self.epoch
                continue
            score = bid.score
            # Dominance cap: damp the previous speaker's bid.
            if (agent_id == self._last_speaker
                    and self._consecutive >= self.limits.max_consecutive_turns):
                score = 0
                self._passed_at[agent_id] = self.epoch
                continue
            if best is None or score > best.score:
                best = Bid(agent_id, score, bid.intent)

        # If everyone we polled passed, check the full quorum.
        if best is None:
            all_passed = all(
                self._passed_at.get(a) == self.epoch for a in eligible
            )
            return None if all_passed else None  # both routes: no speaker
        return best.agent_id

    async def _speak_phase(self, agent_id: str) -> None:
        result = await self.agents[agent_id].take_turn(self.transcript)

        if result.spawned_task is not None:
            self.register_task(result.spawned_task, result.task_label or agent_id)

        if result.content is None:
            self._passed_at[agent_id] = self.epoch
            return

        content = sanitize_agent_output(result.content)

        # Loop detection: near-duplicate contributions in the recent window.
        digest = hashlib.sha256(content.strip().lower().encode()).hexdigest()
        if self._recent_hashes.count(digest) >= self.limits.loop_dup_threshold:
            log.warning("loop detected (duplicate content from %s) — "
                        "recording as PASS", agent_id)
            self._passed_at[agent_id] = self.epoch
            return
        self._recent_hashes.append(digest)

        self._tokens_spent += max(1, len(content) // 4)  # crude estimate; swap in real usage
        self._append(Message(agent_id, Role.AGENT, content, self.epoch))
        self._bump_epoch()  # invalidates all recorded passes

        if agent_id == self._last_speaker:
            self._consecutive += 1
        else:
            self._last_speaker, self._consecutive = agent_id, 1

    # ------------------------------ lifecycle ----------------------------- #

    async def _resolve_and_reset(self, aborted: bool) -> None:
        self._transition(ChatState.RESOLVED)
        note = "aborted by [FULL STOP]" if aborted else "natural quiescence"
        self._append(Message("orchestrator", Role.SYSTEM,
                             f"conversation resolved ({note})", self.epoch))
        if self.on_resolved is not None:
            await self.on_resolved(list(self.transcript))  # summarize / archive
        self._reset()

    def _reset(self) -> None:
        self.transcript.clear()
        self.epoch = 0
        self._passed_at.clear()
        self._rounds = 0
        self._last_speaker = None
        self._consecutive = 0
        self._recent_hashes.clear()
        self._tokens_spent = 0
        self._stop = False
        for t in self._pending_tasks:
            t.cancel()
        self._pending_tasks.clear()
        if not self.silence_survives_reset:
            for aid in self.agent_state:
                self.agent_state[aid] = AgentState.ELIGIBLE
        self._transition(ChatState.IDLE)

    # ------------------------------ helpers ------------------------------- #

    def _append(self, msg: Message) -> None:
        self.transcript.append(msg)

    def _bump_epoch(self) -> None:
        self.epoch += 1
        self._passed_at.clear()

    def _transition(self, new: ChatState) -> None:
        log.info("chat state: %s -> %s", self.state.name, new.name)
        self.state = new
        self._wake.set()

    async def _wait_for_event(self) -> None:
        self._wake.clear()
        await self._wake.wait()