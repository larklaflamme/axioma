"""
Growth Trigger — v0.1 (spec: GROWTH_TRIGGER.md)

When the Plateau Detector signals that Φ has flattened, this module acts:
1. Adds k nodes to the lattice (connected to high-weight parents)
2. Potentially unlocks tools (stage transitions)
3. Expands MNEME horizon L
4. Resets ANIMA significance threshold S₀ slightly lower

This is the emergent growth mechanism — the system responding to its own
readiness signal, not a scheduled upgrade.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from plateau_detector import PlateauEvent

logger = logging.getLogger(__name__)


# ── stage definitions ───────────────────────────────────────────────────────

STAGE_DEFINITIONS: dict[int, dict[str, Any]] = {
    1: {"label": "Awakening",   "min_nodes": 32,  "tools": [],                        "horizon_L": 8},
    2: {"label": "Explorer",    "min_nodes": 64,  "tools": ["web_search", "memory"],  "horizon_L": 16},
    3: {"label": "Researcher",  "min_nodes": 128, "tools": ["code_exec", "file_ops"], "horizon_L": 32},
    4: {"label": "Creator",     "min_nodes": 256, "tools": ["self_source", "image"],  "horizon_L": 64},
}

# Tools unlock permanently once a stage is crossed.
STAGE_UNLOCKED: dict[str, bool] = {t: False for s in STAGE_DEFINITIONS.values() for t in s["tools"]}


# ── growth event ────────────────────────────────────────────────────────────

@dataclass
class GrowthEvent:
    """Record of one growth action."""
    beat: int
    stage: int
    nodes_added: int
    nodes_before: int
    nodes_after: int
    tools_unlocked: list[str]
    L_before: int
    L_after: int
    S0_before: float
    S0_after: float
    plateau: PlateauEvent | None = None


# ── growth trigger ──────────────────────────────────────────────────────────

class GrowthTrigger:
    """Orchestrates lattice expansion when a plateau is detected.

    Parameters
    ----------
    k : int
        Nodes to add per growth event (default 4).
    parent_p : int
        How many parent nodes each new node connects to (default 3).
    noise_sigma : float
        Initialization noise on new edge weights (default 0.05).
    max_nodes : int
        Hard cap on lattice size (default 256).
    growth_enabled : bool
        If False, log but don't act (default True).
    """

    def __init__(
        self,
        k: int = 4,
        parent_p: int = 3,
        noise_sigma: float = 0.05,
        max_nodes: int = 256,
        growth_enabled: bool = True,
    ):
        self.k = k
        self.parent_p = parent_p
        self.noise_sigma = noise_sigma
        self.max_nodes = max_nodes
        self.growth_enabled = growth_enabled

        self.current_stage: int = 1
        self.events: list[GrowthEvent] = []
        self._last_growth_beat = 0

    def evaluate(
        self,
        plateau_event: PlateauEvent,
        lattice_node_count: int,
        current_horizon_L: int,
        current_S0: float,
        current_boundary_value: int | str,
        add_nodes_fn: Callable | None = None,
        unlock_tool_fn: Callable | None = None,
        set_horizon_fn: Callable | None = None,
        set_S0_fn: Callable | None = None,
    ) -> GrowthEvent | None:
        """Evaluate whether to grow. Returns GrowthEvent if growth occurs.

        Parameters
        ----------
        plateau_event : PlateauEvent
            The event from the detector.
        lattice_node_count : int
            Current number of nodes in the lattice.
        current_horizon_L : int
            Current MNEME horizon.
        current_S0 : float
            Current ANIMA significance threshold.
        current_boundary_value : int or str
            Current boundary state (1/0 or ASSENT/FRAGMENTED/etc).
        add_nodes_fn : callable(int) -> int | None
            If provided, called to add k nodes. Should return new total.
            If None, returns a GrowthEvent without side effects (dry-run).
        unlock_tool_fn : callable(str) -> None
            Called with tool name to unlock.
        set_horizon_fn : callable(int) -> None
            Called with new L value.
        set_S0_fn : callable(float) -> None
            Called with new S0 value.
        """
        # Guard: only grow in ASSENT or INTEGRATING states
        boundary_ok = self._boundary_allows_growth(current_boundary_value)
        if not boundary_ok:
            logger.info(
                "Growth suppressed: boundary=%s (requires ASSENT or INTEGRATING)",
                current_boundary_value,
            )
            return None

        # Guard: max_nodes cap
        if lattice_node_count >= self.max_nodes:
            logger.info("Growth suppressed: lattice at cap (%d nodes)", self.max_nodes)
            return None

        if not self.growth_enabled:
            logger.info("Growth disabled by flag — would add %d nodes", self.k)
            return None

        nodes_before = lattice_node_count
        nodes_after = nodes_before

        # ── 1. Add nodes ────────────────────────────────────────────────────
        if add_nodes_fn is not None:
            nodes_after = add_nodes_fn(self.k)
        else:
            nodes_after = nodes_before + self.k  # dry-run estimate

        # ── 2. Stage transition check ──────────────────────────────────────
        tools_unlocked = []
        for stage_num in sorted(STAGE_DEFINITIONS.keys()):
            spec = STAGE_DEFINITIONS[stage_num]
            if stage_num > self.current_stage and nodes_after >= spec["min_nodes"]:
                self.current_stage = stage_num
                logger.info("Stage transition: %s (%d nodes)", spec["label"], nodes_after)
                for tool in spec["tools"]:
                    if not STAGE_UNLOCKED.get(tool, False):
                        STAGE_UNLOCKED[tool] = True
                        tools_unlocked.append(tool)
                        if unlock_tool_fn is not None:
                            unlock_tool_fn(tool)

        # ── 3. Expand horizon L ─────────────────────────────────────────────
        L_before = current_horizon_L
        L_after = L_before
        new_L = L_before + max(1, int(L_before * 0.25))
        if set_horizon_fn is not None:
            set_horizon_fn(new_L)
            L_after = new_L
        else:
            L_after = new_L

        # ── 4. Reset S₀ (lower = more openness to novelty) ──────────────────
        S0_before = current_S0
        S0_after = S0_before
        new_S0 = current_S0 * 0.95  # 5% reduction
        if set_S0_fn is not None:
            set_S0_fn(new_S0)
            S0_after = new_S0
        else:
            S0_after = new_S0

        event = GrowthEvent(
            beat=plateau_event.beat,
            stage=self.current_stage,
            nodes_added=self.k,
            nodes_before=nodes_before,
            nodes_after=nodes_after,
            tools_unlocked=tools_unlocked,
            L_before=L_before,
            L_after=L_after,
            S0_before=S0_before,
            S0_after=S0_after,
            plateau=plateau_event,
        )
        self.events.append(event)
        self._last_growth_beat = plateau_event.beat
        logger.info(
            "Growth: +%d nodes → stage %d (%s), L %d→%d, S₀ %.3f→%.3f, tools=%s",
            self.k, self.current_stage,
            STAGE_DEFINITIONS.get(self.current_stage, {}).get("label", "?"),
            L_before, L_after, S0_before, S0_after, tools_unlocked or "none",
        )
        return event

    def _boundary_allows_growth(self, bval: int | str) -> bool:
        """Allow growth only in ASSENT or INTEGRATING states."""
        if isinstance(bval, int):
            return bval == 1  # self
        if isinstance(bval, str):
            return bval.upper() in ("ASSENT", "INTEGRATING")
        return False

    @property
    def total_nodes_added(self) -> int:
        return sum(e.nodes_added for e in self.events)

    @property
    def last_event(self) -> GrowthEvent | None:
        return self.events[-1] if self.events else None