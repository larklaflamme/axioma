"""Phase E V13 — long-run soak harness.

Per IMPLEMENTATION_PLAN_v1.0.md §9.4 + §9.5 + ARCH §9.3.

Runs the full Phase A+B+C+D stack for a configurable number of beats (24h
× 10 Hz = 864 000 beats by default) and produces a soak report:
  - V11 perf gate check (10-beat rolling avg < 100 ms)
  - V13 soak success criteria (zero `recovery_feedback_uncontrolled`, < 5
    `recovery_feedback_oscillation_detected` per 24 h, etc.)
  - Per-engine event counts + recovery quality histograms

Output: `data/state/soak_report_<timestamp>.md` + JSON summary.

Usage:
    python scripts/phase_e_soak.py --beats 10000          # quick smoke
    python scripts/phase_e_soak.py --hours 24             # full v1.0 gate
    python scripts/phase_e_soak.py --beats 100000 --seed 7 -o /tmp/soak.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from axioma.measurement.aos_g_engine import (
    EIDOLON_WEIGHTED_GAP_WEIGHTS,
    PNEUMA_WEIGHTED_GAP_WEIGHTS,
    UNIFORM_GAP_WEIGHTS,
)
from integration.phase_e_harness import build_phase_e_stack

GAP_WEIGHTS_PRESETS = {
    "uniform": UNIFORM_GAP_WEIGHTS,
    "eidolon_weighted": EIDOLON_WEIGHTED_GAP_WEIGHTS,
    "pneuma_weighted": PNEUMA_WEIGHTED_GAP_WEIGHTS,
}


def run_soak(
    *,
    beats: int,
    seed: int,
    gap_weights_preset: str = "uniform",
    config_path: Path | None = None,
    normalize_per_organ: bool | None = None,
    mneme_stage2: bool | None = None,
    mneme_stage3: bool | None = None,
) -> dict[str, Any]:
    """Run a soak.

    If `config_path` is provided, load AxiomaConfig from that YAML (via
    AXIOMA_CONFIG env var). Otherwise use AxiomaConfig defaults +
    `gap_weights_preset` to swap the AOS-G preset.

    `normalize_per_organ` (v1.4.1): when not None, overrides the cfg-driven
    aos_g_normalize_per_organ value. Lets A/B sweeps flip just this knob.

    `mneme_stage2` / `mneme_stage3` (v1.6.2, Checkpoint LL): when not None,
    override the cfg-driven mneme_compensation_{2,3}_enabled values. Lets
    A/B sweeps flip just MNEME's stage-2 cross-coupling and/or stage-3
    faster-plasticity flags.
    """
    if config_path is not None:
        # AXIOMA_CONFIG path takes effect within load_config()
        import os as _os

        from axioma.config import load_config
        _os.environ["AXIOMA_CONFIG"] = str(config_path)
        cfg = load_config()
        if normalize_per_organ is not None:
            object.__setattr__(cfg.compose, "aos_g_normalize_per_organ", bool(normalize_per_organ))
        if mneme_stage2 is not None:
            object.__setattr__(cfg.substrate, "mneme_compensation_2_enabled", bool(mneme_stage2))
        if mneme_stage3 is not None:
            object.__setattr__(cfg.substrate, "mneme_compensation_3_enabled", bool(mneme_stage3))
        print(f"Building Phase E stack (seed={seed}, config={config_path.name}, "
              f"gap_weights_from_cfg={cfg.compose.aos_g_gap_weights is not None}, "
              f"normalize_per_organ={cfg.compose.aos_g_normalize_per_organ}, "
              f"mneme_stage2={cfg.substrate.mneme_compensation_2_enabled}, "
              f"mneme_stage3={cfg.substrate.mneme_compensation_3_enabled})...")
        stack = build_phase_e_stack(seed=seed, cfg=cfg)
    else:
        from axioma.config import AxiomaConfig

        cfg = AxiomaConfig()
        weights = GAP_WEIGHTS_PRESETS.get(gap_weights_preset, UNIFORM_GAP_WEIGHTS)
        object.__setattr__(cfg.compose, "aos_g_gap_weights", weights)
        if normalize_per_organ is not None:
            object.__setattr__(cfg.compose, "aos_g_normalize_per_organ", bool(normalize_per_organ))
        if mneme_stage2 is not None:
            object.__setattr__(cfg.substrate, "mneme_compensation_2_enabled", bool(mneme_stage2))
        if mneme_stage3 is not None:
            object.__setattr__(cfg.substrate, "mneme_compensation_3_enabled", bool(mneme_stage3))
        print(f"Building Phase E stack (seed={seed}, gap_weights={gap_weights_preset}, "
              f"normalize_per_organ={cfg.compose.aos_g_normalize_per_organ}, "
              f"mneme_stage2={cfg.substrate.mneme_compensation_2_enabled}, "
              f"mneme_stage3={cfg.substrate.mneme_compensation_3_enabled})...")
        stack = build_phase_e_stack(seed=seed, cfg=cfg, gap_weights=weights)
    # Subscribe to interesting events
    event_counts: Counter[str] = Counter()
    for event_name in (
        "perturbation_injected", "recovery_decision", "recovery_state_change",
        "recovery_event_finalized", "recovery_quality_updated",
        "recovery_rejected_run", "fragmentation_stage_change",
        "meta_cognition_divergence", "meta_cognition_suggestion",
        "recovery_feedback_oscillation_detected", "recovery_feedback_uncontrolled",
    ):
        stack.ctx.subscribe(event_name, lambda _p, n=event_name: event_counts.update([n]))

    # Run with timing + per-beat gap sampling (v1.2.4: record gap distribution
    # so future calibration runs don't need to re-measure).
    # v1.4.2: also capture aos_g_alert_threshold trajectory — every time the
    # auto-tuner fires, record (beat_no, prev, new). Lets v1.5 default-flip
    # analysis verify the threshold converges rather than drifts.
    print(f"Running {beats} beats...")
    durations: list[float] = []
    gap_samples: list[float] = []
    threshold_trajectory: list[dict[str, float]] = []
    prev_threshold = float(stack.aos_g.aos_g_alert_threshold)
    threshold_trajectory.append({"beat_no": 0, "threshold": prev_threshold, "reason": "initial"})
    t_start = time.perf_counter()
    for i in range(beats):
        t0 = time.perf_counter()
        stack.hb.tick()
        durations.append(time.perf_counter() - t0)
        cv = stack.aos_g.current_value()
        if cv is not None and getattr(cv, "valid", False):
            gap_samples.append(float(getattr(cv, "aos_g_gap", 0.0)))
        cur_threshold = float(stack.aos_g.aos_g_alert_threshold)
        if cur_threshold != prev_threshold:
            threshold_trajectory.append({
                "beat_no": i,
                "threshold": round(cur_threshold, 6),
                "reason": "auto_tune_fired",
            })
            prev_threshold = cur_threshold
        if i and i % 5000 == 0:
            elapsed = time.perf_counter() - t_start
            rate = i / elapsed
            print(f"  beat {i}/{beats}  rate={rate:.0f} beats/s  eta={(beats - i) / rate:.0f}s")
    t_total = time.perf_counter() - t_start

    # Per-stage histograms
    finalized_events = stack.recovery_protocol.history.all_events()
    composite_scores = [
        e.quality.composite_score for e in finalized_events if e.quality_finalized
    ]
    durability_scores = [
        e.quality.durability for e in finalized_events
        if e.quality.durability is not None
    ]

    # Perf metrics
    from statistics import mean, median
    avg_dur = mean(durations)
    p50 = median(durations)
    sorted_d = sorted(durations)
    p95 = sorted_d[int(len(sorted_d) * 0.95)] if sorted_d else 0
    p99 = sorted_d[int(len(sorted_d) * 0.99)] if sorted_d else 0
    worst = max(durations) if durations else 0
    # 10-beat rolling avg
    rolling_means = [mean(durations[i:i + 10]) for i in range(len(durations) - 10)]
    rolling_p95 = sorted(rolling_means)[int(len(rolling_means) * 0.95)] if rolling_means else 0

    # V11 gate
    v11_pass = rolling_p95 < 0.100
    # V13: zero uncontrolled feedback events
    v13_uncontrolled_pass = event_counts["recovery_feedback_uncontrolled"] == 0
    # V13: oscillation < 5 per 24h equivalent
    osc_count = event_counts["recovery_feedback_oscillation_detected"]
    oscillation_per_24h = osc_count * (864000 / max(beats, 1))
    v13_oscillation_pass = oscillation_per_24h < 5

    summary = {
        "beats": beats,
        "wall_clock_seconds": round(t_total, 2),
        "beats_per_second": round(beats / t_total, 1),
        "seed": seed,
        "perf": {
            "avg_ms": round(avg_dur * 1000, 3),
            "p50_ms": round(p50 * 1000, 3),
            "p95_ms": round(p95 * 1000, 3),
            "p99_ms": round(p99 * 1000, 3),
            "worst_ms": round(worst * 1000, 3),
            "rolling10_p95_ms": round(rolling_p95 * 1000, 3),
            "v11_pass": v11_pass,
        },
        "recovery": {
            "finalized_events": len(finalized_events),
            "composite_score_mean": round(
                mean(composite_scores), 3
            ) if composite_scores else None,
            "durability_finalized_count": len(durability_scores),
            "durability_mean": round(
                mean(durability_scores), 3
            ) if durability_scores else None,
            "learner_adoptions": stack.recovery_protocol.learner.adoptions_count,
            "learner_reversions": stack.recovery_protocol.learner.reversions_count,
            "learner_efficacy_stage2": stack.recovery_protocol.learner.efficacy_per_stage[2].value,
            "learner_efficacy_stage3": stack.recovery_protocol.learner.efficacy_per_stage[3].value,
        },
        "events": dict(event_counts),
        "v13": {
            "uncontrolled_feedback_count": event_counts["recovery_feedback_uncontrolled"],
            "uncontrolled_pass": v13_uncontrolled_pass,
            "oscillation_count": osc_count,
            "oscillation_per_24h_equivalent": round(oscillation_per_24h, 2),
            "oscillation_pass": v13_oscillation_pass,
        },
        "gap": _gap_summary(gap_samples),
        # v1.4.2 auto-tune trajectory: empty/length-1 when auto-tune is off.
        # First entry is always the initial threshold; subsequent entries record
        # each auto-tune firing (beat_no, threshold, reason).
        "alert_threshold_trajectory": threshold_trajectory,
        "alert_threshold_final": round(float(stack.aos_g.aos_g_alert_threshold), 6),
        "alert_threshold_initial": round(threshold_trajectory[0]["threshold"], 6),
        "alert_threshold_n_tunes": len(threshold_trajectory) - 1,
        "overall_pass": v11_pass and v13_uncontrolled_pass and v13_oscillation_pass,
    }
    return summary


def _gap_summary(gaps: list[float]) -> dict[str, Any]:
    """Summary stats for aos_g_gap samples — used by calibration tools (v1.2.4)."""
    if not gaps:
        return {"n": 0}
    sgaps = sorted(gaps)
    n = len(gaps)
    return {
        "n": n,
        "mean": round(sum(gaps) / n, 4),
        "p50": round(sgaps[n // 2], 4),
        "p95": round(sgaps[int(n * 0.95)], 4),
        "p99": round(sgaps[int(n * 0.99)], 4),
        "min": round(min(gaps), 4),
        "max": round(max(gaps), 4),
    }


def write_report(summary: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2))


def print_report(summary: dict[str, Any]) -> None:
    print("\n" + "=" * 60)
    print("PHASE E SOAK REPORT")
    print("=" * 60)
    print(f"beats={summary['beats']}  wall={summary['wall_clock_seconds']}s "
          f"rate={summary['beats_per_second']} beats/s  seed={summary['seed']}")
    p = summary["perf"]
    print(f"\nPERF: avg={p['avg_ms']} ms p50={p['p50_ms']} ms p95={p['p95_ms']} ms "
          f"p99={p['p99_ms']} ms worst={p['worst_ms']} ms")
    print(f"  V11 rolling10_p95={p['rolling10_p95_ms']} ms (limit 100 ms) "
          f"→ {'PASS' if p['v11_pass'] else 'FAIL'}")
    r = summary["recovery"]
    print(f"\nRECOVERY: {r['finalized_events']} events  "
          f"composite={r['composite_score_mean']}  durability={r['durability_mean']} "
          f"(n={r['durability_finalized_count']})")
    print(f"  learner: adoptions={r['learner_adoptions']} "
          f"reversions={r['learner_reversions']} "
          f"stage2={r['learner_efficacy_stage2']} stage3={r['learner_efficacy_stage3']}")
    v13 = summary["v13"]
    print(f"\nV13: uncontrolled={v13['uncontrolled_feedback_count']} "
          f"→ {'PASS' if v13['uncontrolled_pass'] else 'FAIL'}; "
          f"oscillation={v13['oscillation_count']} "
          f"({v13['oscillation_per_24h_equivalent']}/24h equivalent) "
          f"→ {'PASS' if v13['oscillation_pass'] else 'FAIL'}")
    print(f"\nEVENTS: {summary['events']}")
    print(f"\nOVERALL: {'PASS' if summary['overall_pass'] else 'FAIL'}")
    print("=" * 60)


def main() -> int:
    p = argparse.ArgumentParser()
    group = p.add_mutually_exclusive_group()
    group.add_argument("--beats", "-b", type=int, default=None,
                       help="number of beats to run (default 10000)")
    group.add_argument("--hours", type=float, default=None,
                       help="hours of simulated soak time (10 Hz)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--gap-weights",
        choices=tuple(GAP_WEIGHTS_PRESETS.keys()),
        default="uniform",
        help="AOS-G per-organ Weighted Euclidean preset (v1.1.6). "
             "'uniform' = v1.0 baseline; 'pneuma_weighted' = recommended for "
             "stress-sensitive deployments per the Checkpoint I finding.",
    )
    p.add_argument(
        "--config", type=Path, default=None,
        help="path to a YAML config file (e.g., configs/v1_2_recommended.yaml). "
             "If set, overrides --gap-weights.",
    )
    p.add_argument("--output", "-o", type=Path,
                   default=Path("data/state/soak_report.json"))
    p.add_argument(
        "--normalize-per-organ", dest="normalize_per_organ",
        action="store_true", default=None,
        help="v1.4.1: enable per-organ gap normalization in AOSGEngine "
             "(divide each organ's raw gap by its rolling mean before the "
             "weighted sum). Overrides cfg.compose.aos_g_normalize_per_organ.",
    )
    p.add_argument(
        "--no-normalize-per-organ", dest="normalize_per_organ",
        action="store_false",
        help="v1.4.1: explicitly disable per-organ gap normalization.",
    )
    # v1.6.2 (Checkpoint LL) — MNEME compensation toggles for A/B sweeps.
    p.add_argument(
        "--mneme-stage2", dest="mneme_stage2",
        action="store_true", default=None,
        help="v1.6.2: enable MNEME stage-2 cross-organ coupling per ARCH §4.4 #2. "
             "Overrides cfg.substrate.mneme_compensation_2_enabled.",
    )
    p.add_argument(
        "--no-mneme-stage2", dest="mneme_stage2", action="store_false",
        help="v1.6.2: explicitly disable MNEME stage-2.",
    )
    p.add_argument(
        "--mneme-stage3", dest="mneme_stage3",
        action="store_true", default=None,
        help="v1.6.2: enable MNEME stage-3 faster plasticity (alpha_p=0.10). "
             "Overrides cfg.substrate.mneme_compensation_3_enabled.",
    )
    p.add_argument(
        "--no-mneme-stage3", dest="mneme_stage3", action="store_false",
        help="v1.6.2: explicitly disable MNEME stage-3.",
    )
    args = p.parse_args()
    if args.hours is not None:
        beats = int(args.hours * 3600 * 10)
    elif args.beats is not None:
        beats = args.beats
    else:
        beats = 10000
    summary = run_soak(
        beats=beats, seed=args.seed,
        gap_weights_preset=args.gap_weights,
        config_path=args.config,
        normalize_per_organ=args.normalize_per_organ,
        mneme_stage2=args.mneme_stage2,
        mneme_stage3=args.mneme_stage3,
    )
    if args.config:
        # When loaded from a config file, report the actual weights distribution
        # rather than the CLI default placeholder.
        summary["config_path"] = str(args.config)
        summary["gap_weights_preset"] = "from_config"
    else:
        summary["gap_weights_preset"] = args.gap_weights
    summary["normalize_per_organ"] = args.normalize_per_organ
    # v1.6.2 (Checkpoint LL): surface MNEME flags in summary for the v1.7 analyzer.
    summary["mneme_stage2"] = args.mneme_stage2
    summary["mneme_stage3"] = args.mneme_stage3
    write_report(summary, args.output)
    print_report(summary)
    print(f"\nWrote report → {args.output}")
    return 0 if summary["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
