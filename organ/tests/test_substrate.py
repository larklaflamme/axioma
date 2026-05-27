import asyncio
import numpy as np
import pytest

from organ.schemas import validate_ranges
from organ.substrate import Heartbeat


def test_heartbeat_tick_in_range():
    hb = Heartbeat(seed=0, compose_every=30)
    for _ in range(200):
        hb.tick()
    for organ in hb.organs:
        validate_ranges(organ.name, organ.get_state())


def test_distinct_traces():
    hb = Heartbeat(seed=0)
    arrs_1 = [organ.get_state_array().copy() for organ in hb.organs]
    for _ in range(50):
        hb.tick()
    arrs_2 = [organ.get_state_array().copy() for organ in hb.organs]
    for a, b in zip(arrs_1, arrs_2):
        assert not np.allclose(a, b)


def test_pneuma_buffer_after_compose():
    hb = Heartbeat(seed=0, compose_every=5)
    # Run a few beats to trigger compose events.
    asyncio.run(_drive(hb, 20))
    # After draining, buffer should be 0.
    assert hb.pneuma.get_state().buffer_depth == 0


async def _drive(hb, n):
    for _ in range(n):
        await hb.tick_async()
