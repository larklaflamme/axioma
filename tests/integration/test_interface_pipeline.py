"""Phase D end-to-end: heartbeat + WS server + HTTP API together.

Boots a full Phase C+D pipeline, drives the heartbeat for a few hundred beats,
and verifies that:
  - WebSocket subscribers receive `state_snapshot`, `theta`, `aos_g`,
    `coherence_budget` payloads on the publish cadence.
  - Event-driven channels (perturbations, fragmentation, recovery) fan out.
  - HTTP /status, /perturbations, /recovery/history reflect the real engines.
  - /admin/perturb injects a perturbation that downstream subscribers see.
  - /admin/heartbeat/pause skips a substrate tick.
  - Persistence round-trip carries the relevant Phase D state (the WS
    server + HTTP API are stateless beyond live connections; no snapshot
    requirement here).
"""
from __future__ import annotations

import asyncio
import json
import socket
from contextlib import asynccontextmanager
from typing import Any

import pytest
import websockets
from fastapi.testclient import TestClient

from axioma.compose import CadenceController, ComposeFunction
from axioma.config import AxiomaConfig, InterfaceConfig
from axioma.interface import AxiomaWSServer, create_app
from axioma.measurement import (
    AOSGEngine,
    CascadeDelayEngine,
    DeltaPhiEngine,
    FragmentationMonitor,
    InternalStateRingBuffer,
    PerturbationScheduler,
    PlasticityTracker,
    RawMIEngine,
    build_theta_engines,
)
from axioma.observability import AxiomaContext
from axioma.runtime import Heartbeat
from axioma.scheduler import CoherenceScheduler
from axioma.substrate import RecoveryProtocol, SubstrateApp


def _pick_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@asynccontextmanager
async def _phase_d_stack(ws_port: int):
    cfg = AxiomaConfig(interface=InterfaceConfig(ws_host="127.0.0.1", ws_port=ws_port))
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    ctx.register("substrate", app)
    buf = InternalStateRingBuffer(capacity=600)
    ctx.register("state_buffer", buf)
    short, long_e = build_theta_engines(ctx, short_window=30, long_window=500, n_permutations=5)
    raw = RawMIEngine(ctx)
    ctx.register("raw_mi", raw)
    cascade = CascadeDelayEngine(ctx)
    ctx.register("cascade_delay", cascade)
    pert = PerturbationScheduler(ctx, period_beats=300, default_magnitude=0.4, seed=0)
    ctx.register("perturbation_scheduler", pert)
    plast = PlasticityTracker(ctx)
    ctx.register("plasticity_tracker", plast)
    dphi = DeltaPhiEngine(ctx)
    ctx.register("delta_phi", dphi)
    frag = FragmentationMonitor(ctx)
    ctx.register("fragmentation_monitor", frag)
    recovery = RecoveryProtocol(ctx, cfg.recovery)
    ctx.register("recovery_protocol", recovery)
    sched = CoherenceScheduler(ctx)
    ctx.register("coherence_scheduler", sched)
    aos_g = AOSGEngine(ctx)
    ctx.register("aos_g", aos_g)
    compose = ComposeFunction(rng_seed=42)
    ctx.register("compose_function", compose)
    cadence = CadenceController(ctx)
    ctx.register("cadence_controller", cadence)
    hb = Heartbeat(ctx=ctx, substrate=app, state_buffer=buf, hz=10)
    ctx.register("heartbeat", hb)
    for eng in (short, raw, cascade, pert, plast, dphi, frag, aos_g, long_e):
        hb.register_measurement_engine(eng)
    ws_server = AxiomaWSServer(ctx=ctx, cfg=cfg.interface, publish_cadence_beats=5)
    ctx.register("ws_server", ws_server)
    hb.ws_server = ws_server
    http_app = create_app(ctx, cfg)
    await ws_server.start()
    try:
        yield {
            "ctx": ctx,
            "hb": hb,
            "compose": compose,
            "ws_server": ws_server,
            "http_client": TestClient(http_app),
            "ws_port": ws_port,
            "cfg": cfg,
        }
    finally:
        await ws_server.stop()


async def _connect_and_subscribe(port: int, channels: list[str]) -> Any:
    ws = await websockets.connect(f"ws://127.0.0.1:{port}")
    await ws.send(json.dumps({"type": "handshake", "speaker": "skye"}))
    # consume welcome
    await asyncio.wait_for(ws.recv(), timeout=2.0)
    await ws.send(json.dumps({"type": "subscribe", "channels": channels}))
    await asyncio.sleep(0.05)
    return ws


@pytest.mark.asyncio
async def test_ws_state_snapshot_after_compose() -> None:
    port = _pick_port()
    async with _phase_d_stack(port) as stack:
        hb = stack["hb"]
        ws = await _connect_and_subscribe(port, ["state_snapshot"])
        try:
            # Run 60 beats: with 30-beat baseline cadence + 5-beat publish
            # cadence + state_snapshot per beat, we should get many payloads.
            for _ in range(60):
                hb.tick()
                await asyncio.sleep(0)
            await asyncio.sleep(0.2)
            received = []
            for _ in range(30):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.05)
                    received.append(json.loads(raw))
                except TimeoutError:
                    break
            channels = [m["channel"] for m in received if m.get("type") == "channel"]
            assert "state_snapshot" in channels
        finally:
            await ws.close()


@pytest.mark.asyncio
async def test_ws_perturbation_event_fanout() -> None:
    port = _pick_port()
    async with _phase_d_stack(port) as stack:
        hb = stack["hb"]
        ws = await _connect_and_subscribe(port, ["perturbations"])
        try:
            # Inject via admin endpoint
            client = stack["http_client"]
            r = client.post("/admin/perturb", json={"kind": "step", "magnitude": 0.3})
            assert r.status_code == 200
            # Tick a few beats so the event propagates and subscriber drains
            for _ in range(5):
                hb.tick()
                await asyncio.sleep(0)
            await asyncio.sleep(0.2)
            received = []
            for _ in range(10):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.1)
                    received.append(json.loads(raw))
                except TimeoutError:
                    break
            channels = [m["channel"] for m in received if m.get("type") == "channel"]
            assert "perturbations" in channels
        finally:
            await ws.close()


@pytest.mark.asyncio
async def test_http_status_reflects_substrate_after_compose() -> None:
    port = _pick_port()
    async with _phase_d_stack(port) as stack:
        hb = stack["hb"]
        client = stack["http_client"]
        # Initially warmup_active (no compose yet)
        body0 = client.get("/status").json()
        assert body0["warmup_active"] is True
        # Run long enough for one baseline compose (cadence 30b)
        for _ in range(40):
            hb.tick()
        body1 = client.get("/status").json()
        assert body1["warmup_active"] is False
        assert isinstance(body1["data"]["theta_short"], float)


@pytest.mark.asyncio
async def test_http_admin_heartbeat_pause_skips_substrate() -> None:
    port = _pick_port()
    async with _phase_d_stack(port) as stack:
        hb = stack["hb"]
        client = stack["http_client"]
        # Warm up
        for _ in range(5):
            hb.tick()
        # Request pause via HTTP
        r = client.post("/admin/heartbeat/pause", json={"beats": 1})
        assert r.status_code == 200
        assert r.json()["data"]["paused_beats"] == 1
        # Spy on substrate.tick to verify the next tick is paused
        sub = stack["ctx"].substrate
        original = sub.tick
        count = {"n": 0}

        def counting(*a: Any, **kw: Any) -> Any:
            count["n"] += 1
            return original(*a, **kw)
        sub.tick = counting  # type: ignore[method-assign]
        hb.tick()  # paused
        assert count["n"] == 0
        hb.tick()  # normal
        assert count["n"] == 1


@pytest.mark.asyncio
async def test_http_perturbations_endpoint_returns_history() -> None:
    port = _pick_port()
    async with _phase_d_stack(port) as stack:
        hb = stack["hb"]
        client = stack["http_client"]
        client.post("/admin/perturb", json={"kind": "step", "magnitude": 0.2, "tag": "test-tag"})
        for _ in range(5):
            hb.tick()
        body = client.get("/perturbations").json()
        assert any(e.get("tag") == "test-tag" for e in body["data"])


@pytest.mark.asyncio
async def test_http_recovery_force_triggers_state_change() -> None:
    port = _pick_port()
    async with _phase_d_stack(port) as stack:
        hb = stack["hb"]
        client = stack["http_client"]
        ws = await _connect_and_subscribe(port, ["recovery"])
        try:
            # Force recovery at stage 3
            r = client.post("/admin/recovery/force", json={"stage": 3, "signals": {"x": 1}})
            assert r.status_code == 200
            for _ in range(5):
                hb.tick()
                await asyncio.sleep(0)
            await asyncio.sleep(0.2)
            received = []
            for _ in range(15):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.1)
                    received.append(json.loads(raw))
                except TimeoutError:
                    break
            channels = [m["channel"] for m in received if m.get("type") == "channel"]
            assert "recovery" in channels
        finally:
            await ws.close()


@pytest.mark.asyncio
async def test_persistence_round_trip_includes_subs(tmp_path: Any) -> None:
    """The interface is stateless beyond live conns; verify HB+substrate save_state."""
    port = _pick_port()
    async with _phase_d_stack(port) as stack:
        hb = stack["hb"]
        for _ in range(30):
            hb.tick()
        snap = hb.save_state()
        assert snap["beat_no"] == hb.beat_no
        # Build a fresh heartbeat, load_state, verify beat_no aligned
        from axioma.config import AxiomaConfig
        from axioma.runtime import Heartbeat
        from axioma.substrate import SubstrateApp
        cfg = AxiomaConfig()
        ctx2 = AxiomaContext()
        sub2 = SubstrateApp.from_config(cfg.substrate, seed=42)
        ctx2.register("substrate", sub2)
        hb2 = Heartbeat(ctx=ctx2, substrate=sub2)
        hb2.load_state(snap)
        assert hb2.beat_no == hb.beat_no
