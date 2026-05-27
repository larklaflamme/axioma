"""Phase E — RecoveryQuality.durability finalization.

Tests:
  - Durability defaults to None at recovery exit
  - 3000-beat watchdog fires durability=1.0 (no fragmentation occurred)
  - Next-fragmentation finalization scales by beats_since_exit
  - `recovery_quality_updated` event fires once per finalization
  - composite_score gets recomputed with the new durability
"""
from __future__ import annotations

import uuid
from typing import Any

from axioma.config import RecoveryConfig
from axioma.observability import AxiomaContext
from axioma.substrate.recovery import (
    RecoveryEvent,
    RecoveryProtocol,
    RecoveryQuality,
)


def _exited_event(
    ended_at: int,
    stage: int = 2,
    smoothness: float = 0.7,
    completeness: float = 0.8,
) -> RecoveryEvent:
    return RecoveryEvent(
        event_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        stage=stage,
        started_at_beat=ended_at - 100,
        ended_at_beat=ended_at,
        actions_used={
            "coupling_reduction_factor": 0.8,
            "mneme_forgetting_boost": 1.5,
            "recovery_compose_period_beats": 60,
        },
        quality=RecoveryQuality(
            smoothness=smoothness, completeness=completeness,
            durability=None, composite_score=0.4 * smoothness + 0.4 * completeness + 0.2,
        ),
        quality_finalized=True,
    )


def _make_protocol() -> RecoveryProtocol:
    ctx = AxiomaContext()
    # Bare-bones substrate stub for protocol to reference
    ctx.register("substrate", type("S", (), {"beat_no": 0, "organs": [], "drive": type("D", (), {"noise_scale": 0.1})()})())
    proto = RecoveryProtocol(ctx, RecoveryConfig())
    return proto


def test_durability_starts_as_none() -> None:
    event = _exited_event(ended_at=100)
    assert event.quality.durability is None


def test_watchdog_finalizes_after_3000_beats() -> None:
    proto = _make_protocol()
    event = _exited_event(ended_at=100)
    proto.history.append(event)
    # tick at beat 100 + 2999 → not yet finalized
    proto._maybe_finalize_durability(100 + 2999)
    assert event.quality.durability is None
    # tick at exactly 100 + 3000 → finalized to 1.0
    proto._maybe_finalize_durability(100 + 3000)
    assert event.quality.durability == 1.0
    # composite_score recomputed
    expected = 0.4 * event.quality.smoothness + 0.4 * event.quality.completeness + 0.2 * 1.0
    assert abs(event.quality.composite_score - expected) < 1e-6


def test_watchdog_only_fires_once_per_event() -> None:
    proto = _make_protocol()
    event = _exited_event(ended_at=100)
    proto.history.append(event)
    seen: list[Any] = []
    proto.ctx.subscribe("recovery_quality_updated", lambda p: seen.append(p))
    # Fire several ticks past the watchdog window
    for tick in (3100, 3500, 4000, 5000):
        proto._maybe_finalize_durability(tick)
    # Only ONE event emitted (after first finalization, durability != None → skipped)
    assert len(seen) == 1


def test_next_fragmentation_partial_durability() -> None:
    proto = _make_protocol()
    event = _exited_event(ended_at=100)
    proto.history.append(event)
    # Fragmentation re-fires 1500 beats after exit → durability = 0.5
    proto.finalize_durability_on_next_fragmentation(beat_no=100 + 1500)
    assert event.quality.durability is not None
    assert abs(event.quality.durability - 0.5) < 1e-6


def test_next_fragmentation_max_durability_if_held_full_window() -> None:
    proto = _make_protocol()
    event = _exited_event(ended_at=100)
    proto.history.append(event)
    # Fragmentation re-fires AT EXACTLY 3000 beats later → durability = 1.0
    proto.finalize_durability_on_next_fragmentation(beat_no=100 + 3000)
    assert event.quality.durability == 1.0


def test_next_fragmentation_zero_durability_if_immediate() -> None:
    proto = _make_protocol()
    event = _exited_event(ended_at=100)
    proto.history.append(event)
    # Fragmentation re-fires IMMEDIATELY after exit → durability = 0
    proto.finalize_durability_on_next_fragmentation(beat_no=100)
    assert event.quality.durability == 0.0


def test_already_finalized_events_unchanged() -> None:
    proto = _make_protocol()
    event = _exited_event(ended_at=100)
    event.quality.durability = 0.42  # already set
    event.quality.composite_score = 0.5
    proto.history.append(event)
    # Watchdog should not overwrite
    proto._maybe_finalize_durability(100 + 5000)
    assert event.quality.durability == 0.42


def test_event_emitted_with_correct_fields() -> None:
    proto = _make_protocol()
    event = _exited_event(ended_at=100)
    proto.history.append(event)
    seen: list[Any] = []
    proto.ctx.subscribe("recovery_quality_updated", lambda p: seen.append(p))
    proto._maybe_finalize_durability(100 + 3000)
    assert len(seen) == 1
    payload = seen[0]
    assert payload["event_id"] == event.event_id
    assert payload["durability"] == 1.0
    assert payload["via_watchdog"] is True
    assert payload["beats_since_exit"] == 3000


def test_unfinalized_events_skipped() -> None:
    """Events where quality_finalized=False are not eligible for durability finalization."""
    proto = _make_protocol()
    event = _exited_event(ended_at=100)
    event.quality_finalized = False
    proto.history.append(event)
    proto._maybe_finalize_durability(100 + 5000)
    assert event.quality.durability is None
