"""RawMIEngine — per-organ pairwise MI on small windows for cascade dynamics.

Per ARCH_DESIGN_v1.0.md §6.3 (D1/C10) + IMPLEMENTATION_PLAN_v1.0.md §6.1 step 2.

Provides:
  - 5-beat sliding window MI for each pair (10 pairs across 5 organs) — used
    by CascadeDelayEngine for fast peak detection
  - 20-beat sliding window MI for the same pairs — used for overall cascade
    structure reporting

GPU-batched: all 10 pairs computed in one kernel call per call to compute().

Why fast windows (vs θ_short 30-beat): cascade dynamics happen on 1-5 beats
(per Control 1's +4 → +28 beat range). 30-beat θ smooths over them; 5-beat
raw MI catches them.

Note: with tiny windows (n=5 with d=5-7 per organ pair), MI estimates have
high variance — but cascade_delay computes a *difference* of peak times,
so the noise mostly cancels. This is the architecture's deliberate trade-off
(ARCH §6.3 acceptance: cascade_delay reports +4-28 beat range from Control 1).
"""
from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np
import torch

from ..observability import get_logger
from ..observability.context import AxiomaContext
from ..persistence.snapshot import Stateful  # noqa: F401
from ..schemas import ORGAN_ORDER
from .engine_base import MeasurementEngine
from .theta_core import (
    _cov_torch,
    _logdet_torch,
    pairwise_mi_cpu,
    select_summary_columns,
)

log = get_logger(__name__)


# All 10 unordered organ pairs
ORGAN_PAIRS: list[tuple[str, str]] = list(combinations(ORGAN_ORDER, 2))


def _pair_key(a: str, b: str) -> str:
    """Canonical pair key (alphabetical order)."""
    return f"{a}-{b}" if a < b else f"{b}-{a}"


def _pairwise_mi_batched_gpu(
    window: dict[str, np.ndarray],
    device: torch.device,
) -> dict[str, float]:
    """Compute pairwise MI for all 10 organ pairs from a (n, D_organ) per-organ window.

    Returns {pair_key: mi_value}. GPU-batched: one logdet call per organ
    block + one logdet call per joint pair (total: 5 + 10 = 15 small batches).
    """
    n = window[ORGAN_ORDER[0]].shape[0]
    if n < 3:
        return {_pair_key(a, b): 0.0 for a, b in ORGAN_PAIRS}

    # Z-score each summary column per organ (cheap inline normalization;
    # tiny windows aren't worth Shapiro-Wilk testing)
    block_tensors: dict[str, torch.Tensor] = {}
    block_logdet: dict[str, torch.Tensor] = {}
    for o in ORGAN_ORDER:
        summary = select_summary_columns(o, window[o])  # (n, s_o)
        # z-score with safe sd
        sd = summary.std(axis=0, keepdims=True)
        sd = np.where(sd < 1e-12, 1.0, sd)
        norm = (summary - summary.mean(axis=0, keepdims=True)) / sd
        # Drop any column that became all-zero after normalization (constant)
        keep = norm.std(axis=0) > 1e-10
        norm = norm[:, keep]
        if norm.shape[1] == 0:
            # No varying dims — degenerate; this organ contributes 0 to all pairs
            block_tensors[o] = torch.empty(n, 0, device=device, dtype=torch.float32)
            continue
        t = torch.from_numpy(norm.astype(np.float32)).to(device)
        block_tensors[o] = t
        block_logdet[o] = _logdet_torch(_cov_torch(t))

    result: dict[str, float] = {}
    for a, b in ORGAN_PAIRS:
        key = _pair_key(a, b)
        ta, tb = block_tensors[a], block_tensors[b]
        if ta.shape[1] == 0 or tb.shape[1] == 0:
            result[key] = 0.0
            continue
        joint = torch.cat([ta, tb], dim=-1)
        ld_joint = _logdet_torch(_cov_torch(joint))
        mi = 0.5 * (block_logdet[a] + block_logdet[b] - ld_joint)
        result[key] = float(torch.clamp(mi, min=0.0).item())
    return result


def _pairwise_mi_batched_cpu(window: dict[str, np.ndarray]) -> dict[str, float]:
    """CPU equivalent of the GPU pairwise computation."""
    n = window[ORGAN_ORDER[0]].shape[0]
    if n < 3:
        return {_pair_key(a, b): 0.0 for a, b in ORGAN_PAIRS}
    # Build a single (n, 19) summary matrix; reuse the v0.2-style block_slices
    block_slices: list[tuple[str, slice]] = []
    parts: list[np.ndarray] = []
    start = 0
    for o in ORGAN_ORDER:
        s = select_summary_columns(o, window[o])
        # z-score with safe sd
        sd = s.std(axis=0, keepdims=True)
        sd = np.where(sd < 1e-12, 1.0, sd)
        s = ((s - s.mean(axis=0, keepdims=True)) / sd).astype(np.float32)
        # drop constant cols
        keep = s.std(axis=0) > 1e-10
        s = s[:, keep]
        d = s.shape[1]
        if d > 0:
            block_slices.append((o, slice(start, start + d)))
        parts.append(s)
        start += d
    if not block_slices:
        return {_pair_key(a, b): 0.0 for a, b in ORGAN_PAIRS}
    X = np.concatenate(parts, axis=1).astype(np.float32)
    mis, _total = pairwise_mi_cpu(X, block_slices)
    # Normalize key style to alphabetical
    result: dict[str, float] = {_pair_key(a, b): 0.0 for a, b in ORGAN_PAIRS}
    for (a, b), v in mis.items():
        result[_pair_key(a, b)] = float(v)
    return result


class RawMIEngine(MeasurementEngine):
    """Per-organ pairwise MI on 5-beat (fast) and 20-beat (slower) windows.

    Default cadences (per ARCH §4.6):
      - 5-beat MI: every beat (natural_period=1)
      - 20-beat MI: every 5 beats (natural_period=5)

    To keep should_run() returning a single bool, this engine treats every
    beat as a run; the 20-beat update is internally gated to every 5th call.

    Storage: each pair gets two rolling deques (one per window size). The
    most recent value is what cascade_delay reads via `latest_5beat()` /
    `latest_20beat()`.
    """

    name = "raw_mi"
    natural_period_beats = 1
    schema_version = 1

    def __init__(
        self,
        ctx: AxiomaContext,
        *,
        short_window: int = 5,
        long_window: int = 20,
        long_period: int = 5,
        history_capacity: int = 600,
        backend: str = "auto",
    ) -> None:
        super().__init__(ctx)
        if short_window < 3:
            raise ValueError(f"short_window must be >= 3, got {short_window}")
        if long_window < short_window:
            raise ValueError("long_window must be >= short_window")
        self.short_window = short_window
        self.long_window = long_window
        self.long_period = long_period
        self.history_capacity = history_capacity
        self.backend = backend  # 'gpu', 'cpu', 'auto'

        from collections import deque
        # Per-pair rolling history of (beat_no, mi) — used by CascadeDelayEngine
        self._short_history: dict[str, deque[tuple[int, float]]] = {
            _pair_key(a, b): deque(maxlen=history_capacity) for a, b in ORGAN_PAIRS
        }
        self._long_history: dict[str, deque[tuple[int, float]]] = {
            _pair_key(a, b): deque(maxlen=history_capacity) for a, b in ORGAN_PAIRS
        }
        self._latest_short: dict[str, float] = {
            _pair_key(a, b): 0.0 for a, b in ORGAN_PAIRS
        }
        self._latest_long: dict[str, float] = {
            _pair_key(a, b): 0.0 for a, b in ORGAN_PAIRS
        }
        self._last_short_beat: int | None = None
        self._last_long_beat: int | None = None
        self._device: torch.device | None = None  # lazy

    def _resolve_device(self) -> torch.device:
        if self._device is None:
            if self.backend == "cpu":
                self._device = torch.device("cpu")
            elif self.backend == "gpu":
                self._device = torch.device("cuda")
            else:  # auto
                self._device = torch.device(
                    "cuda" if torch.cuda.is_available() else "cpu"
                )
        return self._device

    def compute(self) -> None:
        if not self.ctx.has("state_buffer"):
            return
        buf = self.ctx.get("state_buffer")
        if len(buf) < self.short_window:
            return  # not warm
        # Latest beat number from the buffer
        beat_no = int(buf.window_beats(1)[0])

        # Always update short window (every beat)
        short_window = buf.window(self.short_window)
        device = self._resolve_device()
        if device.type == "cpu":
            short_mi = _pairwise_mi_batched_cpu(short_window)
        else:
            short_mi = _pairwise_mi_batched_gpu(short_window, device=device)
        for key, v in short_mi.items():
            self._latest_short[key] = v
            self._short_history[key].append((beat_no, v))
        self._last_short_beat = beat_no

        # Update long window every long_period beats (default 5)
        if beat_no % self.long_period == 0 and len(buf) >= self.long_window:
            long_window = buf.window(self.long_window)
            if device.type == "cpu":
                long_mi = _pairwise_mi_batched_cpu(long_window)
            else:
                long_mi = _pairwise_mi_batched_gpu(long_window, device=device)
            for key, v in long_mi.items():
                self._latest_long[key] = v
                self._long_history[key].append((beat_no, v))
            self._last_long_beat = beat_no

    # ── Accessors used by CascadeDelayEngine ─────────────────────────────

    def latest_5beat(self) -> dict[str, float]:
        """Most recent 5-beat MI per pair. Empty values are 0.0."""
        return dict(self._latest_short)

    def latest_20beat(self) -> dict[str, float]:
        return dict(self._latest_long)

    def history_5beat(self, pair_key: str) -> list[tuple[int, float]]:
        """(beat_no, mi) trace for a specific pair (oldest → newest)."""
        return list(self._short_history.get(pair_key, ()))

    def history_20beat(self, pair_key: str) -> list[tuple[int, float]]:
        return list(self._long_history.get(pair_key, ()))

    def current_value(self) -> dict[str, dict[str, float]]:
        """Combined snapshot used by WS push + state_snapshot."""
        return {
            "short_5beat": dict(self._latest_short),
            "long_20beat": dict(self._latest_long),
        }

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "short_window": self.short_window,
            "long_window": self.long_window,
            "long_period": self.long_period,
            "latest_short": self._latest_short,
            "latest_long": self._latest_long,
            "short_history": {k: list(v) for k, v in self._short_history.items()},
            "long_history": {k: list(v) for k, v in self._long_history.items()},
            "last_short_beat": self._last_short_beat,
            "last_long_beat": self._last_long_beat,
        }

    def load_state(self, snapshot: dict[str, Any]) -> None:
        from collections import deque
        if snapshot.get("short_window") != self.short_window:
            return  # cold-start on config change
        if snapshot.get("long_window") != self.long_window:
            return
        self._latest_short = dict(snapshot.get("latest_short", {}))
        self._latest_long = dict(snapshot.get("latest_long", {}))
        for k, hist in snapshot.get("short_history", {}).items():
            self._short_history[k] = deque(
                ((int(b), float(v)) for b, v in hist), maxlen=self.history_capacity
            )
        for k, hist in snapshot.get("long_history", {}).items():
            self._long_history[k] = deque(
                ((int(b), float(v)) for b, v in hist), maxlen=self.history_capacity
            )
        self._last_short_beat = snapshot.get("last_short_beat")
        self._last_long_beat = snapshot.get("last_long_beat")


__all__ = ["ORGAN_PAIRS", "RawMIEngine", "_pair_key"]
