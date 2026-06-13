"""
logbook.py — Phase 1.4: SQLite logbook for curvature-driven compose events.

Per §5.2 of curvature_compose_design.md (DEFINITION 683e1bdb1a82).

Provides:
  - LogbookWriter: write compose events and sectional curvature records
  - LogbookReader: query patterns from §5.3 (negative curvature jumps,
                   theta-drop correlation, d_geo vs d_c timeline)
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_PATH = Path(__file__).parent / "logbook_schema.sql"


class LogbookWriter:
    """Writer for the curvature-driven compose logbook.

    Usage::

        lw = LogbookWriter("/path/to/logbook.db")
        event_id = lw.write_compose_event(
            timestamp=42,
            theta_before=0.85,
            regime="B",
            theta_0=[0.1, 0.2, ...],
            theta_1=[0.15, 0.18, ...],
            d_geo=0.0021,
            d_c=0.0017,
            fired=True,
            theta_after=0.92,
            neighbourhood_size=5,
            affected_outcomes=[2, 7, 12],
            regime_reason="N=10 < 30, using categorical metric",
            planes=[...]
        )
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        schema = SCHEMA_PATH.read_text()
        self._conn.executescript(schema)
        self._conn.commit()

    def write_compose_event(
        self,
        timestamp: int,
        theta_before: float,
        regime: str,
        theta_0: list[float],
        theta_1: list[float],
        d_geo: float,
        d_c: float,
        fired: bool,
        theta_after: float | None = None,
        threshold_alpha: float = 1.0,
        neighbourhood_size: int = 0,
        affected_outcomes: list[int] | None = None,
        regime_reason: str | None = None,
        planes: list[dict[str, Any]] | None = None,
    ) -> str:
        """Write one compose event and its sectional curvature records.

        Returns the assigned compose_id (UUID string).
        """
        conn = self._connect()
        compose_id = uuid.uuid4().hex

        affected_json = json.dumps(affected_outcomes or [])

        conn.execute(
            """INSERT INTO compose_events
               (compose_id, timestamp, theta_before, theta_after,
                regime, theta_0_json, theta_1_json,
                d_geo, d_c, threshold_alpha,
                fired, neighbourhood_size, affected_outcomes_json, regime_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                compose_id, timestamp, theta_before, theta_after,
                regime, json.dumps(theta_0), json.dumps(theta_1),
                d_geo, d_c, threshold_alpha,
                1 if fired else 0, neighbourhood_size, affected_json, regime_reason,
            ),
        )

        # Write plane records and compute summary
        pos = neg = null = 0
        if planes:
            for p in planes:
                conn.execute(
                    """INSERT INTO sectional_curvature_planes
                       (compose_id, plane_name, K, sign, coupling_strength)
                       VALUES (?, ?, ?, ?, ?)""",
                    (compose_id, p["plane"], p["K"], p["sign"], p.get("coupling_strength")),
                )
                if p["sign"] == "positive":
                    pos += 1
                elif p["sign"] == "negative":
                    neg += 1
                else:
                    null += 1

        conn.execute(
            """INSERT OR REPLACE INTO curvature_summary
               (compose_id, negative_count, positive_count, null_count)
               VALUES (?, ?, ?, ?)""",
            (compose_id, neg, pos, null),
        )

        conn.commit()
        return compose_id

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


class LogbookReader:
    """Reader for the curvature-driven compose logbook.

    Implements the query patterns from §5.3.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def events_with_negative_curvature_increase(self, min_negative: int = 1) -> list[sqlite3.Row]:
        """Query: 'Show all compose events where negative_count >= min_negative'."""
        conn = self._connect()
        cur = conn.execute(
            """SELECT c.compose_id, c.timestamp, c.d_geo, c.d_c, c.fired,
                      c.theta_before, c.theta_after,
                      s.negative_count, s.positive_count, s.null_count
               FROM compose_events c
               JOIN curvature_summary s ON c.compose_id = s.compose_id
               WHERE s.negative_count >= ?
               ORDER BY c.timestamp""",
            (min_negative,),
        )
        return cur.fetchall()

    def theta_drop_curvature_correlation(self) -> list[sqlite3.Row]:
        """Query: 'What is the correlation between θ drop and negative curvature?'"""
        conn = self._connect()
        cur = conn.execute(
            """SELECT c.compose_id, c.timestamp,
                      c.theta_before - COALESCE(c.theta_after, c.theta_before) AS theta_drop,
                      p.plane_name, p.K, p.sign, p.coupling_strength
               FROM compose_events c
               JOIN sectional_curvature_planes p ON c.compose_id = p.compose_id
               WHERE c.fired = 1
               ORDER BY c.timestamp"""
        )
        return cur.fetchall()

    def geodesic_timeline(self, limit: int = 1000) -> list[sqlite3.Row]:
        """Query: 'Plot d_geo vs d_c over the last N compose events'."""
        conn = self._connect()
        cur = conn.execute(
            """SELECT timestamp, d_geo, d_c, fired, regime
               FROM compose_events
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,),
        )
        return cur.fetchall()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None