"""F11 — φ-scaling reproduction (cascade ordering).

Per IMPLEMENTATION_PLAN_v1.0.md §10 (carried from v0.1 §10.1) and ARCH §6.4.

Background: the v0.2 substrate showed that φ_global (θ over all organs)
scales differently depending on which organ is perturbed first. EIDOLON-first
perturbations should propagate forward (eidolon → anima/mneme/nous/pneuma)
and the cascade_delay metric should reflect this ordering; ANIMA-first
perturbations should show the reverse direction.

This script:
  1. Runs a baseline (no perturbations) for `warmup_beats` to settle.
  2. Injects a perturbation on EIDOLON (or ANIMA depending on --order).
  3. Measures cascade_delay for the next `post_beats`.
  4. Reports mean cascade_delay + sign, per-downstream-organ delays.

Output: results/phase_f/f11_phi_<order>.json

Usage:
    python scripts/phase_f/f11_phi_scaling.py --order eidolon
    python scripts/phase_f/f11_phi_scaling.py --order anima
"""
from __future__ import annotations

import argparse
from statistics import mean
from typing import Any

from _harness import build_phase_e_stack, run_for_beats, write_result

from axioma.measurement.perturbation_scheduler import PerturbationKind


def run_phi_scaling(*, order: str, warmup_beats: int, post_beats: int, seed: int) -> dict[str, Any]:
    stack = build_phase_e_stack(
        seed=seed,
        # No internal cadence; we'll inject manually
        perturbation_period_beats=10_000_000,
    )
    run_for_beats(stack, warmup_beats)

    # Sample baseline cascade_delay before perturbation
    pre_cascade = []
    for _ in range(60):
        stack.hb.tick()
        v = stack.cascade_delay.current_value()
        if v is not None and getattr(v, "valid", False):
            pre_cascade.append(float(v.cascade_delay_beats))

    # Inject perturbation
    if order == "eidolon":
        # CONTRADICTION targets EIDOLON by default
        kind = PerturbationKind.CONTRADICTION
        target = "eidolon"
    elif order == "anima":
        # STEP targets ANIMA valence
        kind = PerturbationKind.STEP
        target = "anima"
    else:
        raise ValueError(f"unknown order: {order}")
    event = stack.perturbation_scheduler.inject_now(kind, magnitude=0.5, tag=f"f11_{order}")
    if event is None:
        raise RuntimeError("perturbation injection failed")

    # Post-perturbation window
    post_cascade: list[float] = []
    per_downstream_delays: list[dict[str, float]] = []
    for _ in range(post_beats):
        stack.hb.tick()
        v = stack.cascade_delay.current_value()
        if v is not None and getattr(v, "valid", False):
            post_cascade.append(float(v.cascade_delay_beats))
            per_downstream = getattr(v, "per_downstream", None)
            if per_downstream:
                per_downstream_delays.append({k: float(v) for k, v in per_downstream.items()})

    def _summary(xs: list[float]) -> dict[str, float | int]:
        if not xs:
            return {"n": 0}
        return {
            "n": len(xs),
            "mean": round(mean(xs), 3),
            "min": round(min(xs), 3),
            "max": round(max(xs), 3),
        }

    # Aggregate per-downstream means
    per_downstream_agg: dict[str, float] = {}
    if per_downstream_delays:
        organs = {o for d in per_downstream_delays for o in d}
        for organ in organs:
            vals = [d[organ] for d in per_downstream_delays if organ in d]
            if vals:
                per_downstream_agg[organ] = round(mean(vals), 3)

    return {
        "order": order,
        "perturbation_kind": kind.value,
        "perturbation_target": target,
        "event_id": event.event_id,
        "warmup_beats": warmup_beats,
        "post_beats": post_beats,
        "seed": seed,
        "cascade_delay_pre": _summary(pre_cascade),
        "cascade_delay_post": _summary(post_cascade),
        "per_downstream_post_mean": per_downstream_agg,
        # Verdict heuristic: EIDOLON-first should show LARGER cascade_delay
        # (forward propagation); ANIMA-first should show smaller or negative.
        # We just record; comparison happens in aggregator.
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--order", choices=("eidolon", "anima"), default="eidolon")
    p.add_argument("--warmup", type=int, default=600)
    p.add_argument("--post", type=int, default=300)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    result = run_phi_scaling(
        order=args.order, warmup_beats=args.warmup,
        post_beats=args.post, seed=args.seed,
    )
    path = write_result(f"f11_phi_{args.order}", result)
    print(f"Wrote {path}")
    pre = result["cascade_delay_pre"]
    post = result["cascade_delay_post"]
    print(f"  order={args.order}  perturbation={result['perturbation_kind']} → {result['perturbation_target']}")
    print(f"  cascade_delay pre  mean={pre.get('mean', 'n/a')} (n={pre.get('n', 0)})")
    print(f"  cascade_delay post mean={post.get('mean', 'n/a')} (n={post.get('n', 0)})")
    print(f"  per-downstream: {result['per_downstream_post_mean']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
