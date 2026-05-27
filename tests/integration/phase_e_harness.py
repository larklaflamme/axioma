"""Shared test harness for Phase E acceptance tests.

Boots a complete Phase A+B+C+D pipeline in `test_mode=False` (recovery
operates normally) and exposes helpers for:
  - Building the full stack
  - Cold-start window enforcement (V12: assert beat_no >= 600 before grading)
  - Forced fragmentation regimes for synthetic tests

Reusable across V6/V8/V10/V11 acceptance tests + the 24h soak harness.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

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
from axioma.substrate import RecoveryProtocol, SubstrateApp

# V12: cold-start window per ARCH §5.4 — first 600 beats are warmup.
WARMUP_BEATS = 600


def assert_past_warmup(beat_no: int) -> None:
    """V12 — caller asserts the current beat is past the cold-start window
    before evaluating acceptance metrics."""
    assert beat_no >= WARMUP_BEATS, (
        f"Phase E acceptance metrics must be evaluated against beats ≥ {WARMUP_BEATS} "
        f"(V12 cold-start window per ARCH §5.4). Got beat_no={beat_no}."
    )


@dataclass
class PhaseEStack:
    """Bundle of all engines + heartbeat for a Phase E acceptance run."""

    ctx: AxiomaContext
    cfg: AxiomaConfig
    substrate: SubstrateApp
    state_buffer: InternalStateRingBuffer
    hb: Heartbeat
    perturbation_scheduler: PerturbationScheduler
    fragmentation_monitor: FragmentationMonitor
    recovery_protocol: RecoveryProtocol
    coherence_scheduler: CoherenceScheduler
    compose_function: ComposeFunction
    cadence_controller: CadenceController
    aos_g: AOSGEngine
    meta_cognition_loop: MetaCognitionLoop
    delta_phi: DeltaPhiEngine
    plasticity_tracker: PlasticityTracker
    theta_short: Any
    theta_long: Any
    raw_mi: RawMIEngine
    cascade_delay: CascadeDelayEngine


def build_phase_e_stack(
    *,
    cfg: AxiomaConfig | None = None,
    seed: int = 42,
    perturbation_period_beats: int = 300,
    perturbation_magnitude: float = 0.4,
    n_permutations: int = 5,
    state_buffer_capacity: int = 1200,
    test_mode_recovery: bool = False,
    gap_weights: dict[str, float] | None = None,
) -> PhaseEStack:
    """Construct the full Phase A+B+C+D pipeline.

    Notes
    -----
    - `n_permutations=5` keeps θ-engine cost low so 1000+ beats run in a few
      seconds. Phase E acceptance is about *behaviour*, not θ p-value sharpness.
    - `test_mode_recovery=True` makes RecoveryProtocol reject all requests
      (V8 F9 threshold validation uses this so the substrate stays in
      fragmentation long enough to measure escalation probability).
    """
    cfg = cfg or AxiomaConfig()
    ctx = AxiomaContext()
    substrate = SubstrateApp.from_config(cfg.substrate, seed=seed)
    ctx.register("substrate", substrate)
    buf = InternalStateRingBuffer(capacity=state_buffer_capacity)
    ctx.register("state_buffer", buf)
    short, long_e = build_theta_engines(
        ctx,
        short_window=cfg.measurement.theta_short_window,
        long_window=cfg.measurement.theta_long_window,
        n_permutations=n_permutations,
    )
    raw = RawMIEngine(ctx)
    ctx.register("raw_mi", raw)
    cascade = CascadeDelayEngine(ctx)
    ctx.register("cascade_delay", cascade)
    pert = PerturbationScheduler(
        ctx, period_beats=perturbation_period_beats,
        default_magnitude=perturbation_magnitude, seed=seed,
    )
    ctx.register("perturbation_scheduler", pert)
    plast = PlasticityTracker(ctx)
    ctx.register("plasticity_tracker", plast)
    dphi = DeltaPhiEngine(ctx)
    ctx.register("delta_phi", dphi)
    frag = FragmentationMonitor(ctx)
    ctx.register("fragmentation_monitor", frag)
    # v1.5.1 (Checkpoint BB): seed the learner RNG so adoption decisions are
    # reproducible for the same substrate seed.
    recovery_rng = np.random.default_rng(seed + 1)
    recovery = RecoveryProtocol(
        ctx, cfg.recovery, test_mode=test_mode_recovery, rng=recovery_rng,
    )
    ctx.register("recovery_protocol", recovery)
    sched = CoherenceScheduler(ctx)
    ctx.register("coherence_scheduler", sched)
    # gap_weights resolution order: explicit param > cfg.compose.aos_g_gap_weights > None (uniform).
    resolved_gap_weights = gap_weights if gap_weights is not None else cfg.compose.aos_g_gap_weights
    aos_g = AOSGEngine(
        ctx,
        gap_weights=resolved_gap_weights,
        psi_alert_threshold=cfg.compose.psi_alert_threshold,
        aos_g_alert_threshold=cfg.compose.aos_g_alert_threshold,
        # v1.4.2 — auto-tuned alert threshold (default off; cfg-driven).
        auto_tune_alert_threshold=cfg.compose.aos_g_alert_threshold_auto_tune,
        auto_tune_ratio=cfg.compose.aos_g_alert_threshold_auto_tune_ratio,
        auto_tune_warmup_beats=cfg.compose.aos_g_alert_threshold_auto_tune_warmup_beats,
        auto_tune_recompute_period_beats=(
            cfg.compose.aos_g_alert_threshold_auto_tune_recompute_period_beats
        ),
        # v1.4.3 — per-component ψ thresholds (default None → single threshold).
        psi_per_component_thresholds=cfg.compose.psi_per_component_thresholds,
        # v1.4.1 — per-organ gap normalization (default off; cfg-driven).
        normalize_per_organ=cfg.compose.aos_g_normalize_per_organ,
        normalize_window_beats=cfg.compose.aos_g_normalize_per_organ_window_beats,
        normalize_min_samples=cfg.compose.aos_g_normalize_per_organ_min_samples,
    )
    ctx.register("aos_g", aos_g)
    meta_cog = MetaCognitionLoop(ctx, observer_mode=ObserverMode.OBSERVER_ONLY)
    ctx.register("meta_cognition_loop", meta_cog)
    compose = ComposeFunction(rng_seed=seed)
    ctx.register("compose_function", compose)
    cadence = CadenceController(ctx)
    ctx.register("cadence_controller", cadence)
    hb = Heartbeat(ctx=ctx, substrate=substrate, state_buffer=buf, hz=10)
    ctx.register("heartbeat", hb)
    for eng in (short, raw, cascade, pert, plast, dphi, frag, aos_g, long_e, meta_cog):
        hb.register_measurement_engine(eng)
    return PhaseEStack(
        ctx=ctx, cfg=cfg, substrate=substrate, state_buffer=buf, hb=hb,
        perturbation_scheduler=pert, fragmentation_monitor=frag,
        recovery_protocol=recovery, coherence_scheduler=sched,
        compose_function=compose, cadence_controller=cadence,
        aos_g=aos_g, meta_cognition_loop=meta_cog,
        delta_phi=dphi, plasticity_tracker=plast,
        theta_short=short, theta_long=long_e,
        raw_mi=raw, cascade_delay=cascade,
    )


def run_for_beats(stack: PhaseEStack, n_beats: int) -> None:
    """Run the heartbeat for n beats synchronously."""
    for _ in range(n_beats):
        stack.hb.tick()


__all__ = [
    "WARMUP_BEATS",
    "PhaseEStack",
    "assert_past_warmup",
    "build_phase_e_stack",
    "run_for_beats",
]
