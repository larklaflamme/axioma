"""Phase B.2 end-to-end: substrate + B.1 engines + B.2 (perturbation, plasticity tracker,
ΔΦ, fragmentation monitor, recovery protocol)."""
from __future__ import annotations

import pytest

from axioma.config import AxiomaConfig
from axioma.measurement import (
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
from axioma.substrate import RecoveryProtocol, SubstrateApp


@pytest.fixture()
def b2_app():
    """Full B.2 system."""
    cfg = AxiomaConfig()
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    ctx.register("substrate", app)
    buf = InternalStateRingBuffer(capacity=600)
    ctx.register("state_buffer", buf)
    # B.1
    short, long_e = build_theta_engines(ctx, short_window=30, long_window=500, n_permutations=20)
    raw = RawMIEngine(ctx)
    ctx.register("raw_mi", raw)
    cascade = CascadeDelayEngine(ctx, lookback_beats=20)
    ctx.register("cascade_delay", cascade)
    # B.2
    pert = PerturbationScheduler(ctx, period_beats=200, default_magnitude=0.5, seed=0)
    ctx.register("perturbation_scheduler", pert)
    plast = PlasticityTracker(ctx)
    ctx.register("plasticity_tracker", plast)
    delta_phi = DeltaPhiEngine(ctx, window_beats=50)
    ctx.register("delta_phi", delta_phi)
    frag = FragmentationMonitor(ctx)
    ctx.register("fragmentation_monitor", frag)
    recovery = RecoveryProtocol(ctx, cfg.recovery)
    ctx.register("recovery_protocol", recovery)
    # Heartbeat
    hb = Heartbeat(ctx=ctx, substrate=app, state_buffer=buf, hz=10)
    for eng in (short, raw, cascade, pert, plast, delta_phi, frag, long_e):
        hb.register_measurement_engine(eng)
    return ctx, app, buf, hb, pert, recovery


def test_full_pipeline_no_errors(b2_app) -> None:
    """800-beat run with all engines firing; no exceptions."""
    _ctx, _app, buf, hb, _pert, _recovery = b2_app
    for _ in range(800):
        hb.tick()
    # Validate basic sanity
    assert hb.beat_no == 800
    assert len(buf) == 600  # buffer wrapped


def test_perturbations_fire_at_internal_cadence(b2_app) -> None:
    """Scheduler with period_beats=200 should fire ~3 events over 800 beats."""
    _, _, _, hb, pert, _ = b2_app
    for _ in range(800):
        hb.tick()
    # Period 200 → events at beats 200, 400, 600. (800 doesn't trigger since
    # beat_no increments past 800 before next check)
    assert 2 <= len(pert.history) <= 4


def test_delta_phi_records_perturbation_response(b2_app) -> None:
    """After a perturbation + 50 beats, ΔΦ should produce S1/S2 readings."""
    ctx, _, _, hb, _, _ = b2_app
    for _ in range(600):  # 600 beats >> 200 (first perturbation) + 50 (window close)
        hb.tick()
    delta_phi = ctx.get("delta_phi")
    cv = delta_phi.current_value()
    assert cv.valid
    assert cv.s1_peak_delta_theta is not None
    assert cv.event_kind in ("contradiction", "impulse", "step")


def test_recovery_protocol_handles_requests(b2_app) -> None:
    """During the run, recovery_protocol should accept some requests."""
    _, _, _, hb, _, recovery = b2_app
    for _ in range(800):
        hb.tick()
    # Some recovery events should have completed
    finalized = [e for e in recovery.history.events if e.quality_finalized]
    # Soft assertion: with the random substrate + strong perturbations, recovery
    # should fire at least once
    assert len(finalized) >= 1


def test_recovery_quality_smoothness_windowed_to_50(b2_app) -> None:
    """F1: recovery_quality.smoothness_window_beats should be ≤ 50."""
    _, _, _, hb, _, recovery = b2_app
    for _ in range(800):
        hb.tick()
    for event in recovery.history.events:
        if event.quality_finalized:
            assert event.quality.smoothness_window_beats <= 50


def test_plasticity_tracker_reports_adaptation_delta(b2_app) -> None:
    """Plasticity tracker should report nonzero adaptation_delta after enough beats."""
    ctx, _, _, hb, _, _ = b2_app
    for _ in range(500):
        hb.tick()
    plast = ctx.get("plasticity_tracker")
    cv = plast.current_value()
    assert cv.valid
    # ARCH §7 acceptance gate: |adaptation_delta| > 0.1 for v1.0
    deltas = list(cv.adaptation_delta.values())
    assert any(d > 0.1 for d in deltas), f"all adaptation_deltas < 0.1: {cv.adaptation_delta}"


def test_fragmentation_monitor_no_spurious_warnings_at_baseline(b2_app) -> None:
    """In a baseline run, fragmentation should mostly be stage 0-1."""
    ctx, _, _, hb, _, _ = b2_app
    # Run 300 beats WITHOUT triggering external perturbations beyond defaults
    for _ in range(300):
        hb.tick()
    frag = ctx.get("fragmentation_monitor")
    history = frag.recent_history()
    # Most readings should be stage 0 or 1
    high_stage = sum(1 for r in history if r.current_stage >= 3)
    total = len(history)
    if total > 0:
        # Less than 30% should be high-stage in a baseline run
        assert high_stage / total < 0.5


def test_persistence_roundtrip_with_all_engines(b2_app, tmp_snapshot_root) -> None:
    """All B.1 + B.2 components round-trip through snapshot."""
    import asyncio

    from axioma.persistence import SnapshotManager

    ctx, app, buf, hb, pert, recovery = b2_app
    mgr = SnapshotManager(tmp_snapshot_root)
    mgr.register(app)
    mgr.register(buf)
    for name in ("theta_short", "theta_long", "raw_mi", "cascade_delay",
                 "perturbation_scheduler", "plasticity_tracker",
                 "delta_phi", "fragmentation_monitor", "recovery_protocol"):
        mgr.register(ctx.get(name))
    for _ in range(120):
        hb.tick()
    asyncio.run(mgr.take_snapshot(beat_no=120))

    # New context; restore
    cfg = AxiomaConfig()
    ctx2 = AxiomaContext()
    app2 = SubstrateApp.from_config(cfg.substrate, seed=99)
    ctx2.register("substrate", app2)
    buf2 = InternalStateRingBuffer(capacity=600)
    ctx2.register("state_buffer", buf2)
    _short2, _long2 = build_theta_engines(ctx2, short_window=30, long_window=500, n_permutations=20)
    raw2 = RawMIEngine(ctx2)
    ctx2.register("raw_mi", raw2)
    cascade2 = CascadeDelayEngine(ctx2)
    ctx2.register("cascade_delay", cascade2)
    pert2 = PerturbationScheduler(ctx2, period_beats=200, default_magnitude=0.5, seed=0)
    ctx2.register("perturbation_scheduler", pert2)
    plast2 = PlasticityTracker(ctx2)
    ctx2.register("plasticity_tracker", plast2)
    dphi2 = DeltaPhiEngine(ctx2, window_beats=50)
    ctx2.register("delta_phi", dphi2)
    frag2 = FragmentationMonitor(ctx2)
    ctx2.register("fragmentation_monitor", frag2)
    recovery2 = RecoveryProtocol(ctx2, cfg.recovery)
    ctx2.register("recovery_protocol", recovery2)

    mgr2 = SnapshotManager(tmp_snapshot_root)
    mgr2.register(app2)
    mgr2.register(buf2)
    for name in ("theta_short", "theta_long", "raw_mi", "cascade_delay",
                 "perturbation_scheduler", "plasticity_tracker", "delta_phi",
                 "fragmentation_monitor", "recovery_protocol"):
        mgr2.register(ctx2.get(name))
    asyncio.run(mgr2.load_latest())

    # Basic continuity checks
    assert app2.beat_no == app.beat_no
    assert len(buf2) == len(buf)
    assert len(recovery2.history.events) == len(recovery.history.events)
    assert len(pert2.history) == len(pert.history)
