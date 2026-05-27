"""Shared pytest fixtures for the AXIOMA test suite."""
from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest

from axioma.config import AxiomaConfig, load_config
from axioma.observability import AxiomaContext, configure_logging


@pytest.fixture(scope="session", autouse=True)
def _configure_logging() -> None:
    """Quiet console logging for tests; structlog → console (non-JSON)."""
    configure_logging(level="WARNING", json=False)


@pytest.fixture()
def fresh_ctx() -> AxiomaContext:
    """A fresh, empty AxiomaContext per test."""
    return AxiomaContext()


@pytest.fixture()
def default_cfg() -> AxiomaConfig:
    """Default AxiomaConfig (no YAML, no env overrides)."""
    return AxiomaConfig()


@pytest.fixture()
def loaded_cfg() -> AxiomaConfig:
    """Config loaded via load_config() (picks up default.yaml + env)."""
    return load_config()


@pytest.fixture()
def tmp_snapshot_root(tmp_path: Path) -> Path:
    """Per-test snapshot root inside pytest's tmp_path."""
    p = tmp_path / "state"
    p.mkdir()
    return p


@pytest.fixture()
def anyio_backend() -> str:
    """pytest-asyncio uses 'asyncio' backend by default."""
    return "asyncio"


# Make async tests work with the asyncio_mode=auto in pyproject.toml
@pytest.fixture(scope="session")
def event_loop_policy() -> Iterator[asyncio.AbstractEventLoopPolicy]:
    """Per-session event loop policy. Override if a test needs a custom policy."""
    yield asyncio.DefaultEventLoopPolicy()
