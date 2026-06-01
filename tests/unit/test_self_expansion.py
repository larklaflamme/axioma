"""Tests for axioma.self_expansion: validator, tool executor, pre-built tools."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from axioma.self_expansion import (
    USING_MCP,
    TextContent,
    Tool,
    ToolExecutor,
    validate,
    validate_static,
)
from axioma.self_expansion.pre_built import (
    BashExecServer,
    FileSystemServer,
    PythonExecServer,
)

# ── Types shim ────────────────────────────────────────────────────────


def test_tool_shim_has_required_fields() -> None:
    """The MCP-shim (or real MCP type) supports name+description+inputSchema."""
    t = Tool(name="x", description="d", inputSchema={"type": "object"})
    assert t.name == "x"
    assert t.description == "d"
    assert t.inputSchema == {"type": "object"}


def test_text_content_shim() -> None:
    tc = TextContent(type="text", text="hello")
    assert tc.text == "hello"
    assert tc.type == "text"


def test_using_mcp_flag_is_bool() -> None:
    assert isinstance(USING_MCP, bool)


# ── Validator stage 1 ─────────────────────────────────────────────────


_VALID_MODULE = '''
from axioma.self_expansion.types import Tool, TextContent

class GeneratedServer:
    ALL_TOOLS = [Tool(name="echo", description="d", inputSchema={"type": "object"})]
    def __init__(self) -> None:
        pass
    async def _dispatch(self, name: str, args: dict):
        if name == "echo":
            return [TextContent(type="text", text=str(args))]
        return [TextContent(type="text", text=f"[ERROR] unknown {name}")]
'''


def test_validate_accepts_well_formed_module() -> None:
    r = validate(_VALID_MODULE, "ok.py")
    assert r.ok
    assert r.stage == 3
    assert r.tools == ["echo"]


def test_validate_static_accepts_well_formed_module() -> None:
    r = validate_static(_VALID_MODULE, "ok.py")
    assert r.ok
    assert r.stage == 2


def test_validate_rejects_syntax_error() -> None:
    r = validate("def x(:\n  pass", "bad.py")
    assert not r.ok
    assert r.stage == 1
    assert "SyntaxError" in r.error


def test_validate_rejects_too_large() -> None:
    big = "x = 1\n" * 20000  # ~120 KB
    r = validate(big, "big.py")
    assert not r.ok
    assert r.stage == 1
    assert "exceeds" in r.error


def test_validate_rejects_forbidden_subprocess_import() -> None:
    src = "import subprocess\n" + _VALID_MODULE
    r = validate(src, "x.py")
    assert not r.ok
    assert r.stage == 2
    assert "subprocess" in r.error


def test_validate_rejects_forbidden_eval_call() -> None:
    src = _VALID_MODULE + "\ndef bad():\n    eval('1+1')\n"
    r = validate(src, "x.py")
    assert not r.ok
    assert r.stage == 2
    assert "eval" in r.error


def test_validate_rejects_forbidden_os_system() -> None:
    src = _VALID_MODULE + "\nimport os\ndef bad():\n    os.system('echo')\n"
    r = validate(src, "x.py")
    assert not r.ok
    assert r.stage == 2
    assert "os.system" in r.error


def test_validate_requires_generated_server_class() -> None:
    src = (
        "from axioma.self_expansion.types import Tool, TextContent\n"
        "class NotGeneratedServer:\n"
        "    ALL_TOOLS = []\n"
        "    def __init__(self): pass\n"
        "    async def _dispatch(self, n, a): return []\n"
    )
    r = validate_static(src, "x.py")
    assert not r.ok
    assert "GeneratedServer" in r.error


def test_validate_requires_all_tools() -> None:
    src = (
        "class GeneratedServer:\n"
        "    def __init__(self): pass\n"
        "    async def _dispatch(self, n, a): return []\n"
    )
    r = validate_static(src, "x.py")
    assert not r.ok
    assert "ALL_TOOLS" in r.error


def test_validate_requires_dispatch_async() -> None:
    src = (
        "from axioma.self_expansion.types import Tool\n"
        "class GeneratedServer:\n"
        "    ALL_TOOLS = [Tool(name='x', description='d', inputSchema={})]\n"
        "    def __init__(self): pass\n"
        "    def _dispatch(self, n, a): return []\n"  # sync, not async
    )
    r = validate_static(src, "x.py")
    assert not r.ok
    assert "async" in r.error


def test_validate_requires_init() -> None:
    src = (
        "from axioma.self_expansion.types import Tool\n"
        "class GeneratedServer:\n"
        "    ALL_TOOLS = [Tool(name='x', description='d', inputSchema={})]\n"
        "    async def _dispatch(self, n, a): return []\n"
    )
    r = validate_static(src, "x.py")
    assert not r.ok
    assert "__init__" in r.error


# ── Executor: registration + routing ───────────────────────────────────


class _StubServer:
    ALL_TOOLS = [
        Tool(name="add", description="add a+b", inputSchema={"type": "object"}),
        Tool(name="echo", description="echo msg", inputSchema={"type": "object"}),
    ]

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def _dispatch(self, name: str, args: dict):
        self.calls.append((name, args))
        if name == "add":
            return [TextContent(type="text", text=str(args["a"] + args["b"]))]
        if name == "echo":
            return [TextContent(type="text", text=str(args["msg"]))]
        return [TextContent(type="text", text=f"[ERROR] unknown: {name}")]


def test_executor_register_and_route(tmp_path: Path) -> None:
    ex = ToolExecutor(generated_dir=tmp_path)
    s = _StubServer()
    ex.register_server("stub", s)
    assert "add" in ex.tool_names
    assert "echo" in ex.tool_names
    assert len(ex.tools) == 2


def test_executor_rejects_server_without_all_tools(tmp_path: Path) -> None:
    class BadServer:
        async def _dispatch(self, n, a): return []
    ex = ToolExecutor(generated_dir=tmp_path)
    with pytest.raises(ValueError, match="ALL_TOOLS"):
        ex.register_server("bad", BadServer())


def test_executor_rejects_server_without_dispatch(tmp_path: Path) -> None:
    class BadServer:
        ALL_TOOLS = []
    ex = ToolExecutor(generated_dir=tmp_path)
    with pytest.raises(ValueError, match="_dispatch"):
        ex.register_server("bad", BadServer())


@pytest.mark.asyncio
async def test_executor_execute_async_routes_call(tmp_path: Path) -> None:
    ex = ToolExecutor(generated_dir=tmp_path)
    s = _StubServer()
    ex.register_server("stub", s)
    result = await ex.execute_async("add", {"a": 2, "b": 3})
    assert result == "5"
    assert s.calls == [("add", {"a": 2, "b": 3})]


@pytest.mark.asyncio
async def test_executor_unknown_tool_returns_friendly_error(tmp_path: Path) -> None:
    ex = ToolExecutor(generated_dir=tmp_path)
    ex.register_server("stub", _StubServer())
    out = await ex.execute_async("nonexistent", {})
    assert "[Unknown tool: nonexistent" in out
    assert "Available: add, echo" in out


def test_executor_sync_execute_works_outside_loop(tmp_path: Path) -> None:
    ex = ToolExecutor(generated_dir=tmp_path)
    ex.register_server("stub", _StubServer())
    result = ex.execute("echo", {"msg": "hi"})
    assert result == "hi"


def test_executor_collision_evicts_previous(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Two servers registering the same tool name — second wins, first's def evicted."""
    ex = ToolExecutor(generated_dir=tmp_path)
    ex.register_server("first", _StubServer())
    ex.register_server("second", _StubServer())
    # `add` exists in both; route points to the latest, tools list deduped.
    names = [t["name"] for t in ex.tools]
    assert names.count("add") == 1
    assert names.count("echo") == 1


# ── Executor: hot-load ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_executor_load_module_and_call(tmp_path: Path) -> None:
    """Write a valid module to disk, hot-load it, call its tool."""
    mod_path = tmp_path / "echo_tool.py"
    mod_path.write_text(_VALID_MODULE)
    ex = ToolExecutor(generated_dir=tmp_path)
    info = ex.load_module(mod_path)
    assert info["status"] == "active"
    assert info["tools"] == ["echo"]
    assert info["module_name"].startswith("axioma_dynamic_echo_tool_")
    # Tool is callable
    result = await ex.execute_async("echo", {"hello": "world"})
    assert "hello" in result and "world" in result


def test_executor_load_module_writes_registry(tmp_path: Path) -> None:
    mod_path = tmp_path / "echo_tool.py"
    mod_path.write_text(_VALID_MODULE)
    ex = ToolExecutor(generated_dir=tmp_path)
    ex.load_module(mod_path)
    registry = json.loads((tmp_path / "dynamic_registry.json").read_text())
    assert len(registry["loaded"]) == 1
    assert registry["loaded"][0]["status"] == "active"


def test_executor_load_module_idempotent(tmp_path: Path) -> None:
    mod_path = tmp_path / "echo_tool.py"
    mod_path.write_text(_VALID_MODULE)
    ex = ToolExecutor(generated_dir=tmp_path)
    info1 = ex.load_module(mod_path)
    info2 = ex.load_module(mod_path)
    # Same module_name returned, no double-registration
    assert info1["module_name"] == info2["module_name"]
    assert len([s for s in ex.server_names
                if s.startswith("axioma_dynamic_echo_tool_")]) == 1


def test_executor_load_module_rejects_invalid(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("import subprocess\n")
    ex = ToolExecutor(generated_dir=tmp_path)
    with pytest.raises(ValueError, match="Validation failed"):
        ex.load_module(bad)


def test_executor_unload_module(tmp_path: Path) -> None:
    mod_path = tmp_path / "echo_tool.py"
    mod_path.write_text(_VALID_MODULE)
    ex = ToolExecutor(generated_dir=tmp_path)
    info = ex.load_module(mod_path)
    mod_name = info["module_name"]
    ex.unload_module(mod_name)
    # Tool gone from route + tools list
    assert "echo" not in ex.tool_names
    # Module gone from sys.modules
    assert mod_name not in sys.modules


def test_executor_reload_module_picks_up_source_change(tmp_path: Path) -> None:
    mod_path = tmp_path / "echo_tool.py"
    mod_path.write_text(_VALID_MODULE)
    ex = ToolExecutor(generated_dir=tmp_path)
    info = ex.load_module(mod_path)
    # Change source — add a new tool "shout"
    new_src = _VALID_MODULE.replace(
        'ALL_TOOLS = [Tool(name="echo", description="d", inputSchema={"type": "object"})]',
        'ALL_TOOLS = [Tool(name="echo", description="d", inputSchema={"type": "object"}), '
        'Tool(name="shout", description="s", inputSchema={"type": "object"})]'
    ).replace(
        'if name == "echo":\n            return [TextContent(type="text", text=str(args))]',
        'if name == "echo":\n            return [TextContent(type="text", text=str(args))]\n'
        '        if name == "shout":\n            return [TextContent(type="text", text=str(args).upper())]'
    )
    mod_path.write_text(new_src)
    ex.reload_module(info["module_name"])
    assert "shout" in ex.tool_names


def test_executor_restore_from_registry(tmp_path: Path) -> None:
    """Two executors back-to-back: second one restores what the first loaded."""
    mod_path = tmp_path / "echo_tool.py"
    mod_path.write_text(_VALID_MODULE)
    ex1 = ToolExecutor(generated_dir=tmp_path)
    ex1.load_module(mod_path)
    # Second executor (fresh state) restores from the persisted registry
    ex2 = ToolExecutor(generated_dir=tmp_path)
    n = ex2.restore_from_registry()
    assert n == 1
    assert "echo" in ex2.tool_names


# ── FileSystemServer ────────────────────────────────────────────────────


def _fs_server(tmp_path: Path) -> FileSystemServer:
    return FileSystemServer(read_roots=[tmp_path], write_roots=[tmp_path])


def _dispatch_sync(server, name: str, args: dict) -> str:
    """Helper: run async dispatch + join text blocks."""
    blocks = asyncio.run(server._dispatch(name, args))
    return "\n".join(b.text for b in blocks)


def test_fs_write_then_read(tmp_path: Path) -> None:
    fs = _fs_server(tmp_path)
    p = tmp_path / "x.txt"
    out = _dispatch_sync(fs, "file_write", {"path": str(p), "content": "hello"})
    assert "wrote" in out
    out = _dispatch_sync(fs, "file_read", {"path": str(p)})
    assert out == "hello"


def test_fs_write_rejected_outside_write_scope(tmp_path: Path) -> None:
    # Write scope only includes a subdir
    sub = tmp_path / "inner"
    sub.mkdir()
    fs = FileSystemServer(read_roots=[tmp_path], write_roots=[sub])
    out_path = tmp_path / "outside.txt"
    out = _dispatch_sync(fs, "file_write", {"path": str(out_path), "content": "x"})
    assert "[ERROR]" in out
    assert "outside write scope" in out


def test_fs_read_rejected_outside_read_scope(tmp_path: Path) -> None:
    # /etc is universally not in scope
    fs = FileSystemServer(read_roots=[tmp_path])
    out = _dispatch_sync(fs, "file_read", {"path": "/etc/hostname"})
    assert "[ERROR]" in out


def test_fs_exists(tmp_path: Path) -> None:
    fs = _fs_server(tmp_path)
    p = tmp_path / "x.txt"
    out = _dispatch_sync(fs, "file_exists", {"path": str(p)})
    assert out == "false"
    p.write_text("hi")
    out = _dispatch_sync(fs, "file_exists", {"path": str(p)})
    assert out == "true"


def test_fs_list_lists_dir(tmp_path: Path) -> None:
    fs = _fs_server(tmp_path)
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    out = _dispatch_sync(fs, "file_list", {"path": str(tmp_path)})
    items = json.loads(out)
    names = sorted(i["name"] for i in items)
    assert "a.txt" in names
    assert "b.txt" in names


def test_fs_path_resolve_reports_scope(tmp_path: Path) -> None:
    fs = _fs_server(tmp_path)
    out = _dispatch_sync(fs, "path_resolve", {"path": str(tmp_path / "x.txt")})
    info = json.loads(out)
    assert info["in_read_scope"] is True
    assert info["in_write_scope"] is True


def test_fs_mkdir_then_delete_dir(tmp_path: Path) -> None:
    fs = _fs_server(tmp_path)
    d = tmp_path / "newdir"
    _dispatch_sync(fs, "file_mkdir", {"path": str(d)})
    assert d.is_dir()
    out = _dispatch_sync(fs, "file_delete", {"path": str(d)})
    info = json.loads(out)
    assert info["deleted"] is True
    assert not d.exists()


# ── BashExecServer ──────────────────────────────────────────────────────


def test_bash_exec_runs_command() -> None:
    b = BashExecServer()
    out = _dispatch_sync(b, "bash_exec", {"command": "echo hello"})
    info = json.loads(out)
    assert info["exit_code"] == 0
    assert "hello" in info["output"]
    assert info["truncated"] is False


def test_bash_exec_captures_nonzero_exit() -> None:
    b = BashExecServer()
    out = _dispatch_sync(b, "bash_exec", {"command": "exit 7"})
    info = json.loads(out)
    assert info["exit_code"] == 7


def test_bash_exec_times_out() -> None:
    b = BashExecServer(default_timeout_seconds=0.5)
    out = _dispatch_sync(b, "bash_exec", {"command": "sleep 5"})
    info = json.loads(out)
    assert info.get("timed_out") is True
    assert info["exit_code"] is None


def test_bash_exec_honours_cwd(tmp_path: Path) -> None:
    b = BashExecServer()
    out = _dispatch_sync(b, "bash_exec", {"command": "pwd", "cwd": str(tmp_path)})
    info = json.loads(out)
    assert str(tmp_path) in info["output"]


def test_bash_exec_env_overrides() -> None:
    b = BashExecServer()
    out = _dispatch_sync(b, "bash_exec",
                         {"command": "echo $AXIOMA_TEST_VAR",
                          "env": {"AXIOMA_TEST_VAR": "the-value"}})
    info = json.loads(out)
    assert "the-value" in info["output"]


def test_bash_which_finds_python() -> None:
    b = BashExecServer()
    out = _dispatch_sync(b, "bash_which", {"name": "python3"})
    assert out.startswith("/")


def test_bash_which_missing() -> None:
    b = BashExecServer()
    out = _dispatch_sync(b, "bash_which", {"name": "this-command-does-not-exist-xyz"})
    assert "[ERROR]" in out


def test_bash_env_redacts_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AXIOMA_TEST_API_KEY", "verysecret")
    monkeypatch.setenv("AXIOMA_TEST_NORMAL", "normal-val")
    b = BashExecServer()
    out = _dispatch_sync(b, "bash_env", {"filter_prefix": "AXIOMA_TEST_"})
    env = json.loads(out)
    assert env.get("AXIOMA_TEST_API_KEY") == "(redacted)"
    assert env.get("AXIOMA_TEST_NORMAL") == "normal-val"


# ── PythonExecServer ────────────────────────────────────────────────────


def test_python_exec_runs_code() -> None:
    p = PythonExecServer()
    out = _dispatch_sync(p, "python_exec", {"code": "print(2+3)"})
    info = json.loads(out)
    assert info["exit_code"] == 0
    assert "5" in info["stdout"]
    assert info["stderr"] == ""


def test_python_exec_captures_stderr_and_exit() -> None:
    p = PythonExecServer()
    out = _dispatch_sync(p, "python_exec",
                         {"code": "import sys; print('out'); print('err', file=sys.stderr); sys.exit(2)"})
    info = json.loads(out)
    assert info["exit_code"] == 2
    assert "out" in info["stdout"]
    assert "err" in info["stderr"]


def test_python_exec_times_out() -> None:
    p = PythonExecServer(default_timeout_seconds=0.5)
    out = _dispatch_sync(p, "python_exec", {"code": "import time; time.sleep(5)"})
    info = json.loads(out)
    assert info.get("timed_out") is True


def test_python_exec_stdin_pipe() -> None:
    p = PythonExecServer()
    out = _dispatch_sync(p, "python_exec",
                         {"code": "import sys; print(sys.stdin.read())",
                          "stdin": "hello-stdin"})
    info = json.loads(out)
    assert "hello-stdin" in info["stdout"]


def test_python_run_file(tmp_path: Path) -> None:
    p = PythonExecServer()
    script = tmp_path / "x.py"
    script.write_text("import sys; print('args=', sys.argv[1:])")
    out = _dispatch_sync(p, "python_run_file",
                         {"path": str(script), "args": ["a", "b"]})
    info = json.loads(out)
    assert info["exit_code"] == 0
    assert "['a', 'b']" in info["stdout"]


def test_python_version_reports_runtime() -> None:
    p = PythonExecServer()
    out = _dispatch_sync(p, "python_version", {})
    info = json.loads(out)
    assert info["version_info"][0] == sys.version_info[0]
    assert Path(info["executable"]).exists()


# ── Dispatch never raises ─────────────────────────────────────────────


def test_dispatch_never_raises_on_unknown_tool() -> None:
    """All pre-built servers swallow Exceptions and return _err()."""
    for server in (FileSystemServer(read_roots=[Path.cwd()]),
                   BashExecServer(), PythonExecServer()):
        out = _dispatch_sync(server, "definitely_not_a_tool", {})
        assert "[ERROR]" in out
