"""Calibration session inspection CLI (v1.8.2, Checkpoint PP).

Read-only inspection of F6 (zone) and F8 (meta-cog) calibration sessions
persisted to disk by `axioma.interface.calibration.CalibrationRecorder`
(via `POST /admin/calibration/session/end`).

The recorder writes one JSON file per session to
`results/phase_f/calibration_session_<id>.json` (configurable via
`results_root`). This CLI lists, summarises, and drills into those files
without booting the substrate.

Use cases:
  - "What calibration sessions have I run?" → --list (default)
  - "What's the detail of this specific session?" → --session ID_PREFIX
  - "Across all sessions, what's the aggregate verdict?" → --summary
  - "Only show zone calibrations / only meta_cog" → --kind zone | --kind meta_cog

Usage:
    python -m axioma.tools.calibration_inspect [ROOT] [OPTIONS]

    ROOT: calibration results directory (default: results/phase_f).

Examples:
    # List all calibration sessions
    python -m axioma.tools.calibration_inspect

    # Show only zone sessions (F6 validation)
    python -m axioma.tools.calibration_inspect --kind zone

    # Drill into one session by session_id prefix (first 8 chars usually unique)
    python -m axioma.tools.calibration_inspect --session a3f1b2c4

    # Aggregate summary across all sessions in the directory
    python -m axioma.tools.calibration_inspect --summary

    # Aggregate over zone-only sessions
    python -m axioma.tools.calibration_inspect --summary --kind zone
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _load_session(path: Path) -> dict[str, Any] | None:
    """Load a session JSON file. Returns None on decode failure."""
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        print(
            f"failed to decode {path}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None
    if not isinstance(data, dict):
        print(
            f"{path}: decoded as {type(data).__name__}, expected dict",
            file=sys.stderr,
        )
        return None
    return data


def _discover_sessions(root: Path) -> list[Path]:
    """Find all calibration_session_*.json files under root, sorted by name."""
    if not root.exists():
        return []
    return sorted(root.glob("calibration_session_*.json"))


def _filter_by_kind(sessions: list[dict[str, Any]], kind: str | None) -> list[dict[str, Any]]:
    if kind is None:
        return sessions
    return [s for s in sessions if s.get("kind") == kind]


def cmd_list(root: Path, kind: str | None) -> int:
    """Print a table of all calibration sessions in root, optionally filtered."""
    paths = _discover_sessions(root)
    if not paths:
        print(f"No calibration sessions in {root}")
        return 0

    sessions: list[tuple[Path, dict[str, Any]]] = []
    for p in paths:
        data = _load_session(p)
        if data is None:
            continue
        sessions.append((p, data))

    if kind is not None:
        sessions = [(p, d) for (p, d) in sessions if d.get("kind") == kind]
        if not sessions:
            print(f"No calibration sessions in {root} matching --kind {kind}")
            return 0

    print(f"{len(sessions)} calibration sessions in {root}"
          + (f" (filter: --kind {kind})" if kind else ""))
    print()
    header = (
        f"{'SESSION_ID':<10}  {'KIND':<9}  {'TASK_TYPE':<15}  "
        f"{'N_PAIRS':>7}  {'KAPPA/ACC':>10}  {'VERDICT':<18}"
    )
    print(header)
    print("-" * len(header))
    # Sort by started_at_beat (or filename if absent) — most-recent first
    sessions.sort(
        key=lambda t: t[1].get("started_at_beat", 0),
        reverse=True,
    )
    for _path, data in sessions:
        sid = str(data.get("session_id", "?"))[:8]
        skind = str(data.get("kind", "?"))
        task = str(data.get("task_type", "?"))[:15]
        n = data.get("n_pairs", 0)
        # Zone sessions have `kappa`; meta_cog has `accuracy_rate`
        if skind == "zone":
            metric = data.get("kappa")
        elif skind == "meta_cog":
            metric = data.get("accuracy_rate")
        else:
            metric = None
        metric_str = f"{metric:.3f}" if isinstance(metric, int | float) else "—"
        verdict = str(data.get("verdict", "?"))[:18]
        print(
            f"{sid:<10}  {skind:<9}  {task:<15}  "
            f"{n!s:>7}  {metric_str:>10}  {verdict:<18}"
        )
    return 0


def cmd_session(root: Path, prefix: str) -> int:
    """Show full detail for a session whose session_id starts with PREFIX."""
    paths = _discover_sessions(root)
    matches: list[tuple[Path, dict[str, Any]]] = []
    for p in paths:
        data = _load_session(p)
        if data is None:
            continue
        if str(data.get("session_id", "")).startswith(prefix):
            matches.append((p, data))
    if not matches:
        print(f"no session_id starts with {prefix!r} in {root}", file=sys.stderr)
        return 2
    for path, data in matches:
        print(f"=== {path.name} ===")
        # Summary fields first, then pairs
        summary_keys = [
            "session_id", "kind", "task_type", "n_pairs", "agreements",
            "kappa", "accuracy_rate", "f8_verdict", "accuracy_verdict",
            "verdict", "operator_distribution", "system_distribution",
            "duration_minutes", "started_at_beat",
        ]
        for k in summary_keys:
            if k in data:
                print(f"  {k}: {data[k]}")
        pairs = data.get("pairs", [])
        if pairs:
            print(f"  pairs: {len(pairs)} (first 5 + last 5 shown)")
            sample = pairs[:5] + (pairs[-5:] if len(pairs) > 10 else [])
            for p in sample:
                conf = p.get("confidence")
                conf_str = f" conf={conf:.2f}" if isinstance(conf, int | float) else ""
                print(
                    f"    beat={p.get('beat_no')}: "
                    f"operator={p.get('operator')!r:>15}  "
                    f"system={p.get('system')!r:>15}"
                    f"{conf_str}"
                )
        print()
    return 0


def cmd_summary(root: Path, kind: str | None) -> int:
    """Aggregate metric summary across all (or filtered) sessions in root."""
    paths = _discover_sessions(root)
    if not paths:
        print(f"No calibration sessions in {root}")
        return 0

    all_sessions: list[dict[str, Any]] = []
    for p in paths:
        data = _load_session(p)
        if data is None:
            continue
        all_sessions.append(data)
    sessions = _filter_by_kind(all_sessions, kind)
    if not sessions:
        msg = "" if kind is None else f" matching --kind {kind}"
        print(f"No calibration sessions in {root}{msg}")
        return 0

    by_kind: dict[str, list[dict[str, Any]]] = {}
    for s in sessions:
        by_kind.setdefault(s.get("kind", "unknown"), []).append(s)

    print(f"Aggregate across {len(sessions)} sessions in {root}"
          + (f" (filter: --kind {kind})" if kind else ""))
    print()

    for skind, group in sorted(by_kind.items()):
        print(f"== kind: {skind} ({len(group)} sessions) ==")
        n_pairs = sum(s.get("n_pairs", 0) for s in group)
        print(f"  total pairs:    {n_pairs}")
        verdicts = Counter(s.get("verdict", "?") for s in group)
        print(f"  verdicts:       {dict(verdicts)}")
        if skind == "zone":
            kappas = [s["kappa"] for s in group if isinstance(s.get("kappa"), int | float)]
            if kappas:
                print(f"  mean kappa:     {statistics.mean(kappas):.3f}")
                print(f"  min/max kappa:  {min(kappas):.3f} / {max(kappas):.3f}")
        if skind == "meta_cog":
            accs = [
                s["accuracy_rate"]
                for s in group
                if isinstance(s.get("accuracy_rate"), int | float)
            ]
            if accs:
                print(f"  mean accuracy:  {statistics.mean(accs):.3f}")
                print(f"  min/max acc.:   {min(accs):.3f} / {max(accs):.3f}")
        # Task-type distribution
        task_types = Counter(s.get("task_type", "?") for s in group)
        if task_types:
            print(f"  task_types:     {dict(task_types)}")
        print()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        prog="python -m axioma.tools.calibration_inspect",
        description="Inspect F6/F8 calibration session results.",
    )
    p.add_argument(
        "root",
        type=Path,
        nargs="?",
        default=Path("results/phase_f"),
        help="calibration results directory (default: results/phase_f)",
    )
    action = p.add_mutually_exclusive_group()
    action.add_argument(
        "--list", action="store_true",
        help="list all sessions (default)",
    )
    action.add_argument(
        "--session", type=str, default=None, metavar="PREFIX",
        help="show full detail for a session whose session_id starts with PREFIX",
    )
    action.add_argument(
        "--summary", action="store_true",
        help="aggregate metric summary across all (or filtered) sessions",
    )
    p.add_argument(
        "--kind", type=str, default=None, choices=("zone", "meta_cog"),
        help="filter --list / --summary by session kind",
    )
    args = p.parse_args()

    # --kind with --session would be ambiguous (the prefix uniquely identifies);
    # silently ignore --kind in that case.
    if args.session is not None:
        return cmd_session(args.root, args.session)
    if args.summary:
        return cmd_summary(args.root, args.kind)
    # default: --list
    return cmd_list(args.root, args.kind)


if __name__ == "__main__":
    raise SystemExit(main())
