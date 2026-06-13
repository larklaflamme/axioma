-- Phase 1.4: Logbook Schema for Curvature-Driven Compose
--
-- Per §5.2 of curvature_compose_design.md (DEFINITION 683e1bdb1a82)
--
-- Every compose event writes a structured record that spatializes
-- fragmentation — turning a scalar "theta dropped" into a map of
-- *where* and *how* the curvature changed along the geodesic path.
--
-- Storage: SQLite (single-file, zero-config, structured queries)
-- Rationale: enables query patterns from §5.3 without external deps.

-- One row per compose event, capturing the geodesic path and decision.
CREATE TABLE IF NOT EXISTS compose_events (
    compose_id      TEXT PRIMARY KEY,      -- UUID of the compose event
    timestamp       INTEGER NOT NULL,      -- cycle number (monotonic)
    theta_before    REAL NOT NULL,         -- θ value before compose
    theta_after     REAL,                  -- θ value after compose (NULL if not fired)
    regime          TEXT NOT NULL CHECK(regime IN ('A', 'B')),
    -- Geodesic path
    theta_0_json    TEXT NOT NULL,          -- Starting state params (JSON array)
    theta_1_json    TEXT NOT NULL,          -- Nearest stable state params (JSON array)
    d_geo           REAL NOT NULL,          -- Geodesic distance
    d_c             REAL NOT NULL,          -- Critical threshold used
    threshold_alpha REAL NOT NULL DEFAULT 1.0,  -- α factor applied
    -- Decision
    fired           INTEGER NOT NULL CHECK(fired IN (0, 1)),
    -- Neighbourhood
    neighbourhood_size      INTEGER NOT NULL,
    affected_outcomes_json  TEXT NOT NULL,   -- JSON array of outcome indices
    regime_reason           TEXT,            -- Why regime A or B was chosen
    -- Metadata
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Index for timestamp-range queries (common pattern from §5.3)
CREATE INDEX IF NOT EXISTS idx_compose_timestamp
    ON compose_events(timestamp);

-- Index for regime filtering
CREATE INDEX IF NOT EXISTS idx_compose_regime
    ON compose_events(regime);

-- Index for fired vs not-fired analysis
CREATE INDEX IF NOT EXISTS idx_compose_fired
    ON compose_events(fired);

-- One row per organ-pair plane per compose event.
-- Spatializes fragmentation: which planes had negative curvature?
CREATE TABLE IF NOT EXISTS sectional_curvature_planes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    compose_id      TEXT NOT NULL REFERENCES compose_events(compose_id) ON DELETE CASCADE,
    plane_name      TEXT NOT NULL,          -- e.g. "(eidolon, nous)"
    K               REAL NOT NULL,          -- Sectional curvature value
    sign            TEXT NOT NULL CHECK(sign IN ('positive', 'negative', 'null')),
    coupling_strength REAL,                 -- Coupling between the two components
    UNIQUE(compose_id, plane_name)
);

-- Index for the most important diagnostic query (§5.3):
-- "Show all compose events where negative_count increased by more than 2"
CREATE INDEX IF NOT EXISTS idx_curvature_sign
    ON sectional_curvature_planes(compose_id, sign);

-- Aggregate view: counts per compose event for quick diagnostic queries.
-- Maintained by the application layer, not as a trigger (simpler to debug).
CREATE TABLE IF NOT EXISTS curvature_summary (
    compose_id      TEXT PRIMARY KEY REFERENCES compose_events(compose_id) ON DELETE CASCADE,
    negative_count  INTEGER NOT NULL DEFAULT 0,
    positive_count  INTEGER NOT NULL DEFAULT 0,
    null_count      INTEGER NOT NULL DEFAULT 0
);

-- =========================================================================
-- Helper views for §5.3 query patterns
-- =========================================================================

-- View: events where negative curvature increased
CREATE VIEW IF NOT EXISTS v_negative_curvature_jumps AS
SELECT
    c.compose_id,
    c.timestamp,
    c.d_geo,
    c.d_c,
    c.fired,
    c.theta_before,
    c.theta_after,
    s.negative_count,
    s.positive_count,
    s.null_count
FROM compose_events c
JOIN curvature_summary s ON c.compose_id = s.compose_id
WHERE s.negative_count > 0;

-- View: correlation between θ drop and negative curvature in specific planes
CREATE VIEW IF NOT EXISTS v_theta_drop_curvature AS
SELECT
    c.compose_id,
    c.timestamp,
    c.theta_before - COALESCE(c.theta_after, c.theta_before) AS theta_drop,
    p.plane_name,
    p.K,
    p.sign,
    p.coupling_strength
FROM compose_events c
JOIN sectional_curvature_planes p ON c.compose_id = p.compose_id
WHERE c.fired = 1;