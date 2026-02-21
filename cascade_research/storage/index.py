"""
Index Manager - Syncs File Storage with SQLite Index

Handles indexing entries from file-based KBs into the SQLite FTS database.
Supports incremental updates based on file modification times.
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import CascadeConfig, KBType, load_config
from ..models import Entry, EventEntry, ResearchEntry
from .database import CascadeDB
from .repository import KBRepository


class IndexManager:
    """
    Manages the SQLite FTS index for all KBs.

    Responsibilities:
    - Full reindexing of KBs
    - Incremental updates based on file changes
    - Index statistics and health checks
    """

    def __init__(self, db: CascadeDB, config: CascadeConfig | None = None):
        self.db = db
        self.config = config or load_config()

    def _entry_to_dict(self, entry: Entry, kb_name: str, file_path: Path) -> dict[str, Any]:
        """Convert an Entry to a dict for database storage."""
        data = {
            'id': entry.id,
            'kb_name': kb_name,
            'entry_type': entry.entry_type,
            'title': entry.title,
            'body': entry.body,
            'summary': entry.summary,
            'file_path': str(file_path),
            'tags': entry.tags,
            'sources': [s.to_dict() for s in entry.sources],
            'links': [l.to_dict() for l in entry.links],
            'created_at': entry.created_at.isoformat() if entry.created_at else None,
            'updated_at': entry.updated_at.isoformat() if entry.updated_at else None,
        }

        # Event-specific fields
        if isinstance(entry, EventEntry):
            data['date'] = entry.date
            data['importance'] = entry.importance
            # Handle status (could be enum, string, or list)
            status = entry.status
            if hasattr(status, 'value'):
                status = status.value
            elif isinstance(status, list):
                status = status[0] if status else None
            data['status'] = status
            # Handle location (could be list)
            location = entry.location
            if isinstance(location, list):
                location = ', '.join(str(loc) for loc in location)
            data['location'] = location
            data['actors'] = entry.actors if isinstance(entry.actors, list) else []

        # Research-specific fields
        elif isinstance(entry, ResearchEntry):
            data['research_status'] = entry.research_status.value if entry.research_status else None
            data['role'] = entry.role
            # Handle era as list or string
            era = entry.era
            if isinstance(era, list):
                era = ', '.join(str(e) for e in era)
            data['era'] = era

        return data

    def index_kb(
        self,
        kb_name: str,
        progress_callback: Callable[[int, int], None] | None = None
    ) -> int:
        """
        Fully reindex a knowledge base.

        Args:
            kb_name: Name of the KB to index
            progress_callback: Optional callback(current, total) for progress updates

        Returns:
            Number of entries indexed
        """
        kb_config = self.config.get_kb(kb_name)
        if not kb_config:
            raise ValueError(f"KB '{kb_name}' not found in config")

        repo = KBRepository(kb_config)

        # Register KB in database
        self.db.register_kb(
            name=kb_name,
            kb_type=kb_config.kb_type,
            path=str(kb_config.path),
            description=kb_config.description
        )

        # Count total files for progress
        total_files = repo.count()
        indexed_count = 0
        error_count = 0

        # Index all entries
        for entry, file_path in repo.list_entries():
            try:
                data = self._entry_to_dict(entry, kb_name, file_path)
                self.db.upsert_entry(data)
                indexed_count += 1

                if progress_callback:
                    progress_callback(indexed_count, total_files)

            except Exception as e:
                print(f"[ERROR] Failed to index {file_path}: {e}")
                error_count += 1

        # Update KB stats
        self.db.update_kb_indexed(kb_name, indexed_count)

        if error_count > 0:
            print(f"[WARN] {error_count} entries failed to index")

        return indexed_count

    def index_all(
        self,
        progress_callback: Callable[[str, int, int], None] | None = None
    ) -> dict[str, int]:
        """
        Index all configured KBs.

        Args:
            progress_callback: Optional callback(kb_name, current, total)

        Returns:
            Dict of kb_name -> entries indexed
        """
        results = {}

        for kb in self.config.knowledge_bases:
            if not kb.path.exists():
                print(f"[WARN] Skipping {kb.name}: path does not exist")
                continue

            def kb_progress(current: int, total: int):
                if progress_callback:
                    progress_callback(kb.name, current, total)

            count = self.index_kb(kb.name, kb_progress)
            results[kb.name] = count

        return results

    def index_entry(self, entry: Entry, kb_name: str, file_path: Path) -> None:
        """Index a single entry."""
        data = self._entry_to_dict(entry, kb_name, file_path)
        self.db.upsert_entry(data)

    def remove_entry(self, entry_id: str, kb_name: str) -> bool:
        """Remove an entry from the index."""
        return self.db.delete_entry(entry_id, kb_name)

    def remove_kb(self, kb_name: str) -> None:
        """Remove a KB and all its entries from the index."""
        self.db.unregister_kb(kb_name)

    def get_index_stats(self) -> dict[str, Any]:
        """Get statistics about the index."""
        stats = {
            'kbs': {},
            'total_entries': 0,
            'total_tags': 0,
            'total_links': 0,
        }

        for kb in self.config.knowledge_bases:
            kb_stats = self.db.get_kb_stats(kb.name)
            if kb_stats:
                stats['kbs'][kb.name] = kb_stats
                stats['total_entries'] += kb_stats.get('actual_count', 0)

        # Get global counts
        row = self.db.conn.execute("SELECT COUNT(*) FROM tag").fetchone()
        stats['total_tags'] = row[0] if row else 0

        row = self.db.conn.execute("SELECT COUNT(*) FROM link").fetchone()
        stats['total_links'] = row[0] if row else 0

        return stats

    def check_health(self) -> dict[str, Any]:
        """
        Check index health and consistency.

        Returns dict with:
        - missing_files: entries in DB but file not found
        - unindexed_files: files not in DB
        - stale_entries: entries where file is newer than index
        """
        health = {
            'missing_files': [],
            'unindexed_files': [],
            'stale_entries': [],
        }

        for kb in self.config.knowledge_bases:
            if not kb.path.exists():
                continue

            repo = KBRepository(kb)

            # Get all indexed entries for this KB
            indexed = {}
            for row in self.db.conn.execute(
                "SELECT id, file_path, indexed_at FROM entry WHERE kb_name = ?",
                (kb.name,)
            ).fetchall():
                indexed[row['id']] = {
                    'file_path': row['file_path'],
                    'indexed_at': row['indexed_at']
                }

            # Check each file
            seen_ids = set()
            for file_path in repo.list_files():
                try:
                    entry_class = EventEntry if kb.kb_type == KBType.EVENTS else ResearchEntry
                    entry = entry_class.load(file_path)
                    seen_ids.add(entry.id)

                    if entry.id not in indexed:
                        health['unindexed_files'].append({
                            'kb': kb.name,
                            'path': str(file_path),
                            'id': entry.id
                        })
                    else:
                        # Check if file is newer than index
                        indexed_at = indexed[entry.id]['indexed_at']
                        if indexed_at:
                            file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                            index_time = datetime.fromisoformat(indexed_at.replace('Z', '+00:00').replace('+00:00', ''))
                            if file_mtime > index_time:
                                health['stale_entries'].append({
                                    'kb': kb.name,
                                    'id': entry.id,
                                    'file_mtime': file_mtime.isoformat(),
                                    'indexed_at': indexed_at
                                })
                except Exception:
                    continue

            # Check for missing files
            for entry_id, info in indexed.items():
                if entry_id not in seen_ids:
                    health['missing_files'].append({
                        'kb': kb.name,
                        'id': entry_id,
                        'path': info['file_path']
                    })

        return health

    def sync_incremental(self, kb_name: str | None = None) -> dict[str, int]:
        """
        Incremental sync: only update changed/new files.

        Returns dict with counts of added, updated, removed entries.
        """
        results = {'added': 0, 'updated': 0, 'removed': 0}

        kbs = [self.config.get_kb(kb_name)] if kb_name else self.config.knowledge_bases
        kbs = [kb for kb in kbs if kb and kb.path.exists()]

        for kb in kbs:
            repo = KBRepository(kb)

            # Get current index state
            indexed = {}
            for row in self.db.conn.execute(
                "SELECT id, file_path, indexed_at FROM entry WHERE kb_name = ?",
                (kb.name,)
            ).fetchall():
                indexed[row['id']] = {
                    'file_path': row['file_path'],
                    'indexed_at': row['indexed_at']
                }

            seen_ids = set()

            # Check each file
            for entry, file_path in repo.list_entries():
                seen_ids.add(entry.id)

                if entry.id not in indexed:
                    # New entry
                    self.index_entry(entry, kb.name, file_path)
                    results['added'] += 1
                else:
                    # Check if updated
                    indexed_at = indexed[entry.id]['indexed_at']
                    if indexed_at:
                        try:
                            file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                            index_time = datetime.fromisoformat(indexed_at.replace('Z', '+00:00').replace('+00:00', ''))
                            if file_mtime > index_time:
                                self.index_entry(entry, kb.name, file_path)
                                results['updated'] += 1
                        except Exception:
                            pass

            # Remove deleted entries
            for entry_id in indexed:
                if entry_id not in seen_ids:
                    self.remove_entry(entry_id, kb.name)
                    results['removed'] += 1

            # Update KB stats
            self.db.update_kb_indexed(kb.name, len(seen_ids))

        return results


def create_index(config: CascadeConfig | None = None) -> IndexManager:
    """Create an IndexManager with default configuration."""
    config = config or load_config()
    db = CascadeDB(config.settings.index_path)
    return IndexManager(db, config)
