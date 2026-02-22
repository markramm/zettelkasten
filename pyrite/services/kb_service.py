"""
Knowledge Base Service

Unified KB operations used by API, CLI, and UI layers.
"""

from datetime import UTC, datetime
from typing import Any

from ..config import KBConfig, PyriteConfig
from ..models import Entry, EventEntry
from ..models.core_types import (
    ENTRY_TYPE_REGISTRY,
    OrganizationEntry,
    PersonEntry,
)
from ..models.generic import GenericEntry
from ..storage.database import PyriteDB
from ..storage.index import IndexManager
from ..storage.repository import KBRepository


class KBService:
    """
    Service for KB operations.

    Provides:
    - KB listing and stats
    - Entry CRUD with proper type handling
    - Index synchronization
    """

    def __init__(self, config: PyriteConfig, db: PyriteDB):
        self.config = config
        self.db = db
        self._index_mgr = IndexManager(db, config)

    # =========================================================================
    # KB Operations
    # =========================================================================

    def list_kbs(self) -> list[dict[str, Any]]:
        """List all configured knowledge bases with stats."""
        kbs = []
        for kb in self.config.knowledge_bases:
            stats = self.db.get_kb_stats(kb.name)
            kbs.append(
                {
                    "name": kb.name,
                    "type": kb.kb_type,
                    "path": str(kb.path),
                    "description": kb.description,
                    "read_only": kb.read_only,
                    "entries": stats.get("entry_count", 0) if stats else 0,
                    "indexed": bool(stats.get("last_indexed")) if stats else False,
                    "last_indexed": stats.get("last_indexed") if stats else None,
                }
            )
        return kbs

    def get_kb(self, name: str) -> KBConfig | None:
        """Get KB config by name."""
        return self.config.get_kb(name)

    def get_kb_stats(self, name: str) -> dict[str, Any] | None:
        """Get stats for a specific KB."""
        return self.db.get_kb_stats(name)

    # =========================================================================
    # Entry Operations
    # =========================================================================

    def get_entry(self, entry_id: str, kb_name: str | None = None) -> dict[str, Any] | None:
        """
        Get entry by ID.

        If kb_name not specified, searches all KBs.
        """
        if kb_name:
            result = self.db.get_entry(entry_id, kb_name)
            if result:
                result["outlinks"] = self.db.get_outlinks(entry_id, kb_name)
                result["backlinks"] = self.db.get_backlinks(entry_id, kb_name)
            return result

        # Search all KBs
        for kb in self.config.knowledge_bases:
            result = self.db.get_entry(entry_id, kb.name)
            if result:
                result["outlinks"] = self.db.get_outlinks(entry_id, kb.name)
                result["backlinks"] = self.db.get_backlinks(entry_id, kb.name)
                return result
        return None

    def create_entry(
        self, kb_name: str, entry_id: str, title: str, entry_type: str, body: str = "", **kwargs
    ) -> Entry:
        """
        Create a new entry.

        Args:
            kb_name: Target KB name
            entry_id: Entry ID (filename without .md)
            title: Entry title
            entry_type: Type (event, person, organization, note, topic, etc.)
            body: Markdown body content
            **kwargs: Additional fields (date, importance, tags, etc.)

        Returns:
            Created Entry object

        Raises:
            ValueError: If KB not found or is read-only
        """
        kb_config = self.config.get_kb(kb_name)
        if not kb_config:
            raise ValueError(f"KB not found: {kb_name}")
        if kb_config.read_only:
            raise ValueError(f"KB is read-only: {kb_name}")

        repo = KBRepository(kb_config)

        # Create appropriate entry type
        if entry_type == "event":
            entry = EventEntry(
                id=entry_id,
                title=title,
                body=body,
                date=kwargs.get("date"),
                importance=kwargs.get("importance", 3),
                location=kwargs.get("location"),
                status=kwargs.get("status", "confirmed"),
                participants=kwargs.get("participants", []),
                tags=kwargs.get("tags", []),
                summary=kwargs.get("summary", ""),
            )
        elif entry_type == "person":
            entry = PersonEntry(
                id=entry_id,
                title=title,
                body=body,
                role=kwargs.get("role", ""),
                importance=kwargs.get("importance", 5),
                tags=kwargs.get("tags", []),
                summary=kwargs.get("summary", ""),
            )
        elif entry_type == "organization":
            entry = OrganizationEntry(
                id=entry_id,
                title=title,
                body=body,
                importance=kwargs.get("importance", 5),
                tags=kwargs.get("tags", []),
                summary=kwargs.get("summary", ""),
            )
        elif entry_type in ENTRY_TYPE_REGISTRY:
            cls = ENTRY_TYPE_REGISTRY[entry_type]
            entry = cls(
                id=entry_id,
                title=title,
                body=body,
                tags=kwargs.get("tags", []),
                summary=kwargs.get("summary", ""),
            )
        else:
            # Check plugin registry, then fall back to GenericEntry
            from ..models.core_types import get_entry_class

            resolved_cls = get_entry_class(entry_type)
            if resolved_cls is not GenericEntry:
                entry = resolved_cls.from_frontmatter(
                    {
                        "id": entry_id,
                        "title": title,
                        "type": entry_type,
                        "tags": kwargs.get("tags", []),
                        "summary": kwargs.get("summary", ""),
                        **(kwargs.get("metadata") or {}),
                    },
                    body,
                )
            else:
                entry = GenericEntry(
                    id=entry_id,
                    title=title,
                    body=body,
                    _entry_type=entry_type,
                    tags=kwargs.get("tags", []),
                    summary=kwargs.get("summary", ""),
                    metadata=kwargs.get("metadata", {}),
                )

        # Run before_save hooks
        hook_ctx = {"kb_name": kb_name, "user": "", "operation": "create"}
        entry = self._run_hooks("before_save", entry, hook_ctx)

        # Save to file
        file_path = repo.save(entry)

        # Ensure KB is registered before indexing
        self.db.register_kb(
            name=kb_name,
            kb_type=kb_config.kb_type,
            path=str(kb_config.path),
            description=kb_config.description,
        )

        # Index the entry
        self._index_mgr.index_entry(entry, kb_name, file_path)

        # Run after_save hooks
        self._run_hooks("after_save", entry, hook_ctx)

        return entry

    def update_entry(self, entry_id: str, kb_name: str, **updates) -> Entry:
        """
        Update an existing entry.

        Args:
            entry_id: Entry ID to update
            kb_name: KB containing the entry
            **updates: Fields to update

        Returns:
            Updated Entry object

        Raises:
            ValueError: If entry not found or KB is read-only
        """
        kb_config = self.config.get_kb(kb_name)
        if not kb_config:
            raise ValueError(f"KB not found: {kb_name}")
        if kb_config.read_only:
            raise ValueError(f"KB is read-only: {kb_name}")

        repo = KBRepository(kb_config)
        entry = repo.load(entry_id)
        if not entry:
            raise ValueError(f"Entry not found: {entry_id}")

        # Apply updates
        for key, value in updates.items():
            if hasattr(entry, key):
                setattr(entry, key, value)

        entry.updated_at = datetime.now(UTC)

        # Run before_save hooks
        hook_ctx = {"kb_name": kb_name, "user": "", "operation": "update"}
        entry = self._run_hooks("before_save", entry, hook_ctx)

        # Save to file
        file_path = repo.save(entry)

        # Re-index
        self._index_mgr.index_entry(entry, kb_name, file_path)

        # Run after_save hooks
        self._run_hooks("after_save", entry, hook_ctx)

        return entry

    def delete_entry(self, entry_id: str, kb_name: str) -> bool:
        """
        Delete an entry.

        Returns:
            True if deleted, False if not found

        Raises:
            ValueError: If KB is read-only
        """
        kb_config = self.config.get_kb(kb_name)
        if not kb_config:
            raise ValueError(f"KB not found: {kb_name}")
        if kb_config.read_only:
            raise ValueError(f"KB is read-only: {kb_name}")

        repo = KBRepository(kb_config)

        # Load entry for hooks before deleting
        entry = repo.load(entry_id)
        hook_ctx = {"kb_name": kb_name, "user": "", "operation": "delete"}
        if entry:
            entry = self._run_hooks("before_delete", entry, hook_ctx)

        # Delete from file system
        file_deleted = repo.delete(entry_id)

        # Delete from index
        self.db.delete_entry(entry_id, kb_name)

        # Run after_delete hooks
        if entry:
            self._run_hooks("after_delete", entry, hook_ctx)

        return file_deleted

    # =========================================================================
    # Hooks
    # =========================================================================

    @staticmethod
    def _run_hooks(hook_name: str, entry: Entry, context: dict) -> Entry:
        """Run plugin lifecycle hooks. Returns the (possibly modified) entry."""
        try:
            from ..plugins import get_registry

            return get_registry().run_hooks(hook_name, entry, context)
        except Exception:
            return entry

    # =========================================================================
    # Index Operations
    # =========================================================================

    def sync_index(self, kb_name: str | None = None) -> dict[str, Any]:
        """
        Synchronize index with file system.

        Args:
            kb_name: Specific KB to sync, or None for all

        Returns:
            Sync statistics
        """
        return self._index_mgr.sync_incremental(kb_name)

    def get_index_stats(self) -> dict[str, Any]:
        """Get index statistics."""
        return self._index_mgr.get_index_stats()
