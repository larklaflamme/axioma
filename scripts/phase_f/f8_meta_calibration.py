"""F8 — meta-cognition confidence calibration.

Per IMPLEMENTATION_PLAN_v1.0.md §10.3 + ARCH §6.7.3.

Full F8 spec: 5 one-hour blind-labeled sessions (operator = Skye); compare
`meta_cog.overall_assessment` against operator label every 100 beats;
`accuracy = 1 if match else 0`; `miscalibration = |confidence - accuracy|`;
`mean_miscalibration` threshold:
  ≤ 0.20 → PASS
  (0.20, 0.35] → SOFT_FAIL (v1.1 work)
  > 0.35 → HARD_FAIL (heightened caveat, treat as uninformative)

This script ships the **reproducible synthetic version**: a deterministic
"ideal operator" labels assessment from substrate signals; we compare against
meta-cog's actual emissions. The real F8 needs live blind-labeled sessions.

Also applies the **three-criterion verdict** from PLAN §10.3:
  1. Accuracy ≥ 80% PASS / ≥ 65% SOFT / < 65% HARD
  2. Acceptance rate ≥ 30% (skipped here — observer_only default → 0% by design)
  3. No vicious circle (skipped here — single regime; the back-to-back A/B test is operator-driven)

Output: results/phase_f/f8_meta_calibration.json

Usage:
    python scripts/phase_f/f8_meta_calibration.py --session-beats 1500
"""
from __future__ import annotations

import argparse
from collections import Counter
from statistics import mean
from typing import Any

from _harness import build_phase_e_stack, run_for_beats, write_result

from axioma.measurement.meta_cognition_loop import OverallAssessment


def _synthetic_operator_assessment(
    theta_short: float,
    frag_stage: int,
    recovery_active: bool,
    perturbations_recent: int,
) -> str:
    """Deterministic operator-like assessment for harness validation."""
    if frag_stage >= 3:
        return OverallAssessment.FRAGMENTED.value
    if recovery_active:
        return OverallAssessment.RECOVERING.value
    if frag_stage >= 2:
        return OverallAssessment.STRESSED.value
    if perturbations_recent >= 3:
        return OverallAssessment.EXPLORING.value
    if theta_short < 0.3:
        return OverallAssessment.STRESSED.value
    return OverallAssessment.NOMINAL.value


def run_session(*, beats: int, seed: int) -> dict[str, Any]:
    stack = build_phase_e_stack(seed=seed, perturbation_period_beats=400)
    # Track recent perturbations
    recent_perturbations: list[int] = []
    stack.ctx.subscribe(
        "perturbation_injected",
        lambda _p: recent_perturbations.append(stack.hb.beat_no),
    )

    # Track meta-cog emissions
    meta_emissions: list[dict[str, Any]] = []
    def _on_meta(payload: Any) -> None:
        meta_emissions.append({
            "beat_no": getattr(payload, "beat_no", 0),
            "assessment": (
                payload.overall_assessment.value
                if hasattr(payload, "overall_assessment")
                else None
            ),
            "confidence": float(getattr(payload, "confidence", 0.0)),
        })
    stack.ctx.subscribe("meta_cognition", _on_meta)

    run_for_beats(stack, 600)  # V12 warmup
    run_for_beats(stack, beats)

    # For each meta-cog emission, compute the operator label at that beat
    samples = []
    for m in meta_emissions:
        if m["assessment"] is None:
            continue
        beat = m["beat_no"]
        # Operator inputs
        cv = stack.theta_short.current_value()
        theta = float(getattr(cv, "theta", 0.0)) if cv is not None else 0.0
        frag = stack.fragmentation_monitor.current_value().current_stage
        recovery_active = stack.recovery_protocol.state.value == "active"
        pert_recent = sum(1 for b in recent_perturbations if (beat - 200) <= b <= beat)
        op_label = _synthetic_operator_assessment(theta, frag, recovery_active, pert_recent)
        accuracy = 1 if m["assessment"] == op_label else 0
        miscalibration = abs(m["confidence"] - accuracy)
        samples.append({
            "beat_no": beat,
            "system": m["assessment"],
            "operator": op_label,
            "confidence": m["confidence"],
            "accuracy": accuracy,
            "miscalibration": miscalibration,
        })

    if not samples:
        return {"verdict": "INSUFFICIENT_DATA", "samples": 0}

    accuracy_rate = mean(s["accuracy"] for s in samples)
    mean_miscalibration = mean(s["miscalibration"] for s in samples)
    f8_verdict = (
        "PASS" if mean_miscalibration <= 0.20
        else "SOFT_FAIL" if mean_miscalibration <= 0.35
        else "HARD_FAIL"
    )
    accuracy_verdict = (
        "PASS" if accuracy_rate >= 0.80
        else "SOFT_FAIL" if accuracy_rate >= 0.65
        else "HARD_FAIL"
    )
    # Stricter wins
    combined_verdict = max(
        f8_verdict, accuracy_verdict,
        key=lambda v: {"PASS": 0, "SOFT_FAIL": 1, "HARD_FAIL": 2}[v],
    )
    return {
        "session_beats": beats,
        "seed": seed,
        "n_meta_emissions": len(samples),
        "accuracy_rate": round(accuracy_rate, 3),
        "mean_miscalibration": round(mean_miscalibration, 3),
        "system_distribution": dict(Counter(s["system"] for s in samples)),
        "operator_distribution": dict(Counter(s["operator"] for s in samples)),
        "f8_verdict": f8_verdict,
        "accuracy_verdict": accuracy_verdict,
        "combined_verdict": combined_verdict,
        "note": "Synthetic operator labels — real F8 needs live blind-labeled sessions.",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--session-beats", type=int, default=1500)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    result = run_session(beats=args.session_beats, seed=args.seed)
    path = write_result("f8_meta_calibration", result)
    print(f"Wrote {path}")
    if result.get("verdict") == "INSUFFICIENT_DATA":
        print("  Insufficient meta-cog emissions to evaluate. Increase --session-beats.")
        return 1
    print(f"  accuracy={result['accuracy_rate']}  miscalibration={result['mean_miscalibration']}")
    print(f"  F8 → {result['f8_verdict']}  accuracy → {result['accuracy_verdict']}  combined → {result['combined_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
