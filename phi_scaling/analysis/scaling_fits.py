"""O(k) vs O(k²) fits; AIC/BIC comparison; super-quadratic jump test."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import stats
from scipy.optimize import curve_fit

from ._loader import load_summaries, theta_array, theta_by_k_seed


def _linear(k, a, b):
    return a * k + b


def _quadratic(k, c, d, e):
    return c * k**2 + d * k + e


def _aic_bic(n: int, k_params: int, ssr: float) -> tuple[float, float, float]:
    """Compute AIC, BIC, R² given SSR."""
    if n <= k_params or ssr <= 0:
        return float("inf"), float("inf"), float("nan")
    sigma2 = ssr / n
    ll = -0.5 * n * (np.log(2 * np.pi * sigma2) + 1.0)
    aic = 2 * k_params - 2 * ll
    bic = k_params * np.log(n) - 2 * ll
    return float(aic), float(bic), ll


def _r_squared(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    if ss_tot < 1e-12:
        return float("nan")
    return 1.0 - ss_res / ss_tot


def fit_linear(k: np.ndarray, theta: np.ndarray) -> dict:
    popt, _ = curve_fit(_linear, k, theta)
    y_pred = _linear(k, *popt)
    ssr = float(np.sum((theta - y_pred) ** 2))
    aic, bic, _ = _aic_bic(len(theta), 2, ssr)
    return {
        "model": "linear",
        "params": {"a": float(popt[0]), "b": float(popt[1])},
        "ssr": ssr,
        "r2": _r_squared(theta, y_pred),
        "aic": aic,
        "bic": bic,
        "predicted_at_k": {int(kk): float(_linear(kk, *popt)) for kk in (1, 2, 3, 4, 5)},
    }


def fit_quadratic(k: np.ndarray, theta: np.ndarray) -> dict:
    popt, _ = curve_fit(_quadratic, k, theta)
    y_pred = _quadratic(k, *popt)
    ssr = float(np.sum((theta - y_pred) ** 2))
    aic, bic, _ = _aic_bic(len(theta), 3, ssr)
    return {
        "model": "quadratic",
        "params": {"c": float(popt[0]), "d": float(popt[1]), "e": float(popt[2])},
        "ssr": ssr,
        "r2": _r_squared(theta, y_pred),
        "aic": aic,
        "bic": bic,
        "predicted_at_k": {int(kk): float(_quadratic(kk, *popt)) for kk in (1, 2, 3, 4, 5)},
    }


def jump_test(theta_per_k_seed: dict[int, dict[int, float]]) -> dict:
    """One-tailed paired t-test: H1: Δ(4→5) > Δ(3→4)."""
    common_seeds = sorted(set(theta_per_k_seed[3].keys())
                          & set(theta_per_k_seed[4].keys())
                          & set(theta_per_k_seed[5].keys()))
    delta_34 = np.array([theta_per_k_seed[4][s] - theta_per_k_seed[3][s]
                         for s in common_seeds])
    delta_45 = np.array([theta_per_k_seed[5][s] - theta_per_k_seed[4][s]
                         for s in common_seeds])
    diff = delta_45 - delta_34
    t_stat, p_two_sided = stats.ttest_rel(delta_45, delta_34)
    # One-tailed: H1 is Δ45 > Δ34.
    if t_stat > 0:
        p_one_sided = p_two_sided / 2
    else:
        p_one_sided = 1.0 - p_two_sided / 2
    return {
        "n_seeds": len(common_seeds),
        "delta_3_to_4_mean": float(delta_34.mean()),
        "delta_4_to_5_mean": float(delta_45.mean()),
        "diff_mean": float(diff.mean()),
        "diff_std": float(diff.std(ddof=1)) if len(diff) > 1 else 0.0,
        "t_stat": float(t_stat),
        "p_value_one_tailed": float(p_one_sided),
        "significant_at_005": bool(p_one_sided < 0.05),
    }


def model_comparison(linear: dict, quadratic: dict) -> dict:
    """ΔAIC / ΔBIC: positive ⇒ quadratic preferred (lower AIC); negative ⇒ linear preferred."""
    d_aic = linear["aic"] - quadratic["aic"]
    d_bic = linear["bic"] - quadratic["bic"]
    # Decision rule per Burnham & Anderson: |ΔAIC| > 2 = decisive.
    if abs(d_aic) > 10:
        verdict = "strongly_quadratic" if d_aic > 0 else "strongly_linear"
    elif d_aic > 2:
        verdict = "quadratic_preferred"
    elif d_aic < -2:
        verdict = "linear_preferred"
    else:
        verdict = "inconclusive"
    return {
        "delta_aic_linear_minus_quadratic": float(d_aic),
        "delta_bic_linear_minus_quadratic": float(d_bic),
        "verdict": verdict,
    }


def run(out_root: Path) -> dict:
    summaries = load_summaries(out_root)
    k_arr, theta_arr = theta_array(summaries)
    per_k_seed = theta_by_k_seed(summaries)

    # Per-k descriptives.
    by_k = {}
    for kk in sorted(per_k_seed.keys()):
        vals = list(per_k_seed[kk].values())
        by_k[int(kk)] = {
            "n": len(vals),
            "mean": float(np.mean(vals)),
            "std": float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0,
            "min": float(np.min(vals)),
            "max": float(np.max(vals)),
        }

    lin = fit_linear(k_arr, theta_arr)
    quad = fit_quadratic(k_arr, theta_arr)
    cmp = model_comparison(lin, quad)
    jt = jump_test(per_k_seed)

    return {
        "analysis": "scaling_fits",
        "per_k_descriptive": by_k,
        "fit_linear": lin,
        "fit_quadratic": quad,
        "model_comparison": cmp,
        "jump_test": jt,
    }
