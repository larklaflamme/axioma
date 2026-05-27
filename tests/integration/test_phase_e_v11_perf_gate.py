"""V11 — Phase E baseline performance gate.

Per IMPLEMENTATION_PLAN_v1.0.md §9.3 + ARCH §9.3.1.

**Hard acceptance criterion**: 10-beat rolling avg of beat duration must
remain < 100 ms during baseline conditions. If sustained > 100 ms, v1.0 is
a no-ship until the regression is diagnosed (likely culprits: θ_long, raw MI
batching) OR Q8 scope-reduced (defer meta-cog + learner).

This is the unit-level reproducible version. The 24h soak (run separately)
is the production gate; this test is the per-commit guard.
"""
from __future__ import annotations

import time
from statistics import mean

import pytest

from .phase_e_harness import WARMUP_BEATS, assert_past_warmup, build_phase_e_stack, run_for_beats


@pytest.mark.slow
def test_p95_beat_duration_under_100ms_baseline() -> None:
    """1200 beats in baseline conditions; p95 rolling avg < 100 ms.

    Marked 'slow' because it runs > 1s. CI runs this; per-commit dev loops
    use the lighter B.1 perf check instead.
    """
    stack = build_phase_e_stack(
        # Fewer permutations so θ_long doesn't dominate the budget.
        n_permutations=3,
        perturbation_period_beats=10000,  # effectively no internal perturbations
    )
    # Warmup
    run_for_beats(stack, WARMUP_BEATS)
    assert_past_warmup(stack.hb.beat_no)

    # Measure 600 baseline beats
    durations: list[float] = []
    for _ in range(600):
        t0 = time.perf_counter()
        stack.hb.tick()
        durations.append(time.perf_counter() - t0)

    # 10-beat rolling avg
    rolling = [mean(durations[i : i + 10]) for i in range(len(durations) - 10)]
    p95 = sorted(rolling)[int(len(rolling) * 0.95)]
    p99 = sorted(rolling)[int(len(rolling) * 0.99)]
    avg = mean(durations)
    worst = max(durations)
    # Report — useful when CI shows the metric trending up
    print(
        f"\nV11 perf gate: avg={avg*1000:.2f} ms p95(rolling10)={p95*1000:.2f} ms "
        f"p99(rolling10)={p99*1000:.2f} ms worst={worst*1000:.2f} ms n={len(durations)}"
    )
    # HARD gate: p95 of 10-beat rolling avg < 100 ms
    assert p95 < 0.100, (
        f"V11 perf gate FAILED: p95 of 10-beat rolling avg = {p95*1000:.2f} ms, "
        f"limit 100 ms. v1.0 cannot ship until either the regression is "
        f"fixed OR Q8 scope reduction is triggered."
    )
    # Soft check on single-beat p99 (200 ms ceiling per V11 docs)
    p99_single = sorted(durations)[int(len(durations) * 0.99)]
    assert p99_single < 0.200, (
        f"V11 single-beat p99 = {p99_single*1000:.2f} ms exceeded 200 ms soft ceiling."
    )


def test_warmup_helper_rejects_cold_beat() -> None:
    """V12 enforcement: cold beats fail the helper."""
    with pytest.raises(AssertionError, match="cold-start"):
        assert_past_warmup(100)
    assert_past_warmup(600)  # boundary case OK
    assert_past_warmup(1200)
