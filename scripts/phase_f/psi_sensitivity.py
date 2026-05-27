"""ψ component sensitivity — how much does each sub-signal contribute?

Per IMPLEMENTATION_PLAN v0.1 §10.1 + ARCH §5.4.

ψ = min(gap_variance_health, structural_health, compose_probe_health). We
want to know: under stress, which component drops first? If one component
always dominates the min, the others are decorative; if they trade off,
each carries signal.

Records (gap_variance_health, structural_health, compose_probe_health, ψ)
every beat for a perturbed run, then computes:
  - Pearson correlation between each component and ψ
  - Fraction of beats each component WAS the min (dominator)
  - Per-component stats

Output: results/phase_f/psi_sensitivity.json
"""
from __future__ import annotations

import argparse
from collections import Counter
from statistics import mean
from typing import Any

from _harness import build_phase_e_stack, run_for_beats, write_result


def _corr(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    denom = (sxx * syy) ** 0.5
    if denom < 1e-9:
        return 0.0
    return float(sxy / denom)


def run_sensitivity(*, beats: int, seed: int) -> dict[str, Any]:
    stack = build_phase_e_stack(
        seed=seed,
        # Push the substrate with frequent perturbations to stress ψ components
        perturbation_period_beats=120,
        perturbation_magnitude=0.5,
    )
    run_for_beats(stack, 600)
    gvh: list[float] = []
    sh: list[float] = []
    cph: list[float] = []
    psi: list[float] = []
    dominator: list[str] = []
    for _ in range(beats):
        stack.hb.tick()
        cv = stack.aos_g.current_value()
        if cv is None:
            continue
        g = float(getattr(cv, "gap_variance_health", 1.0))
        s = float(getattr(cv, "structural_health", 1.0))
        c = float(getattr(cv, "compose_probe_health", 1.0))
        p = float(getattr(cv, "psi", min(g, s, c)))
        gvh.append(g)
        sh.append(s)
        cph.append(c)
        psi.append(p)
        # Which component WAS the min?
        triples = [("gap_variance_health", g), ("structural_health", s), ("compose_probe_health", c)]
        triples.sort(key=lambda kv: kv[1])
        dominator.append(triples[0][0])
    if not psi:
        return {"verdict": "INSUFFICIENT_DATA"}
    n = len(psi)
    return {
        "beats_sampled": n,
        "seed": seed,
        "gap_variance_health": {"mean": round(mean(gvh), 3), "corr_with_psi": round(_corr(gvh, psi), 3)},
        "structural_health": {"mean": round(mean(sh), 3), "corr_with_psi": round(_corr(sh, psi), 3)},
        "compose_probe_health": {"mean": round(mean(cph), 3), "corr_with_psi": round(_corr(cph, psi), 3)},
        "psi": {"mean": round(mean(psi), 3), "min": round(min(psi), 3), "max": round(max(psi), 3)},
        "dominator_fractions": {k: round(v / n, 3) for k, v in Counter(dominator).items()},
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--beats", type=int, default=1500)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    result = run_sensitivity(beats=args.beats, seed=args.seed)
    path = write_result("psi_sensitivity", result)
    print(f"Wrote {path}")
    print(f"  dominators: {result.get('dominator_fractions', {})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
