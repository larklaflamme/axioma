"""Single-trial runner for the AOS-G gap experiment.

One trial = one (condition, seed) combination, 600 beats:
  - Substrate ticks beat-by-beat.
  - Perturbation injects pre-update (via heartbeat.on_pre_update) inside its window.
  - Compose runs every beat (decision §2.1 of IMPLEMENTATION_PLAN).
  - Adaptive controller decides which beats are "compose events" (logged).
  - Per-event metric extraction (design §5.1).
  - Per-trial summary at end (design §5.2 — partially; θ + Granger filled by metrics.py).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from organ.schemas import ORGAN_DIMS, ORGAN_ORDER
from organ.substrate import CoupledLatentDynamics, Heartbeat

from .compose import ComposeFunction
from .config import (
    DEFAULT_COUPLING,
    H2_POST_WINDOW,
    H2_PRE_WINDOW,
    N_BEATS,
    PERTURBATION_BEAT,
    PERTURBATION_DURATION,
)
from .frequency import AdaptiveComposeController
from .perturbations import build as build_perturbation


@dataclass
class TrialConfig:
    condition: str
    seed: int
    n_beats: int = N_BEATS
    coupling: float = DEFAULT_COUPLING
    perturbation_beat: int = PERTURBATION_BEAT
    perturbation_duration: int = PERTURBATION_DURATION


@dataclass
class TrialResult:
    config: TrialConfig
    per_event: list[dict] = field(default_factory=list)        # design §5.1
    internal_trajectory: np.ndarray = field(default=None)      # (n_beats, 27)
    external_trajectory: np.ndarray = field(default=None)      # (n_beats, 27)
    per_organ_delta: dict[str, np.ndarray] = field(default_factory=dict)  # (n_beats,) per organ
    delta_norm_series: np.ndarray = field(default=None)        # (n_beats,) total Euclidean delta
    per_organ_delta_z: dict[str, np.ndarray] = field(default_factory=dict)  # z-normalized vs baseline
    fidelity_series: dict[str, np.ndarray] = field(default_factory=dict)  # (n_beats,) per organ
    integration_series: np.ndarray = field(default=None)       # (n_beats,) PNEUMA.integration_level
    self_coherence_series: np.ndarray = field(default=None)    # (n_beats,) EIDOLON.self_coherence
    elapsed_s: float = 0.0


def _concat(states: dict[str, np.ndarray]) -> np.ndarray:
    return np.concatenate([states[o] for o in ORGAN_ORDER]).astype(np.float32)


def _organ_slices() -> dict[str, slice]:
    out = {}
    start = 0
    for o in ORGAN_ORDER:
        out[o] = slice(start, start + ORGAN_DIMS[o])
        start += ORGAN_DIMS[o]
    return out


ORGAN_SLICES = _organ_slices()


def run_single_trial(cfg: TrialConfig, verbose: bool = False) -> TrialResult:
    rng = np.random.default_rng(cfg.seed)

    # Substrate.
    dyn = CoupledLatentDynamics(coupling=cfg.coupling, seed=cfg.seed)
    hb = Heartbeat(dynamics=dyn, seed=cfg.seed)

    # Perturbation.
    pert = build_perturbation(
        cfg.condition,
        trigger_beat=cfg.perturbation_beat,
        duration=cfg.perturbation_duration,
        seed=cfg.seed,
    )
    hb.on_pre_update(lambda b: pert.apply_pre_update(b, {o.name: o for o in hb.organs}))

    # Compose function.
    cf = ComposeFunction(seed=cfg.seed)

    # Frequency controller.
    fc = AdaptiveComposeController()

    n = cfg.n_beats
    internal = np.zeros((n, sum(ORGAN_DIMS.values())), dtype=np.float32)
    external = np.zeros((n, sum(ORGAN_DIMS.values())), dtype=np.float32)
    delta_norm_series = np.zeros(n, dtype=np.float32)
    per_organ_delta = {o: np.zeros(n, dtype=np.float32) for o in ORGAN_ORDER}
    fidelity_series = {o: np.zeros(n, dtype=np.float32) for o in ORGAN_ORDER}
    integration_series = np.zeros(n, dtype=np.float32)
    self_coh_series = np.zeros(n, dtype=np.float32)

    per_event: list[dict] = []
    next_compose_beat = 0
    auto_trigger_warmup = 100  # ignore auto-trigger before baseline has settled
    t0 = time.monotonic()

    for b in range(n):
        # Substrate step (pre-update hooks fire inside .tick()).
        hb.tick()
        # Capture internal state arrays.
        internal_arrays = {o.name: o.get_state_array() for o in hb.organs}
        # Update rolling stats *before* compose (μ uses past, not present).
        if b == 0:
            cf.update_rolling(internal_arrays)
        # Compose using rolling stats up to the previous beat.
        integ = float(hb.pneuma.get_state().integration_level)
        coh = float(hb.eidolon.get_state().self_coherence)
        comp = cf.compose(internal_arrays, integration_level=integ, self_coherence=coh)
        # NOW push current internal into rolling so next beat sees it.
        if b > 0:
            cf.update_rolling(internal_arrays)
        external_arrays = comp.external_arrays

        # Per-beat trajectories.
        int_vec = _concat(internal_arrays)
        ext_vec = _concat(external_arrays)
        internal[b] = int_vec
        external[b] = ext_vec
        diff_vec = int_vec - ext_vec
        delta_norm_series[b] = float(np.linalg.norm(diff_vec))
        for o in ORGAN_ORDER:
            sl = ORGAN_SLICES[o]
            per_organ_delta[o][b] = float(np.linalg.norm(diff_vec[sl]))
            fidelity_series[o][b] = comp.fidelity_factors[o]
        integration_series[b] = integ
        self_coh_series[b] = coh

        # Maintain baseline mean of delta for auto-trigger (use the per-beat
        # series, not just compose events).
        phase = fc.phase(b)
        if b >= auto_trigger_warmup and b < fc.pert_start:
            # 100-beat trailing window of pre-perturbation delta
            baseline_mean = float(delta_norm_series[max(0, b - 99): b + 1].mean())
        elif b < auto_trigger_warmup:
            baseline_mean = 0.0   # disables auto-trigger until warmup
        else:
            # After perturbation phase starts, freeze the baseline_mean reference.
            baseline_mean = float(delta_norm_series[auto_trigger_warmup: fc.pert_start].mean())

        # Decide whether to log this beat as a compose event.
        interval = fc.desired_interval(b, float(delta_norm_series[b]), baseline_mean)
        if b >= next_compose_beat:
            event = {
                "trial_id": f"{cfg.condition}_s{cfg.seed}",
                "beat_no": int(b),
                "phase": phase,
                "auto_triggered": fc.is_auto_triggered(b),
                "condition": cfg.condition,
                "seed": int(cfg.seed),
                "delta_norm": float(delta_norm_series[b]),
                "per_organ_delta": {o: float(per_organ_delta[o][b]) for o in ORGAN_ORDER},
                "fidelity_factors": {o: float(comp.fidelity_factors[o]) for o in ORGAN_ORDER},
                "integration_level": integ,
                "self_coherence": coh,
            }
            per_event.append(event)
            next_compose_beat = b + interval

    # Z-normalize per-organ delta vs the pre-perturbation baseline (beats 100-180)
    # so cascade ordering isn't dominated by raw-dimension scale.
    per_organ_delta_z = {}
    for o in ORGAN_ORDER:
        baseline_segment = per_organ_delta[o][100 : fc.pert_start]
        mu_b = float(baseline_segment.mean())
        sd_b = float(baseline_segment.std() + 1e-9)
        per_organ_delta_z[o] = ((per_organ_delta[o] - mu_b) / sd_b).astype(np.float32)

    elapsed = time.monotonic() - t0
    if verbose:
        print(f"  trial {cfg.condition}_s{cfg.seed}: {n} beats, {len(per_event)} events, {elapsed:.2f}s")

    return TrialResult(
        config=cfg,
        per_event=per_event,
        internal_trajectory=internal,
        external_trajectory=external,
        per_organ_delta=per_organ_delta,
        per_organ_delta_z=per_organ_delta_z,
        delta_norm_series=delta_norm_series,
        fidelity_series=fidelity_series,
        integration_series=integration_series,
        self_coherence_series=self_coh_series,
        elapsed_s=elapsed,
    )
