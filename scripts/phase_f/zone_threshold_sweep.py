"""Zone threshold sweep — v1.1.1 enabler for F6 SOFT_FAIL.

Per Checkpoint F: the F6 zone validation against a synthetic operator shows
the system's FLOW threshold is too conservative (requires θ>1.0 AND s1>0 AND
s2 finite AND cascade<10 simultaneously; synthetic operator just checks θ>1.0).

This sweep:
  1. Runs the substrate stack with the synthetic operator (same as F6).
  2. Sweeps over (flow_theta_min, flow_cascade_max) candidate values.
  3. For each candidate, replaces the heartbeat's zone thresholds, re-runs
     a short session, and measures κ across all 3 task types.
  4. Reports the candidate that maximizes mean(κ) subject to min(κ) ≥ 0.3.

Output: results/phase_f/zone_threshold_sweep.json + a recommended
zone_thresholds.json for v1.1 use.

Usage:
    python scripts/phase_f/zone_threshold_sweep.py --beats-per-task 1500
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from _harness import build_phase_e_stack, run_for_beats, write_result

from axioma.compose.zone import DEFAULT_THRESHOLDS
from axioma.schemas import Zone


def _synthetic_operator(theta: float, frag: int) -> str:
    if frag >= 3:
        return Zone.FRAGMENTED.value
    if frag >= 2:
        return Zone.RECOVERING.value
    if theta > 1.0:
        return Zone.FLOW.value
    if theta > 0.5:
        return Zone.FOCUS.value
    return Zone.IDLE.value


def _cohens_kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    if n == 0:
        return 0.0
    po = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    cats = sorted(set(a) | set(b))
    ca, cb = Counter(a), Counter(b)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in cats)
    return 1.0 if pe == 1.0 else float((po - pe) / (1 - pe))


def _run_task(thresholds: dict[str, float], task: str, beats: int, seed: int) -> dict[str, Any]:
    pert_period = {
        "analytical": 200, "creative": 500, "idle": 10_000_000,
    }[task]
    stack = build_phase_e_stack(seed=seed, perturbation_period_beats=pert_period)
    # Inject custom thresholds into the heartbeat by patching classify_zone via
    # the cfg's compose.weights? We have no direct hook; instead patch
    # _classify_and_attach_zone to use these thresholds.
    original = stack.hb._classify_and_attach_zone

    def patched(external: Any, theta_short: float) -> None:
        from axioma.compose.zone import classify_zone
        try:
            delta_phi_s1: float | None = None
            delta_phi_s2: float | None = None
            delta_phi_s3: float = 0.0
            cascade_delay_beats: float = 0.0
            fragmentation_stage: int = 0
            if stack.ctx.has("delta_phi"):
                dp = stack.ctx.get("delta_phi").current_value()
                if dp is not None:
                    delta_phi_s1 = getattr(dp, "s1_peak_delta_theta", None)
                    delta_phi_s2 = getattr(dp, "s2_recovery_beats", None)
                    delta_phi_s3 = float(getattr(dp, "s3_context_variance", 0.0))
            if stack.ctx.has("cascade_delay"):
                cd = stack.ctx.get("cascade_delay").current_value()
                if cd is not None and getattr(cd, "valid", False):
                    cascade_delay_beats = float(getattr(cd, "cascade_delay_beats", 0.0))
            if stack.ctx.has("fragmentation_monitor"):
                fr = stack.ctx.get("fragmentation_monitor").current_value()
                if fr is not None:
                    fragmentation_stage = int(getattr(fr, "current_stage", 0))
            beats_in_zone = stack.hb.beat_no - stack.hb._prev_zone_entered_beat
            zone = classify_zone(
                theta_short=theta_short,
                delta_phi_s1=delta_phi_s1, delta_phi_s2=delta_phi_s2,
                delta_phi_s3=delta_phi_s3,
                cascade_delay_beats=cascade_delay_beats,
                fragmentation_stage=fragmentation_stage,
                prev_zone=stack.hb._prev_zone,
                beats_in_zone=beats_in_zone,
                thresholds=thresholds,  # ← custom thresholds
            )
            external.zone = zone
            if zone != stack.hb._prev_zone:
                stack.hb._prev_zone = zone
                stack.hb._prev_zone_entered_beat = stack.hb.beat_no
        except Exception:
            pass
    stack.hb._classify_and_attach_zone = patched  # type: ignore[method-assign]
    del original  # silence linter

    run_for_beats(stack, 600)
    op_labels: list[str] = []
    sys_labels: list[str] = []
    for i in range(beats):
        stack.hb.tick()
        if i % 100 != 0:
            continue
        ext = stack.compose_function.latest_external
        if ext is None:
            continue
        cv = stack.theta_short.current_value()
        theta = float(getattr(cv, "theta", 0.0)) if cv is not None else 0.0
        frag = stack.fragmentation_monitor.current_value().current_stage
        op_labels.append(_synthetic_operator(theta, frag))
        sys_labels.append(ext.zone.value)
    if not op_labels:
        return {"task": task, "kappa": 0.0, "n": 0}
    return {
        "task": task,
        "n": len(op_labels),
        "kappa": round(_cohens_kappa(op_labels, sys_labels), 3),
        "agreements": sum(1 for a, b in zip(op_labels, sys_labels, strict=True) if a == b),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--beats-per-task", type=int, default=1500)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    # Sweep grid — vary the two thresholds the F6 finding flagged as conservative
    flow_theta_candidates = [0.7, 0.85, 1.0, 1.15]
    flow_cascade_candidates = [10.0, 20.0, 30.0]
    candidates = []
    for ft in flow_theta_candidates:
        for fc in flow_cascade_candidates:
            thresholds = dict(DEFAULT_THRESHOLDS)
            thresholds["flow_theta_min"] = ft
            thresholds["flow_cascade_max"] = fc
            task_results = [
                _run_task(thresholds, task, args.beats_per_task, args.seed)
                for task in ("analytical", "creative", "idle")
            ]
            kappas = [r["kappa"] for r in task_results]
            mean_kappa = sum(kappas) / len(kappas)
            min_kappa = min(kappas)
            candidates.append({
                "flow_theta_min": ft,
                "flow_cascade_max": fc,
                "task_results": task_results,
                "mean_kappa": round(mean_kappa, 3),
                "min_kappa": round(min_kappa, 3),
                "passes_v1_1_gate": min_kappa >= 0.3,
            })
            print(f"  flow_theta={ft} flow_cascade={fc} mean κ={mean_kappa:.3f} "
                  f"min κ={min_kappa:.3f} {'PASS' if min_kappa >= 0.3 else ''}")

    passing = [c for c in candidates if c["passes_v1_1_gate"]]
    best: dict[str, Any] | None
    if passing:
        best = max(passing, key=lambda c: c["mean_kappa"])
    else:
        # Best-effort: highest mean κ even if below gate
        best = max(candidates, key=lambda c: c["mean_kappa"])
    out = {
        "n_candidates": len(candidates),
        "n_passing_v1_1_gate": len(passing),
        "candidates": candidates,
        "best": best,
        "verdict": "PASS" if passing else "SOFT_FAIL (no candidate hit min κ ≥ 0.3 — needs live F6 sessions)",
    }
    path = write_result("zone_threshold_sweep", out)
    print(f"\nWrote {path}")
    print(f"  best: flow_theta={best['flow_theta_min']} flow_cascade={best['flow_cascade_max']} "
          f"mean κ={best['mean_kappa']} min κ={best['min_kappa']}")
    # Also write a recommended zone_thresholds.json for v1.1 use
    recommended = dict(DEFAULT_THRESHOLDS)
    recommended["flow_theta_min"] = best["flow_theta_min"]
    recommended["flow_cascade_max"] = best["flow_cascade_max"]
    rec_path = Path(path).parent / "zone_thresholds.json"
    rec_path.write_text(json.dumps({
        "thresholds": recommended,
        "source": "zone_threshold_sweep.py (synthetic operator)",
        "verdict": out["verdict"],
        "note": "Synthetic-operator calibration. Real F6 sessions (v1.1.1) override.",
    }, indent=2))
    print(f"  recommended thresholds → {rec_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
