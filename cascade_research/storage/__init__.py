"""
cascade-research Storage Layer

SQLAlchemy ORM for standard tables, raw SQL for FTS5/sqlite-vec virtual tables.
"""

from .database import CascadeDB
from .index import IndexManager
from .models import KB, Base, Entry, EntryActor, EntryTag, Link, Source, Tag
from .repository import KBRepository

__all__ = [
    "Base",
    "CascadeDB",
    "Entry",
    "EntryActor",
    "EntryTag",
    "IndexManager",
    "KB",
    "KBRepository",
    "Link",
    "Source",
    "Tag",
]
