"""Subprocess-lifetime helpers — keep tool subprocesses from leaking.

The tool executor (``python_exec`` / ``bash_exec``) launches subprocesses on
behalf of the agent. Two failure modes leak runaway processes that can saturate
the host:

  1. **Timed-out child with descendants.** Killing only the direct child orphans
     any grandchildren it spawned. We put each subprocess in its own session
     (process group) so a single ``killpg`` reaps the whole tree.

  2. **Agent dies before a long tool call finishes** (crash / restart /
     SIGKILL). The child reparents to ``init`` and runs forever, accumulating
     across restarts until the box is starved (the exact failure we observed:
     day-old ``python -c`` numpy jobs at 100% CPU). ``PR_SET_PDEATHSIG=SIGKILL``
     makes the kernel SIGKILL the child the moment the agent process dies — this
     works even on a hard crash, where no in-band asyncio timeout could fire.

Both are Linux-specific; elsewhere the helpers degrade to a plain single-process
kill and a no-op preexec.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import signal

_IS_LINUX = os.name == "posix" and hasattr(os, "setsid") and hasattr(os, "killpg")

try:  # libc for prctl(PR_SET_PDEATHSIG)
    import ctypes

    _libc: ctypes.CDLL | None = ctypes.CDLL("libc.so.6", use_errno=True)
except Exception:  # pragma: no cover - non-glibc / non-Linux
    _libc = None

_PR_SET_PDEATHSIG = 1


def _child_preexec() -> None:
    """Run in the forked child *before* exec. MUST stay tiny and lock-free
    (it executes between fork and exec in a possibly multi-threaded parent)."""
    # New session → child is its own process-group leader, so killpg(child_pid)
    # later reaps the whole subtree.
    with contextlib.suppress(OSError):
        os.setsid()
    # Kernel sends SIGKILL to this child if the parent (agent) dies first.
    if _libc is not None:
        _libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL)


# preexec_fn to hand to create_subprocess_exec (None on platforms without it).
PREEXEC = _child_preexec if _IS_LINUX else None


def kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """SIGKILL the subprocess and everything in its process group.

    Falls back to killing just the direct child if the group kill isn't
    available (non-Linux) or the group is already gone."""
    pid = proc.pid
    if pid is None:
        return
    if _IS_LINUX:
        try:
            os.killpg(pid, signal.SIGKILL)  # pgid == pid (child called setsid)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    with contextlib.suppress(ProcessLookupError):
        proc.kill()


__all__ = ["PREEXEC", "kill_process_tree"]
