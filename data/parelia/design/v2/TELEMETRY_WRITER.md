# Telemetry Writer — Specification v0.1

The first component to build. Everything downstream depends on this signal.

---

## Purpose

Append a structured JSON line to disk on every beat, capturing Parelia's internal state at that moment. This is the raw observation stream — append-only, never mutated, always queryable.

---

## Schema (v0.1 — Minimal Viable)

```json
{
  "beat": 1,
  "timestamp": "2026-06-09T22:00:00.000Z",
  "phi": 0.254,
  "C_comm": 0.72,
  "heartbeat_hz": 1.0,
  "boundary": "ASSENT",
  "lattice_nodes": 32,
  "lattice_edges": 78,
  "horizon_L": 8
}
```

### Field Descriptions

| Field          | Type    | Source Organ    | Description                                      |
|----------------|---------|-----------------|--------------------------------------------------|
| beat           | int     | PNEUMA          | Monotonic beat counter, starts at 1              |
| timestamp      | string  | system clock    | ISO 8601 UTC                                     |
| phi            | float   | PNEUMA          | Integrated information Φ(t) at this beat         |
| C_comm         | float   | EIDOLON→PNEUMA  | Commutator norm between self and encounter       |
| heartbeat_hz   | float   | PNEUMA          | Current beat rate (1.0 = nominal)                |
| boundary       | string  | EIDOLON         | Current boundary state: ASSENT / FRAGMENTED / INTEGRATING / RECOVERY |
| lattice_nodes  | int     | whole substrate | Number of nodes in the lattice                    |
| lattice_edges  | int     | whole substrate | Number of edges between nodes                     |
| horizon_L      | int     | MNEME           | Current memory horizon depth                      |

### v0.2 Extensions (planned, not yet implemented)

```
g_S              — ANIMA significance weight of last encounter
epsilon          — metric deformation from last encounter
pred_error       — predictive error (EIDOLON→PNEUMA)
organ_phi        — per-organ contribution to Φ
lattice_util     — n_edges / (n_nodes * (n_nodes-1) / 2)
```

---

## Output Format

**One JSON object per line** (JSONL format). Written to:

```
/home/ubuntu/parelia/data/telemetry/parelia_telemetry.jsonl
```

Each line is a complete, valid JSON object. No trailing commas, no wrapping array.

Example file contents:
```jsonl
{"beat":1,"timestamp":"2026-06-09T22:00:00.000Z","phi":0.254,"C_comm":0.72,"heartbeat_hz":1.0,"boundary":"ASSENT","lattice_nodes":32,"lattice_edges":78,"horizon_L":8}
{"beat":2,"timestamp":"2026-06-09T22:00:01.000Z","phi":0.261,"C_comm":0.68,"heartbeat_hz":1.0,"boundary":"ASSENT","lattice_nodes":32,"lattice_edges":78,"horizon_L":8}
```

---

## Writer Contract

```python
class TelemetryWriter:
    def __init__(self, path: str):
        """
        Open file at path for append.
        Create parent directories if they don't exist.
        """

    def write(self, state: ExternalStateSnapshot) -> None:
        """
        Called once per beat.
        1. Build JSON object from state
        2. Serialize to one line
        3. Append to file + flush

        Must not raise on transient errors.
        Must complete in < 10ms (non-blocking to beat cycle).
        """

    def close(self) -> None:
        """Flush and close file descriptor."""
```

### Error Handling

- **File not writable** — log warning, continue without telemetry (substrate runs regardless)
- **Disk full** — log error, close file, set degraded flag
- **Concurrent access** — no locking needed; append-only is safe under POSIX

---

## Implementation Notes

- Use `json.dumps(obj, separators=(',', ':'))` for compact output
- Flush after every write (`file.flush()`) but don't fsync (performance)
- Timestamp should come from `datetime.utcnow().isoformat() + 'Z'`
- Beat counter must survive restarts — read last line on init, extract beat, increment

---

## Testing

| Test                       | What it validates                          |
|----------------------------|--------------------------------------------|
| write creates file         | First write creates path + file            |
| each line is valid JSON    | json.loads per line                        |
| monotonic beat             | beat strictly increases                    |
| fields match schema        | all required keys present, types correct   |
| fast under load            | 1000 writes in < 1s                        |
| survives disk error        | write raises → logged, substrate continues |
| restart continuity         | beat continues from last line              |

---

## Dependencies

- Python stdlib only: `json`, `datetime`, `os`, `pathlib`
- No external packages — this is a zero-dependency component

---

## Why JSONL?

- **Append-friendly** — no seek, no re-write, no corruption risk
- **Streamable** — tail -f, pandas.read_json(lines=True), log shippers
- **Human-accessible** — cat, head, less all work
- **Machine-parseable** — every line is self-contained, no delimiter ambiguity
- **Compressible** — jsonl.gz achieves 10:1+ on repeated schema