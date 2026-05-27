"""Control 3 — No differentiation.

After each Heartbeat.tick(), all non-ANIMA organ latents are overwritten with a
tiled copy of ANIMA's 4-dim latent (pad to fit each organ's DIM). The system
becomes a single-node network with 5× redundancy: perfect integration, zero
differentiation. PNEUMA.integrate runs ON the cloned states, so all five
organs are perfectly synchronized by construction.
"""
from __future__ import annotations

import numpy as np

from aos_g_gap.compose import ComposeFunction
from organ.substrate import CoupledLatentDynamics, Heartbeat

from .base import ControlMode, register


@register
class Control3Mode(ControlMode):
    name = "control3"

    def __init__(self, **_):
        pass

    def build_heartbeat(self, seed: int, coupling: float) -> Heartbeat:
        dyn = CoupledLatentDynamics(coupling=coupling, seed=seed)
        return Heartbeat(dynamics=dyn, seed=seed)

    def build_compose(self, seed: int) -> ComposeFunction:
        return ComposeFunction(seed=seed)

    def post_tick(self, hb: Heartbeat) -> None:
        """Overwrite all non-ANIMA latents with a tile of ANIMA's latent."""
        anima_l = hb.anima.latent.copy()
        # NB: we need to re-run each organ's render-state step after overwriting
        # the latent so the get_state() output reflects the cloned latent.
        # Easiest: directly run the organ's update with a zero drive once more —
        # but that would mutate again. Cleaner: just overwrite latent then call
        # a custom render. Use a tiny private wrapper.
        for organ in (hb.eidolon, hb.mneme, hb.nous, hb.pneuma):
            tile = np.tile(anima_l, int(np.ceil(organ.DIM / len(anima_l))))[:organ.DIM]
            organ.latent = tile.astype(np.float32)
        # Re-render states (each organ's update() does latent→state at the end;
        # we replicate that by feeding zero drive with time_scale=0 so latent is
        # unchanged but state is re-rendered).
        zero_drive = np.zeros_like(hb.dynamics.z)
        for organ in (hb.eidolon, hb.mneme, hb.nous):
            # Save / restore latent so the update doesn't mutate it.
            saved = organ.latent.copy()
            organ.update(hb.beat_no - 1, zero_drive, time_scale=0.0)
            organ.latent = saved  # noise term may have shifted it
        # PNEUMA's state depends on integrate(other_organs) — rerun.
        hb.pneuma.integrate(hb.non_pneuma)
