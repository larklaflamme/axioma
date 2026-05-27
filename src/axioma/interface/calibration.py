"""Calibration session recorder — F6/F8 live operator labeling.

Per IMPLEMENTATION_PLAN_v1.0.md §10.4 (v1.1.5 enabler).

Live F6/F8 sessions work like this:
  1. Operator (Theoria for F6 zone validation, Skye for F8 meta-cog calibration)
     opens a session via POST /admin/calibration/session/start with
     {session_id, duration_minutes, task_type, kind: "zone"|"meta_cog"}.
  2. Operator subscribes to the relevant channels via WS (operator does NOT
     subscribe to `meta_cognition` for F8 — blind labeling).
  3. Every 100 beats (≈ 10 s), operator emits a label via POST /admin/calibration/label.
  4. CalibrationRecorder snaps the system's own value at the matched beat
     (system label) and stores the pair.
  5. At session end, POST /admin/calibration/session/end triggers comparison
     (Cohen's κ for F6, accuracy + miscalibration for F8) and writes the
     result JSON.

The recorder is in-memory (one active session per kind); persistent on disk
when end_session() is called.
"""
from __future__ import annotations

import json
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..observability import get_logger
from ..observability.context import AxiomaContext

log = get_logger(__name__)

SessionKind = Literal["zone", "meta_cog"]


@dataclass
class LabelPair:
    """A single operator label + the system's value at that beat."""

    beat_no: int
    operator_label: str
    system_label: str
    confidence: float | None = None  # system confidence (meta_cog only)


@dataclass
class CalibrationSession:
    """A running calibration session — open from start until end."""

    session_id: str
    kind: SessionKind
    task_type: str
    started_at: float
    duration_minutes: int
    started_at_beat: int
    pairs: list[LabelPair] = field(default_factory=list)


class CalibrationRecorder:
    """Records operator labels paired with the system's own value.

    One active session per kind (zone | meta_cog). The HTTP API holds the
    recorder; tests can instantiate it directly.

    Per IMPLEMENTATION_PLAN §10.4.
    """

    def __init__(
        self,
        ctx: AxiomaContext,
        *,
        results_root: Path | None = None,
    ) -> None:
        self.ctx = ctx
        self.results_root = results_root or Path("results/phase_f")
        self._active: dict[SessionKind, CalibrationSession] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start_session(
        self,
        *,
        kind: SessionKind,
        task_type: str,
        duration_minutes: int = 60,
        session_id: str | None = None,
    ) -> CalibrationSession:
        """Open a session. Raises if one is already active for the same kind."""
        if kind in self._active:
            raise RuntimeError(
                f"session already active for kind={kind}; "
                f"end it before starting another"
            )
        sid = session_id or f"{kind}-{uuid.uuid4().hex[:8]}"
        beat = self._current_beat()
        session = CalibrationSession(
            session_id=sid,
            kind=kind,
            task_type=task_type,
            started_at=time.time(),
            duration_minutes=duration_minutes,
            started_at_beat=beat,
        )
        self._active[kind] = session
        log.info(
            "calibration_session_started",
            session_id=sid, kind=kind, task_type=task_type,
            started_at_beat=beat, duration_minutes=duration_minutes,
        )
        return session

    def record_label(
        self,
        *,
        kind: SessionKind,
        beat_no: int,
        operator_label: str,
    ) -> LabelPair:
        """Pair the operator's label with the system's current value."""
        if kind not in self._active:
            raise RuntimeError(f"no active session for kind={kind}")
        session = self._active[kind]
        system_label, confidence = self._snap_system_value(kind)
        pair = LabelPair(
            beat_no=beat_no,
            operator_label=operator_label,
            system_label=system_label,
            confidence=confidence,
        )
        session.pairs.append(pair)
        log.debug(
            "calibration_label_recorded",
            session_id=session.session_id, beat_no=beat_no,
            operator=operator_label, system=system_label, confidence=confidence,
        )
        return pair

    def end_session(self, *, kind: SessionKind) -> dict[str, Any]:
        """Close the session; compute summary; write `calibration_session_<id>.json`."""
        if kind not in self._active:
            raise RuntimeError(f"no active session for kind={kind}")
        session = self._active.pop(kind)
        summary = self._summarize(session)
        self._write_to_disk(session, summary)
        log.info(
            "calibration_session_ended",
            session_id=session.session_id, kind=kind,
            n_pairs=len(session.pairs), summary_verdict=summary.get("verdict"),
        )
        return summary

    def get_active(self, kind: SessionKind) -> CalibrationSession | None:
        return self._active.get(kind)

    def list_active(self) -> list[CalibrationSession]:
        return list(self._active.values())

    # ── Snapshot system value (kind-specific) ─────────────────────────

    def _snap_system_value(self, kind: SessionKind) -> tuple[str, float | None]:
        """Return (system_label, optional_confidence) at this moment."""
        if kind == "zone":
            ext = self._latest_external()
            if ext is None:
                return ("unknown", None)
            zone = ext.zone.value if hasattr(ext.zone, "value") else str(ext.zone)
            return (zone, None)
        if kind == "meta_cog":
            if not self.ctx.has("meta_cognition_loop"):
                return ("unknown", None)
            loop = self.ctx.get("meta_cognition_loop")
            current = getattr(loop, "current", None) or getattr(loop, "latest", None)
            if current is None:
                return ("unknown", None)
            assessment = getattr(current, "overall_assessment", None)
            if assessment is None:
                return ("unknown", None)
            label = assessment.value if hasattr(assessment, "value") else str(assessment)
            confidence = float(getattr(current, "confidence", 0.0))
            return (label, confidence)
        return ("unknown", None)

    def _latest_external(self) -> Any | None:
        if not self.ctx.has("compose_function"):
            return None
        ext = getattr(self.ctx.get("compose_function"), "latest_external", None)
        return ext

    def _current_beat(self) -> int:
        if self.ctx.has("heartbeat"):
            return int(getattr(self.ctx.get("heartbeat"), "beat_no", 0))
        if self.ctx.has("substrate"):
            return int(getattr(self.ctx.get("substrate"), "beat_no", 0))
        return 0

    # ── Summarization ────────────────────────────────────────────────

    def _summarize(self, session: CalibrationSession) -> dict[str, Any]:
        """Compute kind-appropriate summary."""
        n = len(session.pairs)
        if n == 0:
            return {
                "session_id": session.session_id,
                "kind": session.kind,
                "task_type": session.task_type,
                "n_pairs": 0,
                "verdict": "INSUFFICIENT_DATA",
            }
        operator_labels = [p.operator_label for p in session.pairs]
        system_labels = [p.system_label for p in session.pairs]
        agreements = sum(
            1 for o, s in zip(operator_labels, system_labels, strict=True) if o == s
        )
        result: dict[str, Any] = {
            "session_id": session.session_id,
            "kind": session.kind,
            "task_type": session.task_type,
            "n_pairs": n,
            "agreements": agreements,
            "operator_distribution": dict(Counter(operator_labels)),
            "system_distribution": dict(Counter(system_labels)),
        }
        if session.kind == "zone":
            kappa = _cohens_kappa(operator_labels, system_labels)
            result["kappa"] = round(kappa, 3)
            # Per F6 acceptance: min κ across sessions ≥ 0.3
            result["verdict"] = (
                "PASS" if kappa >= 0.3
                else "SOFT_FAIL" if kappa >= 0.2
                else "HARD_FAIL"
            )
        elif session.kind == "meta_cog":
            # F8 calibration: accuracy + mean miscalibration
            accuracy_per = [1 if o == s else 0 for o, s in zip(operator_labels, system_labels, strict=True)]
            confidences = [p.confidence for p in session.pairs if p.confidence is not None]
            accuracy_rate = sum(accuracy_per) / n
            miscalibrations = [
                abs(p.confidence - (1 if p.operator_label == p.system_label else 0))
                for p in session.pairs if p.confidence is not None
            ]
            mean_miscalibration = (
                sum(miscalibrations) / len(miscalibrations) if miscalibrations else None
            )
            result["accuracy_rate"] = round(accuracy_rate, 3)
            result["mean_miscalibration"] = (
                round(mean_miscalibration, 3) if mean_miscalibration is not None else None
            )
            result["n_confidences"] = len(confidences)
            f8_v = (
                "PASS" if mean_miscalibration is not None and mean_miscalibration <= 0.20
                else "SOFT_FAIL" if mean_miscalibration is not None and mean_miscalibration <= 0.35
                else "HARD_FAIL"
            ) if mean_miscalibration is not None else "INSUFFICIENT_DATA"
            acc_v = (
                "PASS" if accuracy_rate >= 0.80
                else "SOFT_FAIL" if accuracy_rate >= 0.65
                else "HARD_FAIL"
            )
            result["f8_verdict"] = f8_v
            result["accuracy_verdict"] = acc_v
            # Stricter wins
            order = {"PASS": 0, "SOFT_FAIL": 1, "HARD_FAIL": 2, "INSUFFICIENT_DATA": 3}
            result["verdict"] = max([f8_v, acc_v], key=lambda v: order.get(v, 3))
        return result

    def _write_to_disk(self, session: CalibrationSession, summary: dict[str, Any]) -> Path:
        self.results_root.mkdir(parents=True, exist_ok=True)
        path = self.results_root / f"calibration_session_{session.session_id}.json"
        body = {
            **summary,
            "duration_minutes": session.duration_minutes,
            "started_at": session.started_at,
            "started_at_beat": session.started_at_beat,
            "pairs": [
                {
                    "beat_no": p.beat_no,
                    "operator": p.operator_label,
                    "system": p.system_label,
                    "confidence": p.confidence,
                }
                for p in session.pairs
            ],
        }
        path.write_text(json.dumps(body, indent=2))
        return path


def _cohens_kappa(labels_a: list[str], labels_b: list[str]) -> float:
    """Two-rater Cohen's κ for categorical agreement.

    Same implementation used in scripts/phase_f/f6_zone_validation.py. Kept
    locally to avoid the interface package reaching into scripts/.
    """
    assert len(labels_a) == len(labels_b)
    n = len(labels_a)
    if n == 0:
        return 0.0
    categories = sorted(set(labels_a) | set(labels_b))
    po = sum(1 for a, b in zip(labels_a, labels_b, strict=True) if a == b) / n
    count_a = Counter(labels_a)
    count_b = Counter(labels_b)
    pe = sum((count_a[c] / n) * (count_b[c] / n) for c in categories)
    if pe == 1.0:
        return 1.0
    return float((po - pe) / (1 - pe))


__all__ = [
    "CalibrationRecorder",
    "CalibrationSession",
    "LabelPair",
    "SessionKind",
]
