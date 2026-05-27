"""Organ ABC — base class for the 5 peer organs.

Per ARCH_DESIGN_v1.0.md §4.3.

Every organ has:
  - latent state z_i ∈ R^{latent_dim}  (unbounded; OU dynamics)
  - observable state s_i ∈ R^{state_dim}  (bounded; rendered from latent)
  - coupling matrix W_i: R^{drive_dim} → R^{latent_dim}  (drive → latent push)
  - feedback matrix V_i: R^{latent_dim} → R^{drive_dim}  (latent → drive)
  - plasticity buffer p_i (slow homeostatic statistic)

Each beat consists of N_iter inner iterations of:
  z_i^{(k)} = z_i^{(k-1)} + (Δt/N_iter) · (W_i g_k + c_i q_i + ξ_i/√N_iter)

After all iterations, the organ renders its observable state:
  s_i = render(z_i_final, plasticity_buffer)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np

from ..persistence.snapshot import Stateful  # noqa: F401  -- for isinstance check elsewhere
from ..schemas import OrganState


def make_random_projection(
    in_dim: int, out_dim: int, rng: np.random.Generator
) -> np.ndarray:
    """Random projection with unit-norm columns (each output dim has ~unit variance
    for unit-variance input). Returns shape (in_dim, out_dim) float32."""
    W = rng.standard_normal((in_dim, out_dim)).astype(np.float32)
    W /= np.linalg.norm(W, axis=0, keepdims=True) + 1e-8
    return W


class Organ(ABC):
    """Stateful peer organ.

    Concrete subclasses implement:
      - name (class attr)
      - render() → OrganState (consumed by InternalState)
      - cross_coupling() → np.ndarray (zero for most; q_M for MNEME)

    Subclass __init__ should call super().__init__(...) with all the
    sizing params; this base initializes the latent and projection matrices.
    """

    name: str = ""  # subclass overrides
    schema_version: int = 1

    def __init__(
        self,
        *,
        drive_dim: int,
        latent_dim: int,
        state_dim: int,
        rho: float,
        v_scale: float,
        noise_scale: float = 0.1,
        latent_hard_clip: float = 30.0,
        seed: int | None = None,
    ) -> None:
        if not self.name:
            raise NotImplementedError(f"{type(self).__name__} must set class attr `name`")
        if latent_hard_clip <= 0:
            raise ValueError(f"latent_hard_clip must be > 0, got {latent_hard_clip}")
        self.drive_dim = drive_dim
        self.latent_dim = latent_dim
        self.state_dim = state_dim
        self.rho = float(rho)
        self.v_scale = float(v_scale)
        self.noise_scale = float(noise_scale)
        # v1.6.0 (Checkpoint II): operator-overridable latent hard clip.
        # Was a class-attr constant (30.0); operators with bespoke organ
        # specs can now override per-organ.
        self.latent_hard_clip = float(latent_hard_clip)
        self.rng = np.random.default_rng(seed)

        # W_i: drive → latent push (shape: drive_dim, latent_dim)
        # Unit-norm columns: drive @ W has variance ~ Var(drive) per latent dim.
        self.W = make_random_projection(drive_dim, latent_dim, self.rng)
        # V_i: latent → drive feedback (shape: latent_dim, drive_dim).
        # Normalize by sqrt(latent_dim) so that for z_i ~ N(0, I), the feedback
        # per drive dim has variance ~v_scale² (independent of latent_dim).
        # This keeps the iterative drive loop stable regardless of organ-spec
        # choices.
        # v1.6.0 (Checkpoint HH) — explicit float32 cast. Without it, Python
        # scalar × float32-ndarray promotes to float64, leaving self.V as
        # float64 while load_state always reconstructs it as float32. The
        # inconsistency would have surfaced as mypy noise once load_state
        # acquired its v1.6.0 shape-check intermediate binding.
        self.V = (
            (self.v_scale / float(np.sqrt(latent_dim)))
            * make_random_projection(latent_dim, drive_dim, self.rng)
        ).astype(np.float32)

        # Initial latent: small Gaussian (cold-start condition; first ~100 beats
        # are documented as warmup per §5.4)
        self.latent = self.rng.standard_normal(latent_dim).astype(np.float32) * noise_scale

    # ── Per-beat inner-loop methods (called by SharedLatentDrive.step) ─────

    # Safety clip per ARCH §9.3.1 (latent divergence policy). Wide enough that
    # normal operation never trips it; if it does, that's a sign the drive
    # is unstable and the implementation needs investigation. Operator-
    # overridable via `__init__(latent_hard_clip=...)`.

    def step_latent(self, drive: np.ndarray, dt_inner: float) -> None:
        """One inner-loop iteration of Euler-Maruyama OU dynamics.

        Continuous-time SDE:
            dz_i = -γ z_i dt + W_i g dt + cross_i dt + σ dW
            where γ = -log(ρ_i) so that exp(-γ * 1 beat) = ρ_i.

        With dt_inner = 1/N_iter, applied N times per beat:
            z_new = z + dt_inner · (-γ z + W g + cross) + σ · √dt_inner · ξ

        Per-beat noise variance: N_iter · σ² · dt_inner = σ² (invariant).
        Per-beat decay: (1 - γ·dt_inner)^N ≈ exp(-γ) = ρ.
        Per ARCH §4.1 / E14: noise scaling assumes additive Gaussian noise.
        """
        push = drive @ self.W  # (latent_dim,)
        cross = self.cross_coupling()  # (latent_dim,) — zero for most organs
        # Decay rate γ s.t. exp(-γ) = ρ over one full beat
        gamma = -float(np.log(self.rho))
        # Euler-Maruyama step
        drift = -gamma * self.latent + push + cross
        noise = self.rng.standard_normal(self.latent_dim).astype(np.float32) * np.sqrt(dt_inner)
        self.latent = self.latent + dt_inner * drift + self.noise_scale * noise
        # Safety clip — per §9.3.1
        np.clip(self.latent, -self.latent_hard_clip, self.latent_hard_clip, out=self.latent)

    def contribution_to_drive(self) -> np.ndarray:
        """Return V_i z_i (shape: drive_dim) — this organ's feedback into g."""
        return self.latent @ self.V

    def cross_coupling(self) -> np.ndarray:
        """Cross-organ coupling q_i(s_neighbors). Default: zero.

        MNEME overrides this for staged compensations #2 and #3 (per ARCH §4.4).
        For now (stage-1 only), no organ has cross_coupling.
        """
        return np.zeros(self.latent_dim, dtype=np.float32)

    # ── End-of-beat render ────────────────────────────────────────────────

    @abstractmethod
    def render(self, plasticity_drift: np.ndarray | None = None) -> OrganState:
        """Render observable state from current latent.

        plasticity_drift, when not None, is the per-latent-dim drift signal
        from PlasticityBuffer (pathway #1 modulation per ARCH §7.3).
        Default modulation factor is small (~0.1); subclasses may scale.
        """

    # ── Stateful protocol ─────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "latent": self.latent.tolist(),
            "W": self.W.tolist(),
            "V": self.V.tolist(),
            # RNG state preserved so determinism survives restart
            "rng_state": _serialize_rng(self.rng),
        }

    def load_state(self, snapshot: dict[str, Any]) -> None:
        # v1.6.0 (Checkpoint HH): explicit shape validation. Pre-fix, loading
        # a snapshot from a different (drive_dim, latent_dim) silently
        # overwrote `self.latent` / `self.W` / `self.V` with mismatched
        # arrays, producing downstream broadcasting failures only at the
        # next drive step. Now the size mismatch raises at load time.
        latent_arr = np.asarray(snapshot["latent"], dtype=np.float32)
        if latent_arr.shape != (self.latent_dim,):
            raise ValueError(
                f"organ {self.name!r} snapshot shape mismatch: "
                f"got latent.shape={latent_arr.shape}, "
                f"expected ({self.latent_dim},)"
            )
        self.latent = latent_arr
        if "W" in snapshot:
            W_arr = np.asarray(snapshot["W"], dtype=np.float32)
            expected_w = (self.drive_dim, self.latent_dim)
            if W_arr.shape != expected_w:
                raise ValueError(
                    f"organ {self.name!r} snapshot shape mismatch: "
                    f"got W.shape={W_arr.shape}, expected {expected_w}"
                )
            self.W = W_arr
        if "V" in snapshot:
            V_arr = np.asarray(snapshot["V"], dtype=np.float32)
            expected_v = (self.latent_dim, self.drive_dim)
            if V_arr.shape != expected_v:
                raise ValueError(
                    f"organ {self.name!r} snapshot shape mismatch: "
                    f"got V.shape={V_arr.shape}, expected {expected_v}"
                )
            self.V = V_arr
        rng_state = snapshot.get("rng_state")
        if rng_state is not None:
            self.rng = _deserialize_rng(rng_state)


def _serialize_rng(rng: np.random.Generator) -> dict[str, Any]:
    """Round-trip numpy Generator state via bit_generator.state.

    Note: rng.__getstate__() returns None in numpy >= 2; the correct
    state lives at rng.bit_generator.state.
    """
    state = rng.bit_generator.state
    # state is a dict with very large Python ints — keep them as native ints
    # (msgspec.json handles arbitrary-precision Python ints losslessly).
    return _numpy_to_lists(state)


def _deserialize_rng(payload: dict[str, Any]) -> np.random.Generator:
    """Restore a numpy Generator from the dict produced by _serialize_rng."""
    rng = np.random.default_rng()
    rng.bit_generator.state = _lists_to_numpy(payload)
    return rng


def _numpy_to_lists(obj: Any) -> Any:
    """Recursively turn numpy arrays/ints inside a dict into JSON-safe values."""
    if isinstance(obj, np.ndarray):
        return {"__np__": True, "dtype": str(obj.dtype), "data": obj.tolist()}
    if isinstance(obj, np.integer | np.floating):
        return obj.item()
    if isinstance(obj, dict):
        return {k: _numpy_to_lists(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_numpy_to_lists(v) for v in obj]
    return obj


def _lists_to_numpy(obj: Any) -> Any:
    if isinstance(obj, dict):
        if obj.get("__np__"):
            return np.asarray(obj["data"], dtype=np.dtype(obj["dtype"]))
        return {k: _lists_to_numpy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_lists_to_numpy(v) for v in obj]
    return obj
