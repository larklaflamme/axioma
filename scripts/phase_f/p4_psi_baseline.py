"""P4 — baseline ψ measurement.

Per IMPLEMENTATION_PLAN_v1.0.md §10 + the architecture's "what should ψ be
in steady state with no perturbations?" question.

Runs the full stack with internal-perturbation cadence pushed far out (so
the substrate operates baseline-only), then samples ψ over a long window
past the warmup. Reports:
  - mean, p5, p50, p95, p99 ψ
  - mean, p95 gap
  - structural_health / gap_variance_health / compose_probe_health summaries
  - whether ψ holds above the `psi_alert_threshold` (default 0.30)

Output: results/phase_f/p4_psi_baseline.json

Usage:
    python scripts/phase_f/p4_psi_baseline.py            # default 3000 beats
    python scripts/phase_f/p4_psi_baseline.py --beats 10000 --seed 7
"""
from __future__ import annotations

import argparse
from statistics import mean, median
from typing import Any

from _harness import build_phase_e_stack, run_for_beats, write_result


def measure_baseline_psi(*, beats: int, seed: int) -> dict[str, Any]:
    stack = build_phase_e_stack(
        seed=seed,
        # Effectively no internal perturbations — pure baseline run
        perturbation_period_beats=10_000_000,
    )
    # Warmup 600 beats per V12
    run_for_beats(stack, 600)
    # Sample
    psi_samples: list[float] = []
    gap_samples: list[float] = []
    sh_samples: list[float] = []
    gvh_samples: list[float] = []
    cph_samples: list[float] = []
    for _ in range(beats):
        stack.hb.tick()
        cv = stack.aos_g.current_value()
        if cv is not None:
            psi_samples.append(float(getattr(cv, "psi", 0.0)))
            gap_samples.append(float(getattr(cv, "aos_g_gap", 0.0)))
            sh_samples.append(float(getattr(cv, "structural_health", 1.0)))
            gvh_samples.append(float(getattr(cv, "gap_variance_health", 1.0)))
            cph_samples.append(float(getattr(cv, "compose_probe_health", 1.0)))

    def _stats(xs: list[float]) -> dict[str, float | int]:
        if not xs:
            return {"n": 0}
        sxs = sorted(xs)
        n = len(xs)
        return {
            "n": n,
            "mean": round(mean(xs), 4),
            "median": round(median(xs), 4),
            "p5": round(sxs[int(n * 0.05)], 4),
            "p95": round(sxs[int(n * 0.95)], 4),
            "p99": round(sxs[int(n * 0.99)], 4),
            "min": round(min(xs), 4),
            "max": round(max(xs), 4),
        }

    psi_alert_threshold = stack.cfg.compose.psi_alert_threshold
    psi_stats = _stats(psi_samples)
    pct_below_alert = (
        sum(1 for v in psi_samples if v < psi_alert_threshold) / max(1, len(psi_samples))
    )
    return {
        "beats_sampled": beats,
        "seed": seed,
        "warmup_beats": 600,
        "psi": psi_stats,
        "gap": _stats(gap_samples),
        "structural_health": _stats(sh_samples),
        "gap_variance_health": _stats(gvh_samples),
        "compose_probe_health": _stats(cph_samples),
        "psi_alert_threshold": psi_alert_threshold,
        "fraction_below_alert": round(pct_below_alert, 4),
        "verdict": (
            "PASS"
            if (psi_stats.get("mean", 0) >= psi_alert_threshold and pct_below_alert < 0.05)
            else "SOFT_FAIL"
            if pct_below_alert < 0.20
            else "HARD_FAIL"
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--beats", type=int, default=3000)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    result = measure_baseline_psi(beats=args.beats, seed=args.seed)
    path = write_result("p4_psi_baseline", result)
    print(f"Wrote {path}")
    print(f"  ψ mean={result['psi'].get('mean', 'n/a')} "
          f"p5={result['psi'].get('p5', 'n/a')} "
          f"below_alert={result['fraction_below_alert']}")
    print(f"  Verdict: {result['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
