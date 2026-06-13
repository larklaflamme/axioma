#!/usr/bin/env python3
"""
Parelia v2 — Main Entry Point.

Starts the heartbeat loop, loads a preset config, and drives the
orchestrator through its lifecycle.

Usage:
    python3 /home/ubuntu/parelia_v2/run.py                  # default: newborn
    python3 /home/ubuntu/parelia_v2/run.py --preset explorer
    python3 /home/ubuntu/parelia_v2/run.py --beats 200
    python3 /home/ubuntu/parelia_v2/run.py --headless        # no simulation
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure src/ is on path
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from src.orchestrator import PareliaOrchestrator


# ── config loading ─────────────────────────────────────────────────

PRESETS_DIR = _HERE / "config" / "presets"


def load_preset(name: str = "newborn") -> dict:
    """Load a preset JSON config by name."""
    path = PRESETS_DIR / f"{name}.json"
    if not path.exists():
        available = sorted(p.stem for p in PRESETS_DIR.glob("*.json"))
        print(f"[run] Unknown preset '{name}'. Available: {available}")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


# ── simulation data generators ────────────────────────────────────

def simulate_hot(beat: int, phi: float = 0.25, theta: float = 0.02,
                 similarity: float = 0.85, boundary: float = 1.0,
                 node_count: int = 32, **overrides) -> dict:
    """Generate a realistic hot dict for simulated modes."""
    d: dict[str, Any] = {
        "beat_number": beat,
        "frequency_hz": 1.0,
        "phi_raw": phi,
        "phi_smoothed": phi * 0.96 + 0.01,
        "phi_trend": 0.0,
        "raw_similarity": similarity,
        "theta": theta,
        "theta_deviation": theta * 0.5,
        "boundary_value": boundary,
        "node_count": node_count,
        "edge_count": int(node_count * 2.4),
        "predictive_error": 0.02,
        "state_entropy": 0.3,
        "assent_state": 0,
        "workspace_occupancy": 0.3,
        "sieve_pressure": 0.4,
    }
    d.update(overrides)
    return d


def simulate_full(beat: int) -> dict:
    """Generate a realistic full dict for simulated modes."""
    return {
        "pneuma": {"load": 0.5, "capacity": 1.0},
        "nous":   {"contradictions": 0},
        "anima":  {"valence": 0.3, "arousal": 0.4},
        "mneme":  {"trace_count": min(beat, 128)},
        "eidolon": {"stability": 0.9},
        "lattice": {
            "last_epsilon": 0.05,
            "last_g_S": 0.8,
        },
    }


# ── callbacks ─────────────────────────────────────────────────────

def on_growth_callback(decision) -> None:
    """Called when PareliaModule triggers a growth event."""
    print(f"[growth] beat={decision.beat}: +{decision.nodes_added} nodes, "
          f"stage {decision.previous_stage}→{decision.new_stage}, "
          f"tools={decision.tools_unlocked}")


def on_stage_change_callback(old_stage: int, new_stage: int,
                             tools: list[str]) -> None:
    """Called when PareliaModule transitions a stage."""
    print(f"[stage] {old_stage} → {new_stage}: unlocked {tools}")


def on_verdict_callback(verdict) -> None:
    """Called when the rule engine issues a verdict."""
    if verdict.action.name in ("DENY", "FLAG", "ESCALATE"):
        print(f"[rules] {verdict.action.name}: {verdict.reason}")


# ── main loop ─────────────────────────────────────────────────────

def run_simulation(orch: PareliaOrchestrator, total_beats: int = 100,
                   headless: bool = False) -> None:
    """Run a simulated heartbeat loop.

    After 40 beats of stable low-theta, inject a plateau signal so the
    growth machinery can be observed.
    """
    node_count = 32
    phi = 0.25
    theta = 0.02
    similarity = 0.85
    boundary = 1.0

    if not headless:
        print(f"[run] Starting simulation ({total_beats} beats, headless={headless})")
        print(f"[run] 40 beats of stability → 30 beats of plateau signal → "
              f"30 beats recovery")

    for b in range(1, total_beats + 1):
        # Inject plateau: beats 41-70, clamp all signals flat
        if 41 <= b <= 70:
            phi = 0.25
            theta = 0.08          # slightly elevated but flat
            similarity = 0.83     # flat
            boundary = 1.0        # stable

        # After beat 70, let theta recover
        if b > 70:
            theta = max(0.02, theta - 0.01)

        hot = simulate_hot(
            beat=b,
            phi=phi,
            theta=theta,
            similarity=similarity,
            boundary=boundary,
            node_count=node_count,
        )
        full = simulate_full(b)

        result = orch.tick(hot, full)

        # Sync the orchestrator's node count with whatever PareliaModule set
        if result.growth_decision:
            node_count = result.growth_decision.nodes_after

        # Update internal node_count for subsequent beats
        hot["node_count"] = node_count

        if not headless and (b <= 5 or b % 20 == 0 or result.growth_decision):
            print(f"  beat {b:4d} | φ={phi:.3f} θ={theta:.3f} "
                  f"sim={similarity:.3f} | "
                  f"stage={result.vitals['parelia']['stage']} "
                  f"nodes={result.vitals['parelia']['node_count']} "
                  f"{'↗ GROWTH' if result.growth_decision else ''}"
                  f"{' ⚑ PLATEAU' if result.plateau and result.plateau.is_plateau else ''}")

        # Sleep to approximate real-time (optional)
        # time.sleep(0.01)

    # Print final summary
    s = orch.summary()
    print()
    print("═══ Session Summary ═══")
    print(f"  Beats:           {s['beats']}")
    print(f"  Plateau events:  {s['plateaus_fired']}")
    print(f"  Growth events:   {s['growth_events']}")
    print(f"  Stage:           {s['current_stage']} ({s['stage_name']})")
    print(f"  Nodes:           {s['node_count']}")
    print(f"  Tools unlocked:  {s['tools_unlocked']}")
    print(f"  Rule eval count: {s['rule_evaluations']}")
    print(f"  Verdicts:        {s['allows']} allow / {s['denies']} deny / "
          f"{s['modulations']} modulate")


# ── entry point ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Parelia v2 — Heartbeat Loop")
    parser.add_argument("--preset", default="newborn",
                        help="Config preset (newborn, explorer, mature, researcher, composer)")
    parser.add_argument("--beats", type=int, default=100,
                        help="Number of simulated beats (default: 100)")
    parser.add_argument("--headless", action="store_true",
                        help="Minimal output")
    args = parser.parse_args()

    preset = load_preset(args.preset)

    print(f"Parelia v2 starting — preset={args.preset}, beats={args.beats}")

    orch = PareliaOrchestrator(
        preset=args.preset,
        on_growth=on_growth_callback,
        on_stage_change=on_stage_change_callback,
        on_verdict=on_verdict_callback,
        plateau_window=50,
        growth_k=preset.get("kappa", 0.8) * 5,  # scale preset's kappa to nodes
    )

    run_simulation(orch, total_beats=args.beats, headless=args.headless)

    orch.shutdown()
    print("[run] Done.")


if __name__ == "__main__":
    main()