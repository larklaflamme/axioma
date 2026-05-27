"""structlog + prometheus + measure_engine helpers."""
from __future__ import annotations

from axioma.observability import (
    BEAT_DURATION_S,
    ENGINE_DURATION_S,
    PSI,
    THETA_SHORT,
    bind_beat,
    configure_logging,
    get_logger,
    measure_engine,
    unbind_beat,
)


def test_configure_logging_idempotent() -> None:
    configure_logging(level="INFO", json=True)
    configure_logging(level="DEBUG", json=False)  # ok to reconfigure


def test_get_logger_returns_bound_logger() -> None:
    log = get_logger("test")
    log.info("hello", x=1)  # no exception


def test_bind_unbind_beat() -> None:
    bind_beat(42)
    unbind_beat()
    # Re-binding after unbind is fine
    bind_beat(43)
    unbind_beat()


def test_beat_duration_histogram_records() -> None:
    before = _hist_count(BEAT_DURATION_S)
    with BEAT_DURATION_S.time():
        pass
    after = _hist_count(BEAT_DURATION_S)
    assert after == before + 1


def test_engine_duration_records_per_label() -> None:
    before = _hist_count_for(ENGINE_DURATION_S, "test_engine")
    with measure_engine("test_engine"):
        pass
    after = _hist_count_for(ENGINE_DURATION_S, "test_engine")
    assert after == before + 1


def test_gauges_settable() -> None:
    THETA_SHORT.set(1.234)
    PSI.set(0.789)
    assert THETA_SHORT._value.get() == 1.234  # type: ignore[attr-defined]


def _hist_count(hist) -> float:  # type: ignore[no-untyped-def]
    """Sum the `_count` sample across all samples (unlabeled hist)."""
    metric = next(iter(hist.collect()))
    return sum(s.value for s in metric.samples if s.name.endswith("_count"))


def _hist_count_for(hist, label_value: str) -> float:  # type: ignore[no-untyped-def]
    metric = next(iter(hist.collect()))
    return sum(
        s.value
        for s in metric.samples
        if s.name.endswith("_count") and label_value in s.labels.values()
    )
