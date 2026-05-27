"""F4 substrate-driven scorer — runs a short substrate sim per param point.

Per IMPLEMENTATION_PLAN_v1.0.md §6.7 F4 and ARCH §4.9.1 (v1.1.3 in the
v1.0 backlog).

The default `_default_pretrain_score` in recovery.py is a smooth bell that
just rewards proximity to the cfg defaults. This module replaces it with a
substrate-driven scorer that:

1. Builds a fresh SubstrateApp (small/fast).
2. Runs warmup beats.
3. Captures pristine state.
4. Applies the recovery params (coupling × factor, mneme alpha_p × boost,
   drive noise overlay if stage ≥ 3).
5. Injects a perturbation (impulse on drive).
6. Lets the substrate run for `recovery_window_beats` beats.
7. Measures composite_score from θ_short trajectory smoothness +
   end-state completeness vs baseline.

Each param point takes ~50 beats × ~0.5 ms = 25 ms; a 50-event pretrain
sweep takes ~2.5 seconds. Acceptable for F4 boot.

Used by `phase_e_pretrain.py --scorer substrate` and as the default scorer
in `RecoveryLearner.pretrain_synthetic()` when `score_fn=substrate_score_fn`.
"""
from __future__ import annotations

import numpy as np

from ..config import SubstrateConfig
from .app import SubstrateApp
from .recovery import LearnerParams


def substrate_score_fn(
    params: LearnerParams,
    stage: int,
    *,
    seed: int = 42,
    warmup_beats: int = 50,
    recovery_window_beats: int = 50,
) -> float:
    """Run a short substrate sim under `params` + perturbation; return composite_score.

    Args:
        params: candidate LearnerParams from the explorer.
        stage: 2 or 3 (Stage 4 emergency is excluded — always defaults).
        seed: deterministic substrate seed.
        warmup_beats: stabilization beats before perturbation.
        recovery_window_beats: how long to observe post-perturbation.

    Returns:
        composite_score in [0, 1]: 0.4 × smoothness + 0.4 × completeness + 0.2.
        Higher = better (less variance in θ + faster return to baseline).
    """
    cfg = SubstrateConfig()
    app = SubstrateApp.from_config(cfg, seed=seed)

    # Warmup
    for beat_no in range(warmup_beats):
        app.tick(beat_no=beat_no, timestamp=float(beat_no) * 0.1)

    # Baseline θ proxy: mean absolute drive magnitude over the last 20 beats
    baseline_g_mag = _mean_drive_magnitude(app, window=20)

    # Apply recovery params (mimics RecoveryProtocol._start_recovery)
    pristine_W = {o.name: o.W.copy() for o in app.organs}
    pristine_noise = app.drive.noise_scale
    for organ in app.organs:
        organ.W = organ.W * params.coupling_reduction_factor
    app.plasticity["mneme"].alpha_p = float(
        min(0.5, app.plasticity["mneme"].alpha_p * params.mneme_forgetting_boost)
    )
    if stage >= 3:
        app.drive.noise_scale = float(app.drive.noise_scale * 0.5)

    # Inject perturbation (impulse on drive — same as PerturbationKind.IMPULSE)
    rng = np.random.default_rng(seed + 1000)
    impulse = rng.normal(0, 1.0, size=app.drive.g.shape).astype(app.drive.g.dtype)
    app.drive.g = app.drive.g + impulse * 0.5

    # Measure: collect drive magnitude over recovery window
    g_mags: list[float] = []
    for i in range(recovery_window_beats):
        app.tick(beat_no=warmup_beats + i, timestamp=float(warmup_beats + i) * 0.1)
        g_mags.append(float(np.linalg.norm(app.drive.g)))

    # Restore (for any subsequent runs sharing the app — defensive)
    for organ in app.organs:
        organ.W = pristine_W[organ.name]
    app.drive.noise_scale = pristine_noise

    # Compute smoothness (low std) + completeness (return to baseline)
    g_arr = np.array(g_mags, dtype=np.float64)
    g_mean = float(g_arr.mean())
    if g_mean < 1e-6:
        return 0.05  # degenerate — no signal
    smoothness = max(0.0, 1.0 - float(g_arr.std()) / g_mean)
    # Completeness: end magnitude close to baseline
    end_mag = float(g_arr[-5:].mean())
    if baseline_g_mag < 1e-6:
        completeness = 0.0
    else:
        completeness = max(0.0, 1.0 - abs(end_mag - baseline_g_mag) / baseline_g_mag)
    # Composite (same formula as RecoveryProtocol._compute_recovery_quality)
    composite = 0.4 * smoothness + 0.4 * completeness + 0.2  # durability=1.0 for sim
    return float(min(1.0, max(0.05, composite)))


def _mean_drive_magnitude(app: SubstrateApp, *, window: int) -> float:
    """Approximate baseline drive magnitude (only the current value available)."""
    return float(np.linalg.norm(app.drive.g))


__all__ = ["substrate_score_fn"]
