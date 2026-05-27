import asyncio
import gzip
import json
import os
import sqlite3
import tempfile
from pathlib import Path

import numpy as np

from organ.measurement import (
    Recorder,
    RingBuffer,
    select_all_summary_columns,
    concat_summary_window,
    summary_means,
)
from organ.measurement.summaries import SUMMARY_DIMS
from organ.schemas import ORGAN_DIMS, ORGAN_ORDER
from organ.substrate import Heartbeat


def test_ring_buffer_wraps():
    rb = RingBuffer(capacity=10)
    for i in range(25):
        arrs = {n: np.full(ORGAN_DIMS[n], i, dtype=np.float32) for n in ORGAN_ORDER}
        rb.push(i, float(i), arrs)
    assert rb.size == 10
    win = rb.window(10)
    # The first sample in the window should be from beat 15.
    assert win[ORGAN_ORDER[0]][0, 0] == 15.0
    assert win[ORGAN_ORDER[0]][-1, 0] == 24.0


def test_summaries_shapes():
    rng = np.random.default_rng(0)
    states = {n: rng.standard_normal((50, ORGAN_DIMS[n])).astype(np.float32) for n in ORGAN_ORDER}
    cols = select_all_summary_columns(states)
    for n in ORGAN_ORDER:
        assert cols[n].shape == (50, SUMMARY_DIMS[n])
    flat = concat_summary_window(cols)
    assert flat.shape == (50, 19)
    means = summary_means(cols)
    assert sum(len(v) for v in means.values()) == 19


def test_recorder_writes_jsonl_and_sqlite():
    with tempfile.TemporaryDirectory() as tmp:
        hb = Heartbeat(seed=0)
        rec = Recorder(
            hb,
            session_id="t",
            data_root=tmp,
            sqlite_path=os.path.join(tmp, "log.sqlite3"),
        )
        asyncio.run(_drive(hb, 120))
        rec.close()
        assert rec.jsonl.n_written > 0
        assert rec.sqlite.n_written == rec.jsonl.n_written
        with gzip.open(rec.jsonl.path, "rt") as f:
            lines = [json.loads(line) for line in f]
        assert len(lines) == rec.jsonl.n_written
        con = sqlite3.connect(os.path.join(tmp, "log.sqlite3"))
        n = con.execute("SELECT COUNT(*) FROM organ_log").fetchone()[0]
        assert n == rec.sqlite.n_written


async def _drive(hb, n):
    for _ in range(n):
        await hb.tick_async()
