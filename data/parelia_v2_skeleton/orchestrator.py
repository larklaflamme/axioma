"""
Parelia v2 Orchestrator — nervous system.
Wires: TelemetryWriter → PlateauDetector → PareliaModule → MemoryBuffers → RuleEngine
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.telemetry_writer import TelemetryWriter
from src.plateau_detector import PlateauDetector, PlateauEvent
from src.parelia_module import PareliaModule, GrowthDecision
from src.memory_buffers import L1Scratch, L2WorkingMemory
from src.rule_engine import ThetaRuleEngine


@dataclass
class TickResult:
    """Result of one heartbeat cycle."""
    beat: int
    plateau: PlateauEvent | None = None
    growth_decision: GrowthDecision | None = None
    vitals: dict = field(default_factory=dict)
    timestamp: str = ""


class PareliaOrchestrator:
    """Wires all Parelia v2 modules into a live heartbeat cycle.

    Usage:
        orch = PareliaOrchestrator(preset="newborn")
        result = orch.tick(hot, full)
        print(result.vitals)
    """

    def __init__(
        self,
        telemetry_path: str | None = None,
        rules_path: str | None = None,
        preset: str = "newborn",
        growth_k: int = 4,
        max_nodes: int = 256,
        on_growth: Callable | None = None,
        on_stage_change: Callable | None = None,
        on_verdict: Callable | None = None,
        on_plateau: Callable | None = None,
        plateau_window: int = 50,
        l1_capacity: int = 128,
        l2_capacity: int = 64,
        rule_threshold: float = 0.35,
    ):
        # Timestamp for this session
        self._born = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # 1. TelemetryWriter — append-only JSONL beat log
        self.telemetry = TelemetryWriter(
            path=telemetry_path or "/home/ubuntu/parelia_v2/data/telemetry/parelia_telemetry.jsonl",
        )

        # 2. PlateauDetector — multi-signal growth detection
        self.plateau_detector = PlateauDetector(
            window_size=plateau_window,
            on_plateau=on_plateau,
        )

        # 3. PareliaModule — identity, values, stage curriculum, growth decisions
        self.parelia = PareliaModule(
            growth_k=growth_k,
            max_nodes=max_nodes,
            on_growth=on_growth,
            on_stage_change=on_stage_change,
        )

        # 4. MemoryBuffers — L1 scratch (ring) + L2 working memory (decay)
        self.l1 = L1Scratch(capacity=l1_capacity)
        self.l2 = L2WorkingMemory(capacity=l2_capacity)

        # 5. RuleEngine — 3-layer behavioral governance
        self.rule_engine = ThetaRuleEngine(
            parelia_module=self.parelia,
            telemetry_writer=self.telemetry,
            on_verdict=on_verdict,
            default_threshold=rule_threshold,
        )

        # Compile rules from all sources
        self._compile_rules()

        # Runtime state
        self.beat = 0
        self._running = False
        self._tick_history: list[TickResult] = []

    def _compile_rules(self) -> None:
        """Load rules from all four built-in sources."""
        for source in ("values", "stage", "telemetry", "boundary"):
            try:
                count = self.rule_engine.add_source(source)
            except Exception:
                count = 0

    # ── core cycle ──────────────────────────────────────────────────

    def tick(self, hot: dict, full: dict | None = None) -> TickResult:
        """Run one full heartbeat cycle.

        Pipeline:
            1. Log telemetry (TelemetryWriter.write)
            2. Detect plateaus (PlateauDetector.update)
            3. If plateau, trigger growth (PareliaModule.on_plateau)
            4. If growth, store in memory (L1 + L2)
            5. Collect vitals from all modules
        """
        self.beat += 1

        # (1) Log telemetry
        self.telemetry.write(hot, full or {})

        # (2) Detect plateaus
        plateau = self.plateau_detector.update(hot, full)

        # (3) If plateau, check growth
        growth_decision: GrowthDecision | None = None
        if plateau and plateau.is_plateau:
            growth_decision = self.parelia.on_plateau(plateau)

        # (4) If growth, store in memory
        if growth_decision:
            self.l1.write(
                self.beat,
                {
                    "event": "growth",
                    "nodes_added": growth_decision.nodes_added,
                    "new_stage": growth_decision.new_stage,
                    "tools_unlocked": list(growth_decision.tools_unlocked),
                },
                source="growth",
            )
            self.l2.write(
                self.beat,
                {
                    "event": "growth",
                    "nodes_before": growth_decision.nodes_before,
                    "nodes_after": growth_decision.nodes_after,
                    "stage": growth_decision.new_stage,
                    "decision": str(growth_decision),
                },
                source="growth",
                salience=0.9,
            )

        # (5) Collect vitals
        vitals = self._collect_vitals()

        result = TickResult(
            beat=self.beat,
            plateau=plateau,
            growth_decision=growth_decision,
            vitals=vitals,
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

        self._tick_history.append(result)
        return result

    # ── rule evaluation (external proposals) ──────────────────────

    def evaluate_proposal(
        self,
        action_type: str = "",
        tool_name: str = "",
        values_engaged: list[str] | None = None,
    ) -> dict:
        """Evaluate an action proposal through the θ-rule engine.
        
        Returns the verdict dict: {action, reason, rule_id, similarity, ...}
        """
        telemetry = self._build_telemetry_snapshot()
        values_engaged = values_engaged or []
        verdict = self.rule_engine.evaluate(
            action_type=action_type,
            tool_name=tool_name,
            telemetry=telemetry,
            values_engaged=values_engaged,
            current_stage=self.parelia.current_stage,
        )
        return {
            "action": verdict.action.value,
            "reason": verdict.reason,
            "rule_id": verdict.rule_id,
            "similarity": verdict.similarity,
            "weighted_score": verdict.weighted_score,
            "rule_type": verdict.rule_type,
            "modulation": verdict.modulation,
        }

    # ── vitals ─────────────────────────────────────────────────────

    def _collect_vitals(self) -> dict:
        """Gather vitals from all modules into one dict."""
        return {
            "beat": self.beat,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "telemetry": {
                "healthy": self.telemetry.healthy,
                "degraded": self.telemetry.degraded_reason,
                "write_count": self.telemetry.write_count,
            },
            "plateau": {
                "fired_count": self.plateau_detector.fired_count,
                "compose_count": self.plateau_detector.compose_count,
                "last_event": (
                    self.plateau_detector.last_event.to_dict()
                    if self.plateau_detector.last_event
                    else None
                ),
            },
            "parelia": self.parelia.vitals(),
            "memory": {
                "l1": self.l1.vitals(),
                "l2": self.l2.vitals(),
            },
            "rules": self.rule_engine.vitals(),
        }

    def _build_telemetry_snapshot(self) -> dict:
        """Build a telemetry dict from the current state for rule evaluation."""
        pv = self.parelia.vitals()
        pd = self.plateau_detector
        return {
            "beat_number": self.beat,
            "phi_smoothed": pd._phi[-1] if pd._phi else 0.25,
            "theta": pd._theta[-1] if pd._theta else 0.02,
            "raw_similarity": pd._similarity[-1] if pd._similarity else 0.85,
            "zone": "assent",
            "current_stage": pv.get("stage", 0),
            "node_count": pv.get("node_count", 32),
            "theta_deviation": 0.01,
        }

    # ── lifecycle ─────────────────────────────────────────────────

    def summary(self) -> dict:
        """Return a summary of the entire session."""
        return {
            "born": self._born,
            "beats": self.beat,
            "plateaus_fired": self.plateau_detector.fired_count,
            "growth_events": self.parelia.growth_count,
            "current_stage": self.parelia.current_stage,
            "stage_name": self.parelia.stage_name,
            "node_count": self.parelia.current_node_count,
            "tools_unlocked": list(self.parelia.tools_unlocked),
            "rule_evaluations": self.rule_engine.evaluation_count,
            "denies": self.rule_engine._deny_count,
            "allows": self.rule_engine._allow_count,
            "modulations": self.rule_engine._modulate_count,
        }

    def shutdown(self) -> None:
        """Graceful shutdown — flush and close telemetry."""
        self._running = False
        self.telemetry.close()


__all__ = ["PareliaOrchestrator", "TickResult"]