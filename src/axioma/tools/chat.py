"""Interactive chat + control CLI for a running AXIOMA.

Usage:
    python -m axioma.tools.chat                       # localhost defaults
    python -m axioma.tools.chat --ws-port 9999
    python -m axioma.tools.chat --speaker thea
    python -m axioma.tools.chat --admin-key $AXIOMA_ADMIN_KEY

Plain text input is sent as a `conversation_message`. AXIOMA's reply is
rendered as markdown via `rich`. Lines starting with `/` are dispatched as
local commands (HTTP API calls + subscription management + streaming).

Slash commands (type `/help` inside the chat):
  /help                       list commands
  /quit, /exit, /q            exit
  /clear                      clear the screen
  /history                    show this session's conversation transcript
  /status                     pretty-print key vitals from /status
  /health                     pretty-print /health
  /perturb KIND [MAG] [TAG]   POST /admin/perturb (KIND ∈ contradiction|impulse|
                              step|novelty|attention|noise_burst; MAG default 0.5)
  /force STAGE                POST /admin/recovery/force
  /sub CHANNEL [...]          subscribe to one or more channels
  /unsub CHANNEL [...]        unsubscribe
  /channels                   list current subscriptions
  /watch CHANNEL [SECONDS]    stream frames from a channel until Ctrl-C or
                              SECONDS elapse (default: no time limit)
  /admin-key KEY              set/update the admin bearer token in this session
  /timeout SECONDS            set per-message reply timeout (default: OLLAMA_TIMEOUT or 120)
  /speaker NAME               note: requires reconnect; informational only

Subscribed-channel frames print between turns (after each command + after each
chat reply), so you can sub to `theta` or `fragmentation` and see them roll
past as you talk. The conversation channel is always subscribed.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
from collections import defaultdict
from typing import Any

# Heavy imports happen lazily inside main() so `--help` is fast.

# Public channel names AXIOMA serves (kept in sync with axioma.interface.protocol)
KNOWN_CHANNELS = frozenset({
    "conversation", "theta", "per_organ_theta", "per_organ_mi_raw",
    "delta_phi", "aos_g", "plasticity", "fragmentation", "perturbations",
    "coherence_budget", "recovery", "meta_cognition",
    "meta_cognition_suggestion", "presence", "state_snapshot",
})


# ── Helpers ──────────────────────────────────────────────────────────────


def _format_frame_compact(frame: dict[str, Any]) -> str:
    """One-line summary of a channel envelope for between-turn display.

    The returned string contains rich markup escapes around `[channel]` tags so
    callers can pass it directly to `console.print(...)` without rich
    swallowing the brackets as a style.
    """
    ch = frame.get("channel") or "?"
    beat = frame.get("beat_no")
    p = frame.get("payload") or {}
    beat_part = f" b={beat}" if beat is not None else ""
    # Use rich-markup-escaped brackets so [channel] doesn't get interpreted as
    # a style tag.
    def tag(name: str) -> str:
        return f"\\[{name}]"
    if not isinstance(p, dict):
        return f"{tag(ch)}{beat_part} {p!r}"
    if ch == "theta":
        if "theta_short" in p:
            return (f"{tag('theta')}{beat_part} short={p.get('theta_short'):.3f} "
                    f"sig={p.get('significant')}")
        if "theta_long" in p:
            return (f"{tag('theta')}{beat_part} long={p.get('theta_long'):.3f} "
                    f"sig={p.get('significant')}")
    if ch == "aos_g":
        return (f"{tag('aos_g')}{beat_part} gap={p.get('gap', 0):.4f} "
                f"psi={p.get('psi', 0):.3f} alert={p.get('alert')}")
    if ch == "fragmentation":
        prev, new = p.get("previous"), p.get("new")
        return f"{tag('fragmentation')}{beat_part} {prev}→{new}"
    if ch == "meta_cognition":
        return (f"{tag('meta_cog')}{beat_part} {p.get('assessment')!r} "
                f"conf={p.get('confidence')}")
    if ch == "presence":
        return (f"{tag('presence')}{beat_part} {p.get('event')} "
                f"speaker={p.get('speaker')}")
    if ch == "perturbations":
        return (f"{tag('perturb')}{beat_part} kind={p.get('kind')} "
                f"mag={p.get('magnitude')}")
    if ch == "recovery":
        return (f"{tag('recovery')}{beat_part} "
                + " ".join(f"{k}={v}" for k, v in list(p.items())[:3]))
    if ch == "coherence_budget":
        return (f"{tag('coherence')}{beat_part} budget={p.get('budget'):.3f} "
                f"throttle={p.get('throttle_state')}")
    # Fallback: short JSON
    s = json.dumps(p, default=str)
    if len(s) > 140:
        s = s[:137] + "..."
    return f"{tag(ch)}{beat_part} {s}"


# ── Async chat client ────────────────────────────────────────────────────


class ChatClient:
    """One running session: WS for chat + channels, HTTP for admin/read."""

    def __init__(
        self,
        *,
        ws_url: str,
        http_url: str,
        speaker: str,
        admin_key: str | None,
        reply_timeout: float,
    ) -> None:
        self.ws_url = ws_url
        self.http_url = http_url
        self.speaker = speaker
        self.admin_key = admin_key
        self.reply_timeout = reply_timeout
        self.ws: Any = None
        # Channels we explicitly subscribed to via /sub (does not include `conversation`)
        self.user_subs: set[str] = set()
        # Conversation transcript: list of (role, content)
        self.transcript: list[tuple[str, str]] = []
        # Background frame queue
        self.frames: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None
        # Per-channel frame counts (for /channels)
        self._channel_counts: dict[str, int] = defaultdict(int)
        # Console (rich) — set in start()
        self.console: Any = None
        # Set to True when the server closes the WS — every subsequent
        # ws.send / ws.recv would raise, so we short-circuit and let the
        # REPL exit cleanly instead of crashing with an unhandled
        # ConnectionClosed traceback.
        self._connection_closed: bool = False

    # ── Lifecycle ──

    async def start(self) -> None:
        import websockets
        from rich.console import Console

        self.console = Console()
        self.ws = await websockets.connect(self.ws_url, ping_interval=None)
        await self.ws.send(json.dumps({
            "type": "handshake",
            "speaker": self.speaker,
            "min_interval_ms": 0,
        }))
        raw = await asyncio.wait_for(self.ws.recv(), timeout=10.0)
        welcome = json.loads(raw)
        if welcome.get("type") != "welcome":
            raise RuntimeError(f"unexpected handshake response: {welcome}")
        self.console.print(
            f"[green]✓[/green] connected to [bold]{self.ws_url}[/bold] as "
            f"[bold]{self.speaker}[/bold] · "
            f"agent_id=[dim]{welcome.get('agent_id')}[/dim]"
        )
        if welcome.get("zone") is not None:
            self.console.print(
                f"  [dim]welcome snapshot:[/dim] zone={welcome.get('zone')!r} "
                f"cadence={welcome.get('cadence')!r} "
                f"theta_short={welcome.get('theta_short')}"
            )
        # Always subscribe to conversation so we can hear AXIOMA's replies.
        await self.ws.send(json.dumps({
            "type": "subscribe", "channels": ["conversation"],
        }))
        self._reader_task = asyncio.create_task(self._reader_loop())

    async def _send_safe(self, payload: dict[str, Any]) -> bool:
        """Send a JSON payload on the WS; catch the connection-closed family.

        Returns True on success, False if the connection has already closed
        (or closes during the send). On False, the caller should bail out
        and the REPL will detect ``self._connection_closed`` and exit.
        """
        from websockets.exceptions import ConnectionClosed

        if self._connection_closed or self.ws is None:
            self._note_connection_closed()
            return False
        try:
            await self.ws.send(json.dumps(payload))
            return True
        except ConnectionClosed as e:
            self._connection_closed = True
            code = getattr(e, "code", None) or getattr(e.rcvd, "code", None)
            reason = (getattr(e, "reason", "") or
                      getattr(e.rcvd, "reason", "") or "")
            extra = f" (close code {code}: {reason!r})" if code else ""
            self.console.print(
                f"  [yellow]connection closed by server{extra} — "
                f"is AXIOMA still running? (`./scripts/axioma_ctl.sh status`)[/yellow]"
            )
            return False
        except OSError as e:
            # Underlying socket-level failure (broken pipe, etc.) — treat
            # the same as a clean close.
            self._connection_closed = True
            self.console.print(
                f"  [yellow]connection dropped: {type(e).__name__}: {e}[/yellow]"
            )
            return False

    def _note_connection_closed(self) -> None:
        """Print a one-time notice that the connection is already gone."""
        if self.ws is None:
            return
        # Idempotent — only the first call prints; subsequent calls are silent.
        if getattr(self, "_close_notice_printed", False):
            return
        self._close_notice_printed = True
        self.console.print(
            "  [yellow]connection is closed — type [bold]/quit[/bold] "
            "to exit or restart this CLI to reconnect.[/yellow]"
        )

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader_task
        if self.ws is not None:
            with contextlib.suppress(Exception):
                await self.ws.close()

    # ── Reader: drains the WS into the in-memory queue ──

    async def _reader_loop(self) -> None:
        try:
            async for raw in self.ws:
                try:
                    frame = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(frame, dict):
                    ch = frame.get("channel")
                    if ch:
                        self._channel_counts[ch] += 1
                    await self.frames.put(frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Connection closed or other error — mark the flag so the main
            # loop sees that subsequent sends will fail, and surface a clear
            # message on the next iteration instead of crashing.
            pass
        finally:
            # `async for raw in self.ws:` exits cleanly when the server
            # closes the socket — that's also our signal to mark closed.
            self._connection_closed = True

    # ── Subscribed-channel frame drain (between turns) ──

    async def drain_subscribed_frames(self, *, max_frames: int = 50) -> None:
        """Print any pending non-conversation frames (channels the user subbed)."""
        printed = 0
        while printed < max_frames:
            try:
                frame = self.frames.get_nowait()
            except asyncio.QueueEmpty:
                return
            ch = frame.get("channel")
            if ch == "conversation":
                # Conversation frames don't get printed here — they're consumed
                # by send_chat() which awaits an explicit AXIOMA reply.
                # Re-queue so a concurrent send_chat() can pick it up, EXCEPT
                # if we're in between turns: drop our own echo + already-seen
                # frames here. The send loop drains the queue on entry.
                continue
            if ch in self.user_subs or ch is None:
                self.console.print(f"  [dim]{_format_frame_compact(frame)}[/dim]")
                printed += 1
            # else: ignore — could be a subscription_error or other meta frame
            elif frame.get("type") == "subscription_error":
                self.console.print(
                    f"  [yellow]subscription_error[/yellow]: "
                    f"channel={frame.get('channel')} reason={frame.get('reason')}"
                )

    # ── Send a chat message + wait for AXIOMA's reply ──

    async def send_chat(self, content: str) -> None:
        from rich.markdown import Markdown
        from rich.panel import Panel

        # Drain any stale frames so we don't accidentally consume a pre-message
        # conversation frame as "the reply."
        while True:
            try:
                stale = self.frames.get_nowait()
                if stale.get("channel") in self.user_subs:
                    self.console.print(f"  [dim]{_format_frame_compact(stale)}[/dim]")
            except asyncio.QueueEmpty:
                break

        if not await self._send_safe({"type": "message", "content": content}):
            return
        self.transcript.append((self.speaker, content))

        # Wait for an axioma-from conversation frame, printing other-channel
        # frames as we go, until reply or timeout.
        start = time.time()
        while True:
            elapsed = time.time() - start
            remaining = self.reply_timeout - elapsed
            if remaining <= 0:
                self.console.print(
                    f"  [yellow]no reply within {self.reply_timeout}s[/yellow] "
                    f"(is AXIOMA running with [bold]--with-peer-conversation[/bold]? "
                    f"and is Ollama up?)"
                )
                return
            try:
                frame = await asyncio.wait_for(self.frames.get(), timeout=remaining)
            except TimeoutError:
                continue
            ch = frame.get("channel")
            if ch == "conversation":
                payload = frame.get("payload") or {}
                speaker = payload.get("speaker")
                if speaker == "axioma":
                    reply = str(payload.get("content", ""))
                    self.transcript.append(("axioma", reply))
                    elapsed_s = time.time() - start
                    title = f"axioma · {elapsed_s:.1f}s"
                    meta = payload.get("metadata") or {}
                    if meta.get("to_speaker"):
                        title += f" · to_speaker={meta['to_speaker']}"
                    self.console.print(Panel(Markdown(reply), title=title,
                                             border_style="cyan", title_align="left"))
                    return
                # Echo of our own message (the conversation channel fans every
                # message to all subscribers, including the sender) — skip.
                continue
            if ch in self.user_subs:
                self.console.print(f"  [dim]{_format_frame_compact(frame)}[/dim]")

    # ── Slash command dispatch ──

    async def dispatch(self, line: str) -> bool:
        """Run a slash command. Returns True to keep the loop, False to quit."""
        parts = line.strip().split()
        if not parts:
            return True
        cmd, *args = parts
        cmd = cmd.lower().lstrip("/")
        method = getattr(self, f"cmd_{cmd}", None)
        if method is None:
            self.console.print(f"  [yellow]unknown command:[/yellow] /{cmd}  "
                               f"(try [bold]/help[/bold])")
            return True
        try:
            return await method(args)
        except Exception as e:
            self.console.print(f"  [red]error in /{cmd}:[/red] {e}")
            return True

    # ── Commands ──

    async def cmd_help(self, _args: list[str]) -> bool:
        from rich.table import Table
        intro = ("[dim]Type a plain message to chat with AXIOMA. "
                 "Lines starting with [bold]/[/bold] are commands.[/dim]")
        self.console.print(intro)
        t = Table(show_header=True, header_style="bold", title="Commands",
                  title_justify="left")
        t.add_column("Command", style="cyan", no_wrap=True)
        t.add_column("Description")
        rows = [
            ("/help",                    "list commands"),
            ("/quit, /exit, /q",         "exit"),
            ("/clear",                   "clear the screen"),
            ("/history",                 "show this session's conversation transcript"),
            ("/status",                  "pretty-print key vitals from /status"),
            ("/health",                  "pretty-print /health"),
            ("/perturb KIND [MAG] [TAG]", "POST /admin/perturb  (KIND ∈ contradiction|"
                                          "impulse|step|novelty|attention|noise_burst; "
                                          "MAG default 0.5)"),
            ("/force STAGE",             "POST /admin/recovery/force  (STAGE ∈ 2,3,4)"),
            ("/sub CHANNEL [...]",       "subscribe to one or more channels"),
            ("/unsub CHANNEL [...]",     "unsubscribe (refuses to unsub `conversation`)"),
            ("/channels",                "list current subscriptions + per-channel frame counts"),
            ("/watch CHANNEL [SECONDS]", "stream frames from a channel until Ctrl-C or "
                                         "SECONDS elapse"),
            ("/admin-key KEY",           "set/update the admin bearer token in this session"),
            ("/timeout SECONDS",         "set per-message reply timeout (default: OLLAMA_TIMEOUT or 120)"),
            ("/speaker NAME",            "informational: requires reconnect"),
        ]
        for cmd, desc in rows:
            t.add_row(cmd, desc)
        self.console.print(t)
        self.console.print(
            "[dim]Subscribed-channel frames (after /sub) print between turns. "
            "The conversation channel is always subscribed.[/dim]"
        )
        return True

    async def cmd_quit(self, _args: list[str]) -> bool:
        return False
    cmd_exit = cmd_quit
    cmd_q = cmd_quit

    async def cmd_clear(self, _args: list[str]) -> bool:
        self.console.clear()
        return True

    async def cmd_history(self, _args: list[str]) -> bool:
        from rich.markdown import Markdown
        from rich.panel import Panel
        if not self.transcript:
            self.console.print("  [dim](transcript is empty)[/dim]")
            return True
        for i, (role, content) in enumerate(self.transcript, 1):
            tag = f"#{i} {role}"
            if role == "axioma":
                self.console.print(Panel(Markdown(content), title=tag,
                                         border_style="cyan", title_align="left"))
            else:
                self.console.print(Panel(content, title=tag,
                                         border_style="green", title_align="left"))
        return True

    async def cmd_status(self, _args: list[str]) -> bool:
        d = await self._http_get("/status")
        data = (d or {}).get("data") or {}
        if not data:
            self.console.print(f"  [yellow]/status returned no data:[/yellow] {d}")
            return True
        from rich.table import Table
        t = Table(show_header=False, box=None, padding=(0, 2))
        t.add_column(style="bold dim")
        t.add_column()
        t.add_row("beat", str(data.get("beat_no")))
        t.add_row("zone", repr(data.get("zone")))
        t.add_row("cadence", repr(data.get("cadence")))
        t.add_row("theta_short", f"{data.get('theta_short'):.3f}"
                  if isinstance(data.get("theta_short"), (int, float)) else "n/a")
        t.add_row("theta_long", f"{data.get('theta_long'):.3f}"
                  if isinstance(data.get("theta_long"), (int, float)) else "n/a")
        t.add_row("psi", f"{data.get('psi'):.3f}"
                  if isinstance(data.get("psi"), (int, float)) else "n/a")
        t.add_row("aos_g.gap", f"{data.get('aos_g_gap'):.4f}"
                  if isinstance(data.get("aos_g_gap"), (int, float)) else "n/a")
        t.add_row("aos_g.alert", str(data.get("aos_g_alert")))
        t.add_row("fragmentation_stage", str(data.get("fragmentation_stage")))
        t.add_row("coherence_budget", f"{data.get('coherence_budget'):.3f}"
                  if isinstance(data.get("coherence_budget"), (int, float)) else "n/a")
        self.console.print(t)
        return True

    async def cmd_health(self, _args: list[str]) -> bool:
        d = await self._http_get("/health")
        if d is None:
            return True
        self.console.print(f"  status: [bold]{d.get('status')}[/bold]  "
                           f"shutting_down={d.get('shutting_down')}")
        comps = d.get("components", [])
        if comps:
            self.console.print(f"  components ({len(comps)}): {', '.join(comps)}")
        return True

    async def cmd_perturb(self, args: list[str]) -> bool:
        if not args:
            self.console.print("  usage: /perturb KIND [MAGNITUDE] [TAG]")
            return True
        kind = args[0]
        mag = float(args[1]) if len(args) >= 2 else 0.5
        tag = args[2] if len(args) >= 3 else "chat_cli"
        body = {"kind": kind, "magnitude": mag, "tag": tag}
        d = await self._http_post("/admin/perturb", body)
        if d is None:
            return True
        self.console.print(f"  [green]perturb[/green] sent: {body}")
        self.console.print(f"  response: {d}")
        return True

    async def cmd_force(self, args: list[str]) -> bool:
        if not args:
            self.console.print("  usage: /force STAGE  (stage is 2, 3, or 4)")
            return True
        try:
            stage = int(args[0])
        except ValueError:
            self.console.print(f"  [red]invalid stage:[/red] {args[0]}")
            return True
        d = await self._http_post("/admin/recovery/force",
                                  {"stage": stage, "force": True})
        if d is None:
            return True
        self.console.print(f"  [green]force-recovery[/green] sent: stage={stage}")
        self.console.print(f"  response: {d}")
        return True

    async def cmd_sub(self, args: list[str]) -> bool:
        if not args:
            self.console.print("  usage: /sub CHANNEL [CHANNEL ...]")
            return True
        valid = [c for c in args if c in KNOWN_CHANNELS]
        invalid = [c for c in args if c not in KNOWN_CHANNELS]
        if invalid:
            self.console.print(f"  [yellow]unknown channels (ignored):[/yellow] {invalid}")
            self.console.print(f"  [dim]known: {sorted(KNOWN_CHANNELS)}[/dim]")
        if valid:
            if not await self._send_safe({"type": "subscribe", "channels": valid}):
                return True
            self.user_subs.update(valid)
            self.console.print(f"  subscribed: {valid}")
        return True

    async def cmd_unsub(self, args: list[str]) -> bool:
        if not args:
            self.console.print("  usage: /unsub CHANNEL [CHANNEL ...]")
            return True
        # Never let the user unsubscribe from `conversation` — they'd never see
        # AXIOMA's replies again.
        targets = [c for c in args if c != "conversation"]
        if not await self._send_safe({"type": "unsubscribe", "channels": targets}):
            return True
        for c in targets:
            self.user_subs.discard(c)
        self.console.print(f"  unsubscribed: {targets}")
        if "conversation" in args:
            self.console.print("  [yellow]note: refused to unsub `conversation` "
                               "(you'd never see replies)[/yellow]")
        return True

    async def cmd_channels(self, _args: list[str]) -> bool:
        from rich.table import Table
        t = Table(show_header=True, header_style="bold")
        t.add_column("channel")
        t.add_column("status")
        t.add_column("frames", justify="right")
        all_subs = {"conversation"} | self.user_subs
        for ch in sorted(all_subs | set(self._channel_counts.keys())):
            status = "subscribed" if ch in all_subs else "(not subscribed)"
            t.add_row(ch, status, str(self._channel_counts.get(ch, 0)))
        self.console.print(t)
        return True

    async def cmd_watch(self, args: list[str]) -> bool:
        if not args:
            self.console.print("  usage: /watch CHANNEL [SECONDS]")
            return True
        ch = args[0]
        if ch not in KNOWN_CHANNELS:
            self.console.print(f"  [yellow]unknown channel:[/yellow] {ch}")
            return True
        seconds = float(args[1]) if len(args) >= 2 else None
        # Auto-subscribe if needed
        added = ch not in self.user_subs and ch != "conversation"
        if added:
            if not await self._send_safe({"type": "subscribe", "channels": [ch]}):
                return True
            self.user_subs.add(ch)
        deadline = (time.time() + seconds) if seconds is not None else None
        suffix = f" for {seconds}s" if seconds else " (Ctrl-C to stop)"
        # Use escape() so a channel name like "theta" isn't interpreted as a
        # rich style tag (it would silently consume "[theta]").
        from rich.markup import escape
        self.console.print(f"  [bold]watching[/bold] {escape(f'[{ch}]')}{suffix}")
        try:
            while True:
                if deadline is not None and time.time() >= deadline:
                    self.console.print(f"  [dim]({seconds}s elapsed)[/dim]")
                    break
                try:
                    remaining = (deadline - time.time()) if deadline else 1.0
                    frame = await asyncio.wait_for(self.frames.get(),
                                                   timeout=max(0.1, remaining))
                except TimeoutError:
                    continue
                fch = frame.get("channel")
                if fch == ch:
                    self.console.print(f"  {_format_frame_compact(frame)}")
                elif fch in self.user_subs:
                    # Other subscribed channels — show but dimmer
                    self.console.print(f"  [dim]{_format_frame_compact(frame)}[/dim]")
        except KeyboardInterrupt:
            self.console.print("  [dim](watch stopped)[/dim]")
        if added:
            # Leave the subscription on — user might want it. Print a note.
            self.console.print(f"  [dim](still subscribed to {ch}; "
                               f"/unsub {ch} to stop receiving)[/dim]")
        return True

    async def cmd_admin_key(self, args: list[str]) -> bool:
        if not args:
            present = "(set)" if self.admin_key else "(not set)"
            self.console.print(f"  current admin key: {present}")
            self.console.print("  usage: /admin-key KEY  (or /admin-key '' to clear)")
            return True
        self.admin_key = args[0] if args[0] else None
        self.console.print(f"  admin key {'set' if self.admin_key else 'cleared'}")
        return True

    async def cmd_timeout(self, args: list[str]) -> bool:
        if not args:
            self.console.print(f"  current reply timeout: {self.reply_timeout}s")
            return True
        try:
            self.reply_timeout = max(1.0, float(args[0]))
            self.console.print(f"  reply timeout set to {self.reply_timeout}s")
        except ValueError:
            self.console.print(f"  [red]invalid timeout:[/red] {args[0]}")
        return True

    async def cmd_speaker(self, args: list[str]) -> bool:
        if not args:
            self.console.print(f"  current speaker: {self.speaker}")
            self.console.print("  usage: /speaker NAME  (note: requires "
                               "reconnect to take effect; restart this CLI with "
                               "--speaker NAME)")
            return True
        new = args[0]
        self.console.print(f"  [yellow]note:[/yellow] WS handshake speaker is set "
                           f"once at connect time. To switch from "
                           f"[bold]{self.speaker}[/bold] to [bold]{new}[/bold], "
                           f"exit and restart with `--speaker {new}`.")
        return True

    # ── HTTP helpers ──

    async def _http_get(self, path: str) -> dict[str, Any] | None:
        try:
            import httpx
        except ImportError:
            self.console.print("  [red]httpx not installed[/red]")
            return None
        url = self.http_url.rstrip("/") + path
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url)
            if r.status_code >= 400:
                self.console.print(f"  [red]HTTP {r.status_code}[/red] {url}: {r.text[:200]}")
                return None
            return r.json()
        except Exception as e:
            self.console.print(f"  [red]GET {url} failed:[/red] {e}")
            return None

    async def _http_post(self, path: str, body: dict[str, Any]) -> dict[str, Any] | None:
        try:
            import httpx
        except ImportError:
            self.console.print("  [red]httpx not installed[/red]")
            return None
        url = self.http_url.rstrip("/") + path
        headers = {}
        if self.admin_key:
            headers["Authorization"] = f"Bearer {self.admin_key}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(url, json=body, headers=headers)
            if r.status_code == 401:
                self.console.print(
                    "  [yellow]401 unauthorized[/yellow] — set the admin key via "
                    "[bold]/admin-key KEY[/bold] or restart with [bold]--admin-key[/bold]"
                )
                return None
            if r.status_code >= 400:
                self.console.print(f"  [red]HTTP {r.status_code}[/red] {url}: {r.text[:200]}")
                return None
            return r.json()
        except Exception as e:
            self.console.print(f"  [red]POST {url} failed:[/red] {e}")
            return None


# ── Main loop ────────────────────────────────────────────────────────────


async def repl(client: ChatClient) -> int:
    """Main interaction loop."""
    client.console.print(
        "[dim]Type a message to chat with AXIOMA. "
        "Type [bold]/help[/bold] for commands. "
        "[bold]Ctrl-D[/bold] / [bold]/quit[/bold] to exit.[/dim]"
    )
    while True:
        # Exit cleanly if the server has closed the WS — every subsequent
        # send/recv would fail. Surface a clear message rather than looping
        # uselessly or crashing on the next ws.send.
        if client._connection_closed:
            client.console.print(
                "  [yellow]server connection is closed — exiting. "
                "Restart this CLI to reconnect.[/yellow]"
            )
            return 0
        # Drain any pending subscribed-channel frames between turns.
        await client.drain_subscribed_frames()
        try:
            # input() blocks; run it in a thread so the event loop keeps spinning.
            line = await asyncio.to_thread(input, "axioma> ")
        except (EOFError, KeyboardInterrupt):
            client.console.print()
            return 0
        line = line.strip()
        if not line:
            continue
        if line.startswith("/"):
            keep_going = await client.dispatch(line)
            if not keep_going:
                return 0
            continue
        # Plain chat
        try:
            await client.send_chat(line)
        except KeyboardInterrupt:
            client.console.print("  [yellow](interrupted waiting for reply)[/yellow]")


async def _async_main(args: argparse.Namespace) -> int:
    # Chat CLI uses AXIOMA's native handshake protocol on `/`, not the
    # WS_COMM_PROTO inter-agent endpoint (which lives at /ws/<speaker>).
    ws_url = f"ws://{args.host}:{args.ws_port}"
    http_url = f"http://{args.host}:{args.http_port}"
    client = ChatClient(
        ws_url=ws_url,
        http_url=http_url,
        speaker=args.speaker,
        admin_key=args.admin_key,
        reply_timeout=args.reply_timeout,
    )
    try:
        try:
            await client.start()
        except Exception as e:
            print(f"error: could not connect to {ws_url}: {e}", file=sys.stderr)
            print("hint: is AXIOMA running? try `./scripts/axioma_ctl.sh status`",
                  file=sys.stderr)
            return 2
        return await repl(client)
    finally:
        await client.close()


def _default_reply_timeout() -> float:
    """Default reply timeout: honour OLLAMA_TIMEOUT from env if set, else 120 s.

    AXIOMA's peer-conversation handler delegates to Ollama for reply
    generation; if the operator has set OLLAMA_TIMEOUT (typically because
    a thinking model needs minutes for hard prompts), the chat CLI should
    wait at least that long before reporting "no reply within Xs" — otherwise
    the client gives up while Ollama is still legitimately working.
    """
    import os
    raw = os.environ.get("OLLAMA_TIMEOUT", "").strip()
    if not raw:
        return 120.0
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 120.0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m axioma.tools.chat",
        description="Interactive chat + control CLI for a running AXIOMA. "
                    "Plain text = chat. Lines starting with `/` = commands.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--host", default="localhost",
                   help="host running AXIOMA (default: localhost)")
    p.add_argument("--ws-port", type=int, default=8820, help="WS port (default 8820)")
    p.add_argument("--http-port", type=int, default=8821, help="HTTP port (default 8821)")
    p.add_argument("--speaker", default="skye",
                   help="WS handshake speaker (lark|skye|thea|axioma|system|agent; "
                        "default: skye)")
    p.add_argument("--admin-key", default=None,
                   help="admin bearer token (or set later via /admin-key)")
    p.add_argument("--reply-timeout", type=float, default=_default_reply_timeout(),
                   help="how long to wait for AXIOMA's reply per chat message "
                        "(default: OLLAMA_TIMEOUT env var if set, else 120s)")
    args = p.parse_args(argv)
    try:
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
