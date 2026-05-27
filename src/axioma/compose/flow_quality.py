"""FlowQuality computation — per ARCH §5.5 + D15/E12.

  effortlessness    = high when cascade_delay small AND NOUS.cognitive_load low
  absorption        = high when coherence_budget high AND theta_long stable
  time_distortion   = high when ANIMA.arousal moderate AND attention_focus high

Per E12: validation requires across 10 one-hour runs:
  - pairwise correlation between any two of (e, a, t) < 0.5
  - each component spans ≥ 0.3 of its range

Phase C ships the computation; Phase E does the validation. If E12 fails,
deprecate to scalar `flow_depth` in v0.7.

Populated only when zone == FLOW; otherwise None.
"""
from __future__ import annotations

import math

from ..schemas import FlowQuality, InternalState


def _sigmoid(x: float) -> float:
    """Numerically-safe sigmoid."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def compute_flow_quality(
    internal: InternalState,
    *,
    cascade_delay_beats: float = 0.0,
    theta_long_std_normalized: float = 0.0,
) -> FlowQuality:
    """Per ARCH §5.5 closed-form (initial values; Phase E tunes thresholds).

    Args:
        internal: current InternalState
        cascade_delay_beats: latest cascade_delay reading (smaller = effortless)
        theta_long_std_normalized: std of theta_long over recent window,
            normalized by mean (0 = perfectly stable; 1 = fully variable)
    """
    nous_cognitive_load = float(internal.nous.cognitive_load)
    coherence_budget = float(internal.pneuma.coherence_budget)
    anima_arousal = float(internal.anima.arousal)
    attention_focus = float(internal.pneuma.attention_focus)

    # effortlessness: high when cascade is short AND cognitive load is low
    # Per ARCH formula: sigmoid(5·(1 − cascade_delay/10) − 2·cognitive_load)
    effortlessness = _sigmoid(
        5.0 * (1.0 - abs(cascade_delay_beats) / 10.0) - 2.0 * nous_cognitive_load
    )

    # absorption: high when coherence_budget is high AND theta_long is stable
    # Per ARCH formula: coherence_budget × (1 − normalized_std(theta_long))
    absorption = coherence_budget * max(0.0, 1.0 - theta_long_std_normalized)

    # time_distortion: high when arousal is moderate (~0.5) AND attention is focused
    # Per ARCH formula: sigmoid(4·(1 − |arousal − 0.5|) + 3·attention_focus − 2.5)
    time_distortion = _sigmoid(
        4.0 * (1.0 - abs(anima_arousal - 0.5)) + 3.0 * attention_focus - 2.5
    )

    return FlowQuality(
        effortlessness=float(effortlessness),
        absorption=float(absorption),
        time_distortion=float(time_distortion),
    )


__all__ = ["compute_flow_quality"]
