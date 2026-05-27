"""Control-experiment trial harness.

Mirrors aos_g_gap.trial.run_single_trial but takes a ControlMode + magnitude.
The compose function, heartbeat, and perturbation are all built via the mode
factory + the magnitude-scaled perturbation factory.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from aos_g_gap.compose import ComposeFunction
from aos_g_gap.config import DEFAULT_COUPLING
from organ.schemas import ORGAN_DIMS, ORGAN_ORDER

from .config import N_BEATS, PERTURBATION_BEAT, PERTURBATION_DURATION
from .modes import ControlMode, build_mode
from .perturbations import build_perturbation


@dataclass
class ControlTrialConfig:
    mode: str
    perturbation_type: str
    magnitude: float
    seed: int
    n_beats: int = N_BEATS
    coupling: float = DEFAULT_COUPLING
    perturbation_beat: int = PERTURBATION_BEAT
    perturbation_duration: int = PERTURBATION_DURATION
    mode_kwargs: dict | None = None


@dataclass
class ControlTrialResult:
    config: ControlTrialConfig
    internal_trajectory: np.ndarray = field(default=None)
    external_trajectory: np.ndarray = field(default=None)
    delta_norm_series: np.ndarray = field(default=None)
    per_organ_delta: dict[str, np.ndarray] = field(default_factory=dict)
    fidelity_series: dict[str, np.ndarray] = field(default_factory=dict)
    integration_series: np.ndarray = field(default=None)
    self_coherence_series: np.ndarray = field(default=None)
    dt_history: np.ndarray = field(default=None)  # Control 2 only
    elapsed_s: float = 0.0


_ORGAN_SLICES: dict[str, slice] | None = None


def _organ_slices() -> dict[str, slice]:
    global _ORGAN_SLICES
    if _ORGAN_SLICES is not None:
        return _ORGAN_SLICES
    out: dict[str, slice] = {}
    start = 0
    for o in ORGAN_ORDER:
        out[o] = slice(start, start + ORGAN_DIMS[o])
        start += ORGAN_DIMS[o]
    _ORGAN_SLICES = out
    return out


def _concat(arrays: dict[str, np.ndarray]) -> np.ndarray:
    return np.concatenate([arrays[o] for o in ORGAN_ORDER]).astype(np.float32)


def run_control_trial(cfg: ControlTrialConfig) -> ControlTrialResult:
    mode: ControlMode = build_mode(cfg.mode, **(cfg.mode_kwargs or {}))
    hb = mode.build_heartbeat(cfg.seed, cfg.coupling)
    cf: ComposeFunction = mode.build_compose(cfg.seed)

    pert = build_perturbation(
        cfg.perturbation_type,
        magnitude=cfg.magnitude,
        trigger_beat=cfg.perturbation_beat,
        duration=cfg.perturbation_duration,
        seed=cfg.seed,
    )
    hb.on_pre_update(lambda b: pert.apply_pre_update(b, {o.name: o for o in hb.organs}))

    n = cfg.n_beats
    dim_total = sum(ORGAN_DIMS.values())
    internal = np.zeros((n, dim_total), dtype=np.float32)
    external = np.zeros((n, dim_total), dtype=np.float32)
    delta_norm_series = np.zeros(n, dtype=np.float32)
    per_organ_delta = {o: np.zeros(n, dtype=np.float32) for o in ORGAN_ORDER}
    fidelity_series = {o: np.zeros(n, dtype=np.float32) for o in ORGAN_ORDER}
    integration_series = np.zeros(n, dtype=np.float32)
    self_coh_series = np.zeros(n, dtype=np.float32)
    organ_slices = _organ_slices()

    t0 = time.monotonic()
    for b in range(n):
        hb.tick()
        mode.post_tick(hb)  # control3 sharing happens here
        internal_arrays = {o.name: o.get_state_array() for o in hb.organs}
        if b == 0:
            cf.update_rolling(internal_arrays)
        integ = float(hb.pneuma.get_state().integration_level)
        coh = float(hb.eidolon.get_state().self_coherence)
        comp = cf.compose(internal_arrays, integration_level=integ, self_coherence=coh)
        if b > 0:
            cf.update_rolling(internal_arrays)

        int_vec = _concat(internal_arrays)
        ext_vec = _concat(comp.external_arrays)
        internal[b] = int_vec
        external[b] = ext_vec
        diff_vec = int_vec - ext_vec
        delta_norm_series[b] = float(np.linalg.norm(diff_vec))
        for o in ORGAN_ORDER:
            sl = organ_slices[o]
            per_organ_delta[o][b] = float(np.linalg.norm(diff_vec[sl]))
            fidelity_series[o][b] = comp.fidelity_factors[o]
        integration_series[b] = integ
        self_coh_series[b] = coh

    dt_history = None
    if hasattr(hb, "dt_history") and hb.dt_history:
        dt_history = np.array(hb.dt_history, dtype=np.float32)
    elapsed = time.monotonic() - t0
    return ControlTrialResult(
        config=cfg,
        internal_trajectory=internal,
        external_trajectory=external,
        delta_norm_series=delta_norm_series,
        per_organ_delta=per_organ_delta,
        fidelity_series=fidelity_series,
        integration_series=integration_series,
        self_coherence_series=self_coh_series,
        dt_history=dt_history,
        elapsed_s=elapsed,
    )
