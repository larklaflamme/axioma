"""SharedLatentDrive — the iterative inner-loop drive update.

Per ARCH_DESIGN_v1.0.md §4.1.

The drive `g ∈ R^L` is shared across all organs. It is NOT owned by any
organ; PNEUMA is a peer like the others. Each beat runs N_iter inner
iterations of the coupled SDE:

  g_k = ρ_g · g_{k-1}
        + (1/N_iter) · √(1-ρ_g²) · Σ_i V_i · z_i^{(k-1)}
        + η_k / √N_iter
  z_i^{(k)} = z_i^{(k-1)} + (Δt/N_iter) · (W_i g_k + cross_i + ξ_i/√N_iter)

After N_iter steps, g_t = g_{N_iter} and z_i,t = z_i^{(N_iter)}.

The (1/√N_iter) noise scaling assumes additive Gaussian noise (see E14
caveat in ARCH §4.1). For other noise models the scaling must be re-derived.

N_iter = 1 reproduces v0.5's single-step semantics exactly (the inner loop
collapses to one step). N_iter ≥ 3 (default) approximates simultaneous
mutual constraint — what Theoria called resonant binding.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from ..persistence.snapshot import Stateful  # noqa: F401

if TYPE_CHECKING:
    from .base import Organ


class SharedLatentDrive:
    """Iterative drive `g ∈ R^L` with mutual-constraint inner loop.

    Holds:
      - g: current drive vector, float32 of shape (drive_dim,)
      - rho_g: drive's own decay (0 < ρ_g < 1)
      - n_iter: inner-loop iteration count per beat (default 3)
      - rng: numpy Generator for noise draws

    Does NOT hold organ references; organs are passed to step() each beat.
    This keeps the drive testable in isolation.
    """

    name = "shared_drive"
    schema_version = 1

    def __init__(
        self,
        *,
        drive_dim: int,
        n_iter: int = 3,
        rho_g: float = 0.90,
        noise_scale: float = 0.05,
        init_scale: float = 0.1,
        feedback_scale: float = 0.03,
        hard_clip: float = 30.0,
        seed: int | None = None,
    ) -> None:
        """SharedLatentDrive.

        Args:
            feedback_scale: global multiplier on the Σ V_i z_i feedback term.
                The closed loop V·g·W·z·V has gain that depends on organ
                count + drive_dim. Even with per-organ V normalized by
                √latent_dim, the total feedback can destabilize the drive.

                Linear stability analysis: for the simplified two-block
                system [g_new; z_new] = M[g; z] with M = [ρ_g I, α V; W, ρ_i I],
                the off-diagonal product α·v_scale·1 must satisfy
                √(α·v_scale) < (1-ρ_g) / 2 ≈ 0.05 ⇒ α·v_scale < ~0.005.

                With max v_scale=1.4 (MNEME α_M), feedback_scale=0.03 gives
                αVW ~ 0.042·1.4 = 0.06, but α here already includes √(1-ρ²) ≈ 0.44,
                so effective loop gain ≈ 0.03·0.44·1.4 ≈ 0.018 — safely
                below threshold. Phase A.4 N_iter sweep verifies stability
                empirically.
        """
        if n_iter < 1:
            raise ValueError(f"n_iter must be >= 1, got {n_iter}")
        if not 0.0 < rho_g < 1.0:
            raise ValueError(f"rho_g must be in (0, 1), got {rho_g}")
        if hard_clip <= 0:
            raise ValueError(f"hard_clip must be > 0, got {hard_clip}")
        self.drive_dim = drive_dim
        self.n_iter = n_iter
        self.rho_g = float(rho_g)
        self.noise_scale = float(noise_scale)
        self.feedback_scale = float(feedback_scale)
        # v1.6.0 (Checkpoint II): operator-overridable hard clip on the drive
        # vector. Previously a class-attr constant. The default (30.0) is
        # safe for the documented substrate operating range; operators with
        # bespoke v_scale / feedback_scale configurations can bump it.
        self.hard_clip = float(hard_clip)
        self.rng = np.random.default_rng(seed)
        # Cold-start initialization: small Gaussian
        self.g = self.rng.standard_normal(drive_dim).astype(np.float32) * init_scale
        # Pre-compute scalar coefficients
        self._sqrt_one_minus_rho_sq = float(np.sqrt(max(0.0, 1.0 - rho_g**2)))

    # ── Per-beat iterative step ──────────────────────────────────────────

    def step(self, organs: list[Organ]) -> np.ndarray:
        """Run N_iter inner iterations updating g and all organ latents.

        Drive is an Euler-Maruyama OU process with feedback from organs:
            dg = -γ_g g dt + √(1-ρ²) · feedback dt + σ dW

        where γ_g = -log(ρ_g) so exp(-γ_g) = ρ_g over one full beat,
        and feedback = Σ_i V_i z_i (each organ contributes; PNEUMA is a peer).

        After this call, self.g and each organ.latent reflect the new
        beat's values. Caller should render observable states afterward.

        Returns the final g (a reference; do not mutate).
        """
        N = self.n_iter
        dt_inner = 1.0 / N
        drive_dim = self.drive_dim
        gamma_g = -float(np.log(self.rho_g))

        for _k in range(N):
            # 1) Drive update from previous-step organ contributions
            feedback = np.zeros(drive_dim, dtype=np.float32)
            for organ in organs:
                feedback += organ.contribution_to_drive()
            drift = (
                -gamma_g * self.g
                + self.feedback_scale * self._sqrt_one_minus_rho_sq * feedback
            )
            noise = self.rng.standard_normal(drive_dim).astype(np.float32) * np.sqrt(dt_inner)
            self.g = self.g + dt_inner * drift + self.noise_scale * noise
            # Safety clip — keeps drive bounded under any feedback configuration
            np.clip(self.g, -self.hard_clip, self.hard_clip, out=self.g)
            # 2) Each organ reads the updated g and steps its latent
            for organ in organs:
                organ.step_latent(self.g, dt_inner)
        return self.g

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        from .base import _serialize_rng
        return {
            "g": self.g.tolist(),
            "rho_g": self.rho_g,
            "n_iter": self.n_iter,
            "noise_scale": self.noise_scale,
            "drive_dim": self.drive_dim,
            "rng_state": _serialize_rng(self.rng),
        }

    def load_state(self, snapshot: dict[str, Any]) -> None:
        from .base import _deserialize_rng
        # v1.6.0 (Checkpoint HH): explicit shape validation. Pre-fix, loading
        # a snapshot taken with a different drive_dim would silently overwrite
        # `self.g` with a wrong-shape array, producing downstream feedback
        # math errors that only surface as cryptic broadcasting failures
        # later. Now the size mismatch raises at load time.
        g_arr = np.asarray(snapshot["g"], dtype=np.float32)
        if g_arr.shape != (self.drive_dim,):
            raise ValueError(
                f"drive snapshot shape mismatch: got g.shape={g_arr.shape}, "
                f"expected ({self.drive_dim},)"
            )
        self.g = g_arr
        if "rho_g" in snapshot:
            self.rho_g = float(snapshot["rho_g"])
            self._sqrt_one_minus_rho_sq = float(np.sqrt(max(0.0, 1.0 - self.rho_g**2)))
        if "n_iter" in snapshot:
            self.n_iter = int(snapshot["n_iter"])
        if "noise_scale" in snapshot:
            self.noise_scale = float(snapshot["noise_scale"])
        rng_state = snapshot.get("rng_state")
        if rng_state is not None:
            self.rng = _deserialize_rng(rng_state)
