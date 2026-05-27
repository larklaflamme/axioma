"""Control modes: factory mapping a mode name → configured Heartbeat + ComposeFunction."""
from .base import ControlMode, build_mode
from .baseline import BaselineMode
from .control1 import Control1Mode
from .control2 import Control2Mode
from .control3 import Control3Mode
from .control4 import Control4Mode
from .phi_scale import PhiScaleMode
from .phi_scale_reverse import PhiScaleReverseMode

__all__ = [
    "ControlMode",
    "build_mode",
    "BaselineMode",
    "Control1Mode",
    "Control2Mode",
    "Control3Mode",
    "Control4Mode",
    "PhiScaleMode",
    "PhiScaleReverseMode",
]
