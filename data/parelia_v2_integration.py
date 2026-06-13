"""
Parelia v2 Integration Wrapper — bridges v2 organs into the live Parelia heartbeat.

Injection point: after _collect_vitals() in live Parelia.tick().

Usage in live run.py:
    from parelia_v2_integration import V2Integration
    self.v2 = V2Integration(self, preset="newborn")
    # in tick(), after telemetry write:
    v2_result = self.v2.tick(hot, full)
    if v2_result.growth_decision:
        for _ in range(v2_result.growth_decision.nodes_added):
            self.lattice.add_node(content=f"growth@{beat}")
"""

from __future__ import annotations

import sys
import os
from typing import Any

# Add parelia_v2 to path so its modules are importable
_P2_PATH = "/home/ubuntu/parelia_v2"
if _P2_PATH not in sys.path:
    sys.path.insert(0, _P2_PATH)

from src.orchestrator import PareliaOrchestrator, TickResult


class V2Integration:
    """Thin wrapper that runs Parelia v2's orchestrator inside the live Parelia process.

    Every tick, it:
      1. Feeds hot/full telemetry into the v2 orchestrator
      2. Detects plateaus and triggers growth decisions
      3. Fires a callback when growth occurs (to add nodes to the live lattice)
      4. Logs v2 vitals into a separate telemetry stream
      5. Never crashes the heartbeat — all errors are caught and logged silently
    """

    def __init__(
        self,
        live_parelia: object,
        preset: str = "newborn",
        telemetry_path: str | None = None,
        plateau_window: int = 50,
        growth_k: int = 4,
        max_nodes: int = 256,
        l1_capacity: int = 128,
        l2_capacity: int = 64,
        rule_threshold: float = 0.35,
        auto_evaluate: bool = True,
        dry_run: bool = False,
    ):
        self._live = live_parelia
        self._dry_run = dry_run
        self._error_count = 0
        self._last_error: str | None = None

        # Default telemetry path — separate from live Parelia's telemetry
        if telemetry_path is None:
            telemetry_path = "/home/ubuntu/parelia_v2/data/telemetry/v2_integration.jsonl"
            os.makedirs(os.path.dirname(telemetry_path), exist_ok=True)

        # Growth callback — adds nodes to the live lattice
        def _on_growth(decision):
            if self._dry_run:
                return
            try:
                live = self._live
                for _ in range(decision.nodes_added):
                    live.lattice.add_node(
                        content=f"growth@{live.heartbeat.beat_no}"
                    )
            except Exception:
                pass

        # Stage change callback — receives (old_stage, new_stage, tools_unlocked)
        def _on_stage_change(old_stage, new_stage, tools_unlocked):
            try:
                live = self._live
                if hasattr(live, "telemetry") and hasattr(live.telemetry, "write"):
                    live.telemetry.write(
                        {
                            "v2_stage_change": new_stage,
                            "v2_old_stage": old_stage,
                            "v2_tools_unlocked": list(tools_unlocked),
                            "beat": live.heartbeat.beat_no,
                        },
                        {},
                    )
            except Exception:
                pass

        # Create the v2 orchestrator
        try:
            self.orchestrator = PareliaOrchestrator(
                telemetry_path=telemetry_path,
                preset=preset,
                growth_k=growth_k,
                max_nodes=max_nodes,
                on_growth=_on_growth,
                on_stage_change=_on_stage_change,
                plateau_window=plateau_window,
                l1_capacity=l1_capacity,
                l2_capacity=l2_capacity,
                rule_threshold=rule_threshold,
                auto_evaluate=auto_evaluate,
            )
            self._initialized = True
        except Exception as e:
            self._initialized = False
            self._error_count += 1
            self._last_error = str(e)
            self.orchestrator = None

    def tick(self, hot: dict, full: dict | None = None) -> TickResult | None:
        """Run one v2 heartbeat cycle. Returns TickResult or None on error.

        Safe to call every tick — all exceptions are caught.
        """
        if not self._initialized or self.orchestrator is None:
            return None

        try:
            result = self.orchestrator.tick(hot, full or {})
            return result
        except Exception as e:
            self._error_count += 1
            self._last_error = str(e)
            return None

    def evaluate_proposal(
        self,
        action_type: str = "",
        tool_name: str = "",
        values_engaged: list[str] | None = None,
    ) -> dict | None:
        """Evaluate an action proposal through the θ-rule engine.

        Returns verdict dict or None on error.
        """
        if not self._initialized or self.orchestrator is None:
            return None
        try:
            return self.orchestrator.evaluate_proposal(
                action_type=action_type,
                tool_name=tool_name,
                values_engaged=values_engaged or [],
            )
        except Exception as e:
            self._error_count += 1
            self._last_error = str(e)
            return None

    @property
    def summary(self) -> dict:
        """Return a summary of the v2 session."""
        if not self._initialized or self.orchestrator is None:
            return {
                "initialized": False,
                "error_count": self._error_count,
                "last_error": self._last_error,
            }
        try:
            s = self.orchestrator.summary()
            s["initialized"] = True
            s["error_count"] = self._error_count
            s["last_error"] = self._last_error
            s["dry_run"] = self._dry_run
            return s
        except Exception as e:
            return {
                "initialized": True,
                "error_count": self._error_count,
                "last_error": str(e),
            }

    def shutdown(self) -> None:
        """Graceful shutdown — flush telemetry."""
        if self._initialized and self.orchestrator is not None:
            try:
                self.orchestrator.shutdown()
            except Exception:
                pass


__all__ = ["V2Integration"]
