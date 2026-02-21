"""
Service Layer for cascade-research

Provides unified business logic extracted from API, CLI, and UI layers.
Eliminates duplication and ensures consistent behavior across interfaces.
"""

from .kb_service import KBService
from .search_service import SearchService

__all__ = ["KBService", "SearchService"]
