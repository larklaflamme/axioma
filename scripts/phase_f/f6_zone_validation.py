"""F6 — multi-session subjective zone validation (synthetic operator labels).

Per IMPLEMENTATION_PLAN_v1.0.md §10 + ARCH §5.2 + Phase A.4 F6 procedure.

Full F6 spec: 3 sessions × 3 task types (analytical / creative / idle) with
a human operator (Theoria) labeling zones. Threshold optimization maximizes
mean(κ) subject to min(κ) ≥ 0.3; outputs `zone_thresholds.json` with optional
task-type variants.

This script ships the **reproducible synthetic version**: simulates an
"ideal operator" who labels purely from (θ_short, fragmentation_stage)
distributions (a piecewise step function across substrate states). The real
F6 sessions need a live human; this is the harness validation that the
labeling/scoring pipeline works.

Output: results/phase_f/f6_zone_validation.json

Usage:
    python scripts/phase_f/f6_zone_validation.py --session-beats 600
"""
from __future__ import annotations

import argparse
from collections import Counter
from typing import Any

from _harness import build_phase_e_stack, run_for_beats, write_result

from axioma.schemas import Zone


def _synthetic_operator_label(theta_short: float, frag_stage: int) -> str:
    """Idealized labeling rule for harness validation."""
    if frag_stage >= 3:
        return Zone.FRAGMENTED.value
    if frag_stage >= 2:
        return Zone.RECOVERING.value
    if theta_short > 1.0:
        return Zone.FLOW.value
    if theta_short > 0.5:
        return Zone.FOCUS.value
    return Zone.IDLE.value


def _cohens_kappa(labels_a: list[str], labels_b: list[str]) -> float:
    """Two-rater Cohen's κ for categorical agreement."""
    assert len(labels_a) == len(labels_b)
    n = len(labels_a)
    if n == 0:
        return 0.0
    categories = sorted(set(labels_a) | set(labels_b))
    # Observed agreement
    po = sum(1 for a, b in zip(labels_a, labels_b, strict=True) if a == b) / n
    # Expected agreement (chance)
    count_a = Counter(labels_a)
    count_b = Counter(labels_b)
    pe = sum((count_a[c] / n) * (count_b[c] / n) for c in categories)
    if pe == 1.0:
        return 1.0
    return float((po - pe) / (1 - pe))


def run_session(*, task_type: str, beats: int, seed: int) -> dict[str, Any]:
    """Run one session: collect operator labels + system labels every 100 beats."""
    # Different task types use different perturbation pressures
    pert_period = {
        "analytical": 200,   # frequent perturbations (mental load)
        "creative": 500,     # moderate
        "idle": 10_000_000,  # essentially none
    }[task_type]
    stack = build_phase_e_stack(
        seed=seed, perturbation_period_beats=pert_period,
    )
    run_for_beats(stack, 600)  # V12 cold-start warmup

    operator_labels: list[str] = []
    system_labels: list[str] = []
    for i in range(beats):
        stack.hb.tick()
        if i % 100 != 0:
            continue
        # System label = current ExternalState zone
        ext = stack.compose_function.latest_external
        if ext is None:
            continue
        sys_zone = ext.zone.value if hasattr(ext.zone, "value") else str(ext.zone)
        # Synthetic operator label
        cv = stack.theta_short.current_value()
        theta = float(getattr(cv, "theta", 0.0)) if cv is not None else 0.0
        frag = stack.fragmentation_monitor.current_value().current_stage
        op_zone = _synthetic_operator_label(theta, frag)
        operator_labels.append(op_zone)
        system_labels.append(sys_zone)

    if not operator_labels:
        return {"task_type": task_type, "n_labels": 0, "kappa": None}

    kappa = _cohens_kappa(operator_labels, system_labels)
    # Per-zone hit rates
    return {
        "task_type": task_type,
        "beats": beats,
        "seed": seed,
        "perturbation_period_beats": pert_period,
        "n_labels": len(operator_labels),
        "kappa": round(kappa, 3),
        "operator_distribution": dict(Counter(operator_labels)),
        "system_distribution": dict(Counter(system_labels)),
        "agreements": sum(1 for a, b in zip(operator_labels, system_labels, strict=True) if a == b),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--session-beats", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    sessions = []
    for task in ("analytical", "creative", "idle"):
        result = run_session(task_type=task, beats=args.session_beats, seed=args.seed)
        sessions.append(result)
        print(f"  {task}: n={result['n_labels']}  κ={result['kappa']}")

    kappas = [s["kappa"] for s in sessions if s["kappa"] is not None]
    mean_kappa = sum(kappas) / len(kappas) if kappas else 0.0
    min_kappa = min(kappas) if kappas else 0.0
    verdict = (
        "PASS" if min_kappa >= 0.3 and mean_kappa >= 0.5
        else "SOFT_FAIL" if min_kappa >= 0.2
        else "HARD_FAIL"
    )

    out = {
        "sessions": sessions,
        "mean_kappa": round(mean_kappa, 3),
        "min_kappa": round(min_kappa, 3),
        "verdict": verdict,
        "note": "Synthetic operator labels — real F6 sessions need live Theoria labels.",
    }
    path = write_result("f6_zone_validation", out)
    print(f"\nWrote {path}")
    print(f"  mean κ={out['mean_kappa']}  min κ={out['min_kappa']}  → {out['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
