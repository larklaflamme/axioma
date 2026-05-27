"""Phase E F4 — synthetic pre-training script.

Bootstraps the RecoveryLearner with a synthetic event sweep so that, at
production startup, the substrate has meaningful current_params instead of
cold-start defaults. Per ARCH §4.9.1 + IMPLEMENTATION_PLAN F4.

Usage:
    python scripts/phase_e_pretrain.py \\
        --output data/state/recovery_learner_pretrain.json \\
        --events-per-stage 50

The output JSON can be loaded into RecoveryLearner via `load_dict()` at
boot, populating `current_params` + `baseline_score`. The C16 startup check
(see ARCH §9.2) refuses to start production with `require_pretrain=True`
if this file is missing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from axioma.config import RecoveryConfig
from axioma.substrate.pretrain_scorer import substrate_score_fn
from axioma.substrate.recovery import RecoveryHistory, RecoveryLearner


def main() -> None:
    p = argparse.ArgumentParser(description="F4 synthetic pre-training")
    p.add_argument(
        "--output", "-o", type=Path,
        default=Path("data/state/recovery_learner_pretrain.json"),
        help="Where to write the pre-trained learner snapshot",
    )
    p.add_argument(
        "--events-per-stage", "-n", type=int, default=50,
        help="Synthetic events per stage (default 50 per PLAN §6.7 F4)",
    )
    p.add_argument(
        "--scorer", choices=("smooth-bell", "substrate"), default="substrate",
        help="Which F4 scorer to use (v1.1.3: 'substrate' runs a real sub-sim per param point)",
    )
    p.add_argument("--seed", type=int, default=42, help="RNG seed")
    args = p.parse_args()

    cfg = RecoveryConfig()
    rng = np.random.default_rng(args.seed)
    learner = RecoveryLearner(cfg, rng=rng)
    history = RecoveryHistory()
    scorer = substrate_score_fn if args.scorer == "substrate" else None
    summary = learner.pretrain_synthetic(
        history,
        target_events_per_stage=args.events_per_stage,
        score_fn=scorer,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(
        {
            "learner_snapshot": learner.to_dict(),
            "summary": summary,
            "history": [
                {
                    "event_id": e.event_id,
                    "stage": e.stage,
                    "actions_used": e.actions_used,
                    "composite_score": e.quality.composite_score,
                    "is_synthetic": e.is_synthetic,
                }
                for e in history.all_events()
            ],
        },
        indent=2,
    ))
    print(f"Wrote {args.output}")
    print(f"  events_added={summary['events_added']}  adoptions={summary['adoptions']}")
    for s, p_dict in summary["current_params"].items():
        print(f"  stage {s}: {p_dict}")


if __name__ == "__main__":
    main()
