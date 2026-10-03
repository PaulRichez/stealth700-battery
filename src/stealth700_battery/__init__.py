"""Read a Turtle Beach Stealth 700 Gen 3 battery level over USB, without Swarm II."""
from .reader import (
    HeadsetStatus,
    diagnostics,
    find_transmitter_path,
    read_battery,
    read_status,
)

__all__ = [
    "HeadsetStatus",
    "read_status",
    "read_battery",
    "find_transmitter_path",
    "diagnostics",
]

__version__ = "0.1.0"
