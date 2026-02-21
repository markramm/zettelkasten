"""
cascade-research Models

Entry types for different KB types.
"""

from .base import Entry
from .event import EventEntry
from .research import ResearchEntry

__all__ = ["Entry", "EventEntry", "ResearchEntry"]
