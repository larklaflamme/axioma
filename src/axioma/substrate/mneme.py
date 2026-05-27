"""MNEME — memory (5-dim state).

Per ARCH_DESIGN_v1.0.md §4.3 + §4.4 (v1.0 staged compensation, D13/C13):
  latent_dim = 12, state_dim = 5, ρ = 0.88, V_scale = α_M = 1.4

  ★ Stage-1 compensation ON by default: stronger drive coupling via V_scale=1.4.
  Stage #2 (cross-organ channel q_M) and Stage #3 (faster plasticity forgetting)
  are gated behind config flags, default OFF, enabled only if Phase A measurement
  shows stage-1 is insufficient.

  v1.6.2 (Checkpoint KK): stages 2 and 3 are now wired end-to-end —
  stage-2 calls `set_neighbor_states` from SubstrateApp.tick using rendered
  neighbor states from the prior beat (one-beat lag is documented per ARCH
  §4.4 #2: cross-coupling is a slow bypass channel); stage-3 boosts MNEME's
  plasticity buffer's `alpha_p` to 0.10 (2× baseline). Both stay opt-in
  with defaults False; existing deployments are unaffected. Multi-seed
  validation under production load has NOT been performed; treat as
  experimental until an operator runs the equivalent of the v1.4/v1.5
  validation sweep on their own substrate regime.

Rendered fields:
  wm_load             ∈ [0, 7]   integer
  retrieval_rate      ∈ [0, 1]
  decay_rate          ∈ [0, 1]
  episodic_freshness  ∈ [0, 1]
  semantic_coherence  ∈ [0, 1]
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..schemas import MnemeState
from .base import Organ
from .render import to_int_range, to_unit

_MODULATION = 0.1


class Mneme(Organ):
    name = "mneme"

    def __init__(
        self,
        *,
        drive_dim: int,
        latent_dim: int = 12,
        rho: float = 0.88,
        v_scale: float = 1.4,  # MNEME α_M
        noise_scale: float = 0.1,
        latent_hard_clip: float = 30.0,
        # Stage-2/3 compensation flags (default OFF; auto-enabled in Phase A if needed)
        stage2_enabled: bool = False,
        stage3_enabled: bool = False,
        seed: int | None = None,
    ) -> None:
        super().__init__(
            drive_dim=drive_dim,
            latent_dim=latent_dim,
            state_dim=5,
            rho=rho,
            v_scale=v_scale,
            noise_scale=noise_scale,
            latent_hard_clip=latent_hard_clip,
            seed=seed,
        )
        self.stage2_enabled = stage2_enabled
        self.stage3_enabled = stage3_enabled
        # Stage #2 cross-organ projection matrix M (only used if stage2_enabled).
        # Built lazily on first call to ensure_stage2() since it depends on
        # neighbor state_dims which are passed by SubstrateApp wiring.
        self._M: np.ndarray | None = None
        # Place for neighbor states to be set externally if stage2 active
        self._neighbor_states_concat: np.ndarray | None = None

    def cross_coupling(self) -> np.ndarray:
        """Stage-2: direct cross-organ channel q_M(s_neighbors).

        Per ARCH §4.4 #2: bypasses the shared drive bottleneck for memory
        specifically. Memory is the one organ where direct other-organ-state
        access is phenomenologically justified (memories are *of* other states).

        Returns zero vector unless stage-2 is enabled AND neighbor states have
        been set this beat via set_neighbor_states().
        """
        if not self.stage2_enabled:
            return np.zeros(self.latent_dim, dtype=np.float32)
        if self._M is None or self._neighbor_states_concat is None:
            return np.zeros(self.latent_dim, dtype=np.float32)
        # Small magnitude — this is a bypass channel, not the primary push
        return (0.05 * (self._neighbor_states_concat @ self._M)).astype(np.float32)

    def ensure_stage2(self, neighbor_dim: int) -> None:
        """Initialize the cross-organ projection M once we know the concat dim."""
        if self._M is None and self.stage2_enabled:
            self._M = self.rng.standard_normal((neighbor_dim, self.latent_dim)).astype(np.float32)
            self._M /= np.linalg.norm(self._M, axis=0, keepdims=True) + 1e-8

    def set_neighbor_states(self, concat: np.ndarray) -> None:
        """Update the cached neighbor-state concatenation for stage-2 coupling."""
        if self.stage2_enabled:
            self._neighbor_states_concat = concat.astype(np.float32, copy=True)

    def render(self, plasticity_drift: np.ndarray | None = None) -> MnemeState:
        z = self.latent
        drift = (
            _MODULATION * plasticity_drift
            if plasticity_drift is not None
            else np.zeros(self.latent_dim, dtype=np.float32)
        )
        return MnemeState(
            wm_load=to_int_range(float(z[0] + drift[0]), lo=0, hi=7),
            retrieval_rate=to_unit(float(z[1] + drift[1])),
            decay_rate=to_unit(float(z[2] + drift[2])),
            episodic_freshness=to_unit(float(z[3] + drift[3])),
            semantic_coherence=to_unit(float(z[4] + drift[4])),
        )

    def save_state(self) -> dict[str, Any]:
        snap = super().save_state()
        snap["stage2_enabled"] = self.stage2_enabled
        snap["stage3_enabled"] = self.stage3_enabled
        if self._M is not None:
            snap["M"] = self._M.tolist()
        # v1.7 (Checkpoint MM): persist the rolling neighbor-states concat too.
        # Without this, snapshot-restore + stage-2 on produces a one-beat
        # divergence (restored app has _neighbor_states_concat=None → cross_coupling
        # returns zero on the first post-restore beat; original would have used
        # the last beat's neighbors). The snapshot roundtrip test relies on
        # bit-equal continuation, which this fixes.
        if self._neighbor_states_concat is not None:
            snap["neighbor_states_concat"] = self._neighbor_states_concat.tolist()
        return snap

    def load_state(self, snapshot: dict[str, Any]) -> None:
        super().load_state(snapshot)
        self.stage2_enabled = bool(snapshot.get("stage2_enabled", False))
        self.stage3_enabled = bool(snapshot.get("stage3_enabled", False))
        if "M" in snapshot and snapshot["M"] is not None:
            self._M = np.asarray(snapshot["M"], dtype=np.float32)
        if (
            "neighbor_states_concat" in snapshot
            and snapshot["neighbor_states_concat"] is not None
        ):
            self._neighbor_states_concat = np.asarray(
                snapshot["neighbor_states_concat"], dtype=np.float32
            )
