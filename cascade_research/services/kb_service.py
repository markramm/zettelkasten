"""
Knowledge Base Service

Unified KB operations used by API, CLI, and UI layers.
"""

from datetime import UTC, datetime
from typing import Any

from ..config import CascadeConfig, KBConfig, KBType
from ..models import Entry, EventEntry, ResearchEntry
from ..schema import ResearchStatus
from ..storage.database import CascadeDB
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

    def __init__(self, config: CascadeConfig, db: CascadeDB):
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
                    "type": kb.kb_type.value,
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
            entry_type: Type (event, actor, organization, theme, etc.)
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
        if kb_config.kb_type == KBType.EVENTS:
            entry = EventEntry(
                id=entry_id,
                title=title,
                body=body,
                date=kwargs.get("date"),
                importance=kwargs.get("importance", 3),
                location=kwargs.get("location"),
                status=kwargs.get("status", "confirmed"),
                actors=kwargs.get("actors", []),
                tags=kwargs.get("tags", []),
                summary=kwargs.get("summary", ""),
            )
        else:
            # Parse research status
            status_str = kwargs.get("research_status", "stub")
            try:
                research_status = ResearchStatus(status_str)
            except ValueError:
                research_status = ResearchStatus.STUB

            entry = ResearchEntry(
                id=entry_id,
                title=title,
                body=body,
                entry_subtype=entry_type,
                tags=kwargs.get("tags", []),
                summary=kwargs.get("summary", ""),
                research_status=research_status,
                role=kwargs.get("role", ""),
                era=kwargs.get("era", ""),
            )

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

        # Save to file
        file_path = repo.save(entry)

        # Re-index
        self._index_mgr.index_entry(entry, kb_name, file_path)

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

        # Delete from file system
        file_deleted = repo.delete(entry_id)

        # Delete from index
        self.db.delete_entry(entry_id, kb_name)

        return file_deleted

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
        return self._index_mgr.sync(kb_name)

    def get_index_stats(self) -> dict[str, Any]:
        """Get index statistics."""
        return self._index_mgr.get_index_stats()
