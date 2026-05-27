"""Substrate: 5 organs + heartbeat loop."""
from .base import Organ
from .anima import Anima
from .eidolon import Eidolon
from .mneme import Mneme
from .nous import Nous
from .pneuma import Pneuma
from .heartbeat import Heartbeat
from .dynamics import CoupledLatentDynamics

__all__ = [
    "Organ",
    "Anima",
    "Eidolon",
    "Mneme",
    "Nous",
    "Pneuma",
    "Heartbeat",
    "CoupledLatentDynamics",
]
