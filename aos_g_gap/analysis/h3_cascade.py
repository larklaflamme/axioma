"""H3 — Cascade order EIDOLON → ANIMA → NOUS → PNEUMA with 1-5 beat delays.

Method:
  - For the direct_contradiction condition (averaged across seeds), compute the
    *differential* per-organ delta-z relative to the paired baseline trial.
  - Find time-to-peak for each organ in the differential.
  - Test order and delay magnitudes.
  - Granger causality between EIDOLON and PNEUMA delta time series.

Pass criterion (per IMPLEMENTATION_PLAN §6):
  - order matches EIDOLON < ANIMA < NOUS < PNEUMA
  - all delays in [1, 5]
  - Granger eidolon→pneuma p<0.05 with reverse p>0.05.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from organ.schemas import ORGAN_ORDER

from ..config import H3_GRANGER_P, H3_LAG_MAX, H3_LAG_MIN
from ._loader import load_summaries, load_trajectories, trials_by_condition

CASCADE_TARGET_ORDER = ("eidolon", "anima", "nous", "pneuma")


def _try_granger(x: np.ndarray, y: np.ndarray, lag: int = 5) -> dict:
    """Granger test: does x cause y? Returns smallest p among lags 1..lag."""
    try:
        from statsmodels.tsa.stattools import grangercausalitytests

        data = np.column_stack([y, x])  # convention: test if 2nd column G-causes 1st
        res = grangercausalitytests(data, maxlag=lag, verbose=False)
        ps = [v[0]["ssr_ftest"][1] for v in res.values()]
        fs = [v[0]["ssr_ftest"][0] for v in res.values()]
        i = int(np.argmin(ps))
        return {"min_p": float(ps[i]), "F": float(fs[i]), "best_lag": i + 1}
    except Exception as e:
        return {"min_p": float("nan"), "F": float("nan"), "best_lag": -1, "err": str(e)}


def run(out_root: Path) -> dict:
    summaries = load_summaries(out_root)
    by_cond = trials_by_condition(summaries)

    # Gather per-organ per-beat delta for each seed in baseline and contradiction.
    def collect(cond: str) -> dict[int, dict[str, np.ndarray]]:
        out = {}
        for t in by_cond.get(cond, []):
            tr = load_trajectories(Path(t["trial_dir"]))
            out[t["seed"]] = {o: tr[f"per_organ_delta_{o}"] for o in ORGAN_ORDER}
        return out

    baseline = collect("baseline")
    contradiction = collect("direct_contradiction")
    common_seeds = sorted(set(baseline.keys()) & set(contradiction.keys()))
    if not common_seeds:
        return {"hypothesis": "H3", "passed": False, "reason": "no paired baseline/contradiction trials"}

    # Differential per-organ delta = contradiction - baseline, averaged over seeds.
    differential = {o: np.zeros(600, dtype=np.float64) for o in ORGAN_ORDER}
    for seed in common_seeds:
        for o in ORGAN_ORDER:
            differential[o] += contradiction[seed][o] - baseline[seed][o]
    for o in ORGAN_ORDER:
        differential[o] /= len(common_seeds)

    # Time-to-peak in the early cascade window (perturbation start to +50 beats).
    win = (200, 250)
    time_to_peak = {}
    peak_values = {}
    for o in ORGAN_ORDER:
        seg = differential[o][win[0] : win[1]]
        idx = int(np.argmax(seg))
        time_to_peak[o] = win[0] + idx
        peak_values[o] = float(seg[idx])

    # Sort by peak time → observed cascade order.
    observed_order = sorted(ORGAN_ORDER, key=lambda o: time_to_peak[o])
    # Restrict to the four target organs for the order test (MNEME isn't in target).
    obs_target = [o for o in observed_order if o in CASCADE_TARGET_ORDER]

    # Delays relative to the first organ in the observed-target sequence.
    first_target = obs_target[0]
    delays = {o: time_to_peak[o] - time_to_peak[first_target] for o in CASCADE_TARGET_ORDER}

    # Granger causality on EIDOLON ↔ PNEUMA differential delta series across all seeds.
    eid_concat = np.concatenate([
        contradiction[s]["eidolon"] - baseline[s]["eidolon"] for s in common_seeds
    ])
    pne_concat = np.concatenate([
        contradiction[s]["pneuma"] - baseline[s]["pneuma"] for s in common_seeds
    ])
    eid_to_pne = _try_granger(eid_concat, pne_concat, lag=5)
    pne_to_eid = _try_granger(pne_concat, eid_concat, lag=5)

    order_matches = obs_target == list(CASCADE_TARGET_ORDER)
    delays_in_range = all(H3_LAG_MIN <= delays[o] <= H3_LAG_MAX for o in CASCADE_TARGET_ORDER if o != first_target)
    granger_directional = (
        eid_to_pne["min_p"] < H3_GRANGER_P and pne_to_eid["min_p"] > H3_GRANGER_P
    )

    return {
        "hypothesis": "H3",
        "criterion": (
            f"order EIDOLON→ANIMA→NOUS→PNEUMA AND delays ∈ [{H3_LAG_MIN}, {H3_LAG_MAX}] "
            f"AND Granger eidolon→pneuma p<{H3_GRANGER_P} with reverse p>{H3_GRANGER_P}"
        ),
        "common_seeds": common_seeds,
        "time_to_peak": time_to_peak,
        "peak_values": peak_values,
        "observed_order_all": observed_order,
        "observed_order_target": obs_target,
        "target_order": list(CASCADE_TARGET_ORDER),
        "delays_relative_to_first_target": delays,
        "granger_eidolon_to_pneuma": eid_to_pne,
        "granger_pneuma_to_eidolon": pne_to_eid,
        "order_matches": bool(order_matches),
        "delays_in_range": bool(delays_in_range),
        "granger_directional": bool(granger_directional),
        "passed": bool(order_matches and delays_in_range and granger_directional),
    }
