"""Interactive REPL for the AXIOMA self-expansion tool executor.

Usage:
    python -m axioma.tools.shell                # boot with all pre-built tools
    python -m axioma.tools.shell --no-bash      # skip bash/python servers (read-only)
    python -m axioma.tools.shell --generated-dir custom/path

Type tool calls as: `<tool_name> <json args>` (the JSON is optional for
no-arg tools). Slash commands start with `/`:

  /help              list commands
  /tools             list available tools with descriptions
  /tool NAME         show the input schema for one tool
  /servers           list loaded servers (static + dynamic)
  /load PATH         hot-load a .py module from PATH
  /unload NAME       unload a dynamic module by name
  /reload NAME       unload + re-load a dynamic module
  /clear             clear the screen
  /quit              exit

Plain text without a leading `/` is parsed as `<tool_name> <args>` and
dispatched through the executor. Output is rendered via rich (markdown
for replies that look like markdown; pretty-printed JSON otherwise).

This is the demo + debug surface for self-expansion. Operators use it to
sanity-check that tools work end-to-end without booting the full
conversation handler.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import shlex
import sys
from pathlib import Path
from typing import Any


def _make_executor(
    project_root: Path,
    generated_dir: Path,
    enable_bash: bool,
    enable_web: bool,
    enable_wolfram: bool,
) -> Any:
    """Construct the ToolExecutor and register the pre-built static servers."""
    import os

    from axioma.self_expansion import ToolExecutor
    from axioma.self_expansion.pre_built import (
        BashExecServer,
        FileSystemServer,
        PythonExecServer,
        WebSearchServer,
        WolframServer,
    )

    ex = ToolExecutor(generated_dir=generated_dir)
    # File system: read everywhere under the project; write inside data/ + generated/
    read_roots = [project_root]
    write_roots = [
        project_root / "data",
        generated_dir,
        Path("/tmp"),  # convenient scratch for the REPL
    ]
    ex.register_server("filesystem",
                       FileSystemServer(read_roots=read_roots, write_roots=write_roots))
    if enable_bash:
        ex.register_server("bash", BashExecServer())
        ex.register_server("python_exec", PythonExecServer())
    if enable_web:
        ex.register_server("web_search", WebSearchServer(
            tavily_api_key=os.environ.get("TAVILY_API_KEY", ""),
            brave_api_key=os.environ.get("BRAVE_API_KEY", ""),
        ))
    if enable_wolfram:
        ex.register_server("wolfram", WolframServer(
            appid=os.environ.get("WOLFRAM_APPID", ""),
        ))
    # Restore any previously-loaded dynamic modules.
    ex.restore_from_registry()
    return ex


async def _async_main(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    generated_dir = Path(args.generated_dir).resolve()

    try:
        from rich.console import Console
        from rich.markdown import Markdown
        from rich.syntax import Syntax
        from rich.table import Table
    except ImportError:
        print("error: this tool requires `rich` (already an AXIOMA dep)",
              file=sys.stderr)
        return 2

    console = Console()
    console.print(
        f"[green]✓[/green] AXIOMA tool shell  "
        f"(project_root=[bold]{project_root}[/bold], "
        f"generated_dir=[bold]{generated_dir}[/bold])"
    )
    ex = _make_executor(
        project_root, generated_dir,
        enable_bash=not args.no_bash,
        enable_web=not args.no_web,
        enable_wolfram=not args.no_wolfram,
    )
    console.print(
        f"[dim]loaded {len(ex.server_names)} servers, "
        f"{len(ex.tool_names)} tools. Type [bold]/help[/bold] for commands, "
        f"[bold]/tools[/bold] for the tool list, [bold]/quit[/bold] to exit.[/dim]"
    )

    def _render(text: str) -> None:
        # Try JSON first, then markdown, then plain.
        stripped = text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                json.loads(stripped)
                console.print(Syntax(stripped, "json", theme="ansi_dark",
                                     word_wrap=True))
                return
            except json.JSONDecodeError:
                pass
        if any(stripped.startswith(p) for p in ("# ", "## ", "* ", "- ", "| ")):
            console.print(Markdown(text))
            return
        console.print(text)

    async def _exec_tool(line: str) -> None:
        # Split off the tool name; the rest is parsed as JSON or a single string.
        try:
            parts = shlex.split(line, posix=True)
        except ValueError as e:
            console.print(f"[red]parse error:[/red] {e}")
            return
        if not parts:
            return
        tool_name = parts[0]
        rest = line[len(tool_name):].strip()
        if not rest:
            tool_args: dict[str, Any] = {}
        else:
            try:
                parsed = json.loads(rest)
                if not isinstance(parsed, dict):
                    console.print(
                        "[red]tool args must be a JSON object[/red] "
                        f"(got {type(parsed).__name__}). Example: "
                        f"file_read {{\"path\": \"README.md\"}}"
                    )
                    return
                tool_args = parsed
            except json.JSONDecodeError as e:
                console.print(f"[red]JSON parse error:[/red] {e}")
                return
        result = await ex.execute_async(tool_name, tool_args)
        _render(result)

    def cmd_help() -> None:
        t = Table(show_header=True, header_style="bold", title="Commands",
                  title_justify="left")
        t.add_column("Command", style="cyan", no_wrap=True)
        t.add_column("Description")
        rows = [
            ("/help",        "list commands"),
            ("/tools",       "list available tools"),
            ("/tool NAME",   "show input schema for one tool"),
            ("/servers",     "list loaded servers (static + dynamic)"),
            ("/load PATH",   "hot-load a .py module"),
            ("/unload NAME", "unload a dynamic module by name"),
            ("/reload NAME", "reload a dynamic module by name"),
            ("/clear",       "clear the screen"),
            ("/quit",        "exit"),
        ]
        for cmd, desc in rows:
            t.add_row(cmd, desc)
        console.print(t)
        console.print(
            "[dim]Plain text (no leading /) is dispatched as "
            "[bold]<tool_name> <json args>[/bold]. Example: "
            "[bold]file_read {\"path\": \"README.md\"}[/bold][/dim]"
        )

    def cmd_tools() -> None:
        t = Table(show_header=True, header_style="bold", title="Tools",
                  title_justify="left")
        t.add_column("Name", style="cyan", no_wrap=True)
        t.add_column("Server", style="dim", no_wrap=True)
        t.add_column("Description")
        with ex._registry_lock:
            by_name = {td["name"]: td for td in ex._tools}
            tool_to_server = {tn: e.name for tn, e in ex._route.items()}
        for name in sorted(by_name):
            td = by_name[name]
            desc = (td.get("description") or "").split("\n")[0]
            if len(desc) > 80:
                desc = desc[:77] + "..."
            t.add_row(name, tool_to_server.get(name, "?"), desc)
        console.print(t)

    def cmd_tool(args: list[str]) -> None:
        if not args:
            console.print("usage: /tool NAME")
            return
        name = args[0]
        with ex._registry_lock:
            td = next((x for x in ex._tools if x["name"] == name), None)
        if td is None:
            console.print(f"[yellow]unknown tool:[/yellow] {name}")
            return
        console.print(f"[bold cyan]{name}[/bold cyan]")
        console.print(td.get("description") or "(no description)")
        console.print("\n[bold]input_schema:[/bold]")
        console.print(Syntax(
            json.dumps(td.get("input_schema") or {}, indent=2),
            "json", theme="ansi_dark",
        ))

    def cmd_servers() -> None:
        t = Table(show_header=True, header_style="bold", title="Servers",
                  title_justify="left")
        t.add_column("Name", style="cyan", no_wrap=True)
        t.add_column("Kind", no_wrap=True)
        t.add_column("Tools", justify="right")
        t.add_column("Source path", overflow="fold")
        with ex._registry_lock:
            for entry in ex._servers:
                kind = "dynamic" if entry.dynamic else "static"
                t.add_row(entry.name, kind, str(len(entry.tool_names)),
                          entry.source_path or "")
        console.print(t)

    def cmd_load(args: list[str]) -> None:
        if not args:
            console.print("usage: /load PATH")
            return
        path = Path(args[0]).expanduser().resolve()
        try:
            info = ex.load_module(path)
            console.print(f"[green]loaded[/green] {info['module_name']}: "
                          f"{', '.join(info['tools'])}")
        except Exception as e:
            console.print(f"[red]load failed:[/red] {e}")

    def cmd_unload(args: list[str]) -> None:
        if not args:
            console.print("usage: /unload MODULE_NAME")
            return
        try:
            info = ex.unload_module(args[0])
            console.print(f"[green]unloaded[/green] {info['module_name']}")
        except Exception as e:
            console.print(f"[red]unload failed:[/red] {e}")

    def cmd_reload(args: list[str]) -> None:
        if not args:
            console.print("usage: /reload MODULE_NAME")
            return
        try:
            info = ex.reload_module(args[0])
            console.print(f"[green]reloaded[/green] {info['module_name']}")
        except Exception as e:
            console.print(f"[red]reload failed:[/red] {e}")

    # ── Main REPL ──
    while True:
        try:
            line = await asyncio.to_thread(input, "tool> ")
        except (EOFError, KeyboardInterrupt):
            console.print()
            return 0
        line = line.strip()
        if not line:
            continue
        if line.startswith("/"):
            parts = line[1:].split()
            cmd = parts[0].lower()
            args_rest = parts[1:]
            if cmd in ("quit", "exit", "q"):
                return 0
            if cmd == "help":   cmd_help(); continue
            if cmd == "tools":  cmd_tools(); continue
            if cmd == "tool":   cmd_tool(args_rest); continue
            if cmd == "servers": cmd_servers(); continue
            if cmd == "load":   cmd_load(args_rest); continue
            if cmd == "unload": cmd_unload(args_rest); continue
            if cmd == "reload": cmd_reload(args_rest); continue
            if cmd == "clear":  console.clear(); continue
            console.print(f"[yellow]unknown command:[/yellow] /{cmd} "
                          "(try [bold]/help[/bold])")
            continue
        try:
            await _exec_tool(line)
        except KeyboardInterrupt:
            console.print("[yellow](interrupted)[/yellow]")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m axioma.tools.shell",
        description="Interactive REPL for AXIOMA's self-expansion tool executor.",
    )
    p.add_argument("--project-root", default=str(Path.cwd()),
                   help="Read-scope root for the filesystem server (default: cwd).")
    p.add_argument("--generated-dir", default="data/state/generated",
                   help="Directory for dynamic generated modules + registry.")
    p.add_argument("--no-bash", action="store_true",
                   help="Skip the bash + python_exec servers (read-only).")
    p.add_argument("--no-web", action="store_true",
                   help="Skip the web_search server (offline mode).")
    p.add_argument("--no-wolfram", action="store_true",
                   help="Skip the wolfram server.")
    args = p.parse_args(argv)
    try:
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(main())
