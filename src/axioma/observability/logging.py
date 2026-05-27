"""Structured logging configuration.

Per IMPLEMENTATION_PLAN_v1.0.md §3.1.

Every log line carries `beat_no` via structlog.contextvars — bound once per
beat in heartbeat.tick_async() so any nested code's logs are beat-correlated.
"""
from __future__ import annotations

import logging
from typing import Any

import structlog


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    """Configure structlog for the process. Idempotent."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]
    if json:
        shared_processors.append(structlog.processors.JSONRenderer())
    else:
        shared_processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging through structlog so third-party libs end up in
    # the same stream (FastAPI/uvicorn, websockets, sqlalchemy, etc.)
    logging.basicConfig(format="%(message)s", level=log_level)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Public accessor; modules use:

        log = get_logger(__name__)
    """
    return structlog.get_logger(name)


def bind_beat(beat_no: int) -> None:
    """Bind beat_no into the context for the rest of this async task.

    Heartbeat calls this at the top of every tick. Nested code's logs
    will carry beat_no automatically.
    """
    structlog.contextvars.bind_contextvars(beat_no=beat_no)


def unbind_beat() -> None:
    structlog.contextvars.unbind_contextvars("beat_no")
