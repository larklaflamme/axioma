"""Wire protocol primitives (Speaker, Channel, envelope, error codes)."""
from __future__ import annotations

import json

from axioma.interface.protocol import (
    KNOWN_CHANNELS,
    Channel,
    ErrorCode,
    HandshakeRequest,
    Speaker,
    envelope,
    normalize_channel,
)


def test_speaker_axioma_present() -> None:
    assert Speaker.AXIOMA.value == "axioma"
    assert "axioma" in {s.value for s in Speaker}


def test_known_channels_complete() -> None:
    for c in Channel:
        assert c.value in KNOWN_CHANNELS


def test_normalize_channel_unknown_returns_none() -> None:
    assert normalize_channel("not_a_real_channel") is None
    assert normalize_channel(Channel.THETA.value) == Channel.THETA.value


def test_envelope_shape() -> None:
    env = envelope("theta", {"theta_short": 1.23}, beat_no=42)
    assert env["type"] == "channel"
    assert env["channel"] == "theta"
    assert env["beat_no"] == 42
    assert env["payload"] == {"theta_short": 1.23}
    # JSON-serializable
    s = json.dumps(env)
    assert "theta" in s


def test_handshake_request_fields() -> None:
    h = HandshakeRequest(speaker="skye", capabilities=["chat"], min_interval_ms=50)
    assert h.speaker == "skye"
    assert h.min_interval_ms == 50


def test_error_codes_unique_and_4xxx() -> None:
    codes = [
        ErrorCode.BAD_HANDSHAKE,
        ErrorCode.AUTH_INVALID,
        ErrorCode.UNKNOWN_CHANNEL,
        ErrorCode.RATE_LIMITED,
        ErrorCode.SLOW_CONSUMER,
        ErrorCode.SUBSTRATE_SHUTDOWN,
    ]
    assert len(codes) == len(set(codes))
    for c in codes:
        assert 4000 <= c < 5000
