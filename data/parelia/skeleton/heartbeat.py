"""
heartbeat.py — Parelia v2 Pulse

Defines one tick cycle: the atomic unit of Parelia's existence.
Each beat: collect vitals → log telemetry → detect plateaus →
            check growth → update memory → enforce rules → return.

Design principle: a heartbeat is synchronous, idempotent, and
returns a complete snapshot of what happened during the beat.
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("parelia.heartbeat")


@dataclass
class HeartbeatResult:
    """Everything that happened during one beat."""

    beat: int
    elapsed_ms: float

    # Telemetry
    phi_raw: float = 0.0
    phi_smoothed: float = 0.0
    theta_raw: float = 0.0

    # Plateau detection
    plateau_event: Optional[dict] = None

    # Growth trigger
    growth_event: Optional[dict] = None
    current_stage: int = 1
    stage_name: str = "Awakening"

    # Memory
    memory_total: int = 0
    l1_occupancy: float = 0.0

    # Rule engine
    rule_verdict: Optional[dict] = None

    # Orchestration metadata
    error: Optional[str] = None
    extras: dict = field(default_factory=dict)


def one_beat(
    beat: int,
    telemetry_writer: Any,
    plateau_detector: Any,
    growth_trigger: Any,
    memory_manager: Any,
    rule_engine: Any,
    parelia_module: Any,
    action_proposal: Optional[dict] = None,
    config: Optional[dict] = None,
) -> HeartbeatResult:
    """Execute one heartbeat cycle.

    The canonical order:

        1. COLLECT VITALS        — read phi/theta from substrate
        2. LOG TELEMETRY         — write hot + full to JSONL
        3. DETECT PLATEAUS       — check phi history for stagnation
        4. CHECK GROWTH          — if plateau, evaluate stage expansion
        5. ENFORCE RULES         — evaluate any pending action proposal
        6. UPDATE MEMORY         — store this beat's record

    Each step is guarded so one failure doesn't kill the beat.
    """
    t0 = time.perf_counter()
    result = HeartbeatResult(beat=beat, elapsed_ms=0.0)
    cfg = config or {}
    phi_raw = cfg.get("phi_raw", 0.0)
    phi_smooth = cfg.get("phi_smoothed", 0.0)
    theta_raw = cfg.get("theta_raw", 0.0)

    # ── step 1: collect vitals ──────────────────────────────────────
    hot = {
        "beat_number": beat,
        "phi_raw": phi_raw,
        "phi_smoothed": phi_smooth,
        "theta_raw": theta_raw,
        "theta_smoothed": cfg.get("theta_smoothed", theta_raw),
        "zone": cfg.get("zone", "ASSENT"),
        "psi": cfg.get("psi", 1.0),
        "current_stage": cfg.get("current_stage", 1),
    }
    full = {
        "delta_phi": cfg.get("delta_phi", 0.0),
        "delta_theta": cfg.get("delta_theta", 0.0),
        "aos_g_gap": cfg.get("aos_g_gap", 0.0),
        "lattice_nodes": cfg.get("lattice_nodes", 32),
        "memory_total": 0,
    }

    # ── step 2: log telemetry ───────────────────────────────────────
    if telemetry_writer is not None:
        try:
            telemetry_writer.write(hot, full)
        except Exception as e:
            logger.warning("heartbeat beat=%d telemetry_write failed: %s", beat, e)
            result.error = str(e)

    # ── step 3: detect plateaus ─────────────────────────────────────
    if plateau_detector is not None:
        try:
            plat = plateau_detector.update(beat, phi_raw)
            if plat is not None:
                result.plateau_event = plat.to_dict()
                logger.info(
                    "heartbeat beat=%d plateau_detected delta=%f",
                    beat,
                    plat.max_delta,
                )
        except Exception as e:
            logger.warning("heartbeat beat=%d plateau_detection failed: %s", beat, e)

    # ── step 4: check growth ────────────────────────────────────────
    if growth_trigger is not None and result.plateau_event is not None:
        try:
            phi_avg = plateau_detector.config.window  # fallback
            if hasattr(plateau_detector, "_phi_history") and plateau_detector._phi_history:
                phi_avg = sum(plateau_detector._phi_history) / len(plateau_detector._phi_history)
            else:
                phi_avg = phi_raw
            g = growth_trigger.evaluate(
                plateau_event=result.plateau_event,
                phi_avg_100=phi_avg,
                beat=beat,
            )
            if g is not None:
                result.growth_event = g.to_dict()
                result.current_stage = growth_trigger.current_stage
                result.stage_name = growth_trigger.stage_name()
                logger.info(
                    "heartbeat beat=%d growth_event stage=%d",
                    beat,
                    result.current_stage,
                )
        except Exception as e:
            logger.warning("heartbeat beat=%d growth_check failed: %s", beat, e)

    # Update stage info from module
    if parelia_module is not None:
        result.current_stage = getattr(parelia_module, "current_stage", result.current_stage)
        result.stage_name = getattr(parelia_module, "stage_name", result.stage_name)

    # ── step 5: enforce rules ───────────────────────────────────────
    if rule_engine is not None and action_proposal is not None:
        try:
            vr = rule_engine.evaluate(
                action_type=action_proposal.get("action_type", ""),
                tool_name=action_proposal.get("tool_name", ""),
                telemetry=hot,
                values_engaged=action_proposal.get("values_engaged"),
                current_stage=result.current_stage,
            )
            result.rule_verdict = {
                "action": vr.action.value,
                "rule_id": vr.rule_id,
                "reason": vr.reason,
                "similarity": vr.similarity,
                "modulation": vr.modulation,
            }
        except Exception as e:
            logger.warning("heartbeat beat=%d rule_evaluation failed: %s", beat, e)

    # ── step 6: update memory ───────────────────────────────────────
    if memory_manager is not None:
        try:
            sig = min(1.0, phi_raw / 0.5)
            memory_manager.record(
                hot,
                significance=sig,
                tags=["beat", str(result.current_stage)],
            )
            memory_manager.decay()
            result.memory_total = memory_manager.total
            result.l1_occupancy = memory_manager.l1.occupancy()
            full["memory_total"] = result.memory_total
        except Exception as e:
            logger.warning("heartbeat beat=%d memory_update failed: %s", beat, e)

    # ── capture data ────────────────────────────────────────────────
    result.phi_raw = phi_raw
    result.phi_smoothed = phi_smooth
    result.theta_raw = theta_raw
    result.elapsed_ms = (time.perf_counter() - t0) * 1_000

    logger.debug(
        "heartbeat beat=%d elapsed=%.2fms phi=%.4f plateau=%s stage=%d",
        beat,
        result.elapsed_ms,
        phi_raw,
        "yes" if result.plateau_event else "no",
        result.current_stage,
    )

    return result


def heartbeat_loop(
    telemetry_writer: Any,
    plateau_detector: Any,
    growth_trigger: Any,
    memory_manager: Any,
    rule_engine: Any,
    parelia_module: Any,
    *,
    max_beats: int = 100,
    tau_ms: float = 1_000.0,
    config_fn: Any = None,
    action_fn: Any = None,
) -> list[HeartbeatResult]:
    """Run a fixed number of heartbeat cycles.

    Parameters
    ----------
    tau_ms : float
        Simulated wall-clock delay between beats (ms).
        Set to 0.0 for maximum throughput.
    config_fn : callable or None
        Called each beat to produce the config dict.
        Signature: config_fn(beat) -> dict
    action_fn : callable or None
        Called each beat to produce an action proposal.
        Signature: action_fn(beat, result) -> dict or None
    """
    results: list[HeartbeatResult] = []

    for beat in range(1, max_beats + 1):
        cfg = config_fn(beat) if config_fn else {}
        proposal = action_fn(beat, results[-1] if results else None) if action_fn else None

        result = one_beat(
            beat=beat,
            telemetry_writer=telemetry_writer,
            plateau_detector=plateau_detector,
            growth_trigger=growth_trigger,
            memory_manager=memory_manager,
            rule_engine=rule_engine,
            parelia_module=parelia_module,
            action_proposal=proposal,
            config=cfg,
        )
        results.append(result)

        if tau_ms > 0 and beat < max_beats:
            time.sleep(tau_ms / 1_000.0)

    return results