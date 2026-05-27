"""Recovery-history inspection CLI (v1.8.1, Checkpoint OO).

Read-only inspection of the `recovery_protocol` component of a snapshot.
Operates on the on-disk `recovery_protocol.json` written by
`RecoveryProtocol.save_state` — does NOT boot the substrate.

Use cases:
  - "What recovery events happened recently?" → --list (default)
  - "What's the detail of this specific event?" → --event PREFIX
  - "What's the learner's current state?" → --learner
  - "How did the learner adopt over time?" (combined: --learner + grep adoptions_count)

Usage:
    python -m axioma.tools.recovery_inspect ROOT [--current | --target NAME] [filters]

    ROOT: snapshot root (default: data/state/snapshots). The CLI follows the
    `current` symlink (default) or a `--target NAME` you specify.

Examples:
    # List the 20 most recent recovery events in the current snapshot
    python -m axioma.tools.recovery_inspect data/state/snapshots

    # Show full detail for events whose ID starts with "a3f"
    python -m axioma.tools.recovery_inspect data/state/snapshots --event a3f

    # Show only stage-3 events
    python -m axioma.tools.recovery_inspect data/state/snapshots --stage 3

    # Show only real (non-synthetic) events from a specific snapshot
    python -m axioma.tools.recovery_inspect data/state/snapshots \\
        --target 20260527_120000_beat_5000 --real

    # Show learner state (current_params per stage + adoption/reversion counts)
    python -m axioma.tools.recovery_inspect data/state/snapshots --learner
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import msgspec

from ..persistence.snapshot import CURRENT_SYMLINK

_decoder = msgspec.json.Decoder()
_RECOVERY_COMPONENT = "recovery_protocol"


def _resolve_snapshot(root: Path, *, target: str | None, use_current: bool) -> Path | None:
    """Return the snapshot dir to inspect (or None on error)."""
    if target is not None:
        d = root / target
        if not d.exists():
            print(f"snapshot dir not found: {d}", file=sys.stderr)
            return None
        return d
    if use_current:
        cur = root / CURRENT_SYMLINK
        if not cur.exists():
            print(f"no `current` symlink in {root}", file=sys.stderr)
            return None
        return cur.resolve()
    # Default: treat root itself as the snapshot dir (operator passed full path)
    return root


def _load_recovery(snapshot_dir: Path) -> dict[str, Any] | None:
    rp_path = snapshot_dir / f"{_RECOVERY_COMPONENT}.json"
    if not rp_path.exists():
        print(
            f"recovery_protocol.json not found at {rp_path} "
            "(snapshot may not include the recovery component)",
            file=sys.stderr,
        )
        return None
    try:
        data = _decoder.decode(rp_path.read_bytes())
    except Exception as exc:
        print(
            f"failed to decode {rp_path}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None
    if not isinstance(data, dict):
        print(
            f"recovery_protocol.json decoded as {type(data).__name__}, expected dict",
            file=sys.stderr,
        )
        return None
    return data


def _filter_events(
    events: list[dict[str, Any]],
    *,
    stage: int | None,
    synthetic_only: bool,
    real_only: bool,
    limit: int,
) -> list[dict[str, Any]]:
    out = events
    if stage is not None:
        out = [e for e in out if e.get("stage") == stage]
    if synthetic_only:
        out = [e for e in out if e.get("is_synthetic", False)]
    if real_only:
        out = [e for e in out if not e.get("is_synthetic", False)]
    # Most-recent-first
    out = sorted(out, key=lambda e: int(e.get("started_at_beat", 0)), reverse=True)
    return out[:limit]


def cmd_list(
    recovery_data: dict[str, Any],
    *,
    stage: int | None,
    synthetic_only: bool,
    real_only: bool,
    limit: int,
) -> int:
    """Print a table of recovery events (filtered, most-recent first)."""
    history = recovery_data.get("history", [])
    if not isinstance(history, list):
        print(
            f"recovery_protocol.history decoded as {type(history).__name__}, expected list",
            file=sys.stderr,
        )
        return 2
    events = _filter_events(
        history,
        stage=stage, synthetic_only=synthetic_only, real_only=real_only, limit=limit,
    )
    total = len(history)
    print(f"recovery history: {total} total events; showing {len(events)} (most recent first)")
    if stage is not None:
        print(f"  filter: stage={stage}")
    if synthetic_only:
        print("  filter: --synthetic")
    if real_only:
        print("  filter: --real")
    if not events:
        print("\n(no events match the filter)")
        return 0
    print()
    print(f"{'EVENT_ID':<10}  {'STAGE':>5}  {'START':>8}  {'END':>8}  "
          f"{'COMPOSITE':>10}  {'SYNTH':>5}  {'FINAL':>5}")
    print("-" * 70)
    for e in events:
        eid_short = str(e.get("event_id", "?"))[:8]
        stage_val = e.get("stage", "?")
        start = e.get("started_at_beat", "?")
        end = e.get("ended_at_beat", "?")
        q = e.get("quality", {})
        composite = q.get("composite_score", "?") if isinstance(q, dict) else "?"
        synth = "yes" if e.get("is_synthetic", False) else "no"
        final = "yes" if e.get("quality_finalized", False) else "no"
        composite_str = f"{composite:.3f}" if isinstance(composite, int | float) else str(composite)
        print(
            f"{eid_short:<10}  {stage_val!s:>5}  {start!s:>8}  {end!s:>8}  "
            f"{composite_str:>10}  {synth:>5}  {final:>5}"
        )
    return 0


def cmd_event(recovery_data: dict[str, Any], prefix: str) -> int:
    """Show full detail for events whose event_id starts with PREFIX."""
    history = recovery_data.get("history", [])
    if not isinstance(history, list):
        print(
            f"recovery_protocol.history decoded as {type(history).__name__}, expected list",
            file=sys.stderr,
        )
        return 2
    matches = [
        e for e in history
        if str(e.get("event_id", "")).startswith(prefix)
    ]
    if not matches:
        print(f"no event_id starts with {prefix!r}", file=sys.stderr)
        return 2
    print(f"matched {len(matches)} event(s):")
    for e in matches:
        print()
        print(json.dumps(e, indent=2, sort_keys=True, default=str))
    return 0


def cmd_learner(recovery_data: dict[str, Any]) -> int:
    """Show learner state: current_params per stage + adoption counts + efficacy."""
    learner = recovery_data.get("learner", {})
    if not isinstance(learner, dict):
        print(
            f"learner state decoded as {type(learner).__name__}, expected dict",
            file=sys.stderr,
        )
        return 2
    print("recovery_learner state:")
    print(f"  adoptions_count:    {learner.get('adoptions_count', 0)}")
    print(f"  reversions_count:   {learner.get('reversions_count', 0)}")
    bsp = learner.get("baseline_score_per_stage", {})
    if bsp:
        print(f"  baseline_score:     {dict(bsp)}")
    epi = learner.get("efficacy_per_stage", {})
    if epi:
        print(f"  efficacy_per_stage: {dict(epi)}")
    cbr = learner.get("clean_baseline_remaining", {})
    if cbr:
        print(f"  clean_baseline_remaining: {dict(cbr)}")
    cp = learner.get("current_params", {})
    if cp:
        print("  current_params:")
        for stage_str, params in sorted(cp.items()):
            print(f"    stage {stage_str}:")
            if isinstance(params, dict):
                for k, v in sorted(params.items()):
                    print(f"      {k}: {v}")
            else:
                print(f"      {params}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        prog="python -m axioma.tools.recovery_inspect",
        description="Inspect recovery_protocol history + learner state from a snapshot.",
    )
    p.add_argument(
        "root",
        type=Path,
        nargs="?",
        default=Path("data/state/snapshots"),
        help="snapshot root directory (default: data/state/snapshots). "
             "If --current and --target are both omitted, ROOT is treated as "
             "the snapshot dir directly.",
    )
    src_group = p.add_mutually_exclusive_group()
    src_group.add_argument(
        "--current", action="store_true",
        help="follow the `current` symlink under ROOT (default if ROOT is a "
             "snapshot root rather than a specific snapshot dir)",
    )
    src_group.add_argument(
        "--target", type=str, default=None, metavar="NAME",
        help="inspect a specific snapshot dir under ROOT by name",
    )

    action_group = p.add_mutually_exclusive_group()
    action_group.add_argument(
        "--list", action="store_true",
        help="list recovery events as a table (default)",
    )
    action_group.add_argument(
        "--event", type=str, default=None, metavar="PREFIX",
        help="show full detail for events whose event_id starts with PREFIX",
    )
    action_group.add_argument(
        "--learner", action="store_true",
        help="show learner state (current_params + adoption/reversion counts)",
    )

    # Filters for --list
    p.add_argument("--stage", type=int, default=None, metavar="N",
                   help="--list filter: only show events at stage N")
    synth_group = p.add_mutually_exclusive_group()
    synth_group.add_argument("--synthetic", action="store_true",
                             help="--list filter: only show synthetic (F4 pretrain) events")
    synth_group.add_argument("--real", action="store_true",
                             help="--list filter: only show non-synthetic events")
    p.add_argument("--limit", type=int, default=20, metavar="N",
                   help="--list filter: limit to N most recent events (default: 20)")

    args = p.parse_args()

    # If neither --current nor --target was given AND ROOT looks like a snapshot dir
    # (contains recovery_protocol.json directly), treat ROOT as the snapshot dir.
    # Otherwise, default to --current behavior.
    use_current = args.current
    if not args.current and not args.target:
        # Decide: is args.root a snapshot dir or a root?
        rp_at_root = args.root / f"{_RECOVERY_COMPONENT}.json"
        if rp_at_root.exists():
            # ROOT IS a snapshot dir
            snapshot_dir = args.root
        else:
            # Default to --current
            use_current = True
            snapshot_dir = _resolve_snapshot(args.root, target=None, use_current=True)
    else:
        snapshot_dir = _resolve_snapshot(args.root, target=args.target, use_current=use_current)

    if snapshot_dir is None:
        return 2

    recovery_data = _load_recovery(snapshot_dir)
    if recovery_data is None:
        return 2

    if args.event is not None:
        return cmd_event(recovery_data, args.event)
    if args.learner:
        return cmd_learner(recovery_data)
    # Default: --list
    return cmd_list(
        recovery_data,
        stage=args.stage,
        synthetic_only=args.synthetic,
        real_only=args.real,
        limit=args.limit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
