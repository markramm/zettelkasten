"""
cascade-research Storage Layer

SQLAlchemy ORM for standard tables, raw SQL for FTS5/sqlite-vec virtual tables.
"""

from .database import CascadeDB
from .index import IndexManager
from .models import (
    KB,
    Base,
    Entry,
    EntryActor,
    EntryTag,
    EntryVersion,
    Link,
    Repo,
    Source,
    Tag,
    User,
    WorkspaceRepo,
)
from .repository import KBRepository

__all__ = [
    "Base",
    "CascadeDB",
    "Entry",
    "EntryActor",
    "EntryTag",
    "EntryVersion",
    "IndexManager",
    "KB",
    "KBRepository",
    "Link",
    "Repo",
    "Source",
    "Tag",
    "User",
    "WorkspaceRepo",
]
