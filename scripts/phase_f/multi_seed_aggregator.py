"""v1.2.3 — multi-seed soak aggregator.

Aggregates multiple per-seed soak reports into a per-preset summary.
Confirms whether the headline +150% learner-adoptions finding from
Checkpoint J is reproducible across seeds (not just a seed=42 artifact).

Reads soak files matching `soak_seed<N>_<preset>.json`; groups by preset;
reports mean/median/min/max across seeds for each key metric.

Output: results/phase_f/multi_seed_summary.json + a markdown table.

Usage:
    python scripts/phase_f/multi_seed_aggregator.py
    # picks up all soak_seed*_uniform.json + soak_seed*_pneuma.json files
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

RESULTS_DIR = Path("results")
SOAK_FILE_RE = re.compile(r"^(?P<prefix>soak\w*)_seed(?P<seed>\d+)_(?P<preset>\w+)\.json$")

# Alias map: short filename suffix → canonical preset name.
PRESET_ALIASES = {
    "pneuma": "pneuma_weighted",
    "eidolon": "eidolon_weighted",
}


def _read_soaks(
    root: Path, *, filename_prefix: str | None = None,
) -> dict[str, list[tuple[int, dict[str, Any]]]]:
    """Returns {preset_name: [(seed, soak_body), ...]} sorted by seed.

    Args:
        root: directory to scan.
        filename_prefix: if set, only match files whose prefix matches exactly
            (e.g., 'soak50k' to scope to the v1.2.4 long-run set).
    """
    by_preset: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    pattern = f"{filename_prefix}_seed*_*.json" if filename_prefix else "soak*_seed*_*.json"
    for path in sorted(root.glob(pattern)):
        m = SOAK_FILE_RE.match(path.name)
        if not m:
            continue
        if filename_prefix and m.group("prefix") != filename_prefix:
            continue
        seed = int(m.group("seed"))
        preset_raw = m.group("preset")
        preset = PRESET_ALIASES.get(preset_raw, preset_raw)
        try:
            body = json.loads(path.read_text())
        except Exception:
            continue
        by_preset[preset].append((seed, body))
    return by_preset


def _agg(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": round(mean(values), 4),
        "median": round(median(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def aggregate(by_preset: dict[str, list[tuple[int, dict[str, Any]]]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"presets": {}}
    for preset, runs in sorted(by_preset.items()):
        seeds = [seed for seed, _ in runs]
        rolling_p95 = [r["perf"]["rolling10_p95_ms"] for _, r in runs]
        recovery_events = [r["recovery"]["finalized_events"] for _, r in runs]
        composite = [r["recovery"]["composite_score_mean"] for _, r in runs
                     if r["recovery"]["composite_score_mean"] is not None]
        adoptions = [r["recovery"]["learner_adoptions"] for _, r in runs]
        reversions = [r["recovery"]["learner_reversions"] for _, r in runs]
        v11_all_pass = all(r["perf"]["v11_pass"] for _, r in runs)
        v13_uncon_all_pass = all(r["v13"]["uncontrolled_pass"] for _, r in runs)
        v13_osc_all_pass = all(r["v13"]["oscillation_pass"] for _, r in runs)
        overall_all_pass = all(r.get("overall_pass") for _, r in runs)
        summary["presets"][preset] = {
            "n_seeds": len(seeds),
            "seeds": seeds,
            "rolling10_p95_ms": _agg(rolling_p95),
            "finalized_events": _agg(recovery_events),
            "composite_score": _agg(composite),
            "learner_adoptions": _agg(adoptions),
            "learner_reversions": _agg(reversions),
            "v11_all_pass": v11_all_pass,
            "v13_uncontrolled_all_pass": v13_uncon_all_pass,
            "v13_oscillation_all_pass": v13_osc_all_pass,
            "overall_all_pass": overall_all_pass,
        }
    # Cross-preset comparison: pneuma_weighted vs uniform on learner_adoptions
    if "uniform" in summary["presets"] and "pneuma_weighted" in summary["presets"]:
        u = summary["presets"]["uniform"]["learner_adoptions"]["mean"]
        p = summary["presets"]["pneuma_weighted"]["learner_adoptions"]["mean"]
        ratio = round(p / u, 2) if u > 0 else None
        summary["pneuma_vs_uniform"] = {
            "adoptions_mean_uniform": u,
            "adoptions_mean_pneuma_weighted": p,
            "ratio": ratio,
            "reproduces_checkpoint_j_finding": ratio is not None and ratio >= 1.5,
        }
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Multi-seed soak summary (v1.2.3)")
    lines.append("")
    lines.append("## Per-preset aggregates")
    lines.append("")
    for preset, body in summary.get("presets", {}).items():
        lines.append(f"### `{preset}` (n_seeds={body['n_seeds']}, seeds={body['seeds']})")
        lines.append("")
        lines.append("| Metric | mean | median | min | max |")
        lines.append("|---|---|---|---|---|")
        for m in ("rolling10_p95_ms", "finalized_events", "composite_score",
                  "learner_adoptions", "learner_reversions"):
            agg = body.get(m, {})
            lines.append(f"| {m} | {agg.get('mean')} | {agg.get('median')} | "
                         f"{agg.get('min')} | {agg.get('max')} |")
        lines.append("")
        lines.append(f"- V11 perf gate (all seeds): "
                     f"**{'PASS' if body['v11_all_pass'] else 'FAIL'}**")
        lines.append(f"- V13 uncontrolled (all seeds): "
                     f"**{'PASS' if body['v13_uncontrolled_all_pass'] else 'FAIL'}**")
        lines.append(f"- V13 oscillation (all seeds): "
                     f"**{'PASS' if body['v13_oscillation_all_pass'] else 'FAIL'}**")
        lines.append(f"- Overall ship-gate (all seeds): "
                     f"**{'PASS' if body['overall_all_pass'] else 'FAIL'}**")
        lines.append("")
    cmp = summary.get("pneuma_vs_uniform")
    if cmp:
        lines.append("## Cross-preset: PNEUMA-weighted learner-adoptions ratio")
        lines.append("")
        lines.append(f"- uniform mean adoptions: {cmp['adoptions_mean_uniform']}")
        lines.append(f"- pneuma_weighted mean adoptions: {cmp['adoptions_mean_pneuma_weighted']}")
        lines.append(f"- ratio: **{cmp['ratio']}×**")
        lines.append(f"- reproduces Checkpoint J's +150% finding (ratio ≥ 1.5): "
                     f"**{cmp['reproduces_checkpoint_j_finding']}**")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    p.add_argument(
        "--prefix", type=str, default=None,
        help="filename prefix to scope to (e.g., 'soak50k'); default = all soak* files",
    )
    p.add_argument("--output", "-o", type=Path,
                   default=Path("results/phase_f/multi_seed_summary.json"))
    p.add_argument("--md-output", type=Path,
                   default=Path("results/phase_f/multi_seed_summary.md"))
    args = p.parse_args()

    by_preset = _read_soaks(args.results_dir, filename_prefix=args.prefix)
    if not by_preset:
        print(f"No soak*_seed*_*.json files in {args.results_dir} "
              f"(prefix={args.prefix})")
        return 1
    summary = aggregate(by_preset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2))
    args.md_output.write_text(render_markdown(summary))
    print(f"Wrote {args.output}")
    print(f"Wrote {args.md_output}")
    for preset, body in summary.get("presets", {}).items():
        print(f"  {preset}: n_seeds={body['n_seeds']}, "
              f"adoptions mean={body['learner_adoptions']['mean']}, "
              f"overall_pass={body['overall_all_pass']}")
    cmp = summary.get("pneuma_vs_uniform")
    if cmp:
        print(f"  PNEUMA / uniform adoptions ratio: {cmp['ratio']}× "
              f"(reproduces Checkpoint J: {cmp['reproduces_checkpoint_j_finding']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
