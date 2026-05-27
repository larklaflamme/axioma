"""SubstrateApp — wires the drive + 5 organs + plasticity into a beatable unit.

This is the *substrate-only* component that the heartbeat owns. It is
registered with AxiomaContext under name "substrate". The compose, measurement,
and external interface layers consume it through the context.

A single SubstrateApp.tick(beat_no, timestamp) performs heartbeat step 2
(per IMPLEMENTATION_PLAN_v1.0.md §5.0):
  - PerturbationScheduler.tick (stubbed for now; Phase B)
  - SharedLatentDrive.step(N_iter)   -- iterative inner loop
  - For each organ: render(plasticity_drift) -> OrganState
  - For each organ's plasticity buffer: record_beat + maybe_update
  - Build InternalState; PNEUMA load signals are updated from peers

Returns the new InternalState for downstream consumers.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..config import SubstrateConfig
from ..observability.logging import get_logger
from ..persistence.snapshot import Stateful  # noqa: F401
from ..schemas import (
    AnimaState,
    EidolonState,
    InternalState,
    MnemeState,
    NousState,
    PneumaState,
)
from .anima import Anima
from .base import Organ
from .drive import SharedLatentDrive
from .eidolon import Eidolon
from .mneme import Mneme
from .nous import Nous
from .plasticity import PlasticityBuffer
from .pneuma import Pneuma

log = get_logger(__name__)


class SubstrateApp:
    """Container for the substrate's runtime state.

    Designed for testability:
      app = SubstrateApp.from_config(cfg.substrate, seed=42)
      for beat in range(100):
          internal = app.tick(beat_no=beat, timestamp=beat * 0.1)
    """

    name = "substrate"
    schema_version = 1

    def __init__(
        self,
        *,
        drive: SharedLatentDrive,
        anima: Anima,
        eidolon: Eidolon,
        mneme: Mneme,
        nous: Nous,
        pneuma: Pneuma,
        plasticity: dict[str, PlasticityBuffer],
        plasticity_enabled: bool = True,
    ) -> None:
        self.drive = drive
        self.anima = anima
        self.eidolon = eidolon
        self.mneme = mneme
        self.nous = nous
        self.pneuma = pneuma
        # Canonical order matches schemas.ORGAN_ORDER
        self.organs: tuple[Organ, ...] = (anima, eidolon, mneme, nous, pneuma)
        self.plasticity = plasticity  # keyed by organ.name
        self.plasticity_enabled = plasticity_enabled
        self.beat_no = 0
        # Latest rendered InternalState (None before first tick)
        self._last_internal: InternalState | None = None
        # v1.6.0 (Checkpoint II): expose per-load skip detail. Mirrors the
        # FF (Checkpoint FF) LoadResult pattern: callers can inspect this
        # after `load_state` to see which organs / plasticity buffers were
        # absent from the snapshot. Empty lists mean a clean full load.
        self.last_load_skipped_organs: list[str] = []
        self.last_load_skipped_plasticity: list[str] = []

    @classmethod
    def from_config(
        cls,
        cfg: SubstrateConfig,
        *,
        seed: int | None = None,
        plasticity_enabled: bool = True,
    ) -> SubstrateApp:
        """Build a SubstrateApp from a frozen SubstrateConfig.

        Per-organ seeds are derived deterministically from `seed` for
        reproducibility across snapshots/restarts.
        """
        D = cfg.drive_dim
        # Seed offsets — each subsystem gets its own substream
        base = seed if seed is not None else 0
        drive_seed = (base + 1) if seed is not None else None
        anima_seed = (base + 2) if seed is not None else None
        eidolon_seed = (base + 3) if seed is not None else None
        mneme_seed = (base + 4) if seed is not None else None
        nous_seed = (base + 5) if seed is not None else None
        pneuma_seed = (base + 6) if seed is not None else None

        drive = SharedLatentDrive(
            drive_dim=D,
            n_iter=cfg.n_iter,
            rho_g=cfg.rho_g,
            seed=drive_seed,
        )

        anima_spec = cfg.organ_specs["anima"]
        eidolon_spec = cfg.organ_specs["eidolon"]
        mneme_spec = cfg.organ_specs["mneme"]
        nous_spec = cfg.organ_specs["nous"]
        pneuma_spec = cfg.organ_specs["pneuma"]

        anima = Anima(
            drive_dim=D, latent_dim=anima_spec.latent_dim,
            rho=anima_spec.rho, v_scale=anima_spec.v_scale, seed=anima_seed,
        )
        eidolon = Eidolon(
            drive_dim=D, latent_dim=eidolon_spec.latent_dim,
            rho=eidolon_spec.rho, v_scale=eidolon_spec.v_scale, seed=eidolon_seed,
        )
        mneme = Mneme(
            drive_dim=D, latent_dim=mneme_spec.latent_dim,
            rho=mneme_spec.rho, v_scale=mneme_spec.v_scale,
            stage2_enabled=cfg.mneme_compensation_2_enabled,
            stage3_enabled=cfg.mneme_compensation_3_enabled,
            seed=mneme_seed,
        )
        nous = Nous(
            drive_dim=D, latent_dim=nous_spec.latent_dim,
            rho=nous_spec.rho, v_scale=nous_spec.v_scale, seed=nous_seed,
        )
        pneuma = Pneuma(
            drive_dim=D, latent_dim=pneuma_spec.latent_dim,
            rho=pneuma_spec.rho, v_scale=pneuma_spec.v_scale, seed=pneuma_seed,
        )

        # v1.6.2 (Checkpoint KK / GG-2): wire MNEME stage-3 faster plasticity
        # per ARCH §4.4 #3. When enabled, MNEME's plasticity buffer uses a
        # higher alpha_p (faster forgetting) — memory naturally has shorter-
        # term volatility than affective / structural state. Default is the
        # baseline 0.05 (matches v1.0..v1.6.1 behavior); stage3 boosts to 0.10
        # (2× faster, the conventional rule-of-thumb).
        _MNEME_STAGE3_ALPHA_P = 0.10
        plasticity: dict[str, PlasticityBuffer] = {}
        for organ in (anima, eidolon, mneme, nous, pneuma):
            kwargs: dict[str, Any] = {
                "organ_name": organ.name,
                "latent_dim": organ.latent_dim,
            }
            if organ is mneme and cfg.mneme_compensation_3_enabled:
                kwargs["alpha_p"] = _MNEME_STAGE3_ALPHA_P
            plasticity[organ.name] = PlasticityBuffer(**kwargs)
        return cls(
            drive=drive,
            anima=anima, eidolon=eidolon, mneme=mneme, nous=nous, pneuma=pneuma,
            plasticity=plasticity,
            plasticity_enabled=plasticity_enabled,
        )

    # ── Heartbeat tick (substrate-only portion) ──────────────────────────

    def tick(self, beat_no: int, timestamp: float) -> InternalState:
        """One substrate beat. Returns the new InternalState.

        Step ordering (heartbeat §5.0 step 2):
          d. Drive: run N_iter inner iterations, updating g and each organ.latent
          e. Render: each organ.render(plasticity_drift) → OrganState
          f. Plasticity: record_beat + maybe_update (every plasticity.period beats)
          + PNEUMA: set load signals from peers; render is already aware
        """
        # d) Drive update (iterative inner loop)
        self.drive.step(list(self.organs))

        # e) Record latents into plasticity buffers + compute drift to pass to render
        plasticity_drifts: dict[str, np.ndarray | None] = {}
        for organ in self.organs:
            if self.plasticity_enabled:
                buf = self.plasticity[organ.name]
                buf.record_beat(organ.latent)
                buf.maybe_update(beat_no)
                plasticity_drifts[organ.name] = buf.current_drift()
            else:
                plasticity_drifts[organ.name] = None

        # First-pass render: ANIMA / EIDOLON / MNEME / NOUS (we need their state
        # before PNEUMA's render so PNEUMA can compute coherence_budget correctly)
        anima_state = self.anima.render(plasticity_drifts["anima"])
        eidolon_state = self.eidolon.render(plasticity_drifts["eidolon"])
        mneme_state = self.mneme.render(plasticity_drifts["mneme"])
        nous_state = self.nous.render(plasticity_drifts["nous"])

        # Update PNEUMA's load inputs from the just-rendered siblings.
        # cascade_delay_beats is provided by the measurement layer; substrate
        # uses last-known value (initially 0 = no reading yet).
        self.pneuma.set_load_signals(
            nous_cognitive_load=nous_state.cognitive_load,
            mneme_wm_load=mneme_state.wm_load,
        )
        pneuma_state = self.pneuma.render(plasticity_drifts["pneuma"])

        # v1.6.2 (Checkpoint KK / GG-2): wire MNEME stage-2 cross-organ
        # coupling per ARCH §4.4 #2. Concatenate the just-rendered neighbor
        # states (everyone except MNEME itself) and feed them to MNEME for
        # use on the NEXT beat's drive.step → step_latent → cross_coupling.
        # The "one beat lag" is documented per ARCH §4.4 #2: cross-coupling
        # is a slow bypass channel, not real-time. Opt-in via stage2_enabled
        # (default False); existing deployments are unaffected.
        if self.mneme.stage2_enabled:
            neighbor_concat = np.concatenate([
                anima_state.to_array(),
                eidolon_state.to_array(),
                nous_state.to_array(),
                pneuma_state.to_array(),
            ])
            self.mneme.ensure_stage2(neighbor_dim=int(neighbor_concat.size))
            self.mneme.set_neighbor_states(neighbor_concat)

        self.beat_no = beat_no
        self._last_internal = InternalState(
            anima=anima_state,
            eidolon=eidolon_state,
            mneme=mneme_state,
            nous=nous_state,
            pneuma=pneuma_state,
            beat_no=beat_no,
            timestamp=timestamp,
        )
        return self._last_internal

    def get_organ(self, name: str) -> Organ:
        for o in self.organs:
            if o.name == name:
                return o
        raise KeyError(f"unknown organ: {name}")

    def last_internal(self) -> InternalState | None:
        """Most recent InternalState. None before first tick."""
        return self._last_internal

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "beat_no": self.beat_no,
            "drive": self.drive.save_state(),
            "organs": {o.name: o.save_state() for o in self.organs},
            "plasticity": {n: b.save_state() for n, b in self.plasticity.items()},
            "plasticity_enabled": self.plasticity_enabled,
        }

    def load_state(self, snapshot: dict[str, Any]) -> None:
        # v1.6.0 (Checkpoint II): track which components were skipped on load.
        # Reset on each load_state call so callers always see the result of
        # the most recent load, not cumulative skips across multiple loads.
        skipped_organs: list[str] = []
        skipped_plasticity: list[str] = []
        self.beat_no = int(snapshot.get("beat_no", 0))
        self.drive.load_state(snapshot["drive"])
        organ_snapshots = snapshot.get("organs", {})
        for o in self.organs:
            if o.name in organ_snapshots:
                o.load_state(organ_snapshots[o.name])
            else:
                skipped_organs.append(o.name)
                log.warning(
                    "substrate_load_organ_missing",
                    organ=o.name,
                    snapshot_beat=self.beat_no,
                )
        plasticity_snapshots = snapshot.get("plasticity", {})
        for n, b in self.plasticity.items():
            if n in plasticity_snapshots:
                b.load_state(plasticity_snapshots[n])
            else:
                skipped_plasticity.append(n)
                log.warning(
                    "substrate_load_plasticity_missing",
                    plasticity=n,
                    snapshot_beat=self.beat_no,
                )
        self.plasticity_enabled = bool(snapshot.get("plasticity_enabled", True))
        self.last_load_skipped_organs = skipped_organs
        self.last_load_skipped_plasticity = skipped_plasticity

    # Convenience for test assertions
    def render_all(self) -> tuple[AnimaState, EidolonState, MnemeState, NousState, PneumaState]:
        """Return the most recent rendered organ states."""
        if self._last_internal is None:
            raise RuntimeError("SubstrateApp.tick() has not been called yet")
        s = self._last_internal
        return (s.anima, s.eidolon, s.mneme, s.nous, s.pneuma)
