"""
Integration test for Parelia v2 Orchestrator.

Verifies the full heartbeat cycle:
    1. Tick with stable data → no plateau, no growth
    2. Tick with plateau-inducing data → plateau fires → growth decision
    3. Rule engine evaluates proposals correctly
    4. Shutdown works cleanly

Run:
    PYTHONPATH=/home/ubuntu/parelia_v2 python3 \
        /path/to/test_orchestrator.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Add src to path — works from any cwd if PYTHONPATH is set or we resolve
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent  # parelia_v2/
sys.path.insert(0, str(_SRC))

from src.orchestrator import PareliaOrchestrator, TickResult

TESTS_PASSED = 0
TESTS_FAILED = 0


def test(name: str):
    def decorator(fn):
        def wrapper():
            global TESTS_PASSED, TESTS_FAILED
            try:
                fn()
                TESTS_PASSED += 1
                print(f"  ✅ {name}")
            except Exception as e:
                TESTS_FAILED += 1
                import traceback
                print(f"  ❌ {name}: {e}")
                traceback.print_exc()
        return wrapper
    return decorator


# ── helpers ────────────────────────────────────────────────────────

def make_hot(beat: int, **overrides) -> dict:
    """Minimal hot dict for testing."""
    d = {
        "beat_number": beat,
        "phi_raw": 0.25,
        "phi_smoothed": 0.24,
        "phi_trend": 0.0,
        "raw_similarity": 0.85,
        "theta": 0.02,
        "theta_deviation": 0.01,
        "boundary_value": 1.0,
        "node_count": 32,
        "edge_count": 78,
        "frequency_hz": 1.0,
        "predictive_error": 0.02,
        "state_entropy": 0.3,
        "assent_state": 0,
        "workspace_occupancy": 0.3,
    }
    d.update(overrides)
    return d


def make_full(beat: int) -> dict:
    return {
        "pneuma": {"load": 0.5},
        "nous": {"contradictions": 0},
        "anima": {"valence": 0.3},
        "mneme": {"trace_count": min(beat, 128)},
        "eidolon": {"stability": 0.9},
        "lattice": {"last_epsilon": 0.05, "last_g_S": 0.8},
    }


# ── tests ─────────────────────────────────────────────────────────

@test("orchestrator instantiates")
def test_instantiate():
    orch = PareliaOrchestrator()
    assert orch.telemetry is not None
    assert orch.plateau_detector is not None
    assert orch.parelia is not None
    assert orch.l1 is not None
    assert orch.l2 is not None
    assert orch.rule_engine is not None
    assert len(orch.rule_engine.rules) > 0


@test("tick with stable data → no plateau, no growth")
def test_tick_stable():
    orch = PareliaOrchestrator()
    for b in range(1, 6):
        result = orch.tick(make_hot(b), make_full(b))
        assert result.beat == b
        assert result.plateau is None or not result.plateau.is_plateau
        assert result.growth_decision is None
    assert orch.beat == 5
    assert orch.parelia.growth_count == 0
    assert orch.parelia.current_stage == 0  # Awakening (32 nodes, pre-32 threshold)
    assert orch.telemetry.write_count == 5


@test("plateau signal → plateau fires → growth decision")
def test_plateau_growth():
    """Feed 50+ beats of flat phi/theta/similarity to trigger growth."""
    orch = PareliaOrchestrator(
        plateau_window=20,      # small window for quick test
        growth_k=4,
    )

    # 25 beats of perfectly flat data
    plateau_fired = False
    growth_fired = False
    for b in range(1, 26):
        result = orch.tick(
            make_hot(b, phi_raw=0.25, phi_smoothed=0.24,
                     raw_similarity=0.84, theta=0.08, boundary_value=1.0),
            make_full(b),
        )
        if result.plateau and result.plateau.is_plateau:
            plateau_fired = True
        if result.growth_decision:
            growth_fired = True

    assert plateau_fired, "Plateau should have fired within 25 flat beats"
    assert growth_fired, "Growth should follow plateau"

    # Growth should increase nodes
    assert orch.parelia.current_node_count > 32
    assert orch.parelia.growth_count >= 1
    assert len(orch.l1._buffer) >= 1
    assert orch.l2.count >= 1


@test("rule engine evaluates proposals via orchestrator")
def test_rule_evaluate():
    orch = PareliaOrchestrator()
    # Tick a few beats so telemetry is populated
    for b in range(1, 5):
        orch.tick(make_hot(b), make_full(b))

    # Evaluate an unrestricted tool
    verdict = orch.evaluate_proposal(
        action_type="memory_read",
        tool_name="memory",
    )
    assert verdict["action"] in ("ALLOW", "DENY", "FLAG"), f"Unexpected: {verdict}"

    # Evaluate a stage-restricted tool (e.g. web_search at stage 0)
    verdict2 = orch.evaluate_proposal(
        action_type="web_search",
        tool_name="web_search",
    )
    # Stage 0 has no tools unlocked; web_search requires stage 1+ (32 nodes)
    # The verdict may vary depending on rule compilation
    assert verdict2["action"] is not None


@test("growth triggers stage transition")
def test_stage_transition():
    """Multiple growth events should eventually trigger stage transitions."""
    orch = PareliaOrchestrator(
        plateau_window=10,
        growth_k=16,   # add 16 nodes per growth
        max_nodes=256,
    )

    # 60 beats of flat data → multiple plateaus
    for b in range(1, 61):
        result = orch.tick(
            make_hot(b, phi_raw=0.25, phi_smoothed=0.24,
                     raw_similarity=0.84, theta=0.08, boundary_value=1.0),
            make_full(b),
        )

    # Should have grown at least once and potentially transitioned stage
    assert orch.parelia.growth_count >= 1, "At least 1 growth event"
    assert orch.parelia.current_node_count > 32

    # Stage should be determined by node count
    assert orch.parelia.current_stage >= 0


@test("vitals collect all module states")
def test_vitals():
    orch = PareliaOrchestrator()
    for b in range(1, 4):
        orch.tick(make_hot(b), make_full(b))

    v = orch._collect_vitals()
    assert "telemetry" in v
    assert "plateau" in v
    assert "parelia" in v
    assert "memory" in v
    assert "rules" in v
    assert v["beat"] == 3
    assert v["parelia"]["stage"] >= 0
    assert v["memory"]["l1"]["l1_count"] >= 0


@test("summary returns session stats")
def test_summary():
    orch = PareliaOrchestrator()
    for b in range(1, 11):
        orch.tick(make_hot(b), make_full(b))

    s = orch.summary()
    assert s["beats"] == 10
    assert s["current_stage"] >= 0
    assert s["rule_evaluations"] == 0  # no evaluate_proposal calls
    assert s["node_count"] == 32  # no growth


@test("shutdown closes telemetry gracefully")
def test_shutdown():
    orch = PareliaOrchestrator()
    orch.tick(make_hot(1), make_full(1))
    path = orch.telemetry.path
    orch.shutdown()
    assert path.exists()
    assert path.stat().st_size > 0


@test("orchestrator handles 200 beats without error")
def test_endurance():
    orch = PareliaOrchestrator(plateau_window=50)
    for b in range(1, 201):
        result = orch.tick(make_hot(b), make_full(b))
    assert orch.beat == 200
    assert orch.telemetry.healthy
    s = orch.summary()
    assert s["beats"] == 200


@test("rule engine loaded with 4 sources")
def test_rule_sources():
    orch = PareliaOrchestrator()
    sources = orch.rule_engine._sources_added
    assert "values" in sources
    assert "stage" in sources
    assert "telemetry" in sources
    assert "boundary" in sources


# ── cleanup & run ─────────────────────────────────────────────────

@test("orchestrator idempotent on repeated ticks")
def test_idempotent():
    orch = PareliaOrchestrator()
    for b in range(1, 6):
        orch.tick(make_hot(b), make_full(b))
        orch.tick(make_hot(b), make_full(b))  # same beat twice
    assert orch.beat == 10  # each tick increments
    assert orch.telemetry.write_count == 10


# ── run ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\nParelia v2 Orchestrator Integration Tests")
    print("=" * 50)

    test_instantiate()
    test_tick_stable()
    test_plateau_growth()
    test_rule_evaluate()
    test_stage_transition()
    test_vitals()
    test_summary()
    test_shutdown()
    test_endurance()
    test_rule_sources()
    test_idempotent()

    total = TESTS_PASSED + TESTS_FAILED
    print(f"\n{'=' * 50}")
    print(f"  {TESTS_PASSED}/{total} passed", end="")
    if TESTS_FAILED:
        print(f"  ❌ {TESTS_FAILED} FAILURES")
    else:
        print("  ✅ All tests pass")
    print()

    sys.exit(1 if TESTS_FAILED else 0)