"""
cascade-research Storage Layer

SQLite FTS5-based indexing for multi-KB search and retrieval.
"""

from .database import CascadeDB
from .repository import KBRepository
from .index import IndexManager

__all__ = ['CascadeDB', 'KBRepository', 'IndexManager']
