"""ControlMode ABC + factory."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from aos_g_gap.compose import ComposeFunction
from organ.substrate import CoupledLatentDynamics, Heartbeat


class ControlMode(ABC):
    """Encapsulates one experimental condition: builds a substrate + compose."""
    name: str

    @abstractmethod
    def build_heartbeat(self, seed: int, coupling: float) -> Heartbeat:
        """Return a Heartbeat instance configured for this control mode."""

    @abstractmethod
    def build_compose(self, seed: int) -> ComposeFunction:
        """Return a ComposeFunction instance configured for this control mode."""

    def post_tick(self, hb: Heartbeat) -> None:
        """Optional hook fired after each Heartbeat.tick().

        Default: no-op. Control 3 uses this to overwrite organ latents.
        """
        return None


_REGISTRY: dict[str, type[ControlMode]] = {}


def register(cls: type[ControlMode]) -> type[ControlMode]:
    _REGISTRY[cls.name] = cls
    return cls


def build_mode(name: str, **kwargs) -> ControlMode:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown control mode: {name!r}")
    return _REGISTRY[name](**kwargs)
