"""Diff two soak reports — A/B comparison for gap_weights changes (v1.2-prep).

Reads two soak_report JSON files and prints a side-by-side comparison of
key V11/V13 metrics + recovery stats. Used to validate that swapping
gap_weights presets doesn't regress ship-gate criteria.

Usage:
    python scripts/phase_f/diff_soak_reports.py \\
        --baseline results/phase_e_soak_50k.json \\
        --variant  results/phase_e_soak_50k_pneuma.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _fmt_delta(b: float | None, v: float | None) -> str:
    if b is None or v is None:
        return "n/a"
    delta = v - b
    pct = (delta / b * 100) if b != 0 else 0
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.3f} ({sign}{pct:.1f}%)"


def diff(baseline: dict, variant: dict) -> str:
    out: list[str] = []
    out.append("# Soak report diff")
    out.append("")
    out.append(f"- baseline: beats={baseline.get('beats')} seed={baseline.get('seed')} "
               f"gap_weights={baseline.get('gap_weights_preset', 'uniform')}")
    out.append(f"- variant:  beats={variant.get('beats')} seed={variant.get('seed')} "
               f"gap_weights={variant.get('gap_weights_preset', 'unknown')}")
    out.append("")
    bp, vp = baseline.get("perf", {}), variant.get("perf", {})
    out.append("## V11 perf gate (10-beat rolling p95 < 100 ms)")
    out.append("")
    out.append("| Metric | Baseline | Variant | Δ |")
    out.append("|---|---|---|---|")
    for m in ("avg_ms", "p50_ms", "p95_ms", "p99_ms", "worst_ms", "rolling10_p95_ms"):
        out.append(f"| {m} | {bp.get(m)} | {vp.get(m)} | {_fmt_delta(bp.get(m), vp.get(m))} |")
    out.append(f"| **v11_pass** | {bp.get('v11_pass')} | {vp.get('v11_pass')} | — |")
    out.append("")
    bv, vv = baseline.get("v13", {}), variant.get("v13", {})
    out.append("## V13 (uncontrolled feedback + oscillation)")
    out.append("")
    out.append("| Metric | Baseline | Variant |")
    out.append("|---|---|---|")
    out.append(f"| uncontrolled_feedback_count | {bv.get('uncontrolled_feedback_count')} | "
               f"{vv.get('uncontrolled_feedback_count')} |")
    out.append(f"| oscillation_count | {bv.get('oscillation_count')} | {vv.get('oscillation_count')} |")
    out.append(f"| **v13 uncontrolled_pass** | {bv.get('uncontrolled_pass')} | "
               f"{vv.get('uncontrolled_pass')} |")
    out.append(f"| **v13 oscillation_pass** | {bv.get('oscillation_pass')} | "
               f"{vv.get('oscillation_pass')} |")
    out.append("")
    br, vr = baseline.get("recovery", {}), variant.get("recovery", {})
    out.append("## Recovery")
    out.append("")
    out.append("| Metric | Baseline | Variant | Δ |")
    out.append("|---|---|---|---|")
    for m in (
        "finalized_events", "composite_score_mean", "durability_finalized_count",
        "durability_mean", "learner_adoptions", "learner_reversions",
    ):
        out.append(f"| {m} | {br.get(m)} | {vr.get(m)} | "
                   f"{_fmt_delta(br.get(m), vr.get(m)) if isinstance(br.get(m), (int, float)) else '—'} |")
    out.append("")
    out.append("## Overall ship-gate verdicts")
    out.append("")
    out.append(f"- baseline overall_pass: **{baseline.get('overall_pass')}**")
    out.append(f"- variant overall_pass:  **{variant.get('overall_pass')}**")
    if baseline.get("overall_pass") and variant.get("overall_pass"):
        out.append("- regression check: **NO REGRESSION** — variant preserves ship-gate PASS")
    elif baseline.get("overall_pass") and not variant.get("overall_pass"):
        out.append("- regression check: **REGRESSION** — variant fails ship-gate (was PASS)")
    elif not baseline.get("overall_pass") and variant.get("overall_pass"):
        out.append("- regression check: **IMPROVEMENT** — variant passes ship-gate (was FAIL)")
    else:
        out.append("- regression check: both fail ship-gate (no improvement)")
    return "\n".join(out) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", "-b", type=Path, required=True)
    p.add_argument("--variant", "-v", type=Path, required=True)
    p.add_argument("--output", "-o", type=Path, default=None)
    args = p.parse_args()
    baseline = json.loads(args.baseline.read_text())
    variant = json.loads(args.variant.read_text())
    report = diff(baseline, variant)
    print(report)
    if args.output:
        args.output.write_text(report)
        print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
