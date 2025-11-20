"""P1 Synthetic User Behavior Generator."""

from .generator import BehaviorGenerator, EventModel, UserPersona
from .run_simulator import main

__version__ = "0.1.0"
__all__ = ["BehaviorGenerator", "EventModel", "UserPersona", "main"]
