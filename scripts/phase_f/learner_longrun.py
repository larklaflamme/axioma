"""Recovery learner long-run study.

Per IMPLEMENTATION_PLAN v0.1 §10.1 + ARCH §4.9.1.

Runs the full stack long enough for the recovery learner to:
  - Accumulate ≥ N recovery events
  - Show adoptions / reversions / efficacy transitions
  - Demonstrate the F2 monitoring extension cycle in vivo (not synthetic)

Output: results/phase_f/learner_longrun.json

Usage:
    python scripts/phase_f/learner_longrun.py --events 30
"""
from __future__ import annotations

import argparse
from typing import Any

from _harness import build_phase_e_stack, run_for_beats, write_result


def run_learner_longrun(*, target_events: int, seed: int, max_beats: int = 30000) -> dict[str, Any]:
    """Run until we've accumulated target_events finalized recovery events.

    Uses a frequent perturbation cadence to drive fragmentation → recovery.
    """
    stack = build_phase_e_stack(
        seed=seed,
        perturbation_period_beats=80,   # tight to drive recovery
        perturbation_magnitude=0.5,
    )
    run_for_beats(stack, 600)
    finalized_records: list[dict[str, Any]] = []
    stack.ctx.subscribe(
        "recovery_event_finalized",
        lambda ev: finalized_records.append({
            "event_id": ev.event_id,
            "stage": ev.stage,
            "actions": dict(ev.actions_used),
            "composite_score": ev.quality.composite_score,
            "is_synthetic": ev.is_synthetic,
        }),
    )

    beats_run = 0
    while len(finalized_records) < target_events and beats_run < max_beats:
        stack.hb.tick()
        beats_run += 1

    return {
        "events_target": target_events,
        "events_observed": len(finalized_records),
        "beats_run_post_warmup": beats_run,
        "seed": seed,
        "learner": stack.recovery_protocol.learner.to_dict(),
        "first_5_events": finalized_records[:5],
        "last_5_events": finalized_records[-5:],
        "verdict": (
            "PASS" if len(finalized_records) >= target_events
            else "INSUFFICIENT_DATA"
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--events", type=int, default=20,
                   help="number of finalized recovery events to accumulate")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--max-beats", type=int, default=30000)
    args = p.parse_args()
    result = run_learner_longrun(
        target_events=args.events, seed=args.seed, max_beats=args.max_beats,
    )
    path = write_result("learner_longrun", result)
    print(f"Wrote {path}")
    print(f"  events={result['events_observed']}/{result['events_target']}  "
          f"beats={result['beats_run_post_warmup']}")
    print(f"  adoptions={result['learner']['adoptions_count']}  "
          f"reversions={result['learner']['reversions_count']}")
    print(f"  efficacy: stage2={result['learner']['efficacy_per_stage'].get('2', 'n/a')} "
          f"stage3={result['learner']['efficacy_per_stage'].get('3', 'n/a')}")
    print(f"  Verdict: {result['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
