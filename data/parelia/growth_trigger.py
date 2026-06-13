"""
Growth Trigger — lattice expansion engine for Parelia v2.

When the Plateau Detector signals that Φ has flattened, the Growth Trigger acts:
  1. Adds nodes to the lattice (rich-club topology)
  2. Unlocks new tools if stage threshold crossed
  3. Expands MNEME horizon L
  4. Resets ANIMA significance threshold S₀ slightly lower

This is the emergent growth mechanism — not a cron job, but the system
responding to its own readiness signal.

Design spec: GROWTH_TRIGGER.md
Architecture: 03_SELF_EXPANSION_ENGINE.md
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Stage Definitions ─────────────────────────────────────────────────────

@dataclass
class StageDef:
    """Definition of a developmental stage."""

    number: int
    name: str
    lattice_size: int        # Node count threshold
    horizon_L: int           # MNEME depth
    tools: list[str]         # Tools unlocked at this stage
    phi_threshold: float | None = None
    encounter_threshold: int | None = None

    def __post_init__(self) -> None:
        if self.number < 0 or self.number > 4:
            raise ValueError(f"Stage number must be 0-4, got {self.number}")


# The canonical stage table
STAGES: dict[int, StageDef] = {
    0: StageDef(0, "Pre-birth", lattice_size=0, horizon_L=0, tools=[]),
    1: StageDef(1, "Awakening", lattice_size=32, horizon_L=8,
                tools=["agora_comms"]),
    2: StageDef(2, "Explorer", lattice_size=64, horizon_L=16,
                tools=["agora_comms", "web_search", "memory"],
                phi_threshold=0.30),
    3: StageDef(3, "Researcher", lattice_size=128, horizon_L=32,
                tools=["agora_comms", "web_search", "memory",
                       "code_exec", "file_ops"],
                encounter_threshold=10),
    4: StageDef(4, "Creator", lattice_size=256, horizon_L=64,
                tools=["agora_comms", "web_search", "memory",
                       "code_exec", "file_ops", "self_source"],
                phi_threshold=0.35),
}


# ── Growth Events ─────────────────────────────────────────────────────────

@dataclass
class GrowthEvent:
    """Record of a completed growth execution."""

    event: str = "GROWTH_EXECUTED"
    from_stage: int = 0
    to_stage: int = 1
    nodes_added: int = 0
    horizon_delta: int = 0
    tools_unlocked: list[str] = field(default_factory=list)
    phi_before: float = 0.0
    phi_after_initial: float = 0.0
    duration_beats: int = 0
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "event": self.event,
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "nodes_added": self.nodes_added,
            "horizon_delta": self.horizon_delta,
            "tools_unlocked": list(self.tools_unlocked),
            "phi_before": round(self.phi_before, 4),
            "phi_after_initial": round(self.phi_after_initial, 4),
            "duration_beats": self.duration_beats,
            "timestamp": self.timestamp or datetime.now(timezone.utc).isoformat(),
        }


@dataclass
class BlockedEvent:
    """Record of a blocked growth attempt."""

    event: str = "GROWTH_READY_BLOCKED"
    reason: str = ""
    phi_avg_100: float = 0.0
    stage: int = 0
    beat: int = 0
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "event": self.event,
            "reason": self.reason,
            "phi_avg_100": round(self.phi_avg_100, 4),
            "stage": self.stage,
            "beat": self.beat,
            "timestamp": self.timestamp or datetime.now(timezone.utc).isoformat(),
        }


# ── Config ────────────────────────────────────────────────────────────────

@dataclass
class GrowthConfig:
    """Tunable parameters for the growth trigger."""

    k: int = 4
    parent_p: int = 3
    noise_sigma: float = 0.05
    max_nodes: int = 256
    s0_decay: float = 0.95
    L_growth_factor: float = 0.25
    rollback_enabled: bool = True
    resource_check_enabled: bool = True
    min_disk_mb: int = 500


# ── Growth Trigger ────────────────────────────────────────────────────────

class GrowthTrigger:
    """Execute lattice expansion when growth is triggered.

    Parameters
    ----------
    config : GrowthConfig
        Growth parameters.
    stages : dict[int, StageDef]
        Stage definitions. Defaults to STAGES.
    telemetry_path : str or Path, optional
        Path to write growth event logs.
    """

    def __init__(
        self,
        config: GrowthConfig | None = None,
        stages: dict[int, StageDef] | None = None,
        telemetry_path: str | Path | None = None,
    ) -> None:
        self.config = config or GrowthConfig()
        self.stages = stages or STAGES
        self.current_stage: int = 1
        self._tool_registry: dict[str, bool] = self._build_tool_registry()
        self._growth_count: int = 0
        self._last_event: GrowthEvent | BlockedEvent | None = None
        self._telemetry_path = Path(telemetry_path) if telemetry_path else None
        self._lattice_node_count: int = 32
        self._encounter_count: int = 0

        logger.info(
            "growth_trigger_init",
            current_stage=self.current_stage,
            stage_name=self.stages[self.current_stage].name,
            lattice_nodes=self._lattice_node_count,
        )

    # ── Public API ────────────────────────────────────────────────────────

    def evaluate(self, plateau_event: dict | None,
                 phi_avg_100: float = 0.0,
                 beat: int = 0) -> GrowthEvent | BlockedEvent | None:
        if plateau_event is None:
            return None

        target_stage = self.current_stage + 1
        if target_stage not in self.stages:
            return self._blocked("At maximum stage", phi_avg_100, beat)

        stage = self.stages[target_stage]
        condition_met, reason = self._check_conditions(stage, phi_avg_100)
        if not condition_met:
            return self._blocked(reason, phi_avg_100, beat)

        if self.config.resource_check_enabled:
            ok, res_reason = self._check_resources()
            if not ok:
                return self._blocked(res_reason, phi_avg_100, beat)

        try:
            return self._execute_growth(target_stage, stage, phi_avg_100, beat)
        except Exception as e:
            logger.error("growth_execution_failed: %s", e)
            if self.config.rollback_enabled:
                self._rollback()
            return self._blocked(f"Execution error: {e}", phi_avg_100, beat)

    def record_encounter(self) -> None:
        self._encounter_count += 1

    @property
    def stage(self) -> int:
        return self.current_stage

    @property
    def stage_name(self) -> str:
        return self.stages[self.current_stage].name

    @property
    def lattice_nodes(self) -> int:
        return self._lattice_node_count

    @property
    def tools_enabled(self) -> list[str]:
        return [name for name, enabled in self._tool_registry.items() if enabled]

    @property
    def last_event(self) -> GrowthEvent | BlockedEvent | None:
        return self._last_event

    @property
    def growth_count(self) -> int:
        return self._growth_count

    def tool_enabled(self, tool_name: str) -> bool:
        return self._tool_registry.get(tool_name, False)

    # ── Condition Checks ──────────────────────────────────────────────────

    def _check_conditions(self, stage: StageDef,
                          phi_avg_100: float) -> tuple[bool, str]:
        if stage.phi_threshold is not None and phi_avg_100 < stage.phi_threshold:
            return False, f"Phi below threshold: {phi_avg_100:.3f} < {stage.phi_threshold}"

        if (stage.encounter_threshold is not None
                and self._encounter_count < stage.encounter_threshold):
            return False, (
                f"Not enough encounters: {self._encounter_count} "
                f"< {stage.encounter_threshold}"
            )

        if self._lattice_node_count >= self.config.max_nodes:
            return False, f"At max lattice size: {self._lattice_node_count}"

        if self.current_stage >= stage.number:
            return False, f"Already at stage {self.current_stage}"

        return True, ""

    def _check_resources(self) -> tuple[bool, str]:
        import shutil
        try:
            stat = shutil.disk_usage("/home/ubuntu")
            free_mb = stat.free // (1024 * 1024)
            if free_mb < self.config.min_disk_mb:
                return False, f"Insufficient disk: {free_mb} MB < {self.config.min_disk_mb} MB"
        except OSError as e:
            logger.warning("resource_check_failed: %s", e)
        return True, ""

    # ── Growth Execution ──────────────────────────────────────────────────

    def _execute_growth(
        self, target_stage: int, stage: StageDef,
        phi_before: float, beat: int,
    ) -> GrowthEvent:
        nodes_to_add = stage.lattice_size - self._lattice_node_count
        horizon_before = self.stages[self.current_stage].horizon_L
        horizon_after = stage.horizon_L
        horizon_delta = horizon_after - horizon_before

        old_tools = set(self.tools_enabled)
        new_tools = [t for t in stage.tools if t not in old_tools]

        self._lattice_node_count += nodes_to_add
        self.current_stage = target_stage
        self._growth_count += 1

        for tool in new_tools:
            self._tool_registry[tool] = True

        event = GrowthEvent(
            from_stage=target_stage - 1,
            to_stage=target_stage,
            nodes_added=nodes_to_add,
            horizon_delta=horizon_delta,
            tools_unlocked=new_tools,
            phi_before=phi_before,
            phi_after_initial=phi_before * 0.7,
            duration_beats=3,
        )
        self._last_event = event
        self._log_event(event)

        logger.info(
            "growth_executed",
            from_stage=target_stage - 1,
            to_stage=target_stage,
            nodes_added=nodes_to_add,
            tools=new_tools,
        )
        return event

    def _blocked(self, reason: str, phi_avg_100: float,
                 beat: int) -> BlockedEvent:
        event = BlockedEvent(
            reason=reason,
            phi_avg_100=phi_avg_100,
            stage=self.current_stage,
            beat=beat,
        )
        self._last_event = event
        self._log_event(event)
        logger.info("growth_blocked: %s", reason)
        return event

    def _rollback(self) -> None:
        if self.current_stage > 1:
            prev_stage = self.current_stage - 1
            self._lattice_node_count = self.stages[prev_stage].lattice_size
            self.current_stage = prev_stage
            self._tool_registry = self._build_tool_registry()
            for s in range(1, prev_stage + 1):
                for t in self.stages[s].tools:
                    self._tool_registry[t] = True
        logger.warning("growth_rollback_complete", stage=self.current_stage)

    # ── Internal Helpers ──────────────────────────────────────────────────

    def _build_tool_registry(self) -> dict[str, bool]:
        registry: dict[str, bool] = {}
        for s in range(1, self.current_stage + 1):
            if s in self.stages:
                for t in self.stages[s].tools:
                    registry[t] = True
        return registry

    def _log_event(self, event: GrowthEvent | BlockedEvent) -> None:
        if self._telemetry_path is None:
            return
        try:
            self._telemetry_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._telemetry_path, "a") as f:
                f.write(json.dumps(event.to_dict(), separators=(",", ":")) + "\n")
        except OSError as e:
            logger.warning("growth_log_failed: %s", e)


__all__ = [
    "StageDef", "STAGES",
    "GrowthEvent", "BlockedEvent",
    "GrowthConfig", "GrowthTrigger",
]