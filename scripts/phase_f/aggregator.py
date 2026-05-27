"""Phase F aggregator — rolls all results into phase_f_summary.md.

Per IMPLEMENTATION_PLAN_v1.0.md §10.2.

Reads every JSON file under results/phase_f/ and produces a markdown report
suitable for the v1.0 acceptance review.

Usage:
    python scripts/phase_f/aggregator.py             # uses default results dir
    python scripts/phase_f/aggregator.py -o /tmp/r.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _harness import RESULTS_ROOT

# File-name prefixes that are not Phase F experiments (skipped by aggregator):
#   - calibration_session_*: live operator session output (rolled up separately)
#   - zone_thresholds.json: derived output from zone_threshold_sweep.json
_NON_EXPERIMENT_PREFIXES = ("calibration_session_",)
_NON_EXPERIMENT_NAMES = {"zone_thresholds"}


def _read_results() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(RESULTS_ROOT.glob("*.json")):
        if any(path.name.startswith(p) for p in _NON_EXPERIMENT_PREFIXES):
            continue
        if path.stem in _NON_EXPERIMENT_NAMES:
            continue
        try:
            out[path.stem] = json.loads(path.read_text())
        except Exception as e:
            out[path.stem] = {"_parse_error": str(e)}
    return out


def _verdict_emoji(verdict: str | None) -> str:
    if verdict is None:
        return "?"
    return {"PASS": "PASS", "SOFT_FAIL": "SOFT", "HARD_FAIL": "HARD"}.get(verdict, verdict)


def render(results: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("# AXIOMA Phase F — pre-architecture follow-up experiments")
    lines.append("")
    lines.append(f"Aggregated from {len(results)} result files under `results/phase_f/`.")
    lines.append("")
    lines.append("## Verdict roll-up")
    lines.append("")
    lines.append("| Experiment | Key metric | Verdict |")
    lines.append("|---|---|---|")
    for name, body in sorted(results.items()):
        v = body.get("verdict") or body.get("combined_verdict") or body.get("v1_1_4_verdict")
        key = ""
        if name == "p4_psi_baseline":
            key = f"ψ mean = {body.get('psi', {}).get('mean', 'n/a')}, " \
                  f"below_alert = {body.get('fraction_below_alert', 'n/a')}"
        elif name.startswith("f11_phi_"):
            post = body.get("cascade_delay_post", {})
            key = f"post mean = {post.get('mean', 'n/a')} (n={post.get('n', 0)})"
        elif name == "f6_zone_validation":
            key = f"mean κ = {body.get('mean_kappa', 'n/a')}, min κ = {body.get('min_kappa', 'n/a')}"
        elif name == "f8_meta_calibration":
            key = (f"accuracy = {body.get('accuracy_rate', 'n/a')}, "
                   f"miscalibration = {body.get('mean_miscalibration', 'n/a')}")
        elif name == "psi_stress_sweep":
            key = (f"cells: {body.get('n_passes', 0)} PASS, "
                   f"{body.get('n_stressed', 0)} STRESSED, "
                   f"{body.get('n_collapsed', 0)} COLLAPSED; "
                   f"degeneration proof: {body.get('compose_degeneration_proof', {}).get('verdict', '?')}")
        elif name == "zone_threshold_sweep":
            best = body.get("best", {})
            key = (f"best mean κ = {best.get('mean_kappa', 'n/a')} "
                   f"({body.get('n_passing_v1_1_gate', 0)}/{body.get('n_candidates', 0)} pass)")
        elif name == "aos_g_weighted":
            comps = body.get("comparisons", {})
            ratios = [
                f"{n}={c.get('gap_mean_ratio_vs_uniform')}×"
                for n, c in comps.items()
            ]
            key = "gap ratios vs uniform: " + ", ".join(ratios)
        elif name == "psi_sensitivity":
            doms = body.get("dominator_fractions", {})
            key = "dominators: " + ", ".join(f"{k}={v}" for k, v in doms.items())
        elif name == "learner_longrun":
            key = (f"events = {body.get('events_observed', 0)}/{body.get('events_target', 0)}, "
                   f"adoptions = {body.get('learner', {}).get('adoptions_count', 0)}")
        else:
            key = "(see JSON)"
        lines.append(f"| `{name}` | {key} | {_verdict_emoji(v)} |")
    lines.append("")

    # Per-experiment details
    for name, body in sorted(results.items()):
        lines.append(f"## {name}")
        lines.append("")
        if "_parse_error" in body:
            lines.append(f"_Parse error: {body['_parse_error']}_")
            lines.append("")
            continue
        if name == "p4_psi_baseline":
            psi = body.get("psi", {})
            lines.append(f"- beats sampled: {body.get('beats_sampled')}")
            lines.append(f"- ψ stats: mean={psi.get('mean')} p5={psi.get('p5')} p95={psi.get('p95')}")
            lines.append(f"- fraction below psi_alert_threshold "
                         f"({body.get('psi_alert_threshold')}): {body.get('fraction_below_alert')}")
            lines.append(f"- verdict: **{body.get('verdict')}**")
        elif name.startswith("f11_phi_"):
            pre = body.get("cascade_delay_pre", {})
            post = body.get("cascade_delay_post", {})
            lines.append(f"- order: {body.get('order')}, "
                         f"perturbation: {body.get('perturbation_kind')} → {body.get('perturbation_target')}")
            lines.append(f"- cascade_delay pre:  mean={pre.get('mean')} n={pre.get('n')}")
            lines.append(f"- cascade_delay post: mean={post.get('mean')} n={post.get('n')}")
            lines.append(f"- per-downstream: {body.get('per_downstream_post_mean')}")
        elif name == "f6_zone_validation":
            for s in body.get("sessions", []):
                lines.append(f"- {s.get('task_type')}: κ={s.get('kappa')} n={s.get('n_labels')}")
            lines.append(f"- mean κ = {body.get('mean_kappa')}  min κ = {body.get('min_kappa')}  → "
                         f"**{body.get('verdict')}**")
            if note := body.get("note"):
                lines.append(f"- note: {note}")
        elif name == "f8_meta_calibration":
            lines.append(f"- accuracy: {body.get('accuracy_rate')}")
            lines.append(f"- miscalibration: {body.get('mean_miscalibration')}")
            lines.append(f"- F8 verdict: **{body.get('f8_verdict')}**  "
                         f"accuracy verdict: **{body.get('accuracy_verdict')}**  "
                         f"combined: **{body.get('combined_verdict')}**")
            if note := body.get("note"):
                lines.append(f"- note: {note}")
        elif name == "psi_sensitivity":
            for k in ("gap_variance_health", "structural_health", "compose_probe_health"):
                v = body.get(k, {})
                lines.append(f"- {k}: mean={v.get('mean')} corr_with_psi={v.get('corr_with_psi')}")
            lines.append(f"- dominators: {body.get('dominator_fractions')}")
        elif name == "learner_longrun":
            lines.append(f"- events: {body.get('events_observed')}/{body.get('events_target')}")
            lines.append(f"- beats: {body.get('beats_run_post_warmup')}")
            learner = body.get("learner", {})
            lines.append(f"- adoptions: {learner.get('adoptions_count')}  "
                         f"reversions: {learner.get('reversions_count')}")
            lines.append(f"- baseline_score: {learner.get('baseline_score')}")
            lines.append(f"- verdict: **{body.get('verdict')}**")
        elif name == "psi_stress_sweep":
            lines.append(f"- magnitudes: {body.get('magnitudes_tested')}")
            lines.append(f"- periods: {body.get('periods_tested')}")
            lines.append(f"- beats per cell: {body.get('beats_per_cell')}")
            lines.append(f"- cells: {body.get('n_passes')} PASS, "
                         f"{body.get('n_stressed')} STRESSED, "
                         f"{body.get('n_collapsed')} COLLAPSED")
            proof = body.get("compose_degeneration_proof", {})
            lines.append(f"- degeneration proof (synthetic): "
                         f"score-at-zero={proof.get('score_when_gap_always_zero')} "
                         f"score-at-variance={proof.get('score_when_gap_has_variance')} → "
                         f"**{proof.get('verdict')}**")
            lines.append(f"- v1.1.4 verdict: **{body.get('v1_1_4_verdict')}**")
            if note := body.get("note"):
                lines.append(f"- note: {note}")
        elif name == "zone_threshold_sweep":
            lines.append(f"- candidates evaluated: {body.get('n_candidates')}")
            lines.append(f"- candidates passing min κ ≥ 0.3 (v1.1.1 gate): "
                         f"{body.get('n_passing_v1_1_gate')}")
            best = body.get("best", {})
            lines.append(f"- best candidate: flow_theta_min={best.get('flow_theta_min')} "
                         f"flow_cascade_max={best.get('flow_cascade_max')} "
                         f"mean κ={best.get('mean_kappa')} min κ={best.get('min_kappa')}")
            lines.append(f"- verdict: **{body.get('verdict')}**")
        elif name == "aos_g_weighted":
            lines.append(f"- beats per preset: {body.get('beats_per_preset')}, "
                         f"magnitude: {body.get('magnitude')}, period: {body.get('period_beats')}")
            for preset_name, preset in body.get("presets", {}).items():
                g = preset.get("gap", {})
                psi = preset.get("psi", {})
                lines.append(
                    f"- **{preset_name}**: gap mean={g.get('mean')} p95={g.get('p95')}, "
                    f"ψ mean={psi.get('mean')} fraction_below_alert={psi.get('fraction_below_alert')}"
                )
            for comp_name, comp in body.get("comparisons", {}).items():
                lines.append(
                    f"- {comp_name} vs uniform: gap ratio={comp.get('gap_mean_ratio_vs_uniform')}×, "
                    f"ψ delta={comp.get('psi_mean_delta_vs_uniform')} "
                    f"→ {comp.get('interpretation')}"
                )
            lines.append(f"- verdict: **{body.get('verdict')}**")
            if note := body.get("note"):
                lines.append(f"- note: {note}")
        else:
            lines.append("```json")
            lines.append(json.dumps(body, indent=2)[:2000])
            lines.append("```")
        lines.append("")

    # Live calibration sessions (rolled up separately from the experiment grid)
    session_files = sorted(RESULTS_ROOT.glob("calibration_session_*.json"))
    if session_files:
        lines.append("## Live calibration sessions (v1.1.1 / v1.1.2)")
        lines.append("")
        lines.append("| Session | Kind | Task | n_pairs | Verdict |")
        lines.append("|---|---|---|---|---|")
        for sp in session_files:
            try:
                s = json.loads(sp.read_text())
                lines.append(
                    f"| `{s.get('session_id', '?')}` | {s.get('kind', '?')} | "
                    f"{s.get('task_type', '?')} | {s.get('n_pairs', 0)} | "
                    f"{s.get('verdict', '?')} |"
                )
            except Exception:
                pass
        lines.append("")

    # Per ARCH §14 ship gate review
    lines.append("## Ship-gate review (Phase F portion)")
    lines.append("")
    verdicts = [
        (name, body.get("verdict") or body.get("combined_verdict"))
        for name, body in results.items()
    ]
    any_hard = any(v == "HARD_FAIL" for _, v in verdicts)
    any_soft = any(v == "SOFT_FAIL" for _, v in verdicts)
    if any_hard:
        lines.append("- **HARD_FAIL detected** — v1.0 ships with heightened caveat in affected area; "
                     "v1.1 work scheduled.")
    elif any_soft:
        lines.append("- **SOFT_FAIL detected** — v1.0 ships; v1.1 work scheduled for affected area.")
    else:
        lines.append("- All Phase F experiments PASS — no v1.1 follow-up gated by this phase.")
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("-o", "--output", type=Path,
                   default=RESULTS_ROOT / "phase_f_summary.md")
    args = p.parse_args()
    results = _read_results()
    report = render(results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report)
    print(f"Wrote {args.output}  ({len(results)} experiments)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
