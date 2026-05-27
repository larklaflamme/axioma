"""Heartbeat.pause + RecoveryProtocol Stage-4 → pause integration."""
from __future__ import annotations

from typing import Any

from axioma.config import RecoveryConfig, SubstrateConfig
from axioma.observability import AxiomaContext
from axioma.persistence.snapshot import SnapshotManager
from axioma.runtime.heartbeat import Heartbeat
from axioma.substrate import SubstrateApp
from axioma.substrate.recovery import (
    RecoveryDecision,
    RecoveryProtocol,
    RecoveryRequest,
    RecoveryState,
)


def _make_hb_with_recovery(tmp_path: Any) -> tuple[Heartbeat, RecoveryProtocol, SubstrateApp]:
    ctx = AxiomaContext()
    substrate = SubstrateApp.from_config(SubstrateConfig(), seed=42)
    ctx.register("substrate", substrate)
    snap = SnapshotManager(root=tmp_path)
    hb = Heartbeat(ctx=ctx, substrate=substrate, snapshot_manager=snap)
    ctx.register("heartbeat", hb)
    proto = RecoveryProtocol(ctx=ctx, cfg=RecoveryConfig())
    ctx.register("recovery_protocol", proto)
    return hb, proto, substrate


def test_pause_queues_beats(tmp_path: Any) -> None:
    hb, _proto, _sub = _make_hb_with_recovery(tmp_path)
    assert hb._pause_beats_remaining == 0
    hb.pause(beats=2)
    assert hb._pause_beats_remaining == 2
    hb.pause(beats=3)
    assert hb._pause_beats_remaining == 5


def test_pause_zero_is_no_op(tmp_path: Any) -> None:
    hb, _proto, _sub = _make_hb_with_recovery(tmp_path)
    hb.pause(beats=0)
    hb.pause(beats=-1)
    assert hb._pause_beats_remaining == 0


def test_paused_beat_skips_substrate_tick(tmp_path: Any) -> None:
    """Paused beat increments hb.beat_no but does NOT call substrate.tick()."""
    hb, _proto, sub = _make_hb_with_recovery(tmp_path)
    hb.tick()
    call_count = {"n": 0}
    original = sub.tick

    def counting_tick(*a: Any, **kw: Any) -> Any:
        call_count["n"] += 1
        return original(*a, **kw)
    sub.tick = counting_tick  # type: ignore[method-assign]
    hb.pause(beats=1)
    hb_beat_before = hb.beat_no
    hb.tick()
    assert hb.beat_no == hb_beat_before + 1
    assert call_count["n"] == 0  # substrate.tick was NOT called


def test_normal_tick_after_pause_resumes_substrate(tmp_path: Any) -> None:
    hb, _proto, sub = _make_hb_with_recovery(tmp_path)
    hb.tick()
    call_count = {"n": 0}
    original = sub.tick

    def counting_tick(*a: Any, **kw: Any) -> Any:
        call_count["n"] += 1
        return original(*a, **kw)
    sub.tick = counting_tick  # type: ignore[method-assign]
    hb.pause(beats=1)
    hb.tick()  # paused — substrate.tick NOT called
    assert call_count["n"] == 0
    hb.tick()  # normal — substrate.tick called once
    assert call_count["n"] == 1
    assert hb._pause_beats_remaining == 0


def test_recovery_stage4_invokes_pause(tmp_path: Any) -> None:
    """Stage-4 recovery request → handler accepts → heartbeat.pause(1)."""
    hb, proto, _sub = _make_hb_with_recovery(tmp_path)
    # Warm substrate up
    hb.tick()
    hb.tick()
    initial_pause_queue = hb._pause_beats_remaining
    req = RecoveryRequest(
        request_id="req-stage4",
        beat_no=hb.beat_no,
        stage=4,
        signals={"pneuma_frag": 0.9},
    )
    decision = proto.handle_recovery_request(req)
    assert decision == RecoveryDecision.ACCEPT
    proto._start_recovery(req)
    # Heartbeat.pause(1) should have been queued via the recovery hook
    assert hb._pause_beats_remaining == initial_pause_queue + 1
    # Recovery state is ACTIVE
    assert proto.state == RecoveryState.ACTIVE


def test_recovery_stage2_does_not_pause(tmp_path: Any) -> None:
    """Stage 2 does NOT trigger heartbeat pause."""
    hb, proto, _sub = _make_hb_with_recovery(tmp_path)
    hb.tick()
    req = RecoveryRequest(
        request_id="req-stage2",
        beat_no=hb.beat_no,
        stage=2,
        signals={},
    )
    decision = proto.handle_recovery_request(req)
    assert decision == RecoveryDecision.ACCEPT
    proto._start_recovery(req)
    assert hb._pause_beats_remaining == 0


def test_pause_state_persists_per_tick(tmp_path: Any) -> None:
    """Two queued pauses → two paused ticks in a row, then normal resumes."""
    hb, _proto, sub = _make_hb_with_recovery(tmp_path)
    hb.tick()
    call_count = {"n": 0}
    original = sub.tick

    def counting_tick(*a: Any, **kw: Any) -> Any:
        call_count["n"] += 1
        return original(*a, **kw)
    sub.tick = counting_tick  # type: ignore[method-assign]
    hb.pause(beats=2)
    hb.tick()  # paused #1
    hb.tick()  # paused #2
    assert call_count["n"] == 0
    assert hb._pause_beats_remaining == 0
    hb.tick()  # normal — only one substrate.tick call
    assert call_count["n"] == 1
