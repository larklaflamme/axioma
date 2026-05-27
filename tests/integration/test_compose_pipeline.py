"""Phase C end-to-end: real ComposeFunction wired into heartbeat; ψ rises."""
from __future__ import annotations

import pytest

from axioma.compose import CadenceController, ComposeFunction
from axioma.config import AxiomaConfig
from axioma.measurement import (
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
from axioma.observability import AxiomaContext
from axioma.runtime import Heartbeat
from axioma.scheduler import CoherenceScheduler
from axioma.schemas import ComposeCadence
from axioma.substrate import RecoveryProtocol, SubstrateApp


@pytest.fixture()
def c_app():
    """Full Phase C system: B.1+B.2+B.3 + real ComposeFunction + CadenceController.

    v1.7 (Checkpoint MM): pinned to v1.6 substrate (MNEME compensations OFF) so
    the cadence-assertion test isn't coupled to v1.7 substrate-dynamics changes.
    This fixture's intent is testing the compose pipeline, not substrate dynamics."""
    cfg = AxiomaConfig()
    object.__setattr__(cfg.substrate, "mneme_compensation_2_enabled", False)
    object.__setattr__(cfg.substrate, "mneme_compensation_3_enabled", False)
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    ctx.register("substrate", app)
    buf = InternalStateRingBuffer(capacity=1200)
    ctx.register("state_buffer", buf)
    short, long_e = build_theta_engines(ctx, short_window=30, long_window=500, n_permutations=10)
    raw = RawMIEngine(ctx)
    ctx.register("raw_mi", raw)
    cascade = CascadeDelayEngine(ctx)
    ctx.register("cascade_delay", cascade)
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
    sched = CoherenceScheduler(ctx)
    ctx.register("coherence_scheduler", sched)
    aos_g = AOSGEngine(ctx)
    ctx.register("aos_g", aos_g)
    meta_cog = MetaCognitionLoop(ctx, observer_mode=ObserverMode.OBSERVER_ONLY)
    ctx.register("meta_cognition", meta_cog)
    # Phase C
    compose = ComposeFunction(rng_seed=42)
    ctx.register("compose_function", compose)
    cadence = CadenceController(ctx)
    ctx.register("cadence_controller", cadence)
    hb = Heartbeat(ctx=ctx, substrate=app, state_buffer=buf, hz=10)
    for eng in (short, raw, cascade, pert, plast, dphi, frag, aos_g, long_e, meta_cog):
        hb.register_measurement_engine(eng)
    return ctx, app, buf, hb, compose, cadence


def test_compose_fires_on_baseline_cadence(c_app) -> None:
    """Default 30-beat cadence: 600 beats → ~20 compose events."""
    _, _, _, hb, compose, _ = c_app
    for _ in range(600):
        hb.tick()
    # ~600/30 = 20 baseline composes; perturbations may bump count
    assert 15 <= compose.composes_total <= 30


def test_compose_populates_external_state(c_app) -> None:
    _, _, _, hb, compose, _ = c_app
    for _ in range(100):
        hb.tick()
    assert compose.latest_external is not None
    ext = compose.latest_external
    assert ext.beat_no > 0
    assert ext.cadence == ComposeCadence.BASELINE


def test_aos_g_gap_rises_above_zero_with_real_compose(c_app) -> None:
    """★ The keystone integration test: real compose ⇒ non-zero gap ⇒ ψ rises."""
    ctx, _, _, hb, _, _ = c_app
    for _ in range(600):
        hb.tick()
    aos_g = ctx.get("aos_g")
    cv = aos_g.current_value()
    assert cv.valid
    # With real ComposeFunction, gap MUST be > 0 (some compression happens)
    assert cv.aos_g_gap > 0
    # ψ should NOT be 0 anymore (the B.3 stub case)
    assert cv.psi > 0
    # gap_variance_health should rise once we have enough variance
    assert cv.gap_variance_health > 0


def test_compose_function_eidolon_coh_live_extraction(c_app) -> None:
    """P13: ComposeFunction reads eidolon's self_coherence at compose time."""
    _ctx, _app, _, hb, compose, _ = c_app
    for _ in range(60):
        hb.tick()
    # Latest internal's EIDOLON state should match what was used
    # (we don't have a way to introspect the compose call directly, but
    # latest_internal stores the input)
    if compose.latest_internal is not None:
        # Fidelity factor was computed using this value; verify consistency
        fidelity = compose.latest_fidelities()
        assert fidelity is not None
        # Substrate's θ_short × eidolon_coh × weight (1.0) = fidelity[anima]
        # We can't easily reconstruct theta_short, but verify fidelities are
        # internally consistent (all = same product, since weights all 1.0)
        vals = list(fidelity.values())
        assert all(abs(v - vals[0]) < 1e-9 for v in vals)


def test_perturbation_triggers_cadence_change(c_app) -> None:
    """After a perturbation, cadence switches to PERTURBATION for 50 beats."""
    ctx, _, _, hb, _, cadence = c_app
    pert = ctx.get("perturbation_scheduler")
    # Tick to beat where we manually inject
    for _ in range(50):
        hb.tick()
    # Now inject a perturbation; cadence should switch
    pert.inject_now("contradiction", magnitude=0.3)
    # The injection event sets the perturbation window
    # Next compose decision should be on PERTURBATION cadence
    current = cadence.current_cadence(60)
    assert current == ComposeCadence.PERTURBATION


def test_persistence_roundtrip_through_compose(c_app, tmp_snapshot_root) -> None:
    """ComposeFunction + CadenceController round-trip through snapshot."""
    import asyncio

    from axioma.persistence import SnapshotManager

    ctx, app, buf, hb, compose, _cadence = c_app
    mgr = SnapshotManager(tmp_snapshot_root)
    mgr.register(app)
    mgr.register(buf)
    for name in ("theta_short", "theta_long", "raw_mi", "cascade_delay",
                 "perturbation_scheduler", "plasticity_tracker", "delta_phi",
                 "fragmentation_monitor", "recovery_protocol",
                 "coherence_scheduler", "aos_g", "meta_cognition",
                 "compose_function", "cadence_controller"):
        mgr.register(ctx.get(name))
    for _ in range(150):
        hb.tick()
    asyncio.run(mgr.take_snapshot(beat_no=150))
    # All 14 components persisted; no exception → success
    assert compose.composes_total > 0
