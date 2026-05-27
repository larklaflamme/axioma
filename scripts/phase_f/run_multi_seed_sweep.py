"""Convenience wrapper — run a multi-seed × multi-preset soak sweep.

Spawns N seeds × M presets soak processes in parallel; waits for all to
finish; runs the multi-seed aggregator on the results. One-command
reproducer for v1.2.3 / v1.2.4 / v1.3 multi-seed validation runs.

Usage:
    python scripts/phase_f/run_multi_seed_sweep.py \\
        --seeds 7,13,42 \\
        --presets uniform,pneuma_weighted \\
        --beats 50000

Output: per-seed JSON files in results/, then runs
multi_seed_aggregator.py and writes the summary.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOAK_SCRIPT = REPO_ROOT / "scripts" / "phase_e_soak.py"
AGGREGATOR = REPO_ROOT / "scripts" / "phase_f" / "multi_seed_aggregator.py"
RESULTS_DIR = REPO_ROOT / "results"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=str, default="7,13,42")
    p.add_argument(
        "--presets", type=str, default="uniform,pneuma_weighted",
        help="comma-separated preset names",
    )
    p.add_argument("--beats", type=int, default=50000)
    p.add_argument(
        "--max-parallel", type=int, default=4,
        help="max concurrent soak processes",
    )
    p.add_argument(
        "--prefix", default="soak",
        help="output filename prefix (e.g., 'soak50k')",
    )
    p.add_argument("--skip-existing", action="store_true",
                   help="skip cells whose output JSON already exists")
    args = p.parse_args()

    seeds = [int(s.strip()) for s in args.seeds.split(",")]
    presets = [s.strip() for s in args.presets.split(",")]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[int, str, Path]] = []
    for seed in seeds:
        for preset in presets:
            short = preset.replace("_weighted", "")
            output = RESULTS_DIR / f"{args.prefix}_seed{seed}_{short}.json"
            if args.skip_existing and output.exists():
                print(f"  SKIP (exists): {output.name}")
                continue
            jobs.append((seed, preset, output))

    print(f"Planning {len(jobs)} soak runs ({len(seeds)} seeds × {len(presets)} presets) "
          f"× {args.beats} beats; max {args.max_parallel} concurrent.")

    running: list[tuple[subprocess.Popen[bytes], int, str, Path]] = []
    waiting = list(jobs)
    completed: list[tuple[int, str, Path, bool]] = []
    t_start = time.time()

    while waiting or running:
        # Launch up to max_parallel
        while waiting and len(running) < args.max_parallel:
            seed, preset, output = waiting.pop(0)
            cmd = [
                sys.executable, str(SOAK_SCRIPT),
                "--beats", str(args.beats),
                "--seed", str(seed),
                "--gap-weights", preset,
                "-o", str(output),
            ]
            print(f"  → launching seed={seed} preset={preset} → {output.name}")
            proc = subprocess.Popen(
                cmd, cwd=str(REPO_ROOT),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            running.append((proc, seed, preset, output))
        # Reap finished
        still_running: list[tuple[subprocess.Popen[bytes], int, str, Path]] = []
        for proc, seed, preset, output in running:
            rc = proc.poll()
            if rc is None:
                still_running.append((proc, seed, preset, output))
                continue
            ok = (rc == 0 and output.exists())
            completed.append((seed, preset, output, ok))
            elapsed = time.time() - t_start
            status = "OK" if ok else f"FAIL(rc={rc})"
            print(f"  ✓ seed={seed} preset={preset} → {status} (elapsed {elapsed:.0f}s)")
        running = still_running
        if running:
            time.sleep(2.0)

    n_ok = sum(1 for _, _, _, ok in completed if ok)
    print(f"\n{n_ok}/{len(completed)} soaks completed successfully.")
    if n_ok < len(completed):
        print("Some soaks failed — check missing output files manually.")
        return 1

    # Run aggregator
    print("\nRunning multi-seed aggregator ...")
    rc = subprocess.call(
        [sys.executable, str(AGGREGATOR), "--results-dir", str(RESULTS_DIR)],
        cwd=str(REPO_ROOT),
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
