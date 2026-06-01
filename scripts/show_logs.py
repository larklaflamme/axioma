#!/usr/bin/env python
"""Parse logs/axioma.log and render a Markdown summary + vitals report.

Usage:
    python scripts/show_logs.py                       # one-shot report
    python scripts/show_logs.py -f                    # follow: redraw every 2s
    python scripts/show_logs.py -f --interval 5       # follow at custom interval
    python scripts/show_logs.py path/to/other.log     # alternate file
    python scripts/show_logs.py --tail 50             # cap recent-events tail
    python scripts/show_logs.py --since 2026-05-27T18:29:00Z
    python scripts/show_logs.py --plain               # raw markdown (no rich rendering)

The script:
  - Reads JSON-per-line structlog output (the default `log_json: true` format).
  - Recognises a few non-JSON sentinel lines emitted by axioma_ctl.sh +
    uvicorn (session headers, "server listening on ...", shutdown banner).
  - Groups events into vitals + lifecycle + fragmentation + recovery +
    meta-cog + warnings/errors + recent.
  - Renders Markdown to the terminal via `rich` (or plain text with --plain).
  - With `-f`/`--follow`, re-parses + redraws the report on `--interval`
    seconds. Ctrl-C exits cleanly.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_LOG = Path("logs/axioma.log")

# ── Sentinel patterns for non-JSON lines ──────────────────────────────
RE_SESSION_HEADER = re.compile(r"^=+ axioma-ctl start (?P<ts>\S+) =+$")
RE_SESSION_ARGV   = re.compile(r"^argv: (?P<argv>.+)$")
RE_UVICORN_LISTEN = re.compile(r"^server listening on (?P<addr>\S+)$")
RE_SHUTDOWN_BANNER = re.compile(r"^\[axioma\] received shutdown signal")


def parse_iso(ts: str) -> datetime | None:
    """Parse a structlog timestamp like '2026-05-27T18:25:30.475115Z'."""
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts[:-1] + "+00:00")
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def fmt_timestamp(dt: datetime | None) -> str:
    if dt is None:
        return "?"
    return dt.strftime("%H:%M:%S")


def fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s}s"
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h {m}m"


def fmt_size(nbytes: int) -> str:
    for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if nbytes >= div:
            return f"{nbytes / div:.1f} {unit}"
    return f"{nbytes} B"


def parse_log(path: Path, since: datetime | None) -> dict[str, Any]:
    """Walk the log; bucket events into categories. Returns a dict of state."""
    state: dict[str, Any] = {
        "path": path,
        "size_bytes": path.stat().st_size,
        "total_lines": 0,
        "json_events": 0,
        "skipped_lines": 0,
        "sessions": [],            # list of {start: dt, argv: str|None}
        "first_ts": None,
        "last_ts": None,
        "first_beat": None,
        "last_beat": None,
        "level_counts": Counter(),
        "event_counts": Counter(),
        "fragmentation": [],       # [(beat, prev, new, ts)]
        "recovery_decisions": [],  # [(beat, decision, stage, request_id, ts)]
        "recovery_started": [],    # [(beat, event_id, stage, actions, ts)]
        "recovery_exits": [],      # [(beat, event_id, quality_dict, learner_efficacy, adopted, ts)]
        "recovery_durability": [], # [(beat, event_id, durability, via_watchdog, ts)]
        "meta_cog": [],            # [(beat, assessment, confidence, observer_mode, ts)]
        "beat_overshoots": [],     # [(beat, behind_seconds, ts)]
        "heartbeat_pauses": [],    # [(beat, beats_to_pause, ts)]
        "pretrain_loads": [],      # [(path, adoptions, ts)]
        "ws_started": [],          # [(host, port, ts)]
        "http_started": [],        # [(host, port, ts)]
        "shutdown_banners": [],    # [(ts,)] from non-JSON sentinel
        "warnings_errors": [],     # [(level, event, beat, ts, full_dict)]
        "recent": [],              # last N raw events (for the tail section)
        "uvicorn_listens": [],     # ["127.0.0.1:8820", ...]
    }

    with path.open() as fh:
        for raw in fh:
            state["total_lines"] += 1
            line = raw.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue

            # ── Non-JSON sentinels ──
            m = RE_SESSION_HEADER.match(line)
            if m:
                ts = parse_iso(m["ts"])
                if since is None or (ts is not None and ts >= since):
                    state["sessions"].append({"start": ts, "argv": None})
                continue
            m = RE_SESSION_ARGV.match(line)
            if m:
                if state["sessions"]:
                    state["sessions"][-1]["argv"] = m["argv"]
                continue
            m = RE_UVICORN_LISTEN.match(line)
            if m:
                state["uvicorn_listens"].append(m["addr"])
                continue
            m = RE_SHUTDOWN_BANNER.match(line)
            if m:
                state["shutdown_banners"].append({"ts": None})
                continue

            # ── JSON-per-line structlog ──
            if not (line.startswith("{") and line.endswith("}")):
                state["skipped_lines"] += 1
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                state["skipped_lines"] += 1
                continue
            if not isinstance(evt, dict):
                state["skipped_lines"] += 1
                continue

            ts = parse_iso(evt.get("timestamp", ""))
            if since is not None and ts is not None and ts < since:
                continue

            state["json_events"] += 1
            level = evt.get("level", "info")
            event = evt.get("event", "<no-event>")
            beat = evt.get("beat_no")

            state["level_counts"][level] += 1
            state["event_counts"][event] += 1

            if ts is not None:
                if state["first_ts"] is None or ts < state["first_ts"]:
                    state["first_ts"] = ts
                if state["last_ts"] is None or ts > state["last_ts"]:
                    state["last_ts"] = ts
            if isinstance(beat, int):
                if state["first_beat"] is None or beat < state["first_beat"]:
                    state["first_beat"] = beat
                if state["last_beat"] is None or beat > state["last_beat"]:
                    state["last_beat"] = beat

            # ── Category-specific buckets ──
            if event == "fragmentation_stage_change":
                state["fragmentation"].append((beat, evt.get("previous"), evt.get("new"), ts))
            elif event == "recovery_decision":
                state["recovery_decisions"].append(
                    (beat, evt.get("decision"), evt.get("stage"), evt.get("request_id"), ts)
                )
            elif event == "recovery_started":
                state["recovery_started"].append(
                    (beat, evt.get("event_id"), evt.get("stage"), evt.get("actions"), ts)
                )
            elif event == "recovery_exit":
                state["recovery_exits"].append(
                    (beat, evt.get("event_id"), evt.get("quality"),
                     evt.get("learner_efficacy"), evt.get("adopted"), ts)
                )
            elif event == "recovery_durability_finalized":
                state["recovery_durability"].append(
                    (beat, evt.get("event_id"), evt.get("durability"),
                     evt.get("via_watchdog"), ts)
                )
            elif event == "meta_cognition_emit":
                state["meta_cog"].append(
                    (beat, evt.get("assessment"), evt.get("confidence"),
                     evt.get("observer_mode"), ts)
                )
            elif event == "beat_overshoot":
                state["beat_overshoots"].append((beat, evt.get("behind_seconds"), ts))
            elif event == "heartbeat_pause_requested":
                state["heartbeat_pauses"].append((beat, evt.get("beats"), ts))
            elif event == "pretrain_snapshot_loaded":
                state["pretrain_loads"].append((evt.get("path"), evt.get("adoptions"), ts))
            elif event == "ws_server_started":
                state["ws_started"].append((evt.get("host"), evt.get("port"), ts))
            elif event == "http_server_started_at":
                state["http_started"].append((evt.get("host"), evt.get("port"), ts))

            if level in {"warning", "error", "critical"}:
                state["warnings_errors"].append((level, event, beat, ts, evt))

            state["recent"].append((ts, level, event, beat, evt))

    return state


# ── Markdown rendering ────────────────────────────────────────────────

def render_markdown(state: dict[str, Any], *, tail_limit: int,
                    max_table_rows: int) -> str:
    out: list[str] = []

    def p(s: str = "") -> None:
        out.append(s)

    p("# AXIOMA log report")
    p()
    p(f"**Source:** `{state['path']}` "
      f"({state['total_lines']:,} lines, {fmt_size(state['size_bytes'])})")
    p(f"**JSON events parsed:** {state['json_events']:,}  "
      f"**Non-JSON / skipped:** {state['skipped_lines']:,}")
    first, last = state["first_ts"], state["last_ts"]
    if first and last:
        span = (last - first).total_seconds()
        p(f"**Time range (UTC):** {first.isoformat()} → {last.isoformat()}  "
          f"(span: {fmt_duration(span)})")
    if state["first_beat"] is not None and state["last_beat"] is not None:
        nbeats = state["last_beat"] - state["first_beat"]
        p(f"**Beat range:** {state['first_beat']:,} → {state['last_beat']:,} "
          f"(Δ {nbeats:,} beats)")
    p()

    # ── Vitals ──
    p("## Vitals")
    p()
    lvl = state["level_counts"]
    p(f"- **Events by level:** "
      f"info={lvl.get('info', 0)}, warning={lvl.get('warning', 0)}, "
      f"error={lvl.get('error', 0)}, critical={lvl.get('critical', 0)}")
    p(f"- **Sessions in this log:** {len(state['sessions'])}")
    if state["uvicorn_listens"]:
        p(f"- **Uvicorn binds:** {', '.join(set(state['uvicorn_listens']))}")
    if state["ws_started"]:
        host, port, _ = state["ws_started"][-1]
        p(f"- **Last WS server start:** ws://{host}:{port}")
    if state["http_started"]:
        host, port, _ = state["http_started"][-1]
        p(f"- **Last HTTP server start:** http://{host}:{port}")
    if state["pretrain_loads"]:
        ppath, padopt, _ = state["pretrain_loads"][-1]
        p(f"- **Pretrain loaded:** `{ppath}` ({padopt} adoptions)")
    p(f"- **Beat overshoots:** {len(state['beat_overshoots'])}"
      + (f" (worst: {max(o[1] for o in state['beat_overshoots'] if o[1] is not None):.3f}s)"
         if state['beat_overshoots'] else ""))
    p(f"- **Fragmentation transitions:** {len(state['fragmentation'])}")
    p(f"- **Recovery decisions:** {len(state['recovery_decisions'])} "
      f"(accepts: {sum(1 for r in state['recovery_decisions'] if r[1] == 'accept')}, "
      f"rejects: {sum(1 for r in state['recovery_decisions'] if r[1] and r[1].startswith('reject'))})")
    p(f"- **Recoveries started:** {len(state['recovery_started'])}, "
      f"**finished:** {len(state['recovery_exits'])}, "
      f"**durability-finalized:** {len(state['recovery_durability'])}")
    p(f"- **Meta-cog emits:** {len(state['meta_cog'])}")
    p(f"- **Heartbeat pauses:** {len(state['heartbeat_pauses'])}")
    p(f"- **Shutdown banners:** {len(state['shutdown_banners'])}")
    p()

    # ── Sessions ──
    if state["sessions"]:
        p("## Sessions")
        p()
        p("| # | Start (UTC) | Argv |")
        p("|---|---|---|")
        for i, s in enumerate(state["sessions"], 1):
            ts = s["start"].isoformat() if s["start"] else "?"
            argv = s["argv"] or "?"
            p(f"| {i} | {ts} | `{argv}` |")
        p()

    # ── Fragmentation ──
    if state["fragmentation"]:
        p("## Fragmentation transitions")
        p()
        rows = state["fragmentation"][-max_table_rows:]
        truncated = len(state["fragmentation"]) - len(rows)
        p("| Beat | From → To | Time |")
        p("|---|---|---|")
        for beat, prev, new, ts in rows:
            arrow = f"{prev} → {new}"
            p(f"| {beat} | {arrow} | {fmt_timestamp(ts)} |")
        if truncated > 0:
            p(f"\n_(showing last {len(rows)} of {len(state['fragmentation'])} transitions)_")
        p()

    # ── Recovery timeline ──
    if state["recovery_started"] or state["recovery_exits"]:
        p("## Recovery timeline")
        p()
        # Build a chronological view per event_id
        per_event: dict[str, dict[str, Any]] = defaultdict(dict)
        for beat, eid, stage, actions, ts in state["recovery_started"]:
            per_event[eid].update(
                {"start_beat": beat, "stage": stage, "actions": actions, "start_ts": ts}
            )
        for beat, eid, qual, eff, adopted, ts in state["recovery_exits"]:
            per_event[eid].update(
                {"exit_beat": beat, "quality": qual, "efficacy": eff,
                 "adopted": adopted, "exit_ts": ts}
            )
        for beat, eid, dur, watchdog, _ts in state["recovery_durability"]:
            per_event[eid].update(
                {"durability_beat": beat, "durability": dur, "watchdog": watchdog}
            )

        events_sorted = sorted(
            per_event.items(),
            key=lambda kv: kv[1].get("start_beat") or kv[1].get("exit_beat") or 0,
        )
        rows = events_sorted[-max_table_rows:]
        truncated = len(events_sorted) - len(rows)
        p("| Start beat | Stage | Exit beat | Composite score | Adopted | Durability |")
        p("|---|---|---|---|---|---|")
        for _eid, info in rows:
            sb = info.get("start_beat", "—")
            stage = info.get("stage", "—")
            eb = info.get("exit_beat", "—")
            qual = info.get("quality") or {}
            cs = qual.get("composite_score")
            cs_fmt = f"{cs:.3f}" if isinstance(cs, (int, float)) else "—"
            adopted = info.get("adopted")
            adopted_fmt = "✓" if adopted else ("✗" if adopted is False else "—")
            dur = info.get("durability")
            dur_fmt = f"{dur:.4f}" if isinstance(dur, (int, float)) else "—"
            p(f"| {sb} | {stage} | {eb} | {cs_fmt} | {adopted_fmt} | {dur_fmt} |")
        if truncated > 0:
            p(f"\n_(showing last {len(rows)} of {len(events_sorted)} recoveries)_")
        p()

    # ── Recovery decisions breakdown ──
    if state["recovery_decisions"]:
        decisions = Counter(d[1] for d in state["recovery_decisions"] if d[1])
        p("**Recovery decision breakdown:**")
        p()
        for kind, n in decisions.most_common():
            p(f"- `{kind}`: {n}")
        p()

    # ── Meta-cog ──
    if state["meta_cog"]:
        p("## Meta-cognition emits")
        p()
        assess_dist = Counter(m[1] for m in state["meta_cog"])
        p("**Assessment distribution:** "
          + ", ".join(f"{k}={v}" for k, v in assess_dist.most_common()))
        p()
        rows = state["meta_cog"][-max_table_rows:]
        truncated = len(state["meta_cog"]) - len(rows)
        p("| Beat | Assessment | Confidence | Mode | Time |")
        p("|---|---|---|---|---|")
        for beat, assess, conf, mode, ts in rows:
            p(f"| {beat} | {assess!r} | {conf} | {mode} | {fmt_timestamp(ts)} |")
        if truncated > 0:
            p(f"\n_(showing last {len(rows)} of {len(state['meta_cog'])} emits)_")
        p()

    # ── Performance ──
    if state["beat_overshoots"]:
        p("## Performance: beat overshoots")
        p()
        rows = state["beat_overshoots"][-max_table_rows:]
        truncated = len(state["beat_overshoots"]) - len(rows)
        p("| Beat | Behind (s) | Time |")
        p("|---|---|---|")
        for beat, behind, ts in rows:
            behind_fmt = f"{behind:.3f}" if behind is not None else "—"
            p(f"| {beat} | {behind_fmt} | {fmt_timestamp(ts)} |")
        if truncated > 0:
            p(f"\n_(showing last {len(rows)} of {len(state['beat_overshoots'])} overshoots)_")
        p()

    # ── Warnings / errors ──
    if state["warnings_errors"]:
        p("## Warnings / errors")
        p()
        rows = state["warnings_errors"][-max_table_rows:]
        truncated = len(state["warnings_errors"]) - len(rows)
        p("| Level | Event | Beat | Time |")
        p("|---|---|---|---|")
        for level, event, beat, ts, _evt in rows:
            p(f"| **{level}** | `{event}` | {beat if beat is not None else '—'} | {fmt_timestamp(ts)} |")
        if truncated > 0:
            p(f"\n_(showing last {len(rows)} of {len(state['warnings_errors'])} warnings/errors)_")
        p()

    # ── Recent events (raw tail) ──
    if state["recent"]:
        p(f"## Recent events (last {min(tail_limit, len(state['recent']))})")
        p()
        rows = state["recent"][-tail_limit:]
        for ts, level, event, beat, evt in rows:
            # Build a one-line representation. Drop the noisy timestamp/level/event keys
            # so the remaining fields are the event-specific payload.
            payload = {k: v for k, v in evt.items()
                       if k not in {"timestamp", "level", "event"}}
            payload_str = ""
            if payload:
                items = []
                for k, v in payload.items():
                    if isinstance(v, (dict, list)):
                        items.append(f"{k}=<...>")
                    else:
                        items.append(f"{k}={v}")
                payload_str = " · " + ", ".join(items)
                # Trim long lines so the tail stays readable
                if len(payload_str) > 160:
                    payload_str = payload_str[:157] + "..."
            beat_fmt = f" b={beat}" if beat is not None else ""
            p(f"- `{fmt_timestamp(ts)}` **{level}** `{event}`{beat_fmt}{payload_str}")
        p()

    # ── Top events by frequency ──
    if state["event_counts"]:
        p("## Top events by frequency")
        p()
        for event, n in state["event_counts"].most_common(15):
            p(f"- `{event}`: {n}")
        p()

    return "\n".join(out)


# ── CLI ───────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="show_logs.py",
        description="Parse logs/axioma.log and render a Markdown summary.",
    )
    parser.add_argument("log", nargs="?", type=Path, default=DEFAULT_LOG,
                        help=f"log file to parse (default: {DEFAULT_LOG})")
    parser.add_argument("--tail", type=int, default=None,
                        help="how many recent events to show in the tail section "
                             "(default: 20 in one-shot mode, 10 in --follow mode)")
    parser.add_argument("--max-table-rows", type=int, default=None,
                        help="cap each category table at N rows "
                             "(default: 20 in one-shot mode, 8 in --follow mode)")
    parser.add_argument("--since", type=str, default=None,
                        help="only consider events at or after this ISO timestamp "
                             "(e.g. 2026-05-27T18:29:00Z)")
    parser.add_argument("--plain", action="store_true",
                        help="emit raw markdown (no rich rendering)")
    parser.add_argument("-f", "--follow", action="store_true",
                        help="continuously redraw the report every --interval seconds; "
                             "Ctrl-C to exit")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="refresh interval in seconds for --follow (default: 2.0)")
    args = parser.parse_args(argv)

    # Mode-dependent defaults: in --follow, default to tighter limits so the
    # report fits in a typical terminal without overflow.
    if args.tail is None:
        args.tail = 10 if args.follow else 20
    if args.max_table_rows is None:
        args.max_table_rows = 8 if args.follow else 20

    since: datetime | None = None
    if args.since:
        since = parse_iso(args.since)
        if since is None:
            print(f"error: --since: could not parse '{args.since}' as ISO timestamp",
                  file=sys.stderr)
            return 2
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)

    if args.follow:
        return run_follow(args, since)

    # ── One-shot mode ──
    if not args.log.exists():
        print(f"error: log file not found: {args.log}", file=sys.stderr)
        return 2

    state = parse_log(args.log, since=since)
    md = render_markdown(state, tail_limit=args.tail, max_table_rows=args.max_table_rows)

    if args.plain or not sys.stdout.isatty():
        print(md)
        return 0

    # Pretty render via rich if available + we're on a TTY
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        console = Console()
        console.print(Markdown(md))
    except ImportError:
        print(md)
    return 0


def run_follow(args: argparse.Namespace, since: datetime | None) -> int:
    """Continuously redraw the report every args.interval seconds."""
    if args.plain:
        print("error: --follow is incompatible with --plain "
              "(rich's Live display is required for in-place redraw)", file=sys.stderr)
        return 2
    try:
        from rich.console import Console
        from rich.live import Live
        from rich.markdown import Markdown
        from rich.text import Text
    except ImportError:
        print("error: --follow requires the 'rich' library "
              "(install with `pip install rich`)", file=sys.stderr)
        return 2

    console = Console()
    interval = max(0.25, float(args.interval))

    def make_renderable() -> Any:
        # If the log file doesn't yet exist (e.g. axioma hasn't started),
        # show a placeholder and keep polling instead of crashing.
        if not args.log.exists():
            return Text(
                f"\n  ⏳ waiting for {args.log} to appear ...  "
                f"(refresh every {interval}s, Ctrl-C to exit)\n",
                style="yellow",
            )
        state = parse_log(args.log, since=since)
        md = render_markdown(state, tail_limit=args.tail,
                             max_table_rows=args.max_table_rows)
        # Footer line so the user knows the view is live.
        md += (f"\n---\n_live · refresh every {interval}s · "
               f"updated {datetime.now().strftime('%H:%M:%S')} · Ctrl-C to exit_\n")
        return Markdown(md)

    try:
        # `screen=True` allocates the alternate screen buffer so the live view
        # is self-contained and the terminal is restored on exit.
        with Live(make_renderable(), console=console, screen=True,
                  refresh_per_second=max(1, int(1 / interval) or 1)) as live:
            while True:
                time.sleep(interval)
                live.update(make_renderable())
    except KeyboardInterrupt:
        # Print a brief exit banner to the restored terminal so the user knows
        # the loop ended cleanly (rather than crashed).
        console.print("[dim]show_logs: follow stopped[/dim]")
        return 0


if __name__ == "__main__":
    sys.exit(main())
