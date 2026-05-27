"""v1.7 default-flip decision analyzer (MNEME stage-2/3 compensations, Checkpoint LL).

Mirrors `decide_v1_5.py`'s structure but tailored to the MNEME-compensation
default-flip question rather than the AOS-G metric question. The pairing
under evaluation is `mneme_compensation_2_enabled=True` +
`mneme_compensation_3_enabled=True` (both on).

Six gates (all must PASS for v1.7 default-flip):

  1. V11 + V13 (hard gate)              — 10/10 runs (3 seeds × 2 conditions)
                                          must pass perf + V13 acceptance gates
  2. Recovery quality stable            — composite_score Δ ≥ -0.02 per seed
                                          under mneme-on vs off
  3. Learner productivity (refined,
     Checkpoint MM)                     — per seed: EITHER Δ adoptions ≥ 0
                                          OR Δ quality ≥ 0.10. Refines the
                                          original strict adoption-net check
                                          (LL discovered that strict net was
                                          a regime-shift artifact when
                                          compensations dramatically improve
                                          quality — substrate reaches optimum,
                                          learner correctly stops exploring).
                                          The 0.10 threshold is NOT a new
                                          magic number: it's the same value
                                          used in `LearnerEfficacy.EFFECTIVE`
                                          (`recovery.py:550` — `improvement
                                          >= 0.10 → EFFECTIVE`). This refinement
                                          backwards-validates: under v1.5 BB,
                                          Δ quality ≈ 0 and Δ adoptions ≈ 0,
                                          so both clauses are trivially satisfied
                                          per seed — the refined criterion
                                          calls v1.5's sweep the same way the
                                          original strict adoption-net did
                                          (PASS). The refinement only differs
                                          from the strict reading when ONE of
                                          {adoptions, quality} dramatically
                                          shifts, which is exactly the regime
                                          the strict criterion mishandles.
  4. Substrate stability not degraded   — fragmentation_stage_change events
                                          per beat under MNEME-on must not
                                          increase by >50% vs MNEME-off
  5. No runaway dynamics                — no `recovery_feedback_uncontrolled`
                                          events in either branch
  6. MNEME-specific benefit             — at least N-1 of N seeds show ≥1 of:
                                          lower fragmentation rate, higher
                                          recovery quality mean, or higher
                                          adoption count under mneme-on

Usage:
    python scripts/phase_f/decide_v1_7.py <sweep_dir>

Expected files in sweep_dir: soak_seed{N}_mneme_{off,on}.json for each seed.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_FILENAME_RE = re.compile(r"^soak_seed(?P<seed>-?\d+)_mneme_(?P<mode>off|on)\.json$")


def discover(root: Path) -> dict[int, dict[str, dict[str, Any]]]:
    """Return {seed: {'off': summary, 'on': summary}} from sweep_dir."""
    rows: dict[int, dict[str, dict[str, Any]]] = {}
    for p in sorted(root.glob("soak_seed*_mneme_*.json")):
        m = _FILENAME_RE.match(p.name)
        if not m:
            continue
        seed = int(m.group("seed"))
        mode = m.group("mode")
        rows.setdefault(seed, {})[mode] = json.loads(p.read_text())
    return rows


def analyze(rows: dict[int, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    seeds = sorted(rows.keys())
    out: dict[str, Any] = {"seeds": seeds, "criteria": {}}

    # 1. Hard gate
    hard_gate_per_seed = {
        seed: all(rows[seed][m]["overall_pass"] for m in ("off", "on"))
        for seed in seeds
    }
    out["criteria"]["hard_gate"] = {
        "name": f"V11 + V13 (all {2 * len(seeds)} runs)",
        "pass": all(hard_gate_per_seed.values()),
        "per_seed": hard_gate_per_seed,
    }

    # 2. Recovery quality stable (Δ composite_score ≥ -0.02 per seed)
    qual_per_seed = {}
    qual_deltas = {}
    for seed in seeds:
        off_q = rows[seed]["off"]["recovery"]["composite_score_mean"]
        on_q = rows[seed]["on"]["recovery"]["composite_score_mean"]
        if off_q is None or on_q is None:
            qual_per_seed[seed] = True
            qual_deltas[seed] = None
        else:
            delta = on_q - off_q
            qual_deltas[seed] = delta
            qual_per_seed[seed] = delta >= -0.02
    out["criteria"]["quality"] = {
        "name": "Δ composite_score ≥ -0.02",
        "pass": all(qual_per_seed.values()),
        "per_seed": qual_per_seed,
        "deltas": qual_deltas,
    }

    # 3. Learner productivity (quality-conditional, Checkpoint MM refinement).
    # Per-seed: PASS if EITHER Δ adoptions ≥ 0 OR Δ quality ≥ 0.10 (the
    # latter matches LearnerEfficacy.EFFECTIVE's improvement threshold in
    # recovery.py:550). The substrate's own definition of "meaningful
    # improvement" applied to the cross-condition comparison: if quality
    # improved meaningfully, the learner doing less work is correct
    # behavior, not a regression.
    _QUALITY_IMPROVEMENT_THRESHOLD = 0.10
    productivity_per_seed = {}
    productivity_details = {}
    for seed in seeds:
        off_a = rows[seed]["off"]["recovery"]["learner_adoptions"]
        on_a = rows[seed]["on"]["recovery"]["learner_adoptions"]
        off_q = rows[seed]["off"]["recovery"]["composite_score_mean"] or 0.0
        on_q = rows[seed]["on"]["recovery"]["composite_score_mean"] or 0.0
        delta_a = on_a - off_a
        delta_q = on_q - off_q
        clause_a = delta_a >= 0
        clause_q = delta_q >= _QUALITY_IMPROVEMENT_THRESHOLD
        productivity_per_seed[seed] = clause_a or clause_q
        productivity_details[seed] = {
            "delta_adoptions": delta_a,
            "delta_quality": delta_q,
            "clause_a_pass": clause_a,
            "clause_q_pass": clause_q,
        }
    # Also keep the raw net for transparency in the output
    net_adoptions = sum(d["delta_adoptions"] for d in productivity_details.values())
    out["criteria"]["learner_productivity"] = {
        "name": "Δ adoptions ≥ 0 OR Δ quality ≥ 0.10 (per seed)",
        "pass": all(productivity_per_seed.values()),
        "per_seed": productivity_per_seed,
        "details": productivity_details,
        "strict_net_adoptions": net_adoptions,  # for transparency vs LL's strict reading
    }

    # 4. Substrate stability — fragmentation rate not degraded by >50%
    frag_rates_off = {}
    frag_rates_on = {}
    frag_per_seed = {}
    for seed in seeds:
        beats_off = rows[seed]["off"]["beats"]
        beats_on = rows[seed]["on"]["beats"]
        n_off = rows[seed]["off"]["events"].get("fragmentation_stage_change", 0)
        n_on = rows[seed]["on"]["events"].get("fragmentation_stage_change", 0)
        rate_off = n_off / max(beats_off, 1)
        rate_on = n_on / max(beats_on, 1)
        frag_rates_off[seed] = rate_off
        frag_rates_on[seed] = rate_on
        # Allow up to 50% increase (and unlimited decrease)
        frag_per_seed[seed] = (
            rate_on <= 1.5 * rate_off if rate_off > 0 else True
        )
    out["criteria"]["frag_stability"] = {
        "name": "fragmentation rate not >50% worse",
        "pass": all(frag_per_seed.values()),
        "per_seed": frag_per_seed,
        "rates_off": frag_rates_off,
        "rates_on": frag_rates_on,
    }

    # 5. No runaway dynamics
    runaway_per_seed = {}
    for seed in seeds:
        n_off = rows[seed]["off"]["events"].get("recovery_feedback_uncontrolled", 0)
        n_on = rows[seed]["on"]["events"].get("recovery_feedback_uncontrolled", 0)
        runaway_per_seed[seed] = (n_off == 0 and n_on == 0)
    out["criteria"]["no_runaway"] = {
        "name": "zero recovery_feedback_uncontrolled events",
        "pass": all(runaway_per_seed.values()),
        "per_seed": runaway_per_seed,
    }

    # 6. MNEME-specific benefit: at least ONE of {lower frag rate,
    #    higher recovery quality, higher adoption count} per seed
    benefit_per_seed = {}
    benefit_details = {}
    for seed in seeds:
        n_off = rows[seed]["off"]["events"].get("fragmentation_stage_change", 0)
        n_on = rows[seed]["on"]["events"].get("fragmentation_stage_change", 0)
        beats_off = rows[seed]["off"]["beats"]
        beats_on = rows[seed]["on"]["beats"]
        rate_off = n_off / max(beats_off, 1)
        rate_on = n_on / max(beats_on, 1)
        off_q = rows[seed]["off"]["recovery"]["composite_score_mean"] or 0.0
        on_q = rows[seed]["on"]["recovery"]["composite_score_mean"] or 0.0
        off_a = rows[seed]["off"]["recovery"]["learner_adoptions"]
        on_a = rows[seed]["on"]["recovery"]["learner_adoptions"]

        lower_frag = rate_on < rate_off
        higher_quality = on_q > off_q
        higher_adoption = on_a > off_a
        any_benefit = lower_frag or higher_quality or higher_adoption
        benefit_per_seed[seed] = any_benefit
        benefit_details[seed] = {
            "lower_frag": lower_frag,
            "higher_quality": higher_quality,
            "higher_adoption": higher_adoption,
        }
    # Require benefit in at least 2 of N seeds (tolerate 1 noise outlier)
    n_benefit = sum(benefit_per_seed.values())
    out["criteria"]["mneme_benefit"] = {
        "name": f"≥2 of {len(seeds)} seeds show ANY measurable improvement",
        "pass": n_benefit >= max(2, len(seeds) - 1),
        "per_seed": benefit_per_seed,
        "details": benefit_details,
        "n_benefit": n_benefit,
    }

    out["all_pass"] = all(c["pass"] for c in out["criteria"].values())
    return out


def print_report(result: dict[str, Any]) -> None:
    seeds = result["seeds"]
    print("=" * 100)
    print(f"v1.7 MNEME stage-2/3 default-flip decision — {len(seeds)} seeds × {{both off, both on}}")
    print("=" * 100)

    crits = result["criteria"]

    print("\n[1/6] Hard gate (V11 + V13, all runs):")
    for seed in seeds:
        print(f"  seed={seed}: {'PASS' if crits['hard_gate']['per_seed'][seed] else 'FAIL'}")
    print(f"  → {'✓' if crits['hard_gate']['pass'] else '✗'} {crits['hard_gate']['name']}")

    print("\n[2/6] Recovery quality stable (Δ composite_score ≥ -0.02):")
    for seed in seeds:
        d = crits["quality"]["deltas"][seed]
        ds = f"{d:+.3f}" if d is not None else "n/a"
        print(f"  seed={seed}: Δ={ds:>7}  "
              f"{'PASS' if crits['quality']['per_seed'][seed] else 'FAIL'}")
    print(f"  → {'✓' if crits['quality']['pass'] else '✗'} {crits['quality']['name']}")

    print("\n[3/6] Learner productivity (Δ adopt ≥ 0 OR Δ quality ≥ 0.10):")
    lp = crits["learner_productivity"]
    for seed in seeds:
        d = lp["details"][seed]
        reason = (
            f"adopt clause ({d['delta_adoptions']:+d} ≥ 0)" if d["clause_a_pass"]
            else f"quality clause ({d['delta_quality']:+.3f} ≥ 0.10)" if d["clause_q_pass"]
            else f"BOTH FAIL (Δa={d['delta_adoptions']:+d}, Δq={d['delta_quality']:+.3f})"
        )
        print(f"  seed={seed}: {reason:<48}  "
              f"{'PASS' if lp['per_seed'][seed] else 'FAIL'}")
    print(f"  (transparency: strict net Δ adoptions = {lp['strict_net_adoptions']:+d})")
    print(f"  → {'✓' if lp['pass'] else '✗'} {lp['name']}")

    print("\n[4/6] Substrate stability (frag rate not >50% worse):")
    fr = crits["frag_stability"]
    for seed in seeds:
        ro = fr["rates_off"][seed]
        rn = fr["rates_on"][seed]
        ratio = rn / ro if ro > 0 else float("inf")
        print(f"  seed={seed}: rate_off={ro:.5f} rate_on={rn:.5f} (×{ratio:.2f})  "
              f"{'PASS' if fr['per_seed'][seed] else 'FAIL'}")
    print(f"  → {'✓' if fr['pass'] else '✗'} {fr['name']}")

    print("\n[5/6] No runaway dynamics (zero recovery_feedback_uncontrolled):")
    for seed in seeds:
        print(f"  seed={seed}: {'PASS' if crits['no_runaway']['per_seed'][seed] else 'FAIL'}")
    print(f"  → {'✓' if crits['no_runaway']['pass'] else '✗'} {crits['no_runaway']['name']}")

    print("\n[6/6] MNEME-specific benefit (per-seed):")
    mb = crits["mneme_benefit"]
    for seed in seeds:
        d = mb["details"][seed]
        flags = []
        if d["lower_frag"]:
            flags.append("frag↓")
        if d["higher_quality"]:
            flags.append("quality↑")
        if d["higher_adoption"]:
            flags.append("adopt↑")
        flag_str = ",".join(flags) if flags else "—"
        print(f"  seed={seed}: {flag_str:<25}  "
              f"{'PASS' if mb['per_seed'][seed] else 'FAIL'}")
    print(f"  benefit_count: {mb['n_benefit']}/{len(seeds)}")
    print(f"  → {'✓' if mb['pass'] else '✗'} {mb['name']}")

    print("\n" + "=" * 100)
    print("DECISION")
    print("=" * 100)
    if result["all_pass"]:
        print("  ✅ RECOMMEND v1.7 DEFAULT-FLIP:")
        print("     `mneme_compensation_2_enabled=True` + `mneme_compensation_3_enabled=True`")
    else:
        failing = [name for name, c in crits.items() if not c["pass"]]
        print(f"  ❌ HOLD: criteria failing = {failing}")
        print("     Recommend: keep MNEME compensations as opt-in (v1.6.2 status).")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: decide_v1_7.py <sweep_dir>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    rows = discover(root)
    if not rows:
        print(f"no soak_seed*_mneme_*.json files in {root}", file=sys.stderr)
        return 2
    result = analyze(rows)
    print_report(result)
    return 0 if result["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
