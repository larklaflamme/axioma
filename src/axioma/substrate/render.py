"""Non-saturating rendering helpers — linear rescale + clip.

Per ARCH_DESIGN_v1.0.md §4.3 and §4.5 (E15 caveat):

  The v0.4/v0.5/v0.6/v1.0 substrate uses non-saturating dynamics
  (Ornstein-Uhlenbeck in latent space + LINEAR RESCALE at the state
  boundary). This replaces v0.2's bounded tanh/sigmoid renderers.

The rendering maps an unbounded latent component → a bounded state field
without aggressive compression near the rails. Most of the time the latent
sits in the linear region; clip only kicks in at the boundary.

For a latent expected to vary ~N(0, σ²) with σ≈1, dividing by ~3 puts
3σ at the rail — i.e., the clip activates only on rare large excursions.
"""
from __future__ import annotations

import numpy as np

# Linear render range — latent value `scale` maps to the rail.
# Set to 10 so that latent excursions up to ~10 stay in the linear region;
# rarely-occurring excursions beyond that clip. This is the non-saturating
# property: the render is linear over the substrate's typical operating
# range and only clips at the boundary (vs sigmoid/tanh which compress
# aggressively throughout). Per ARCH §4.3 / E15.
_DEFAULT_SIGMA_SCALE = 10.0


def to_unit_centered(latent_value: float, *, scale: float = _DEFAULT_SIGMA_SCALE) -> float:
    """Map unbounded latent → [-1, 1]. Linear with clip.

    With the default scale=10 (`_DEFAULT_SIGMA_SCALE`), values in [-10, 10]
    map linearly to [-1, 1]; values outside that band clip. For an N(0, 1)
    latent the clip basically never fires (10σ excursion); for the substrate's
    typical OU regime (occasional excursions to ~3-5σ scaled by feedback), the
    rescale stays linear over the normal operating range. Per ARCH §4.3 / E15.
    """
    return float(np.clip(latent_value / scale, -1.0, 1.0))


def to_unit(latent_value: float, *, scale: float = _DEFAULT_SIGMA_SCALE) -> float:
    """Map unbounded latent → [0, 1]. Linear rescale of to_unit_centered.

    Default scale=10 (`_DEFAULT_SIGMA_SCALE`) — see `to_unit_centered` for
    the rationale and the operating-range characterization.
    """
    centered = to_unit_centered(latent_value, scale=scale)
    return 0.5 * (centered + 1.0)


def to_range(
    latent_value: float,
    *,
    lo: float,
    hi: float,
    scale: float = _DEFAULT_SIGMA_SCALE,
) -> float:
    """Map unbounded latent → [lo, hi] linearly."""
    unit = to_unit(latent_value, scale=scale)
    return float(lo + unit * (hi - lo))


def to_int_range(
    latent_value: float,
    *,
    lo: int,
    hi: int,
    scale: float = _DEFAULT_SIGMA_SCALE,
) -> int:
    """Map unbounded latent → integer in [lo, hi] inclusive."""
    cont = to_range(latent_value, lo=float(lo), hi=float(hi), scale=scale)
    return int(np.clip(round(cont), lo, hi))


def to_int_nonneg(
    latent_value: float,
    *,
    scale_per_unit: float = 5.0,
) -> int:
    """Map unbounded latent → integer in [0, ∞). For unbounded counts.

    Uses softplus-like positive mapping: max(0, round(scale * positive_part)).
    """
    pos = max(0.0, float(latent_value))
    return round(scale_per_unit * pos)
