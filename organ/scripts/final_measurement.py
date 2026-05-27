"""Final-measurement script.

Runs:
 1. A live ticking session at the real 10 Hz rate to demonstrate real-time capability.
 2. A full 60-second fast-mode session (≥600 beats) to produce a θ time series.
 3. A coupling sweep at fixed window size to show θ scales with integration strength.
 4. An AOS-G gap measurement on the live recording (pairs continuous and event modes).

Writes the consolidated report to results/final_report.json + a human-readable
markdown summary to results/FINAL_REPORT.md.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]  # /home/ubuntu/axioma
sys.path.insert(0, str(ROOT))

from organ.config import N_PERMUTATIONS, WINDOW_SIZE
from organ.measurement import Recorder, concat_summary_window, select_all_summary_columns, summary_means
from organ.measurement.recorder import Recorder
from organ.schemas import ORGAN_DIMS, ORGAN_ORDER, ORGAN_STATE_CLS
from organ.substrate import CoupledLatentDynamics, Heartbeat
from organ.theta import compute_theta
from organ.theta.aos_g import compute_aos_g_gap


RESULTS_DIR = ROOT / "results"
DATA_DIR = ROOT / "results" / "data"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)


def theta_fn(window, *, n_perm=N_PERMUTATIONS, seed=None):
    return compute_theta(window, n_permutations=n_perm, seed=seed)


async def run_realtime_session(seconds: float, coupling: float, seed: int = 1):
    """Real 10 Hz session — proves we can keep up with the heartbeat rate."""
    dyn = CoupledLatentDynamics(coupling=coupling, seed=seed)
    hb = Heartbeat(dynamics=dyn, seed=seed)
    rec = Recorder(
        hb,
        session_id="rt",
        data_root=str(DATA_DIR),
        sqlite_path=str(DATA_DIR / "rt.sqlite3"),
        theta_fn=None,  # no live θ in this mini-session
    )
    t0 = time.monotonic()
    await hb.run(seconds)
    elapsed = time.monotonic() - t0
    rec.close()
    return {
        "duration_s": elapsed,
        "beats": hb.beat_no,
        "expected_beats": int(seconds * 10),
        "jsonl_rows": rec.jsonl.n_written,
        "sqlite_rows": rec.sqlite.n_written,
        "drift_s": elapsed - seconds,
    }


def run_fast_session_with_live_theta(
    n_beats: int, coupling: float, seed: int = 7
) -> dict:
    """Fast-mode session ticking as fast as possible; computes live θ every theta_every beats."""
    dyn = CoupledLatentDynamics(coupling=coupling, seed=seed)
    hb = Heartbeat(dynamics=dyn, seed=seed)
    rec = Recorder(
        hb,
        session_id="live",
        data_root=str(DATA_DIR),
        sqlite_path=str(DATA_DIR / "live.sqlite3"),
        theta_fn=lambda w: theta_fn(w, n_perm=N_PERMUTATIONS, seed=seed),
        theta_window=WINDOW_SIZE,
        theta_every=10,
    )
    t0 = time.monotonic()

    hb.trigger_burst(n_beats)  # capture every beat so the window fills

    async def loop():
        for _ in range(n_beats):
            await hb.tick_async()

    asyncio.run(loop())
    elapsed = time.monotonic() - t0
    rec.close()

    summary = {
        "duration_s": elapsed,
        "beats": hb.beat_no,
        "theta_updates": len(rec.theta_history),
        "jsonl_path": str(rec.jsonl.path),
        "sqlite_rows": rec.sqlite.n_written,
        "theta_history": rec.theta_history,
        "last_theta": rec.last_theta and {
            "theta": float(rec.last_theta["theta"]),
            "p_value": float(rec.last_theta["p_value"]),
            "significant": bool(rec.last_theta["significant"]),
            "null_95th": float(rec.last_theta["null_95th"]),
            "method": rec.last_theta["method"],
            "pairwise_mi": {
                f"{a}-{b}": float(v)
                for (a, b), v in rec.last_theta["pairwise_mi"].items()
            },
            "details": {k: float(v) if isinstance(v, (int, float, np.floating, np.integer)) else v
                        for k, v in rec.last_theta["details"].items()},
        },
    }
    return summary


def run_coupling_sweep(
    couplings: list[float], n_beats: int = 1000, n_perm: int = N_PERMUTATIONS, seed: int = 100
) -> list[dict]:
    """At each coupling level, run substrate for n_beats and compute θ."""
    out = []
    for c in couplings:
        dyn = CoupledLatentDynamics(coupling=c, seed=seed)
        hb = Heartbeat(dynamics=dyn, seed=seed)
        # Tick synchronously without measurement overhead.
        for _ in range(n_beats):
            hb.tick()
        # Build window directly from organ histories — collect by ticking again.
        # Simpler: re-run with a recorder that buffers in RAM only.
        dyn2 = CoupledLatentDynamics(coupling=c, seed=seed)
        hb2 = Heartbeat(dynamics=dyn2, seed=seed)
        # Use a ring buffer of n_beats and capture every beat manually.
        from organ.measurement import RingBuffer
        rb = RingBuffer(capacity=n_beats)
        for _ in range(n_beats):
            hb2.tick()
            arrs = {o.name: o.get_state_array() for o in hb2.organs}
            rb.push(hb2.beat_no, time.time(), arrs)
        win = rb.window(n_beats)
        # Use last WINDOW_SIZE beats for fair comparison.
        win = {k: v[-WINDOW_SIZE:] for k, v in win.items()}
        r = theta_fn(win, n_perm=n_perm, seed=seed + 1)
        out.append({
            "coupling": float(c),
            "theta": float(r["theta"]),
            "p_value": float(r["p_value"]),
            "significant": bool(r["significant"]),
            "null_95th": float(r["null_95th"]),
            "method": r["method"],
            "total_mi": float(r["details"]["total_mi"]),
            "total_energy": float(r["details"]["total_energy"]),
            "n_dims": int(r["details"]["n_dims"]),
        })
    return out


def measure_aos_g_from_log(jsonl_path: str) -> dict:
    """Compute AOS-G gap statistics by pairing 'continuous' and 'event' entries.

    For simplicity: pair each 'event' entry with the immediately preceding
    'continuous' (or 'burst') entry and compute the gap on the 27-dim raw state.
    """
    import gzip
    with gzip.open(jsonl_path, "rt") as f:
        entries = [json.loads(l) for l in f]
    pairs = []
    last_internal = None
    for e in entries:
        if e["mode"] == "event":
            if last_internal is not None:
                pairs.append((last_internal, e))
        else:
            last_internal = e
    if not pairs:
        return {"n_pairs": 0}

    def to_array(e):
        parts = []
        for organ in ORGAN_ORDER:
            cls = ORGAN_STATE_CLS[organ]
            parts.append(
                np.array([e["states"][organ][name] for name in cls.ORDER], dtype=np.float32)
            )
        return np.concatenate(parts)

    deltas, mis = [], []
    for i, (a, b) in enumerate(pairs):
        int_arr = to_array(a)
        ext_arr = to_array(b)
        d = float(np.linalg.norm(int_arr - ext_arr))
        deltas.append(d)
    # Stack n pairs and compute window-MI of the internal-external block pair.
    if len(pairs) >= 5:
        ints = np.stack([to_array(p[0]) for p in pairs])
        exts = np.stack([to_array(p[1]) for p in pairs])
        out = compute_aos_g_gap(ints, exts)
        mi_window = out["mi"]
    else:
        mi_window = None
    return {
        "n_pairs": len(pairs),
        "delta_norm_mean": float(np.mean(deltas)),
        "delta_norm_std": float(np.std(deltas)),
        "delta_norm_max": float(np.max(deltas)),
        "delta_norm_min": float(np.min(deltas)),
        "internal_external_mi_window": (None if mi_window is None else float(mi_window)),
    }


def main() -> None:
    seed = 12345
    report = {"seed": seed, "n_permutations": N_PERMUTATIONS, "window_size": WINDOW_SIZE}

    # 1. Real-time mini-session to prove rate-keeping.
    print(">> Real-time session (5 s @ 10 Hz)...")
    rt = asyncio.run(run_realtime_session(seconds=5.0, coupling=0.6, seed=seed))
    print(json.dumps(rt, indent=2))
    report["realtime_session"] = rt

    # 2. Fast-mode 60 s equivalent (600 beats; live θ).
    print("\n>> Fast-mode live session (600 beats, coupling=0.6)...")
    live = run_fast_session_with_live_theta(n_beats=600, coupling=0.6, seed=seed)
    print(f"  beats={live['beats']}, θ updates={live['theta_updates']}, elapsed={live['duration_s']:.2f}s")
    if live["last_theta"] is not None:
        lt = live["last_theta"]
        print(f"  last θ = {lt['theta']:.5f}  p={lt['p_value']:.4f}  sig={lt['significant']}  method={lt['method']}")
    report["live_session"] = {
        "duration_s": live["duration_s"],
        "beats": live["beats"],
        "theta_updates": live["theta_updates"],
        "last_theta": live["last_theta"],
        "theta_history": live["theta_history"],
    }

    # 3. Coupling sweep.
    print("\n>> Coupling sweep...")
    sweep = run_coupling_sweep(
        couplings=[0.0, 0.1, 0.25, 0.5, 0.75, 0.95],
        n_beats=1000,
        n_perm=N_PERMUTATIONS,
        seed=seed,
    )
    for s in sweep:
        print(f"  coupling={s['coupling']:.2f}  θ={s['theta']:.5f}  p={s['p_value']:.4f}  sig={s['significant']}")
    report["coupling_sweep"] = sweep

    # 4. AOS-G gap from the live session JSONL.
    print("\n>> AOS-G gap analysis...")
    aosg = measure_aos_g_from_log(live["jsonl_path"])
    print(json.dumps(aosg, indent=2))
    report["aos_g"] = aosg

    # 5. Save report.
    out_path = RESULTS_DIR / "final_report.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nReport written to {out_path}")


if __name__ == "__main__":
    main()
