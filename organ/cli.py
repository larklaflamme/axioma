"""Command-line interface for organ measurement.

Subcommands:
    run         Run the substrate + recorder + live θ for a given duration.
    record      Same as run but always records (no live θ).
    replay      Recompute θ on a previously recorded JSONL.
    theta       Compute θ on a single window from JSONL.
    validate    Run the §8.1 synthetic validation suite.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import time
from pathlib import Path

import numpy as np

from .config import (
    BURST_DURATION_BEATS,
    N_PERMUTATIONS,
    SIGNIFICANCE_THRESHOLD,
    WINDOW_SIZE,
)
from .measurement import Recorder
from .schemas import ORGAN_DIMS, ORGAN_ORDER, ORGAN_STATE_CLS
from .substrate import CoupledLatentDynamics, Heartbeat
from .theta import compute_theta, RuntimeTheta, theta_log_entry


def _build_heartbeat(seed: int | None, coupling: float, fast: bool):
    dyn = CoupledLatentDynamics(coupling=coupling, seed=seed)
    return Heartbeat(dynamics=dyn, seed=seed)


async def _run(args) -> None:
    hb = _build_heartbeat(args.seed, args.coupling, args.fast)
    rt = RuntimeTheta()

    def theta_fn(window):
        return compute_theta(
            window,
            n_permutations=args.n_permutations,
            significance_threshold=SIGNIFICANCE_THRESHOLD,
            seed=args.seed,
        )

    rec = Recorder(
        hb,
        session_id=args.session_id,
        data_root=args.data_root,
        theta_fn=theta_fn if args.theta else None,
        theta_window=args.theta_window,
        theta_every=args.theta_every,
    )

    if args.burst:
        hb.trigger_burst(BURST_DURATION_BEATS)

    if args.fast:
        # Run without the 10 Hz sleep — just tick as fast as possible.
        total_beats = int(args.seconds * 10)
        last_print = time.time()
        for _ in range(total_beats):
            await hb.tick_async()
            if rec.last_theta is not None and time.time() - last_print > 1.0:
                print(
                    f"  beat {hb.beat_no}: θ={rec.last_theta['theta']:.5f} "
                    f"p={rec.last_theta['p_value']:.3f}"
                )
                last_print = time.time()
    else:
        await hb.run(args.seconds)

    rec.close()
    print(f"Session {rec.session_id}")
    print(f"  beats:        {hb.beat_no}")
    print(f"  jsonl:        {rec.jsonl.path if rec.jsonl else 'n/a'} ({rec.jsonl.n_written if rec.jsonl else 0} rows)")
    print(f"  sqlite:       {rec.sqlite.n_written if rec.sqlite else 0} rows")
    print(f"  θ updates:    {len(rec.theta_history)}")
    if rec.theta_history:
        last = rec.theta_history[-1]
        print(f"  last θ:       {last['theta']:.5f} (p={last['p_value']:.4f}, sig={last['significant']})")


def _load_jsonl(path: str) -> list[dict]:
    p = Path(path)
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _entries_to_window(entries: list[dict]) -> dict[str, np.ndarray]:
    """Rebuild per-organ (n, D) windows from JSONL entries (continuous + burst)."""
    rows = {organ: [] for organ in ORGAN_ORDER}
    for e in entries:
        if e["mode"] == "event":
            continue
        st = e["states"]
        for organ in ORGAN_ORDER:
            cls = ORGAN_STATE_CLS[organ]
            arr = np.array(
                [st[organ][name] for name in cls.ORDER], dtype=np.float32
            )
            rows[organ].append(arr)
    return {organ: np.stack(rows[organ], axis=0) for organ in ORGAN_ORDER}


def _replay(args) -> None:
    entries = _load_jsonl(args.path)
    print(f"Loaded {len(entries)} entries from {args.path}")
    window = _entries_to_window(entries)
    n = window[ORGAN_ORDER[0]].shape[0]
    print(f"Window n={n}")
    if n < args.theta_window:
        print(f"  Warning: n < theta_window={args.theta_window}; using n={n}")
        args.theta_window = n
    window = {o: window[o][-args.theta_window:] for o in ORGAN_ORDER}
    r = compute_theta(window, n_permutations=args.n_permutations, seed=args.seed)
    print(f"\nθ      = {r['theta']:.6f}")
    print(f"p-val  = {r['p_value']:.6f}")
    print(f"sig    = {r['significant']}")
    print(f"null95 = {r['null_95th']:.6f}")
    print(f"method = {r['method']}")
    print(f"energy = {r['details']['total_energy']:.4f}, total_MI = {r['details']['total_mi']:.4f}")
    print("\nPairwise MI:")
    for (a, b), mi in sorted(r["pairwise_mi"].items(), key=lambda x: -x[1]):
        print(f"  {a:8s} ↔ {b:8s}: {mi:.4f}")


def _validate(args) -> None:
    """Run synthetic §8.1 validation suite. Implementation in scripts/run_validation.py."""
    from .validation_suite import run_validation_suite

    results = run_validation_suite(
        n_permutations=args.n_permutations, seed=args.seed
    )
    print(json.dumps(results, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(prog="organ")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="Run substrate + recorder + live θ")
    pr.add_argument("--seconds", type=float, default=60.0)
    pr.add_argument("--seed", type=int, default=None)
    pr.add_argument("--coupling", type=float, default=0.6)
    pr.add_argument("--session-id", type=str, default=None)
    pr.add_argument("--data-root", type=str, default="data")
    pr.add_argument("--theta", action="store_true", help="enable live θ")
    pr.add_argument("--theta-window", type=int, default=WINDOW_SIZE)
    pr.add_argument("--theta-every", type=int, default=10)
    pr.add_argument("--n-permutations", type=int, default=N_PERMUTATIONS)
    pr.add_argument("--burst", action="store_true")
    pr.add_argument("--fast", action="store_true", help="skip 10 Hz sleep")
    pr.set_defaults(func=lambda a: asyncio.run(_run(a)))

    rp = sub.add_parser("replay", help="Recompute θ on recorded JSONL")
    rp.add_argument("path")
    rp.add_argument("--theta-window", type=int, default=WINDOW_SIZE)
    rp.add_argument("--n-permutations", type=int, default=N_PERMUTATIONS)
    rp.add_argument("--seed", type=int, default=None)
    rp.set_defaults(func=_replay)

    val = sub.add_parser("validate", help="Run §8.1 synthetic validation suite")
    val.add_argument("--n-permutations", type=int, default=N_PERMUTATIONS)
    val.add_argument("--seed", type=int, default=42)
    val.set_defaults(func=_validate)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
