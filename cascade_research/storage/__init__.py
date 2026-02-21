"""
cascade-research Storage Layer

SQLite FTS5-based indexing for multi-KB search and retrieval.
"""

from .database import CascadeDB
from .index import IndexManager
from .repository import KBRepository

__all__ = ["CascadeDB", "KBRepository", "IndexManager"]
