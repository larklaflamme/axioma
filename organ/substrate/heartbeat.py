"""Heartbeat loop ticking at 10 Hz per §3, §6.3.

Dispatches per beat:
  1. drive = dynamics.step()
  2. pre-update hooks (perturbation injection, etc.)
  3. each non-PNEUMA organ.update(beat_no, drive)
  4. PNEUMA.update + PNEUMA.integrate(others)
  5. measurement hook(s) (post-beat, pre-compose)
  6. optional compose() stub → buffer_depth bump + compose hook
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

import numpy as np

from ..config import HEARTBEAT_PERIOD_S, CONTINUOUS_EVERY
from .anima import Anima
from .dynamics import CoupledLatentDynamics
from .eidolon import Eidolon
from .mneme import Mneme
from .nous import Nous
from .pneuma import Pneuma


BeatHook = Callable[[int, str], Awaitable[None] | None]
ComposeHook = Callable[[int], Awaitable[None] | None]
PreUpdateHook = Callable[[int], None]


class Heartbeat:
    def __init__(
        self,
        dynamics: CoupledLatentDynamics | None = None,
        seed: int | None = None,
        compose_every: int = 30,
    ) -> None:
        self.dynamics = dynamics or CoupledLatentDynamics(seed=seed)
        self.anima = Anima(self.dynamics, seed=None if seed is None else seed + 1)
        self.eidolon = Eidolon(self.dynamics, seed=None if seed is None else seed + 2)
        self.mneme = Mneme(self.dynamics, seed=None if seed is None else seed + 3)
        self.nous = Nous(self.dynamics, seed=None if seed is None else seed + 4)
        self.pneuma = Pneuma(self.dynamics, seed=None if seed is None else seed + 5)
        self.organs = (self.anima, self.eidolon, self.mneme, self.nous, self.pneuma)
        self.beat_no = 0
        self.burst_remaining = 0
        self.compose_every = compose_every
        self._beat_hooks: list[BeatHook] = []
        self._compose_hooks: list[ComposeHook] = []
        self._pre_update_hooks: list[PreUpdateHook] = []
        self._running = False

    @property
    def non_pneuma(self):
        return (self.anima, self.eidolon, self.mneme, self.nous)

    def on_beat(self, hook: BeatHook) -> None:
        self._beat_hooks.append(hook)

    def on_compose(self, hook: ComposeHook) -> None:
        self._compose_hooks.append(hook)

    def on_pre_update(self, hook: PreUpdateHook) -> None:
        """Register a hook that fires BEFORE organ updates each tick.
        The hook receives the current beat_no and can modify organ state
        in-place (e.g. for perturbation injection)."""
        self._pre_update_hooks.append(hook)

    def trigger_burst(self, n_beats: int) -> None:
        self.burst_remaining = max(self.burst_remaining, n_beats)

    async def _emit_beat(self, mode: str) -> None:
        for h in self._beat_hooks:
            res = h(self.beat_no, mode)
            if asyncio.iscoroutine(res):
                await res

    async def _emit_compose(self) -> None:
        for h in self._compose_hooks:
            res = h(self.beat_no)
            if asyncio.iscoroutine(res):
                await res

    def tick(self) -> None:
        """Advance one beat synchronously (without sleeping). Returns nothing."""
        drive = self.dynamics.step()
        # Pre-update hooks fire before organ updates.
        for hook in self._pre_update_hooks:
            hook(self.beat_no)
        for organ in self.non_pneuma:
            organ.update(self.beat_no, drive)
        self.pneuma.update(self.beat_no, drive)
        self.pneuma.integrate(self.non_pneuma)
        self.beat_no += 1

    async def tick_async(self) -> None:
        self.tick()
        # Primary measurement hooks.
        emitted = False
        if (self.beat_no - 1) % CONTINUOUS_EVERY == 0:
            await self._emit_beat("continuous")
            emitted = True
        if self.burst_remaining > 0:
            if not emitted or self.burst_remaining != 0:  # always burst-mode mark
                await self._emit_beat("burst")
            self.burst_remaining -= 1
        # Compose stub.
        if self.beat_no % self.compose_every == 0:
            self.pneuma.push_compose()
            await self._emit_beat("event")  # state at compose/send boundary
            await self._emit_compose()
            self.pneuma.drain_compose()

    async def run(self, seconds: float) -> None:
        self._running = True
        deadline = time.monotonic() + seconds
        next_tick = time.monotonic()
        while self._running and time.monotonic() < deadline:
            await self.tick_async()
            next_tick += HEARTBEAT_PERIOD_S
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

    def stop(self) -> None:
        self._running = False
