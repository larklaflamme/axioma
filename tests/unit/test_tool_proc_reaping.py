"""Tool-subprocess reaping — runaway children must not leak.

These guard the fix for the production incident where peer-conversation
`python_exec` jobs orphaned (reparented to init) and ran for days at 100% CPU,
saturating the host. `_proc.kill_process_tree` must reap the whole process group
(not just the direct child), and subprocesses launch in their own session so the
group kill works.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import sys

import pytest

from axioma.self_expansion.pre_built._proc import PREEXEC, kill_process_tree

pytestmark = pytest.mark.skipif(
    not (os.name == "posix" and sys.platform.startswith("linux")),
    reason="process-group reaping is Linux-specific",
)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@pytest.mark.asyncio
async def test_kill_process_tree_reaps_grandchildren() -> None:
    # bash backgrounds a long sleep (a grandchild), prints its PID, then waits.
    proc = await asyncio.create_subprocess_exec(
        "bash", "-c", "sleep 60 & echo $!; wait",
        stdout=asyncio.subprocess.PIPE,
        preexec_fn=PREEXEC,
    )
    try:
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
        child_pid = int(line.strip())
        assert _alive(child_pid), "backgrounded child should be running"

        kill_process_tree(proc)
        # Give the kernel a moment to deliver SIGKILL to the whole group.
        for _ in range(50):
            if not _alive(child_pid) and not _alive(proc.pid):
                break
            await asyncio.sleep(0.05)

        assert not _alive(child_pid), (
            "process-group kill must reap the grandchild — a plain proc.kill() "
            "would leave it orphaned (the production leak)"
        )
        assert not _alive(proc.pid)
    finally:
        kill_process_tree(proc)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=2.0)  # reap the zombie


@pytest.mark.asyncio
async def test_python_exec_timeout_kills_subprocess() -> None:
    from axioma.self_expansion.pre_built.python_exec import PythonExecServer

    server = PythonExecServer()
    # A CPU/sleep job that far outlives the timeout.
    result = await server._dispatch(  # type: ignore[attr-defined]
        "python_exec",
        {"code": "import time\nwhile True: time.sleep(1)", "timeout_seconds": 0.5},
    )
    import json
    payload = json.loads(result[0].text)
    assert payload.get("timed_out") is True
    assert payload.get("exit_code") is None
