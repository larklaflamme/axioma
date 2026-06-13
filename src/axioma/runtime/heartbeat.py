"""Heartbeat — 10 Hz async loop driving the substrate + measurement engines.

Per IMPLEMENTATION_PLAN_v1.0.md §5.0 (heartbeat tick sequence).

Phase A.2: substrate-only (steps 1, 2, 9 of §5.0).
Phase B.1 (this revision): adds step 3 — high-priority measurement engines
(θ_short, raw_mi, cascade_delay) via the `should_run` pattern, plus state-buffer
push between substrate and measurement.

Steps 4-8 (compose / θ_long / ΔΦ / scheduler / meta / interface) are still
stubbed; they're added in Phase B.2/B.3/C/D as their engines come online.

The substrate is ALWAYS run (step 2 — non-negotiable). Measurement engines
are added to `self.measurement_engines` in registration order; each is asked
`should_run()` before `compute()`.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ..observability import (
    BEAT_DURATION_S,
    AxiomaContext,
    bind_beat,
    get_logger,
    unbind_beat,
)
from ..persistence.snapshot import SnapshotManager
from ..schemas import InternalState
from ..substrate import SubstrateApp

log = get_logger(__name__)


class Heartbeat:
    """Async heartbeat loop. Owns SubstrateApp; can optionally own a
    SnapshotManager for periodic snapshots and a list of measurement engines.

    Usage:
        hb = Heartbeat(ctx=ctx, substrate=app, hz=10)
        # Optional: wire engines via register_measurement_engine
        hb.register_measurement_engine(theta_short)
        await hb.run(seconds=10)  # ticks for 10 wall-clock seconds
    """

    name = "heartbeat"
    schema_version = 1

    def __init__(
        self,
        *,
        ctx: AxiomaContext,
        substrate: SubstrateApp,
        snapshot_manager: SnapshotManager | None = None,
        state_buffer: Any | None = None,
        hz: int = 10,
        snapshot_period_beats: int = 600,
    ) -> None:
        if hz <= 0:
            raise ValueError(f"hz must be positive, got {hz}")
        self.ctx = ctx
        self.substrate = substrate
        self.snapshot_manager = snapshot_manager
        self.state_buffer = state_buffer  # InternalStateRingBuffer or None
        self.hz = hz
        self.period_s = 1.0 / hz
        self.snapshot_period_beats = snapshot_period_beats
        self.beat_no = substrate.beat_no  # resume from substrate's snapshot if loaded
        self._running = False
        self._snapshot_task: asyncio.Task[Any] | None = None
        # Measurement engines registered in `should_run` order. Heartbeat asks
        # each one before invoking compute. Per IMPLEMENTATION_PLAN §3.5.
        self.measurement_engines: list[Any] = []
        # Stage-4 emergency pause: number of beats to skip the substrate tick.
        # Each pause()-marked beat increments beat_no and runs persistence, but
        # skips substrate / measurement / compose. Per ARCH §4.9.
        self._pause_beats_remaining: int = 0
        # Zone classifier hysteresis state (Phase F fix)
        from ..schemas import Zone
        self._prev_zone: Zone = Zone.IDLE
        self._prev_zone_entered_beat: int = 0

    def pause(self, *, beats: int = 1) -> None:
        """Request the heartbeat to skip the substrate tick for N beats.

        Used by RecoveryProtocol at Stage-4 entry per ARCH §4.9. The pause is
        cumulative — calling pause(beats=2) twice queues 4 paused beats.
        """
        if beats <= 0:
            return
        self._pause_beats_remaining += int(beats)
        log.warning("heartbeat_pause_requested", beats=beats, queued=self._pause_beats_remaining)

    def register_measurement_engine(self, engine: Any) -> None:
        """Add a measurement engine to the tick sequence.

        Engines are called in registration order. Each is asked
        engine.should_run(beat_no, coherence_budget) before engine.compute().
        Per IMPLEMENTATION_PLAN §3.5 + §5.0 step 3.
        """
        self.measurement_engines.append(engine)
        log.debug("heartbeat_engine_registered", engine=engine.name)

    def _maybe_compose(self, beat_no: int, internal: InternalState) -> None:
        """Step 4 per §5.0 — adaptive-cadence compose.

        If both CadenceController and ComposeFunction are registered, ask the
        controller whether to compose this beat. If yes:
          - extract θ_short live from theta_short engine
          - extract eidolon_coh live from internal.eidolon.self_coherence (P13)
          - call compose; ExternalState is memoized on compose_function
            (consumed by AOSGEngine + Phase D publishers)
          - classify Zone from current measurement state (Phase F fix —
            previously ExternalState.zone was always IDLE)
          - mark PNEUMA's compose buffer (push_compose)
        """
        if not (self.ctx.has("compose_function") and self.ctx.has("cadence_controller")):
            return
        cadence = self.ctx.get("cadence_controller")
        if not cadence.should_compose(beat_no):
            return
        compose = self.ctx.get("compose_function")
        # θ_short: live from engine (None if not warm yet)
        theta_short = 0.0
        if self.ctx.has("theta_short"):
            cv = self.ctx.get("theta_short").current_value()
            if cv is not None:
                theta_short = float(cv.theta)
        # eidolon_coh: extracted live from current internal (per P13)
        try:
            external = compose.compose(internal, theta_short=theta_short)
            # Attach cadence label
            external.cadence = cadence.current_cadence(beat_no)
            # Wire psi from AOS-G's cached reading (1-beat lag, acceptable
            # for a noise-robust integrity signal — compose runs before
            # AOS-G in the same beat per the ordering invariant above).
            if self.ctx.has("aos_g"):
                aos_g_val = self.ctx.get("aos_g").current_value()
                if aos_g_val is not None:
                    psi_val = getattr(aos_g_val, "psi", None)
                    if psi_val is not None:
                        external.psi = float(psi_val)
            # Phase F fix — wire Zone classifier into the compose path.
            self._classify_and_attach_zone(external, theta_short)
            # PNEUMA's buffer_depth gets bumped per compose event
            self.substrate.pneuma.push_compose()
        except Exception:
            log.exception("compose_failed_in_heartbeat", beat_no=beat_no)

    def _classify_and_attach_zone(self, external: Any, theta_short: float) -> None:
        """Set external.zone via classify_zone() using current measurements.

        Idempotent on failure: leaves zone at its default (IDLE) if any
        measurement engine is missing or fails. beats_in_zone counts
        SUBSTRATE beats (not compose events) per ARCH §5.2."""
        try:
            from ..compose.zone import classify_zone
            delta_phi_s1: float | None = None
            delta_phi_s2: float | None = None
            delta_phi_s3: float = 0.0
            cascade_delay_beats: float = 0.0
            fragmentation_stage: int = 0
            if self.ctx.has("delta_phi"):
                dp = self.ctx.get("delta_phi").current_value()
                if dp is not None:
                    delta_phi_s1 = getattr(dp, "s1_peak_delta_theta", None)
                    delta_phi_s2 = getattr(dp, "s2_recovery_beats", None)
                    delta_phi_s3 = float(getattr(dp, "s3_context_variance", 0.0))
            if self.ctx.has("cascade_delay"):
                cd = self.ctx.get("cascade_delay").current_value()
                if cd is not None and getattr(cd, "valid", False):
                    cascade_delay_beats = float(getattr(cd, "cascade_delay_beats", 0.0))
            if self.ctx.has("fragmentation_monitor"):
                fr = self.ctx.get("fragmentation_monitor").current_value()
                if fr is not None:
                    fragmentation_stage = int(getattr(fr, "current_stage", 0))
            beats_in_zone = self.beat_no - self._prev_zone_entered_beat
            zone = classify_zone(
                theta_short=theta_short,
                delta_phi_s1=delta_phi_s1,
                delta_phi_s2=delta_phi_s2,
                delta_phi_s3=delta_phi_s3,
                cascade_delay_beats=cascade_delay_beats,
                fragmentation_stage=fragmentation_stage,
                prev_zone=self._prev_zone,
                beats_in_zone=beats_in_zone,
            )
            external.zone = zone
            # Update hysteresis state (counts substrate beats, not composes)
            if zone != self._prev_zone:
                self._prev_zone = zone
                self._prev_zone_entered_beat = self.beat_no
        except Exception:
            log.exception("zone_classify_failed")

    def _coherence_budget(self) -> float:
        """Best-effort read of the current coherence budget for throttle decisions.

        Returns 1.0 (no throttle) if PNEUMA hasn't rendered yet. Prefers
        the CoherenceScheduler's cached value if available (it's updated
        each tick before measurement engines run).
        """
        if self.ctx.has("coherence_scheduler"):
            try:
                return float(self.ctx.coherence_scheduler.current_budget())
            except Exception:
                pass
        try:
            return float(self.substrate.pneuma.render().coherence_budget)
        except Exception:
            return 1.0

    # ── Single-tick path (synchronous; used by tests + run loop) ─────────

    def tick(self) -> InternalState:
        """Run one beat synchronously (no sleeping). Returns the new InternalState.

        This is the test-friendly path: tests can call hb.tick() in a tight loop
        without involving asyncio timing.
        """
        ts = time.time()
        # Stage-4 emergency pause path: skip substrate / measurement / compose
        # but still advance beat_no and run persistence so downstream timing
        # invariants hold. RecoveryProtocol.tick still runs so the recovery
        # state machine continues to count down.
        if self._pause_beats_remaining > 0:
            self._pause_beats_remaining -= 1
            bind_beat(self.beat_no)
            try:
                if self.ctx.has("recovery_protocol"):
                    try:
                        self.ctx.recovery_protocol.tick(self.beat_no)
                    except Exception:
                        log.exception("recovery_tick_failed_in_pause")
                log.info("heartbeat_paused_beat", beat_no=self.beat_no)
                last_internal = self.substrate.last_internal()
                self.beat_no += 1
                # During a Stage-4 pause we may not yet have a rendered state
                # (pause before first tick). In that case run the substrate
                # exactly once so the contract "tick returns InternalState"
                # is preserved; this is a single-frame slip but keeps the
                # async run loop's typing honest.
                if last_internal is None:
                    return self.substrate.tick(beat_no=self.beat_no - 1, timestamp=ts)
                return last_internal
            finally:
                unbind_beat()
        with BEAT_DURATION_S.time():
            bind_beat(self.beat_no)
            try:
                # Step 2a: RecoveryProtocol.tick — decrement recovery countdown if active
                # (per §5.0 step 2a/2b — recovery is the only substrate-mutating loop)
                if self.ctx.has("recovery_protocol"):
                    try:
                        self.ctx.recovery_protocol.tick(self.beat_no)
                    except Exception:
                        log.exception("recovery_tick_failed")
                # Step 2: substrate (CRITICAL — always runs)
                internal = self.substrate.tick(beat_no=self.beat_no, timestamp=ts)
                # Step 2.5: feed the shared state buffer (consumed by step 3 engines)
                if self.state_buffer is not None:
                    self.state_buffer.push(internal)
                # Step 2.7: CoherenceScheduler.tick — refreshes budget cache
                # + accumulates E13 effectiveness windows. Always runs (it's
                # the source of throttle decisions for measurement engines).
                if self.ctx.has("coherence_scheduler"):
                    try:
                        self.ctx.coherence_scheduler.tick(self.beat_no)
                    except Exception:
                        log.exception("coherence_scheduler_tick_failed")
                # Step 4 (run BEFORE step 3 in our implementation): compose on
                # adaptive cadence so AOSGEngine in step 3 sees a fresh
                # (internal, external) pair from the same beat. The architecture's
                # step numbering is a guideline; the loadbearing invariant is
                # "compose happens after substrate tick + before AOS-G reads the
                # gap." We satisfy that by composing here, then running engines.
                self._maybe_compose(self.beat_no, internal)
                # Step 3: high-priority measurement engines (per §5.0)
                # Each engine: should_run → compute (with measure_engine timing)
                budget = self._coherence_budget()
                for engine in self.measurement_engines:
                    try:
                        engine.run_if_due(self.beat_no, budget)
                    except Exception:
                        log.exception("engine_tick_failed", engine=engine.name)
                # Step 8 (external interface push) is no longer a heartbeat
                # concern: Axioma is now a *client* of The Agora (see
                # interface/agora_bridge.py), which runs its own asyncio loop and
                # reacts to inbound messages rather than being driven per-beat.
                # Substrate telemetry is no longer streamed over a local socket.
                # Step 9: persistence (every snapshot_period_beats)
                if self.snapshot_manager is not None and self.beat_no > 0:
                    if self.beat_no % self.snapshot_period_beats == 0:
                        # Fire as background task — does not block the next tick
                        self._snapshot_task = asyncio.get_event_loop().create_task(
                            self._take_snapshot()
                        )
                self.beat_no += 1
                return internal
            finally:
                unbind_beat()

    async def tick_async(self) -> InternalState:
        """Async variant — currently identical to tick() but exists so future
        measurement engines that need awaits can hook in without restructuring
        the call site."""
        return self.tick()

    async def _take_snapshot(self) -> None:
        if self.snapshot_manager is None:
            return
        try:
            await self.snapshot_manager.take_snapshot(beat_no=self.beat_no - 1)
        except Exception:
            log.exception("snapshot_background_failed", beat_no=self.beat_no - 1)

    # ── Run loop ─────────────────────────────────────────────────────────

    async def run(self, *, seconds: float | None = None, beats: int | None = None) -> None:
        """Run for either a duration (seconds) OR a fixed number of beats.

        Exactly one of seconds / beats must be provided.
        """
        if (seconds is None) == (beats is None):
            raise ValueError("Provide exactly one of seconds= or beats=")
        self._running = True
        target_end_beat = (
            self.beat_no + beats if beats is not None else None
        )
        deadline = (
            time.monotonic() + seconds if seconds is not None else None
        )
        next_tick = time.monotonic()
        log.info(
            "heartbeat_started",
            hz=self.hz,
            start_beat=self.beat_no,
            seconds=seconds,
            beats=beats,
        )
        try:
            while self._running:
                if deadline is not None and time.monotonic() >= deadline:
                    break
                if target_end_beat is not None and self.beat_no >= target_end_beat:
                    break

                await self.tick_async()
                next_tick += self.period_s
                sleep_for = next_tick - time.monotonic()
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                else:
                    # Behind schedule — log overshoot per §6.3 variable-beat policy
                    if -sleep_for > 0.1:
                        log.info(
                            "beat_overshoot",
                            beat_no=self.beat_no - 1,
                            behind_seconds=-sleep_for,
                        )
        finally:
            # Wait for any in-flight snapshot to land before returning
            if self._snapshot_task is not None and not self._snapshot_task.done():
                await self._snapshot_task
            log.info("heartbeat_stopped", final_beat=self.beat_no)

    def stop(self) -> None:
        """Request the run loop to exit on the next iteration."""
        self._running = False

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {"beat_no": self.beat_no, "hz": self.hz}

    def load_state(self, snapshot: dict[str, Any]) -> None:
        self.beat_no = int(snapshot.get("beat_no", 0))
        # hz is config-driven; don't override at load
