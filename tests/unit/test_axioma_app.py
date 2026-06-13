"""AxiomaApp — production stack lifecycle tests.

These tests boot a real AxiomaApp instance (mostly without WS/registry to
avoid binding ports). The harness-equivalent is tested separately via the
phase_e_harness; this tests the production assembler + lifecycle.
"""
from __future__ import annotations

import pytest

from axioma.config import AxiomaConfig
from axioma.runtime.app import AxiomaApp


@pytest.mark.asyncio
async def test_setup_assembles_full_stack() -> None:
    """setup() registers every expected component in the context."""
    cfg = AxiomaConfig()
    app = AxiomaApp(cfg, with_agora=False, with_registry=False)
    await app.setup()
    assert app.ctx is not None
    expected = {
        "substrate", "state_buffer", "theta_short", "theta_long",
        "raw_mi", "cascade_delay", "perturbation_scheduler", "plasticity_tracker",
        "delta_phi", "fragmentation_monitor", "aos_g", "meta_cognition_loop",
        "recovery_protocol", "coherence_scheduler", "compose_function",
        "cadence_controller", "heartbeat",
    }
    registered = set(app.ctx.list_components())
    missing = expected - registered
    assert not missing, f"missing components: {missing}"
    await app.shutdown()


@pytest.mark.asyncio
async def test_setup_is_idempotent() -> None:
    cfg = AxiomaConfig()
    app = AxiomaApp(cfg, with_agora=False, with_registry=False)
    await app.setup()
    initial_components = set(app.ctx.list_components())  # type: ignore[union-attr]
    await app.setup()  # second call should be a no-op
    assert set(app.ctx.list_components()) == initial_components  # type: ignore[union-attr]
    await app.shutdown()


@pytest.mark.asyncio
async def test_run_bounded_beats() -> None:
    cfg = AxiomaConfig()
    # This test exercises bounded-beats execution, not the HTTP server — keep it
    # hermetic (no default-port bind, so it doesn't collide with a live instance).
    app = AxiomaApp(cfg, with_agora=False, with_registry=False, with_http_api=False)
    try:
        await app.run(beats=20)
        assert app.heartbeat is not None
        assert app.heartbeat.beat_no >= 20
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_aos_g_picks_up_config_gap_weights() -> None:
    """If cfg.compose.aos_g_gap_weights is set, AOSGEngine uses it."""
    from axioma.measurement.aos_g_engine import PNEUMA_WEIGHTED_GAP_WEIGHTS
    cfg = AxiomaConfig()
    object.__setattr__(cfg.compose, "aos_g_gap_weights", PNEUMA_WEIGHTED_GAP_WEIGHTS)
    app = AxiomaApp(cfg, with_agora=False, with_registry=False)
    await app.setup()
    try:
        aos_g = app.ctx.get("aos_g")  # type: ignore[union-attr]
        assert aos_g.gap_weights == PNEUMA_WEIGHTED_GAP_WEIGHTS
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_aos_g_threshold_from_config() -> None:
    cfg = AxiomaConfig()
    object.__setattr__(cfg.compose, "aos_g_alert_threshold", 0.152)
    app = AxiomaApp(cfg, with_agora=False, with_registry=False)
    await app.setup()
    try:
        aos_g = app.ctx.get("aos_g")  # type: ignore[union-attr]
        assert aos_g.aos_g_alert_threshold == 0.152
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_with_agora_builds_bridge_and_degrades_gracefully() -> None:
    """With a password set, setup() builds + registers the Agora bridge. When
    the hub is unreachable, start_services() degrades to None (best-effort) and
    never raises — an unreachable Agora must not stop the substrate."""
    import socket
    # An almost-certainly-closed port so the bridge's connect attempt fails fast.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dead_port = s.getsockname()[1]
    s.close()
    cfg = AxiomaConfig()
    object.__setattr__(cfg.interface, "agora_base_url", f"http://127.0.0.1:{dead_port}")
    from pydantic import SecretStr
    object.__setattr__(cfg.interface, "agora_password", SecretStr("pw"))
    app = AxiomaApp(cfg, with_agora=True, with_registry=False, with_http_api=False)
    await app.setup()
    try:
        assert app.agora_bridge is not None
        assert app.ctx.has("agora_bridge")  # type: ignore[union-attr]
        # start_services attempts to connect; unreachable hub → graceful degrade.
        await app.start_services()
        assert app.agora_bridge is None
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_no_agora_skips_bridge() -> None:
    cfg = AxiomaConfig()
    app = AxiomaApp(cfg, with_agora=False, with_registry=False, with_http_api=False)
    await app.setup()
    try:
        assert app.agora_bridge is None
        assert not app.ctx.has("agora_bridge")  # type: ignore[union-attr]
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_shutdown_idempotent() -> None:
    cfg = AxiomaConfig()
    app = AxiomaApp(cfg, with_agora=False, with_registry=False)
    await app.setup()
    await app.shutdown()
    await app.shutdown()  # second call should not raise


# ── v1.5.4 (Checkpoint EE) — true-idempotency + bounded teardown ─────────


@pytest.mark.asyncio
async def test_v1_5_4_shutdown_sets_shutdown_done_flag() -> None:
    """v1.5.4: first shutdown() sets `_shutdown_done`; second call short-circuits
    BEFORE running teardown steps (true idempotency, not just no-raise)."""
    cfg = AxiomaConfig()
    app = AxiomaApp(cfg, with_agora=False, with_registry=False, with_http_api=False)
    await app.setup()
    assert app._shutdown_done is False
    await app.shutdown()
    assert app._shutdown_done is True
    # Second call must return without re-running teardown. We verify this
    # by attaching a peer_conversation handler after the first shutdown and
    # checking the second shutdown does NOT detach it (because it short-circuits).
    from axioma.interface import PeerConversationHandler

    class _StubOllama:
        async def chat(self, *args, **kwargs) -> str:
            return ""
        async def close(self) -> None:
            pass

    app.peer_conversation = PeerConversationHandler(ctx=app.ctx, ollama=_StubOllama())
    app.peer_conversation.attach()
    handler_ref_before = app.peer_conversation._handler_ref
    assert handler_ref_before is not None
    await app.shutdown()  # second call — must short-circuit
    assert app.peer_conversation._handler_ref is handler_ref_before, (
        "second shutdown() should short-circuit, not re-detach peer_conversation"
    )
    # Cleanup
    app.peer_conversation.detach()


@pytest.mark.asyncio
async def test_v1_5_4_shutdown_drains_peer_conversation_inflight() -> None:
    """v1.5.4: shutdown awaits peer_conversation.wait_idle so in-flight
    response tasks finish (or time out cleanly) before the Ollama client is
    closed. Without this, a reply could fire after ollama.close() and crash."""
    import asyncio as _aio

    from axioma.interface import PeerConversationHandler

    class _SlowOllama:
        def __init__(self) -> None:
            self.started = _aio.Event()
            self.finished = False

        async def chat(self, messages, *, max_tokens=None, **_) -> str:
            self.started.set()
            await _aio.sleep(0.05)
            self.finished = True
            return "ok"

        async def close(self) -> None:
            pass

    cfg = AxiomaConfig()
    app = AxiomaApp(cfg, with_agora=False, with_registry=False, with_http_api=False)
    await app.setup()
    stub = _SlowOllama()
    app.peer_conversation = PeerConversationHandler(ctx=app.ctx, ollama=stub)
    app.ollama = stub  # so shutdown awaits .close()
    app.peer_conversation.attach()
    # Fire an inbound message → in-flight Ollama call begins
    await app.ctx.emit(
        "conversation_message",
        {"speaker": "skye", "content": "hi"},
    )
    await stub.started.wait()
    assert stub.finished is False
    # Shutdown — should drain the in-flight task via wait_idle, NOT race past it
    await app.shutdown(peer_drain_timeout=2.0)
    assert stub.finished is True, (
        "shutdown should have drained the in-flight peer task before returning"
    )


@pytest.mark.asyncio
async def test_v1_5_4_shutdown_bounded_when_peer_drain_times_out() -> None:
    """v1.5.4: if a peer task wedges, shutdown still completes within the
    timeout (suppressed TimeoutError) rather than hanging forever."""
    import asyncio as _aio
    import time as _time

    from axioma.interface import PeerConversationHandler

    class _Wedged:
        async def chat(self, messages, *, max_tokens=None, **_) -> str:
            await _aio.sleep(30.0)  # never returns within the test's lifetime
            return ""
        async def close(self) -> None:
            pass

    cfg = AxiomaConfig()
    app = AxiomaApp(cfg, with_agora=False, with_registry=False, with_http_api=False)
    await app.setup()
    wedged = _Wedged()
    app.peer_conversation = PeerConversationHandler(ctx=app.ctx, ollama=wedged)
    app.peer_conversation.attach()
    await app.ctx.emit(
        "conversation_message",
        {"speaker": "skye", "content": "?"},
    )
    await _aio.sleep(0.02)  # let the task start
    t0 = _time.monotonic()
    await app.shutdown(peer_drain_timeout=0.1)  # tiny timeout
    elapsed = _time.monotonic() - t0
    assert elapsed < 1.0, f"shutdown should bound at peer_drain_timeout, took {elapsed}s"
    # Cancel the still-running wedged task so pytest cleanup is clean
    for t in list(app.peer_conversation._inflight):
        t.cancel()


@pytest.mark.asyncio
async def test_start_services_before_setup_fails() -> None:
    cfg = AxiomaConfig()
    app = AxiomaApp(cfg, with_agora=False, with_registry=False)
    with pytest.raises(RuntimeError, match="setup"):
        await app.start_services()


@pytest.mark.asyncio
async def test_http_server_starts_and_serves() -> None:
    """When with_http_api=True, the HTTP server binds + /health returns 200."""
    import socket

    import httpx
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    http_port = s.getsockname()[1]
    s.close()
    cfg = AxiomaConfig()
    object.__setattr__(cfg.interface, "http_port", http_port)
    app = AxiomaApp(cfg, with_agora=False, with_registry=False, with_http_api=True)
    await app.setup()
    await app.start_services()
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"http://127.0.0.1:{http_port}/health", timeout=2.0)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        # Verify /capabilities is also reachable
        async with httpx.AsyncClient() as client:
            r2 = await client.get(f"http://127.0.0.1:{http_port}/capabilities", timeout=2.0)
        assert r2.status_code == 200
        assert "consciousness" in r2.json()["capabilities"]
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_no_http_api_skips_http_server() -> None:
    cfg = AxiomaConfig()
    app = AxiomaApp(cfg, with_agora=False, with_registry=False, with_http_api=False)
    await app.setup()
    await app.start_services()
    try:
        assert app.http_server is None
        assert app._http_serve_task is None
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_http_server_shutdown_clean() -> None:
    """Repeat start+shutdown to verify the HTTP server doesn't leak port bindings."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    http_port = s.getsockname()[1]
    s.close()
    cfg = AxiomaConfig()
    object.__setattr__(cfg.interface, "http_port", http_port)
    app = AxiomaApp(cfg, with_agora=False, with_registry=False, with_http_api=True)
    await app.setup()
    await app.start_services()
    await app.shutdown()
    # Port should be free again — second app on same port should bind cleanly
    cfg2 = AxiomaConfig()
    object.__setattr__(cfg2.interface, "http_port", http_port)
    app2 = AxiomaApp(cfg2, with_agora=False, with_registry=False, with_http_api=True)
    await app2.setup()
    await app2.start_services()
    await app2.shutdown()


@pytest.mark.asyncio
async def test_meta_cog_observer_mode_from_config() -> None:
    from axioma.measurement.meta_cognition_loop import ObserverMode
    cfg = AxiomaConfig()
    # Default is observer_only
    app = AxiomaApp(cfg, with_agora=False, with_registry=False)
    await app.setup()
    try:
        mc = app.ctx.get("meta_cognition_loop")  # type: ignore[union-attr]
        assert mc.observer_mode == ObserverMode.OBSERVER_ONLY
    finally:
        await app.shutdown()
