"""AxiomaApp — production stack assembler.

Per IMPLEMENTATION_PLAN_v1.0.md §9 (process layout & lifecycle). The
test-time analogue is `tests/integration/phase_e_harness.build_phase_e_stack`;
this module is its production sibling, with WebSocket server, HTTP API,
registry client, and peer conversation handler wired in.

Public surface:
  AxiomaApp(cfg)
    .setup()            — async; constructs all engines + interface, optionally
                          loads recovery learner pretrain snapshot
    .run(seconds=, beats=)  — async; runs the heartbeat + serves WS/HTTP
    .shutdown()         — async; tears down WS server, registry client, etc.

Used by `python -m axioma` and any embedded use case that wants the full
production stack (vs the lighter test harness).

Lifecycle ordering at setup:
  1. SubstrateApp + InternalStateRingBuffer
  2. Measurement engines (theta_short, theta_long, raw_mi, cascade_delay,
     plasticity_tracker, perturbation_scheduler, delta_phi, fragmentation_monitor,
     aos_g, meta_cognition_loop, coherence_scheduler)
  3. RecoveryProtocol (substrate-owned)
  4. ComposeFunction + CadenceController
  5. Heartbeat
  6. AxiomaWSServer (binds to ws_host:ws_port)
  7. PeerConversationHandler (Ollama-backed; optional)
  8. RegistryClient (best-effort registration)
  9. HTTP app (FastAPI; lazy-binds via uvicorn in run() — not started in setup)

Lifecycle at shutdown:
  - Reverse order; each component .stop() / .detach() guarded by suppress(Exception)
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from typing import Any

import numpy as np

from ..compose import CadenceController, ComposeFunction
from ..config import AxiomaConfig
from ..infra.ollama import OllamaClient
from ..interface import AxiomaWSServer, PeerConversationHandler, RegistryClient, create_app
from ..measurement import (
    AOSGEngine,
    CascadeDelayEngine,
    DeltaPhiEngine,
    FragmentationMonitor,
    InternalStateRingBuffer,
    MetaCognitionLoop,
    ObserverMode,
    PerturbationScheduler,
    PlasticityTracker,
    RawMIEngine,
    build_theta_engines,
)
from ..observability import AxiomaContext, configure_logging, get_logger
from ..persistence.snapshot import SnapshotManager
from ..scheduler import CoherenceScheduler
from ..substrate import RecoveryProtocol, SubstrateApp
from .heartbeat import Heartbeat

log = get_logger(__name__)


class AxiomaApp:
    """Production stack assembler. One-instance-per-process by convention."""

    def __init__(
        self,
        cfg: AxiomaConfig,
        *,
        seed: int = 42,
        pretrain_snapshot_path: Path | None = None,
        with_ws_server: bool = True,
        with_http_api: bool = True,
        with_registry: bool = True,
        with_peer_conversation: bool = False,
    ) -> None:
        self.cfg = cfg
        self.seed = seed
        self.pretrain_snapshot_path = pretrain_snapshot_path
        self.with_ws_server = with_ws_server
        self.with_http_api = with_http_api
        self.with_registry = with_registry
        self.with_peer_conversation = with_peer_conversation
        # Components — populated by setup()
        self.ctx: AxiomaContext | None = None
        self.substrate: SubstrateApp | None = None
        self.heartbeat: Heartbeat | None = None
        self.ws_server: AxiomaWSServer | None = None
        self.http_server: Any | None = None  # uvicorn.Server
        self._http_serve_task: asyncio.Task[None] | None = None
        self.registry: RegistryClient | None = None
        self.peer_conversation: PeerConversationHandler | None = None
        self.tool_executor: Any = None  # set in setup() when tools enabled
        self.ollama: OllamaClient | None = None
        self._shutdown_event = asyncio.Event()
        self._setup_complete = False
        # v1.5.4 (Checkpoint EE): true idempotency guard. The prior
        # implementation re-ran every teardown step on second shutdown(),
        # masking real errors via `with suppress(Exception)`.
        self._shutdown_done = False

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def setup(self) -> None:
        """Assemble the full stack. Idempotent — safe to call once."""
        if self._setup_complete:
            return
        configure_logging(
            level=self.cfg.observability.log_level,
            json=self.cfg.observability.log_json,
        )
        log.info("axioma_setup_starting",
                 ws=self.with_ws_server, registry=self.with_registry,
                 peer_conv=self.with_peer_conversation)

        ctx = AxiomaContext()
        self.ctx = ctx

        # 1. Substrate + state buffer
        substrate = SubstrateApp.from_config(self.cfg.substrate, seed=self.seed)
        ctx.register("substrate", substrate)
        self.substrate = substrate
        buf = InternalStateRingBuffer(capacity=1200)
        ctx.register("state_buffer", buf)

        # 2. Measurement engines (read-only on substrate)
        short, long_e = build_theta_engines(
            ctx,
            short_window=self.cfg.measurement.theta_short_window,
            long_window=self.cfg.measurement.theta_long_window,
            n_permutations=self.cfg.measurement.n_permutations,
        )
        raw = RawMIEngine(ctx)
        ctx.register("raw_mi", raw)
        cascade = CascadeDelayEngine(ctx)
        ctx.register("cascade_delay", cascade)
        pert = PerturbationScheduler(
            ctx, period_beats=600,  # ARCH §6.4 default internal cadence
            default_magnitude=self.cfg.measurement.perturbation_default_magnitude,
            seed=self.seed,
        )
        ctx.register("perturbation_scheduler", pert)
        plast = PlasticityTracker(ctx)
        ctx.register("plasticity_tracker", plast)
        dphi = DeltaPhiEngine(ctx)
        ctx.register("delta_phi", dphi)
        frag = FragmentationMonitor(ctx)
        ctx.register("fragmentation_monitor", frag)
        aos_g = AOSGEngine(
            ctx,
            gap_weights=self.cfg.compose.aos_g_gap_weights,
            psi_alert_threshold=self.cfg.compose.psi_alert_threshold,
            aos_g_alert_threshold=self.cfg.compose.aos_g_alert_threshold,
            # v1.4.2 — opt-in auto-tuning of the alert threshold.
            auto_tune_alert_threshold=self.cfg.compose.aos_g_alert_threshold_auto_tune,
            auto_tune_ratio=self.cfg.compose.aos_g_alert_threshold_auto_tune_ratio,
            auto_tune_warmup_beats=self.cfg.compose.aos_g_alert_threshold_auto_tune_warmup_beats,
            auto_tune_recompute_period_beats=(
                self.cfg.compose.aos_g_alert_threshold_auto_tune_recompute_period_beats
            ),
            # v1.4.3 — opt-in per-component ψ thresholds.
            psi_per_component_thresholds=self.cfg.compose.psi_per_component_thresholds,
            # v1.4.1 — opt-in per-organ gap normalization.
            normalize_per_organ=self.cfg.compose.aos_g_normalize_per_organ,
            normalize_window_beats=self.cfg.compose.aos_g_normalize_per_organ_window_beats,
            normalize_min_samples=self.cfg.compose.aos_g_normalize_per_organ_min_samples,
        )
        ctx.register("aos_g", aos_g)
        observer_mode_str = self.cfg.meta_cognition.observer_mode
        observer_mode = (
            ObserverMode.EMBEDDED if observer_mode_str == "embedded"
            else ObserverMode.OBSERVER_ONLY
        )
        meta_cog = MetaCognitionLoop(ctx, observer_mode=observer_mode)
        ctx.register("meta_cognition_loop", meta_cog)

        # 3. Recovery (substrate-owned)
        # v1.5.1 (Checkpoint BB): seed the learner's exploration RNG from
        # self.seed so adoption decisions are reproducible across runs of
        # the same substrate seed. Without this, identical substrate seeds
        # produced wildly different adoption counts run-to-run because the
        # learner's exploration was non-deterministic.
        recovery_rng = np.random.default_rng(self.seed + 1)  # +1 to decorrelate from substrate
        recovery = RecoveryProtocol(ctx, self.cfg.recovery, rng=recovery_rng)
        ctx.register("recovery_protocol", recovery)
        if self.pretrain_snapshot_path is not None and self.pretrain_snapshot_path.exists():
            await self._load_pretrain_snapshot(recovery)

        # 4. Coherence scheduler
        sched = CoherenceScheduler(ctx)
        ctx.register("coherence_scheduler", sched)

        # 5. Compose function + cadence
        compose = ComposeFunction(rng_seed=self.seed)
        ctx.register("compose_function", compose)
        cadence = CadenceController(ctx)
        ctx.register("cadence_controller", cadence)

        # 6. Heartbeat (owns the substrate tick loop)
        snapshot_manager = SnapshotManager(root=Path(self.cfg.persistence.snapshot_root))
        hb = Heartbeat(
            ctx=ctx, substrate=substrate, state_buffer=buf,
            snapshot_manager=snapshot_manager,
            hz=self.cfg.runtime.heartbeat_hz,
            snapshot_period_beats=self.cfg.persistence.snapshot_period_beats,
        )
        ctx.register("heartbeat", hb)
        for eng in (short, raw, cascade, pert, plast, dphi, frag, aos_g, long_e, meta_cog):
            hb.register_measurement_engine(eng)
        self.heartbeat = hb

        # 7. WebSocket server
        if self.with_ws_server:
            ws = AxiomaWSServer(ctx=ctx, cfg=self.cfg.interface)
            ctx.register("ws_server", ws)
            hb.ws_server = ws
            self.ws_server = ws

        # 7.5. HTTP API (FastAPI app constructed here; uvicorn server started
        # in start_services). Builds the app even when serving is disabled —
        # tests + embedded use cases can grab `app.http_app` directly.
        if self.with_http_api:
            self._http_app = create_app(ctx, self.cfg)

        # 8. Peer conversation (optional; requires Ollama). Register on the
        # ctx so the WS server's inter-agent receiver (WS_COMM_PROTO) can
        # discover it via ctx.get("peer_conversation").
        if self.with_peer_conversation:
            self.ollama = OllamaClient(self.cfg.infra.ollama)

            # 8a. Self-expansion tool executor — share between the conversation
            # handler (for the tool-use loop) and any other consumer that
            # wants to dispatch tools in-process. Mirrors the shell's
            # construction. The handler picks it up via ctx.get("tool_executor").
            if self.cfg.interface.peer_conversation_tools_enabled:
                import os as _os
                from pathlib import Path as _Path

                from axioma.self_expansion import ToolExecutor
                from axioma.self_expansion.pre_built import (
                    BashExecServer,
                    FileSystemServer,
                    PythonExecServer,
                    WebSearchServer,
                    WolframServer,
                )
                project_root = _Path.cwd()
                generated_dir = _Path("data/state/generated").resolve()
                self.tool_executor = ToolExecutor(generated_dir=generated_dir)
                read_roots = [project_root]
                write_roots = [project_root / "data", generated_dir, _Path("/tmp")]
                self.tool_executor.register_server("filesystem",
                    FileSystemServer(read_roots=read_roots, write_roots=write_roots))
                self.tool_executor.register_server("bash", BashExecServer())
                self.tool_executor.register_server("python_exec", PythonExecServer())
                self.tool_executor.register_server("web_search", WebSearchServer(
                    tavily_api_key=_os.environ.get("TAVILY_API_KEY", ""),
                    brave_api_key=_os.environ.get("BRAVE_API_KEY", ""),
                ))
                self.tool_executor.register_server("wolfram", WolframServer(
                    appid=_os.environ.get("WOLFRAM_APPID", ""),
                ))
                self.tool_executor.restore_from_registry()
                ctx.register("tool_executor", self.tool_executor)
                log.info("axioma_tool_executor_ready",
                         tools=len(self.tool_executor.tool_names),
                         servers=self.tool_executor.server_names)

            self.peer_conversation = PeerConversationHandler(
                ctx=ctx,
                ollama=self.ollama,
                multi_peer_mode=self.cfg.interface.peer_conversation_multi_peer_mode,
                max_tool_iterations=self.cfg.interface.peer_conversation_max_tool_iterations,
            )
            self.peer_conversation.attach()
            ctx.register("peer_conversation", self.peer_conversation)

        # 9. Registry client (best-effort)
        if self.with_registry:
            self.registry = RegistryClient(ctx=ctx, cfg=self.cfg)

        self._setup_complete = True
        log.info("axioma_setup_complete",
                 components=ctx.list_components())

    async def _load_pretrain_snapshot(self, recovery: RecoveryProtocol) -> None:
        """Best-effort load of a learner pretrain snapshot."""
        import json
        if self.pretrain_snapshot_path is None:
            return
        try:
            body = json.loads(self.pretrain_snapshot_path.read_text())
        except Exception as e:
            log.warning("pretrain_snapshot_read_failed", error=str(e),
                        path=str(self.pretrain_snapshot_path))
            return
        snap = body.get("learner_snapshot")
        if not snap:
            log.warning("pretrain_snapshot_no_learner_field",
                        path=str(self.pretrain_snapshot_path))
            return
        with suppress(Exception):
            recovery.learner.load_dict(snap)
            log.info("pretrain_snapshot_loaded",
                     path=str(self.pretrain_snapshot_path),
                     adoptions=recovery.learner.adoptions_count)

    async def start_services(self) -> None:
        """Start WS server + HTTP API + registry."""
        if not self._setup_complete:
            raise RuntimeError("setup() must be called before start_services()")
        if self.ws_server is not None:
            await self.ws_server.start()
            log.info("ws_server_started_at", host=self.cfg.interface.ws_host,
                     port=self.cfg.interface.ws_port)
        if self.with_http_api:
            await self._start_http_server()
        if self.registry is not None:
            await self.registry.start()
            log.info("registry_started")

    async def _start_http_server(self) -> None:
        """Bind uvicorn to (http_host, http_port) and run in a background task.

        Uses uvicorn.Server (not uvicorn.run) so we can await graceful shutdown
        in shutdown() via server.should_exit = True."""
        import uvicorn
        config = uvicorn.Config(
            self._http_app,
            host=self.cfg.interface.http_host,
            port=self.cfg.interface.http_port,
            log_level="warning",  # quiet — structlog handles main logging
            access_log=False,
        )
        self.http_server = uvicorn.Server(config)
        self.http_server.config.load()
        self.http_server.lifespan = config.lifespan_class(config)
        # Run serve() in background so heartbeat is the main loop
        self._http_serve_task = asyncio.create_task(self.http_server.serve())
        # Wait briefly for the server to bind (uvicorn flips `started` async)
        for _ in range(50):  # up to 5s
            if getattr(self.http_server, "started", False):
                break
            await asyncio.sleep(0.1)
        log.info("http_server_started_at",
                 host=self.cfg.interface.http_host,
                 port=self.cfg.interface.http_port)

    async def run(self, *, seconds: float | None = None, beats: int | None = None) -> None:
        """Run the heartbeat until completion or shutdown."""
        if not self._setup_complete:
            await self.setup()
        await self.start_services()
        assert self.heartbeat is not None
        if seconds is None and beats is None:
            # Run until shutdown
            log.info("axioma_running_until_shutdown",
                     hz=self.cfg.runtime.heartbeat_hz)
            # Heartbeat.run accepts seconds= or beats=; for "run forever" we
            # use a very large beats count and rely on shutdown to interrupt.
            run_task = asyncio.create_task(self.heartbeat.run(beats=10_000_000))
            shutdown_task = asyncio.create_task(self._shutdown_event.wait())
            _done, pending = await asyncio.wait(
                [run_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await t
            # Stop the heartbeat loop if it's still running
            self.heartbeat.stop()
        else:
            log.info("axioma_running_bounded", seconds=seconds, beats=beats)
            await self.heartbeat.run(seconds=seconds, beats=beats)

    async def shutdown(self, *, ws_stop_timeout: float = 5.0,
                       peer_drain_timeout: float = 5.0) -> None:
        """Tear down HTTP server, WS server, registry, peer conversation,
        ollama client. Idempotent — second call is a no-op (returns
        immediately) regardless of why shutdown was triggered.

        v1.5.4 (Checkpoint EE) changes:
          - `_shutdown_done` flag short-circuits repeated calls.
          - `peer_conversation.wait_idle(timeout=...)` drains in-flight
            tasks BEFORE the WS server stops, so replies that fire late
            don't race against a dead WS layer.
          - `ws_server.stop()` is wrapped in `wait_for(timeout=...)`,
            matching the HTTP server's bounded-shutdown pattern.
        """
        if self._shutdown_done:
            return
        log.info("axioma_shutdown_starting")
        self._shutdown_event.set()
        if self.peer_conversation is not None:
            with suppress(Exception):
                self.peer_conversation.detach()
            # Drain in-flight responses so they don't fire AFTER the WS
            # server is torn down. wait_idle(None) blocks forever; we always
            # bound it. The drain timeout is small (5s default) so a wedged
            # Ollama call doesn't hold shutdown hostage.
            with suppress(asyncio.TimeoutError, Exception):
                await self.peer_conversation.wait_idle(timeout=peer_drain_timeout)
        if self.ollama is not None:
            with suppress(Exception):
                await self.ollama.close()
        if self.registry is not None:
            with suppress(Exception):
                await self.registry.stop()
        if self.http_server is not None:
            with suppress(Exception):
                self.http_server.should_exit = True
            if self._http_serve_task is not None and not self._http_serve_task.done():
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(self._http_serve_task, timeout=5.0)
        if self.ws_server is not None:
            with suppress(asyncio.TimeoutError, Exception):
                await asyncio.wait_for(
                    self.ws_server.stop(), timeout=ws_stop_timeout,
                )
        self._shutdown_done = True
        log.info("axioma_shutdown_complete")

    # ── Snapshot helpers ──────────────────────────────────────────────

    async def take_snapshot(self) -> None:
        """Force a snapshot on demand."""
        if self.heartbeat is None or self.heartbeat.snapshot_manager is None:
            log.warning("snapshot_requested_but_no_manager")
            return
        with suppress(Exception):
            await self.heartbeat.snapshot_manager.take_snapshot(
                beat_no=self.heartbeat.beat_no
            )


__all__ = ["AxiomaApp"]
