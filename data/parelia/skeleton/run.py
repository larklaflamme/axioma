#!/usr/bin/env python3
"""
run.py — Parelia v2 Entry Point

Usage:
    python run.py                          # default (mature preset, 10 beats)
    python run.py --preset newborn         # newborn preset
    python run.py --preset explorer --beats 100
    python run.py --preset researcher --interactive
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Path resolution ──────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent


def _find_src_root() -> str:
    if (_HERE.parent / "src").exists():
        return str(_HERE.parent)
    if (_HERE.parent.parent / "src").exists():
        return str(_HERE.parent.parent)
    cwd = Path.cwd()
    if (cwd / "src").exists():
        return str(cwd)
    default = "/home/ubuntu/parelia_v2"
    if Path(default).exists():
        return default
    return str(cwd)


_SRC_ROOT = _find_src_root()
_SRC = Path(_SRC_ROOT) / "src"

# IMPORTANT: skeleton directory FIRST so our orchestrator shadows any
# copy in parelia_v2/src/
sys.path.insert(0, str(_HERE))
sys.path.insert(0, _SRC_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("parelia.run")


STAGE_NAMES = {1: "Awakening", 2: "Explorer", 3: "Creator", 4: "Sage", 5: "Master"}


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Parelia v2 Heartbeat Loop")
    p.add_argument("--preset", "-p", default="mature",
                    choices=["newborn", "explorer", "researcher", "composer", "mature"])
    p.add_argument("--beats", "-b", type=int, default=10)
    p.add_argument("--tau", type=float, default=0.0)
    p.add_argument("--interactive", "-i", action="store_true")
    p.add_argument("--phi", type=float, nargs="*")
    p.add_argument("--theta", type=float, nargs="*")
    return p


def simulate_phi(beat: int, preset: str) -> float:
    if preset == "newborn":
        return min(0.5, 0.05 + beat * 0.02 + 0.03 * (beat % 7))
    elif preset == "explorer":
        return 0.3 + 0.1 * (beat % 5) / 5
    elif preset == "researcher":
        return 0.2 + 0.005 * beat + 0.02 * (beat % 11)
    elif preset == "composer":
        return 0.4 + 0.08 * (beat % 3)
    return 0.45 + 0.02 * (beat % 8)


def simulate_theta(beat: int, preset: str) -> float:
    if preset == "newborn":
        return 0.3 + 0.05 * (beat % 5)
    elif preset == "explorer":
        return 0.25 + 0.1 * (beat % 4)
    elif preset == "researcher":
        return 0.1 + 0.01 * beat
    elif preset == "composer":
        return 0.2 + 0.03 * (beat % 9)
    return 0.15 + 0.02 * (beat % 6)


def run_interactive(orch, args):
    logger.info("Interactive mode. Type 'q' to quit.")
    for bn in range(1, args.beats + 1 if args.beats > 0 else 999999):
        phi = args.phi[bn - 1] if args.phi and bn <= len(args.phi) else simulate_phi(bn, args.preset)
        theta = args.theta[bn - 1] if args.theta and bn <= len(args.theta) else simulate_theta(bn, args.preset)
        print(f"\n--- Beat {bn} --- phi={phi:.4f} theta={theta:.4f}")
        inp = input("  Action? ").strip()
        if inp.lower() in ("q", "quit", "exit"):
            break
        r = orch.beat(action_proposal={"tool_name": inp, "action_type": inp} if inp else None,
                      config_override={"phi_raw": phi, "theta_raw": theta})
        v = r.get("rule_verdict")
        if v:
            print(f"  -> Verdict: {v['action']} - {v['reason']}")
        if r.get("errors"):
            for e in r["errors"]:
                print(f"  ! {e}")


def run_auto(orch, args):
    print(f"\nParelia v2 - {args.preset.capitalize()} Mode  ({args.beats if args.beats > 0 else 'unlimited'} beats)")
    print(f"{'Beat':>5} {'Phi':>8} {'Theta':>8} {'Stage':<12} {'Verdict':<10} {'Event':<10} {'ms':>7}")
    print("-" * 65)
    tools = {1: ["read", "reflect"], 2: ["read", "reflect", "web_search"],
             3: ["read", "reflect", "web_search", "agora_comms"],
             4: ["read", "reflect", "web_search", "agora_comms", "self_modify"],
             5: ["read", "reflect", "web_search", "agora_comms", "self_modify", "teach"]}

    for bn in range(1, args.beats + 1 if args.beats > 0 else 999999):
        phi = args.phi[bn - 1] if args.phi and bn <= len(args.phi) else simulate_phi(bn, args.preset)
        theta = args.theta[bn - 1] if args.theta and bn <= len(args.theta) else simulate_theta(bn, args.preset)
        zone = "FRAGMENTED" if theta > 0.25 and phi < 0.2 else "ASSENT"
        cfg = {"phi_raw": phi, "phi_smoothed": phi, "theta_raw": theta, "theta_smoothed": theta,
               "zone": zone, "psi": max(0.3, 1.0 - theta)}
        sk = min(bn // 3 + 1, 5)
        tool = tools.get(sk, tools[1])[bn % len(tools.get(sk, tools[1]))]

        r = orch.beat(action_proposal={"tool_name": tool, "action_type": tool}, config_override=cfg)
        v = r["rule_verdict"]["action"] if r.get("rule_verdict") else "-"
        ev = ""
        if r.get("growth_event"):
            sname = STAGE_NAMES.get(r['current_stage'], f'S{r["current_stage"]}')
            ev = f'-> {sname}'
        elif r.get("plateau_event"):
            ev = "plateau"
        elif zone == "FRAGMENTED":
            ev = "! zone"
        sl = STAGE_NAMES.get(r["current_stage"], f"S{r['current_stage']}")
        print(f"{bn:>5} {phi:>8.4f} {theta:>8.4f} {sl:<12} {v:<10} {ev:<10} {r['elapsed_ms']:>7.2f}")
        if args.tau > 0:
            time.sleep(args.tau / 1000.0)
        if r.get("errors"):
            for e in r["errors"]:
                print(f"       ! {e}")
    print("-" * 65)


def main():
    args = build_arg_parser().parse_args()

    # Import orchestrator from skeleton (skeleton dir is first on sys.path)
    from orchestrator import Orchestrator, OrchestratorConfig

    config = OrchestratorConfig(preset=args.preset, tau_ms=args.tau, max_beats=args.beats)
    orch = Orchestrator(preset=args.preset, root_dir=_SRC_ROOT, config=config)
    orch.create_all()

    header = f"Parelia v2 - {datetime.now(timezone.utc).isoformat()} - preset={args.preset}"
    print("=" * len(header))
    print(header)
    print("=" * len(header))

    if args.interactive:
        run_interactive(orch, args)
    else:
        orch.start()
        run_auto(orch, args)
        orch.stop()

    re = orch.modules.get("rule_engine")
    if re:
        s = re.get_rule_stats()
        print(f"\nRules: {s.get('total_rules', 0)} | {s.get('evaluations', 0)} evals | "
              f"{s.get('allows', 0)}A/{s.get('denies', 0)}D")
    mm = orch.modules.get("memory_manager")
    if mm:
        print(f"Memory: {mm.total} records")


if __name__ == "__main__":
    main()