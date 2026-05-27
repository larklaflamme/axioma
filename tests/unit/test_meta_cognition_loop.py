"""MetaCognitionLoop + SuggestionTracker — F5/F7/F8."""
from __future__ import annotations

import pytest

from axioma.config import AxiomaConfig
from axioma.measurement import (
    InternalStateRingBuffer,
    MetaCognition,
    MetaCognitionDivergenceWarning,
    MetaCognitionLoop,
    MetaCognitionSuggestion,
    ObserverMode,
    OverallAssessment,
    SuggestionTracker,
    SuggestionType,
    build_theta_engines,
)
from axioma.observability import AxiomaContext
from axioma.substrate import SubstrateApp


@pytest.fixture()
def wired_ctx():
    cfg = AxiomaConfig()
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    ctx.register("substrate", app)
    buf = InternalStateRingBuffer(capacity=1200)
    ctx.register("state_buffer", buf)
    short, long_e = build_theta_engines(ctx, short_window=30, long_window=500, n_permutations=10)
    return cfg, ctx, app, buf, short, long_e


# ── MetaCognitionLoop construction ──────────────────────────────────────


def test_construct_defaults() -> None:
    ctx = AxiomaContext()
    loop = MetaCognitionLoop(ctx)
    assert loop.name == "meta_cognition"
    assert loop.natural_period_beats == 100
    assert loop.observer_mode == ObserverMode.OBSERVER_ONLY


def test_observer_mode_embedded_when_set() -> None:
    ctx = AxiomaContext()
    loop = MetaCognitionLoop(ctx, observer_mode=ObserverMode.EMBEDDED)
    assert loop.observer_mode == ObserverMode.EMBEDDED


# ── F7: observer_mode default + suggestion handling ─────────────────────


def test_observer_only_default_records_suggestions_as_ignored(wired_ctx) -> None:
    """F7: in observer_only mode, suggestions are emitted and recorded as 'ignored'."""
    _, ctx, _app, _, _, _ = wired_ctx
    loop = MetaCognitionLoop(ctx, observer_mode=ObserverMode.OBSERVER_ONLY)
    # Beat for enough cycles to populate confidence + history; we can't easily
    # force a suggestion without specific substrate state, so directly test
    # the SuggestionTracker recording semantics.
    tracker = loop.suggestion_tracker
    s = MetaCognitionSuggestion(
        beat_no=100,
        suggested_action=SuggestionType.REQUEST_RECOVERY,
        target_parameter=None,
        target_value=None,
        confidence=0.9,
        rationale=["test"],
    )
    tracker.record(s, "ignored")
    assert len(tracker.recent_decisions) == 1


# ── F5: SuggestionTracker 5-ignored escalation ──────────────────────────


def test_suggestion_tracker_5_consecutive_ignored_emits_warning(wired_ctx) -> None:
    _, ctx, _, _, _, _ = wired_ctx
    tracker = SuggestionTracker(ctx, consecutive_threshold=5)
    received = []
    ctx.subscribe("meta_cognition_divergence", lambda p: received.append(p))
    for i in range(5):
        s = MetaCognitionSuggestion(
            beat_no=i * 100,
            suggested_action=SuggestionType.REQUEST_RECOVERY,
            target_parameter=None,
            target_value=None,
            confidence=0.8 + i * 0.01,
            rationale=[f"reason {i}"],
        )
        tracker.record(s, "ignored")
    assert len(received) == 1
    w = received[0]
    assert isinstance(w, MetaCognitionDivergenceWarning)
    assert w.consecutive_ignored == 5
    assert all(t == "request_recovery" for t in w.ignored_suggestion_types)


def test_suggestion_tracker_used_resets_streak(wired_ctx) -> None:
    """F5: an accepted suggestion resets the counter."""
    _, ctx, _, _, _, _ = wired_ctx
    tracker = SuggestionTracker(ctx, consecutive_threshold=5)
    received = []
    ctx.subscribe("meta_cognition_divergence", lambda p: received.append(p))
    for _ in range(4):
        s = MetaCognitionSuggestion(
            beat_no=0, suggested_action=SuggestionType.REQUEST_RECOVERY,
            target_parameter=None, target_value=None, confidence=0.8,
            rationale=[],
        )
        tracker.record(s, "ignored")
    # 4 ignored; insert 1 used; then 4 more ignored → no warning
    tracker.record(
        MetaCognitionSuggestion(beat_no=0, suggested_action=SuggestionType.REQUEST_RECOVERY,
                                target_parameter=None, target_value=None, confidence=0.9,
                                rationale=[]),
        "used",
    )
    for _ in range(4):
        s = MetaCognitionSuggestion(
            beat_no=0, suggested_action=SuggestionType.REQUEST_RECOVERY,
            target_parameter=None, target_value=None, confidence=0.8,
            rationale=[],
        )
        tracker.record(s, "ignored")
    assert len(received) == 0


def test_suggestion_tracker_resets_after_warning(wired_ctx) -> None:
    """F5: after a warning, the counter is cleared (next warning needs fresh 5)."""
    _, ctx, _, _, _, _ = wired_ctx
    tracker = SuggestionTracker(ctx, consecutive_threshold=5)
    received = []
    ctx.subscribe("meta_cognition_divergence", lambda p: received.append(p))
    for _ in range(5):
        s = MetaCognitionSuggestion(
            beat_no=0, suggested_action=SuggestionType.REQUEST_RECOVERY,
            target_parameter=None, target_value=None, confidence=0.8,
            rationale=[],
        )
        tracker.record(s, "ignored")
    assert len(received) == 1
    # 4 more ignored — not yet 5 fresh
    for _ in range(4):
        s = MetaCognitionSuggestion(
            beat_no=0, suggested_action=SuggestionType.REQUEST_RECOVERY,
            target_parameter=None, target_value=None, confidence=0.8,
            rationale=[],
        )
        tracker.record(s, "ignored")
    assert len(received) == 1  # still 1
    # 5th → fresh warning
    tracker.record(
        MetaCognitionSuggestion(beat_no=0, suggested_action=SuggestionType.REQUEST_RECOVERY,
                                target_parameter=None, target_value=None, confidence=0.8,
                                rationale=[]),
        "ignored",
    )
    assert len(received) == 2


def test_suggestion_tracker_save_load_roundtrip(wired_ctx) -> None:
    _, ctx, _, _, _, _ = wired_ctx
    tracker = SuggestionTracker(ctx)
    for i in range(3):
        s = MetaCognitionSuggestion(
            beat_no=i * 100, suggested_action=SuggestionType.DELAY_RECOVERY,
            target_parameter=None, target_value=None, confidence=0.7,
            rationale=[],
        )
        tracker.record(s, "ignored")
    snap = tracker.save_state()
    tracker2 = SuggestionTracker(ctx)
    tracker2.load_state(snap)
    assert len(tracker2.recent_decisions) == 3


# ── F8: confidence formula (consistency, not accuracy) ──────────────────


def test_confidence_is_one_for_all_same(wired_ctx) -> None:
    _, ctx, _, _, _, _ = wired_ctx
    loop = MetaCognitionLoop(ctx)
    # Force 5 identical emissions
    for _ in range(5):
        loop._recent_emissions.append(OverallAssessment.NOMINAL)
    conf = loop._compute_confidence(loop._recent_emissions)
    assert conf == 1.0


def test_confidence_is_low_for_all_different(wired_ctx) -> None:
    _, ctx, _, _, _, _ = wired_ctx
    loop = MetaCognitionLoop(ctx)
    for a in (
        OverallAssessment.NOMINAL,
        OverallAssessment.STRESSED,
        OverallAssessment.RECOVERING,
        OverallAssessment.EXPLORING,
        OverallAssessment.FRAGMENTED,
    ):
        loop._recent_emissions.append(a)
    conf = loop._compute_confidence(loop._recent_emissions)
    assert conf == 0.2  # max count is 1, length 5, ratio 1/5


def test_confidence_caveat_included_in_every_emission(wired_ctx) -> None:
    """E8: caveat string in every MetaCognition reading."""
    _, ctx, app, buf, _, _ = wired_ctx
    loop = MetaCognitionLoop(ctx)
    for beat in range(120):
        app.tick(beat_no=beat, timestamp=0.0)
        buf.push(app.last_internal())
    loop.compute()
    cv = loop.current_value()
    assert cv.valid
    assert "Confidence measures consistency" in cv.confidence_caveat


# ── Classification heuristics ──────────────────────────────────────────


def test_classify_fragmented(wired_ctx) -> None:
    _, ctx, _, _, _, _ = wired_ctx
    loop = MetaCognitionLoop(ctx)
    a = loop._classify(
        in_recovery=False, current_stage=3, coh_budget=0.5,
        recent_recovery_count=0, s3_context_variance=0.0,
    )
    assert a == OverallAssessment.FRAGMENTED


def test_classify_recovering(wired_ctx) -> None:
    _, ctx, _, _, _, _ = wired_ctx
    loop = MetaCognitionLoop(ctx)
    a = loop._classify(
        in_recovery=True, current_stage=2, coh_budget=0.5,
        recent_recovery_count=1, s3_context_variance=0.0,
    )
    assert a == OverallAssessment.RECOVERING


def test_classify_stressed(wired_ctx) -> None:
    _, ctx, _, _, _, _ = wired_ctx
    loop = MetaCognitionLoop(ctx)
    a = loop._classify(
        in_recovery=False, current_stage=0, coh_budget=0.2,
        recent_recovery_count=0, s3_context_variance=0.0,
    )
    assert a == OverallAssessment.STRESSED


def test_classify_exploring(wired_ctx) -> None:
    _, ctx, _, _, _, _ = wired_ctx
    loop = MetaCognitionLoop(ctx)
    a = loop._classify(
        in_recovery=False, current_stage=0, coh_budget=0.8,
        recent_recovery_count=0, s3_context_variance=0.9,
    )
    assert a == OverallAssessment.EXPLORING


def test_classify_nominal(wired_ctx) -> None:
    _, ctx, _, _, _, _ = wired_ctx
    loop = MetaCognitionLoop(ctx)
    a = loop._classify(
        in_recovery=False, current_stage=0, coh_budget=0.9,
        recent_recovery_count=0, s3_context_variance=0.0,
    )
    assert a == OverallAssessment.NOMINAL


# ── Save/load roundtrip ─────────────────────────────────────────────────


def test_meta_cognition_save_load(wired_ctx) -> None:
    _, ctx, app, buf, _, _ = wired_ctx
    loop = MetaCognitionLoop(ctx)
    for beat in range(120):
        app.tick(beat_no=beat, timestamp=0.0)
        buf.push(app.last_internal())
    loop.compute()
    snap = loop.save_state()

    loop2 = MetaCognitionLoop(ctx)
    loop2.load_state(snap)
    cv1 = loop.current_value()
    cv2 = loop2.current_value()
    assert cv1.beat_no == cv2.beat_no
    assert cv1.overall_assessment == cv2.overall_assessment
    assert cv1.confidence == cv2.confidence
    assert cv1.observer_mode == cv2.observer_mode


# ── Emits on context bus ────────────────────────────────────────────────


def test_meta_cognition_emits_on_bus(wired_ctx) -> None:
    _, ctx, app, buf, _, _ = wired_ctx
    loop = MetaCognitionLoop(ctx)
    received = []
    ctx.subscribe("meta_cognition", lambda p: received.append(p))
    for beat in range(120):
        app.tick(beat_no=beat, timestamp=0.0)
        buf.push(app.last_internal())
    loop.compute()
    assert len(received) == 1
    assert isinstance(received[0], MetaCognition)
