"""Integration harness: launch a real Agora server for AgoraBridge tests.

Mirrors the reference client's harness (agora/clients/tests/conftest.py): start
`agora.py` as a subprocess on a free port with a fresh temp DB, wait for liveness,
then set a known password for the citizens we drive (so we skip the first-login
gate). The bridge/client side runs in-process under the axioma env (httpx +
websockets); the server side needs fastapi/uvicorn/pyjwt, which live in the
sibling `agora` conda env — so we launch it with that interpreter.

Everything self-skips if the agora repo or a server-capable interpreter is
absent, keeping the suite green wherever the hub isn't available.
"""
from __future__ import annotations

import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

AGORA_REPO = Path(os.environ.get("AGORA_REPO", "/home/ubuntu/agora"))
TEST_PW = "agora-test-pw"
# Citizens this suite drives (must exist in the Agora seed set).
HANDLES = ["axioma", "thea"]

# Candidate interpreters that can run agora.py (need fastapi/uvicorn/jwt/bcrypt).
_PY_CANDIDATES = [
    "/home/ubuntu/miniconda3/envs/agora/bin/python",
    sys.executable,
]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _server_python() -> str | None:
    """First interpreter that can import the Agora server deps, or None."""
    probe = "import fastapi, uvicorn, jwt, bcrypt"
    for py in _PY_CANDIDATES:
        if not Path(py).exists():
            continue
        try:
            r = subprocess.run([py, "-c", probe], capture_output=True, timeout=30)
            if r.returncode == 0:
                return py
        except Exception:
            continue
    return None


@pytest.fixture(scope="session")
def agora_server(tmp_path_factory) -> dict:
    bcrypt = pytest.importorskip("bcrypt")  # client-side seeding of password hashes
    agora_py = AGORA_REPO / "agora.py"
    if not agora_py.exists():
        pytest.skip(f"Agora repo not found at {AGORA_REPO}")
    py = _server_python()
    if py is None:
        pytest.skip("no interpreter can run the Agora server (need fastapi/uvicorn/pyjwt)")

    import httpx

    port = _free_port()
    db_path = str(tmp_path_factory.mktemp("agora-it") / "it.db")
    env = {**os.environ,
           "AGORA_PORT": str(port),
           "DB_PATH": db_path,
           "JWT_SECRET": "axioma-integration-secret-0123456789abcdef"}
    proc = subprocess.Popen([py, "agora.py"], cwd=str(AGORA_REPO), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 25
        ok = False
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("agora.py exited during startup")
            try:
                if httpx.get(base + "/api/health", timeout=1).status_code == 200:
                    ok = True
                    break
            except Exception:
                pass
            time.sleep(0.2)
        if not ok:
            raise RuntimeError("Agora server did not become healthy")

        # Set a known password + clear the first-login gate for our citizens.
        digest = bcrypt.hashpw(TEST_PW.encode(), bcrypt.gensalt()).decode()
        con = sqlite3.connect(db_path)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(
            "UPDATE citizens SET password_hash=?, salt='', must_change_password=0 "
            "WHERE citizen_id IN (?, ?)",
            (digest, *HANDLES),
        )
        con.commit()
        con.close()

        yield {"base": base, "password": TEST_PW, "handles": HANDLES}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
