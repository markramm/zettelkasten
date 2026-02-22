"""
Service Layer for cascade-research

Provides unified business logic extracted from API, CLI, and UI layers.
Eliminates duplication and ensures consistent behavior across interfaces.
"""

from .kb_service import KBService
from .query_expansion_service import QueryExpansionService
from .search_service import SearchMode, SearchService

__all__ = ["KBService", "QueryExpansionService", "SearchMode", "SearchService"]
