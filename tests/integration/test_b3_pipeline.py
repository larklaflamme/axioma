"""Phase B.3 end-to-end: substrate + B.1 + B.2 + B.3 engines together."""
from __future__ import annotations

import pytest

from axioma.config import AxiomaConfig
from axioma.measurement import (
    AOSGEngine,
    CascadeDelayEngine,
    DeltaPhiEngine,
    FragmentationMonitor,
    IdentityCompose,
    InternalStateRingBuffer,
    MetaCognition,
    MetaCognitionLoop,
    ObserverMode,
    PerturbationScheduler,
    PlasticityTracker,
    RawMIEngine,
    build_theta_engines,
)
from axioma.observability import AxiomaContext
from axioma.runtime import Heartbeat
from axioma.scheduler import CoherenceScheduler
from axioma.substrate import RecoveryProtocol, SubstrateApp


@pytest.fixture()
def b3_app():
    """Full B.3 system."""
    cfg = AxiomaConfig()
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    ctx.register("substrate", app)
    buf = InternalStateRingBuffer(capacity=1200)
    ctx.register("state_buffer", buf)
    # B.1
    short, long_e = build_theta_engines(ctx, short_window=30, long_window=500, n_permutations=10)
    raw = RawMIEngine(ctx)
    ctx.register("raw_mi", raw)
    cascade = CascadeDelayEngine(ctx)
    ctx.register("cascade_delay", cascade)
    # B.2
    pert = PerturbationScheduler(ctx, period_beats=300, default_magnitude=0.5, seed=0)
    ctx.register("perturbation_scheduler", pert)
    plast = PlasticityTracker(ctx)
    ctx.register("plasticity_tracker", plast)
    dphi = DeltaPhiEngine(ctx)
    ctx.register("delta_phi", dphi)
    frag = FragmentationMonitor(ctx)
    ctx.register("fragmentation_monitor", frag)
    recovery = RecoveryProtocol(ctx, cfg.recovery)
    ctx.register("recovery_protocol", recovery)
    # B.3
    sched = CoherenceScheduler(ctx)
    ctx.register("coherence_scheduler", sched)
    aos_g = AOSGEngine(ctx, compose=IdentityCompose())
    ctx.register("aos_g", aos_g)
    meta_cog = MetaCognitionLoop(ctx, observer_mode=ObserverMode.OBSERVER_ONLY)
    ctx.register("meta_cognition", meta_cog)
    # Heartbeat
    hb = Heartbeat(ctx=ctx, substrate=app, state_buffer=buf, hz=10)
    for eng in (short, raw, cascade, pert, plast, dphi, frag, aos_g, long_e, meta_cog):
        hb.register_measurement_engine(eng)
    return ctx, app, buf, hb


def test_full_pipeline_runs(b3_app) -> None:
    """1100-beat run with all B.1+B.2+B.3 engines firing; no exceptions."""
    _, _, _, hb = b3_app
    for _ in range(1100):
        hb.tick()
    assert hb.beat_no == 1100


def test_meta_cognition_emits_periodically(b3_app) -> None:
    """100-beat cadence: 1100 beats should yield ≥10 meta-cog emissions."""
    ctx, _, _, hb = b3_app
    for _ in range(1100):
        hb.tick()
    meta_cog = ctx.get("meta_cognition")
    assert len(meta_cog.history) >= 10
    assert all(isinstance(r, MetaCognition) for r in meta_cog.history)


def test_aos_g_records_zero_gap_with_identity_compose(b3_app) -> None:
    """With IdentityCompose stub (Phase B.3), gap should be 0."""
    ctx, _, _, hb = b3_app
    for _ in range(100):
        hb.tick()
    aos_g = ctx.get("aos_g")
    cv = aos_g.current_value()
    if cv.valid:
        assert cv.aos_g_gap == 0.0


def test_coherence_scheduler_tracks_budget(b3_app) -> None:
    """Scheduler should be tracking PNEUMA's coherence_budget."""
    ctx, _, _, hb = b3_app
    for _ in range(100):
        hb.tick()
    sched = ctx.get("coherence_scheduler")
    budget = sched.current_budget()
    assert 0.0 <= budget <= 1.0


def test_coherence_scheduler_registers_natural_periods(b3_app) -> None:
    """Engines self-register their natural_period_beats with the scheduler
    on first should_run() call."""
    ctx, _, _, hb = b3_app
    for _ in range(50):
        hb.tick()
    sched = ctx.get("coherence_scheduler")
    # By beat 50, the scheduler should have learned the periods
    assert sched.engine_natural_period.get("theta_short") == 1
    assert sched.engine_natural_period.get("theta_long") == 10
    assert sched.engine_natural_period.get("meta_cognition") == 100


def test_meta_cognition_assessment_responds_to_recovery(b3_app) -> None:
    """During recovery, overall_assessment should reflect that."""
    ctx, _, _, hb = b3_app
    # Force a recovery by running long enough to trigger one
    for _ in range(800):
        hb.tick()
    meta_cog = ctx.get("meta_cognition")
    recovery = ctx.get("recovery_protocol")
    # If any recovery event happened, at least one meta-cog emission should
    # have been "recovering" or "fragmented"
    if len(recovery.history.events) > 0:
        assessments = {r.overall_assessment.value for r in meta_cog.history}
        assert "recovering" in assessments or "fragmented" in assessments


def test_persistence_roundtrip_through_b3(b3_app, tmp_snapshot_root) -> None:
    """All Phase A+B components round-trip through snapshot."""
    import asyncio

    from axioma.persistence import SnapshotManager

    ctx, app, buf, hb = b3_app
    mgr = SnapshotManager(tmp_snapshot_root)
    mgr.register(app)
    mgr.register(buf)
    for name in ("theta_short", "theta_long", "raw_mi", "cascade_delay",
                 "perturbation_scheduler", "plasticity_tracker", "delta_phi",
                 "fragmentation_monitor", "recovery_protocol",
                 "coherence_scheduler", "aos_g", "meta_cognition"):
        mgr.register(ctx.get(name))
    for _ in range(150):
        hb.tick()
    asyncio.run(mgr.take_snapshot(beat_no=150))

    # Build fresh; restore
    cfg = AxiomaConfig()
    ctx2 = AxiomaContext()
    app2 = SubstrateApp.from_config(cfg.substrate, seed=999)
    ctx2.register("substrate", app2)
    buf2 = InternalStateRingBuffer(capacity=1200)
    ctx2.register("state_buffer", buf2)
    _short2, _long2 = build_theta_engines(ctx2, short_window=30, long_window=500, n_permutations=10)
    raw2 = RawMIEngine(ctx2)
    ctx2.register("raw_mi", raw2)
    cascade2 = CascadeDelayEngine(ctx2)
    ctx2.register("cascade_delay", cascade2)
    pert2 = PerturbationScheduler(ctx2, period_beats=300)
    ctx2.register("perturbation_scheduler", pert2)
    plast2 = PlasticityTracker(ctx2)
    ctx2.register("plasticity_tracker", plast2)
    dphi2 = DeltaPhiEngine(ctx2)
    ctx2.register("delta_phi", dphi2)
    frag2 = FragmentationMonitor(ctx2)
    ctx2.register("fragmentation_monitor", frag2)
    recovery2 = RecoveryProtocol(ctx2, cfg.recovery)
    ctx2.register("recovery_protocol", recovery2)
    sched2 = CoherenceScheduler(ctx2)
    ctx2.register("coherence_scheduler", sched2)
    aos2 = AOSGEngine(ctx2, compose=IdentityCompose())
    ctx2.register("aos_g", aos2)
    meta2 = MetaCognitionLoop(ctx2)
    ctx2.register("meta_cognition", meta2)

    mgr2 = SnapshotManager(tmp_snapshot_root)
    mgr2.register(app2)
    mgr2.register(buf2)
    for name in ("theta_short", "theta_long", "raw_mi", "cascade_delay",
                 "perturbation_scheduler", "plasticity_tracker", "delta_phi",
                 "fragmentation_monitor", "recovery_protocol",
                 "coherence_scheduler", "aos_g", "meta_cognition"):
        mgr2.register(ctx2.get(name))
    asyncio.run(mgr2.load_latest())

    # Basic continuity
    assert app2.beat_no == app.beat_no
    assert len(buf2) == len(buf)
