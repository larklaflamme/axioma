"""v1.5 default-flip decision analyzer (refined criteria, Checkpoint Y).

Promoted from `/tmp/v1_5_sweep/decide_v1_5.py` (Checkpoint W scratch) after
Checkpoint X exposed that the strict `|final - first|/first < 20%` proxy was
measuring the wrong thing — the v1.4.4 gating fix brought typical drift into
the 7-24% range, where the 20% cutoff hits natural noise.

Refined criteria (six gates, all must PASS for v1.5 default-flip):

  1. V11 + V13 (hard gate)              — 6/6 runs must pass perf + recovery
                                          feedback acceptance gates
  2. Calibration accuracy               — for normalize-on branch: first_set
                                          within [0.7, 1.5] × final (i.e.,
                                          first auto-tune fires within ±50%
                                          of the eventual converged value)
  3. Cross-seed convergence             — CV(final_across_seeds) < 15%
                                          (converged value is stable across
                                          substrate seeds — auto-tune isn't
                                          picking random values)
  4. No runaway tuning                  — n_tunes ≤ ceil(beats / recompute) + 1
                                          (auto-tune isn't retriggering
                                          excessively)
  5. Recovery quality stable            — composite_score Δ ≥ -0.02 per seed
                                          under normalize-on vs off
  6. Learner adoptions net non-negative — sum(Δ adoptions across seeds) ≥ 0

Rationale for the [0.7, 1.5] band on first/final ratio:
  - At the 50K-beat horizon, only one recompute fires (at beat 36K with
    default settings), so there are exactly two tunes in the trajectory.
  - The gap distribution has natural per-30K-window variance of ~10-15%,
    so any single tune's value will fluctuate by that much vs the long-run
    mean. ±50% accommodates that variance plus 30K-beat trajectory drift
    plus 10% measurement noise on the rolling-mean.
  - A first set landing at 2× the converged value (W's behavior) is the
    failure mode we ship X to fix; this criterion catches that without
    hitting natural statistical noise.

Usage:
    python scripts/phase_f/decide_v1_5.py path/to/sweep_dir

Expected dir contents: soak_seed{N}_normalize_{off,on}.json for each seed.
Discovers seeds dynamically from filenames.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

_FILENAME_RE = re.compile(r"^soak_seed(?P<seed>-?\d+)_normalize_(?P<mode>off|on)\.json$")


def discover(root: Path) -> dict[int, dict[str, dict[str, Any]]]:
    """Return {seed: {'off': summary, 'on': summary}} from sweep_dir."""
    rows: dict[int, dict[str, dict[str, Any]]] = {}
    for p in sorted(root.glob("soak_seed*_normalize_*.json")):
        m = _FILENAME_RE.match(p.name)
        if not m:
            continue
        seed = int(m.group("seed"))
        mode = m.group("mode")
        rows.setdefault(seed, {})[mode] = json.loads(p.read_text())
    return rows


def analyze(rows: dict[int, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    """Run all 6 criteria; return per-criterion + per-seed results + verdict."""
    seeds = sorted(rows.keys())
    out: dict[str, Any] = {"seeds": seeds, "criteria": {}}

    # 1. Hard gate
    hard_gate_per_seed = {
        seed: all(rows[seed][m]["overall_pass"] for m in ("off", "on"))
        for seed in seeds
    }
    out["criteria"]["hard_gate"] = {
        "name": "V11 + V13 (6/6 runs)",
        "pass": all(hard_gate_per_seed.values()),
        "per_seed": hard_gate_per_seed,
    }

    # 2. Calibration accuracy (normalize-on branch only)
    calib_per_seed = {}
    calib_ratios = {}
    for seed in seeds:
        r = rows[seed]["on"]
        first_set = r["alert_threshold_trajectory"][1]["threshold"] if len(
            r["alert_threshold_trajectory"]) >= 2 else None
        final = r["alert_threshold_final"]
        if first_set is None or final == 0:
            ratio = None
            ok = False
        else:
            ratio = first_set / final
            ok = 0.7 <= ratio <= 1.5
        calib_per_seed[seed] = ok
        calib_ratios[seed] = ratio
    out["criteria"]["calibration"] = {
        "name": "first_set / final ∈ [0.7, 1.5]",
        "pass": all(calib_per_seed.values()),
        "per_seed": calib_per_seed,
        "ratios": calib_ratios,
    }

    # 3. Cross-seed convergence (normalize-on branch)
    finals = [rows[seed]["on"]["alert_threshold_final"] for seed in seeds]
    if len(finals) >= 2:
        mean_f = statistics.mean(finals)
        stdev_f = statistics.stdev(finals)
        cv = stdev_f / mean_f if mean_f > 0 else float("inf")
    else:
        mean_f, stdev_f, cv = (finals[0] if finals else 0.0), 0.0, 0.0
    out["criteria"]["cross_seed_convergence"] = {
        "name": "CV(final_across_seeds) < 15%",
        "pass": cv < 0.15,
        "cv": cv,
        "mean": mean_f,
        "stdev": stdev_f,
        "values": finals,
    }

    # 4. No runaway tuning (normalize-on)
    runaway_per_seed = {}
    for seed in seeds:
        r = rows[seed]["on"]
        beats = r["beats"]
        # Default recompute period is 36000; expected tunes = ceil(beats/36K) + 1 (initial+each recompute)
        # The "+1" tolerates timing edge cases.
        expected_max = (beats // 36000) + 1 + 1
        runaway_per_seed[seed] = r["alert_threshold_n_tunes"] <= expected_max
    out["criteria"]["no_runaway"] = {
        "name": "n_tunes ≤ ceil(beats / recompute) + 1",
        "pass": all(runaway_per_seed.values()),
        "per_seed": runaway_per_seed,
    }

    # 5. Recovery quality stable
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

    # 6. Learner adoptions net non-negative
    deltas = {
        seed: (rows[seed]["on"]["recovery"]["learner_adoptions"]
               - rows[seed]["off"]["recovery"]["learner_adoptions"])
        for seed in seeds
    }
    net = sum(deltas.values())
    out["criteria"]["adoptions"] = {
        "name": "Σ Δ adoptions ≥ 0",
        "pass": net >= 0,
        "net_delta": net,
        "per_seed": deltas,
    }

    out["all_pass"] = all(c["pass"] for c in out["criteria"].values())
    return out


def print_report(result: dict[str, Any]) -> None:
    seeds = result["seeds"]
    print("=" * 92)
    print(f"v1.5 default-flip decision — {len(seeds)} seeds × {{normalize off, normalize on}}")
    print("=" * 92)

    crits = result["criteria"]

    print("\n[1/6] Hard gate (V11 + V13, all 6 runs):")
    for seed in seeds:
        print(f"  seed={seed}: {'PASS' if crits['hard_gate']['per_seed'][seed] else 'FAIL'}")
    print(f"  → {'✓' if crits['hard_gate']['pass'] else '✗'} {crits['hard_gate']['name']}")

    print("\n[2/6] Calibration accuracy (first_set / final ∈ [0.7, 1.5]):")
    for seed in seeds:
        r = crits["calibration"]["ratios"][seed]
        rs = f"{r:.3f}" if r is not None else "n/a"
        print(f"  seed={seed}: ratio={rs:>6}  "
              f"{'PASS' if crits['calibration']['per_seed'][seed] else 'FAIL'}")
    print(f"  → {'✓' if crits['calibration']['pass'] else '✗'} {crits['calibration']['name']}")

    print("\n[3/6] Cross-seed convergence:")
    cs = crits["cross_seed_convergence"]
    print(f"  finals: {[f'{v:.4f}' for v in cs['values']]}")
    print(f"  mean={cs['mean']:.4f}  stdev={cs['stdev']:.4f}  CV={cs['cv']:.2%}")
    print(f"  → {'✓' if cs['pass'] else '✗'} {cs['name']}")

    print("\n[4/6] No runaway tuning:")
    for seed in seeds:
        print(f"  seed={seed}: {'PASS' if crits['no_runaway']['per_seed'][seed] else 'FAIL'}")
    print(f"  → {'✓' if crits['no_runaway']['pass'] else '✗'} {crits['no_runaway']['name']}")

    print("\n[5/6] Recovery quality stable (Δ composite_score ≥ -0.02):")
    for seed in seeds:
        d = crits["quality"]["deltas"][seed]
        ds = f"{d:+.3f}" if d is not None else "n/a"
        print(f"  seed={seed}: Δ={ds:>7}  "
              f"{'PASS' if crits['quality']['per_seed'][seed] else 'FAIL'}")
    print(f"  → {'✓' if crits['quality']['pass'] else '✗'} {crits['quality']['name']}")

    print("\n[6/6] Learner adoptions (Σ Δ ≥ 0):")
    for seed in seeds:
        d = crits["adoptions"]["per_seed"][seed]
        print(f"  seed={seed}: Δ={d:+d}")
    print(f"  net: {crits['adoptions']['net_delta']:+d}")
    print(f"  → {'✓' if crits['adoptions']['pass'] else '✗'} {crits['adoptions']['name']}")

    print("\n" + "=" * 92)
    print("DECISION")
    print("=" * 92)
    if result["all_pass"]:
        print("  ✅ RECOMMEND v1.5 DEFAULT-FLIP:")
        print("     `aos_g_normalize_per_organ=True` + `aos_g_alert_threshold_auto_tune=True`")
    else:
        failing = [name for name, c in crits.items() if not c["pass"]]
        print(f"  ❌ HOLD: criteria failing = {failing}")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: decide_v1_5.py <sweep_dir>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    rows = discover(root)
    if not rows:
        print(f"no soak_seed*_normalize_*.json files in {root}", file=sys.stderr)
        return 2
    result = analyze(rows)
    print_report(result)
    return 0 if result["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
