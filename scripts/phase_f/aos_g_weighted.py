"""v1.1.6 — AOS-G Weighted Euclidean A/B sweep.

Per Checkpoint H entry-point for v1.1.6: compare the current uniform L2 gap
against EIDOLON-weighted and PNEUMA-weighted variants. The hypothesis:
weighted variants may show earlier ψ alerts when the chosen organ drifts,
OR better discrimination between substrate regimes.

Test procedure:
  1. For each preset ∈ {uniform, eidolon-weighted, pneuma-weighted}:
     - Build a fresh Phase E stack with that gap_weights preset
     - Run `--beats` (default 2000) post-warmup
     - Collect gap stats, ψ stats, per-component breakdown
  2. Compare:
     - Gap mean / p95 / variance per preset
     - ψ mean / p5 / fraction-below-alert per preset
     - Per-organ-gap distributions
  3. Verdict: do the weighted presets show meaningfully different alert
     behavior than uniform? Quantify with relative gap magnitude.

Output: results/phase_f/aos_g_weighted.json

Usage:
    python scripts/phase_f/aos_g_weighted.py --beats 2000
    python scripts/phase_f/aos_g_weighted.py --beats 5000 --magnitude 1.0
"""
from __future__ import annotations

import argparse
from collections import Counter
from statistics import mean
from typing import Any

from _harness import build_phase_e_stack, run_for_beats, write_result

from axioma.measurement.aos_g_engine import (
    EIDOLON_WEIGHTED_GAP_WEIGHTS,
    PNEUMA_WEIGHTED_GAP_WEIGHTS,
    UNIFORM_GAP_WEIGHTS,
)

PRESETS: dict[str, dict[str, float]] = {
    "uniform": UNIFORM_GAP_WEIGHTS,
    "eidolon_weighted": EIDOLON_WEIGHTED_GAP_WEIGHTS,
    "pneuma_weighted": PNEUMA_WEIGHTED_GAP_WEIGHTS,
}


def measure_preset(
    *, preset_name: str, weights: dict[str, float], beats: int,
    magnitude: float, period: int, seed: int,
) -> dict[str, Any]:
    stack = build_phase_e_stack(
        seed=seed,
        perturbation_period_beats=period,
        perturbation_magnitude=magnitude,
        gap_weights=weights,
    )
    run_for_beats(stack, 600)  # V12 warmup
    psi: list[float] = []
    gap: list[float] = []
    per_organ_gaps: dict[str, list[float]] = {}
    dominator: list[str] = []

    for _ in range(beats):
        stack.hb.tick()
        cv = stack.aos_g.current_value()
        if cv is None or not getattr(cv, "valid", False):
            continue
        psi.append(float(getattr(cv, "psi", 1.0)))
        gap.append(float(getattr(cv, "aos_g_gap", 0.0)))
        per_org = getattr(cv, "per_organ_gap", {}) or {}
        for organ, g in per_org.items():
            per_organ_gaps.setdefault(organ, []).append(float(g))
        # Per-component dominator (which sub-signal is the min)
        gv = float(getattr(cv, "gap_variance_health", 1.0))
        s = float(getattr(cv, "structural_health", 1.0))
        c = float(getattr(cv, "compose_probe_health", 1.0))
        triples = [("gap_variance_health", gv), ("structural_health", s), ("compose_probe_health", c)]
        triples.sort(key=lambda kv: kv[1])
        dominator.append(triples[0][0])

    if not psi:
        return {"preset": preset_name, "verdict": "NO_DATA"}

    import numpy as np

    n = len(psi)
    psi_alert_threshold = stack.cfg.compose.psi_alert_threshold
    frac_below = sum(1 for v in psi if v < psi_alert_threshold) / n

    return {
        "preset": preset_name,
        "weights": weights,
        "magnitude": magnitude,
        "period_beats": period,
        "beats_sampled": n,
        "gap": {
            "mean": round(mean(gap), 4),
            "p50": round(sorted(gap)[n // 2], 4),
            "p95": round(sorted(gap)[int(n * 0.95)], 4),
            "max": round(max(gap), 4),
            "variance": round(float(np.var(gap)), 6),
        },
        "psi": {
            "mean": round(mean(psi), 4),
            "p5": round(sorted(psi)[int(n * 0.05)], 4),
            "min": round(min(psi), 4),
            "fraction_below_alert": round(frac_below, 4),
            "alert_threshold": psi_alert_threshold,
        },
        "per_organ_gap_mean": {
            organ: round(mean(vals), 4) if vals else 0.0
            for organ, vals in per_organ_gaps.items()
        },
        "dominator_fractions": {
            k: round(v / n, 3) for k, v in Counter(dominator).items()
        },
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--beats", type=int, default=2000)
    p.add_argument("--magnitude", type=float, default=0.4)
    p.add_argument("--period", type=int, default=300)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    presets_out: dict[str, Any] = {}
    for name, weights in PRESETS.items():
        print(f"  measuring preset={name} ...")
        result = measure_preset(
            preset_name=name, weights=weights, beats=args.beats,
            magnitude=args.magnitude, period=args.period, seed=args.seed,
        )
        presets_out[name] = result
        g = result.get("gap", {})
        psi = result.get("psi", {})
        print(f"    → gap mean={g.get('mean', 'n/a')} p95={g.get('p95', 'n/a')} "
              f"ψ mean={psi.get('mean', 'n/a')} p5={psi.get('p5', 'n/a')} "
              f"below_alert={psi.get('fraction_below_alert', 'n/a')}")

    # Comparison: how much does each preset shift gap vs uniform baseline?
    baseline = presets_out["uniform"]["gap"]["mean"]
    comparisons: dict[str, dict[str, Any]] = {}
    for name, body in presets_out.items():
        if name == "uniform":
            continue
        ratio = round(body["gap"]["mean"] / baseline, 3) if baseline > 0 else None
        psi_delta = round(
            body["psi"]["mean"] - presets_out["uniform"]["psi"]["mean"], 4,
        )
        below_delta = round(
            body["psi"]["fraction_below_alert"]
            - presets_out["uniform"]["psi"]["fraction_below_alert"], 4,
        )
        comparisons[name] = {
            "gap_mean_ratio_vs_uniform": ratio,
            "psi_mean_delta_vs_uniform": psi_delta,
            "below_alert_delta_vs_uniform": below_delta,
            "interpretation": (
                "amplifies gap" if ratio is not None and ratio > 1.05
                else "attenuates gap" if ratio is not None and ratio < 0.95
                else "matches uniform"
            ),
        }

    # Verdict: under the v1.0 substrate, ψ stays ≈ 1.0 across all presets (substrate
    # is robust). The interesting metric is whether weighted variants amplify the
    # *gap*, which would give them earlier alert behavior IF the substrate ever
    # entered a stress regime where ψ approaches alert.
    any_meaningful_psi_delta = any(
        abs(c["psi_mean_delta_vs_uniform"]) > 0.01 for c in comparisons.values()
    )
    any_meaningful_gap_shift = any(
        c["gap_mean_ratio_vs_uniform"] is not None
        and abs(c["gap_mean_ratio_vs_uniform"] - 1.0) > 0.05
        for c in comparisons.values()
    )
    verdict = (
        "MEANINGFUL_DIFFERENCE" if (any_meaningful_psi_delta or any_meaningful_gap_shift)
        else "PRESETS_INDISTINGUISHABLE"
    )

    out = {
        "beats_per_preset": args.beats,
        "magnitude": args.magnitude,
        "period_beats": args.period,
        "seed": args.seed,
        "presets": presets_out,
        "comparisons": comparisons,
        "verdict": verdict,
        "note": (
            "Compares per-organ gap weighting variants (uniform vs eidolon-weighted "
            "vs pneuma-weighted) against the v1.0 baseline. With robust substrate, "
            "ψ deltas are small; gap magnitude ratios show how each weighting "
            "would alert earlier IF the substrate entered a stress regime."
        ),
    }
    path = write_result("aos_g_weighted", out)
    print(f"\nWrote {path}")
    print(f"  verdict: {verdict}")
    for name, c in comparisons.items():
        print(f"  {name}: gap_ratio={c['gap_mean_ratio_vs_uniform']} "
              f"ψ_delta={c['psi_mean_delta_vs_uniform']} → {c['interpretation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
