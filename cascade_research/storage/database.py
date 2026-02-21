"""
SQLite Database with FTS5 for Multi-KB Search

Provides full-text search across multiple knowledge bases with:
- FTS5 for fast text search with ranking
- KB-aware indexing (entries tagged by KB)
- Support for both Events and Research entry types
- Relationship/link indexing for graph queries
- Tag-based filtering

Architecture note: LobeHub uses PGVector for semantic search with embeddings.
We use SQLite FTS5 for now (simpler, local-first) but the schema is designed
to support adding vector embeddings later via sqlite-vss or similar.
See: https://github.com/lobehub/lobe-chat (RAG pipeline architecture)
"""

import sqlite3
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ..config import KBType
from .migrations import MigrationManager

# Register explicit adapters to avoid Python 3.12+ deprecation warnings
# (the default date/datetime adapters were deprecated in 3.12)
sqlite3.register_adapter(datetime, lambda dt: dt.isoformat())
sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_converter("timestamp", lambda b: datetime.fromisoformat(b.decode()))


class CascadeDB:
    """
    SQLite database for indexing multiple knowledge bases.

    Supports:
    - Full-text search across all KBs or filtered by KB/type
    - Entry metadata storage (titles, summaries, dates)
    - Tag indexing with many-to-many relationships
    - Link/relationship storage for graph queries
    - KB-aware partitioning
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self._run_migrations()

    def _init_schema(self):
        """Initialize database schema with FTS5."""
        c = self.conn.cursor()
        c.execute("PRAGMA foreign_keys = ON;")
        c.execute("PRAGMA journal_mode = WAL;")
        c.execute("PRAGMA synchronous = NORMAL;")

        c.executescript("""
        -- Knowledge bases registry
        CREATE TABLE IF NOT EXISTS kb (
            name TEXT PRIMARY KEY,
            kb_type TEXT NOT NULL,  -- 'events' or 'research'
            path TEXT NOT NULL,
            description TEXT,
            last_indexed TEXT,
            entry_count INTEGER DEFAULT 0
        );

        -- Main entries table (events and research entries)
        CREATE TABLE IF NOT EXISTS entry (
            id TEXT NOT NULL,
            kb_name TEXT NOT NULL,
            entry_type TEXT NOT NULL,  -- 'event', 'actor', 'organization', etc.
            title TEXT NOT NULL,
            body TEXT,
            summary TEXT,
            file_path TEXT,

            -- Event-specific fields
            date TEXT,  -- canonical date for events (YYYY-MM-DD)
            importance INTEGER,
            status TEXT,  -- confirmed, disputed, alleged, rumored
            location TEXT,

            -- Research-specific fields
            research_status TEXT,  -- stub, partial, draft, complete, published
            role TEXT,  -- for actors
            era TEXT,

            -- Timestamps
            created_at TEXT,
            updated_at TEXT,
            indexed_at TEXT DEFAULT CURRENT_TIMESTAMP,

            PRIMARY KEY (id, kb_name),
            FOREIGN KEY (kb_name) REFERENCES kb(name) ON DELETE CASCADE
        );

        -- Full-text search index
        CREATE VIRTUAL TABLE IF NOT EXISTS entry_fts USING fts5(
            id,
            kb_name,
            entry_type,
            title,
            body,
            summary,
            location,
            content='entry',
            content_rowid='rowid',
            tokenize='porter unicode61'
        );

        -- FTS triggers for automatic sync
        CREATE TRIGGER IF NOT EXISTS entry_ai AFTER INSERT ON entry BEGIN
            INSERT INTO entry_fts(rowid, id, kb_name, entry_type, title, body, summary, location)
            VALUES (new.rowid, new.id, new.kb_name, new.entry_type, new.title,
                    COALESCE(new.body, ''), COALESCE(new.summary, ''), COALESCE(new.location, ''));
        END;

        CREATE TRIGGER IF NOT EXISTS entry_ad AFTER DELETE ON entry BEGIN
            INSERT INTO entry_fts(entry_fts, rowid, id, kb_name, entry_type, title, body, summary, location)
            VALUES('delete', old.rowid, old.id, old.kb_name, old.entry_type, old.title,
                   COALESCE(old.body, ''), COALESCE(old.summary, ''), COALESCE(old.location, ''));
        END;

        CREATE TRIGGER IF NOT EXISTS entry_au AFTER UPDATE ON entry BEGIN
            INSERT INTO entry_fts(entry_fts, rowid, id, kb_name, entry_type, title, body, summary, location)
            VALUES('delete', old.rowid, old.id, old.kb_name, old.entry_type, old.title,
                   COALESCE(old.body, ''), COALESCE(old.summary, ''), COALESCE(old.location, ''));
            INSERT INTO entry_fts(rowid, id, kb_name, entry_type, title, body, summary, location)
            VALUES (new.rowid, new.id, new.kb_name, new.entry_type, new.title,
                    COALESCE(new.body, ''), COALESCE(new.summary, ''), COALESCE(new.location, ''));
        END;

        -- Tags table
        CREATE TABLE IF NOT EXISTS tag (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tag_name ON tag(name);

        -- Entry-tag junction table
        CREATE TABLE IF NOT EXISTS entry_tag (
            entry_id TEXT NOT NULL,
            kb_name TEXT NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY (entry_id, kb_name, tag_id),
            FOREIGN KEY (entry_id, kb_name) REFERENCES entry(id, kb_name) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tag(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_entry_tag_entry ON entry_tag(entry_id, kb_name);
        CREATE INDEX IF NOT EXISTS idx_entry_tag_tag ON entry_tag(tag_id);

        -- Actors mentioned in entries (for events)
        CREATE TABLE IF NOT EXISTS entry_actor (
            entry_id TEXT NOT NULL,
            kb_name TEXT NOT NULL,
            actor_name TEXT NOT NULL,
            PRIMARY KEY (entry_id, kb_name, actor_name),
            FOREIGN KEY (entry_id, kb_name) REFERENCES entry(id, kb_name) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_entry_actor_actor ON entry_actor(actor_name);

        -- Links/relationships between entries
        CREATE TABLE IF NOT EXISTS link (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            source_kb TEXT NOT NULL,
            target_id TEXT NOT NULL,
            target_kb TEXT NOT NULL,
            relation TEXT NOT NULL,
            inverse_relation TEXT NOT NULL,
            note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_id, source_kb) REFERENCES entry(id, kb_name) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_link_source ON link(source_id, source_kb);
        CREATE INDEX IF NOT EXISTS idx_link_target ON link(target_id, target_kb);
        CREATE INDEX IF NOT EXISTS idx_link_relation ON link(relation);

        -- Sources/citations
        CREATE TABLE IF NOT EXISTS source (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id TEXT NOT NULL,
            kb_name TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT,
            outlet TEXT,
            date TEXT,
            verified INTEGER DEFAULT 0,
            FOREIGN KEY (entry_id, kb_name) REFERENCES entry(id, kb_name) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_source_entry ON source(entry_id, kb_name);
        CREATE INDEX IF NOT EXISTS idx_source_url ON source(url);
        """)

        self.conn.commit()

    def _run_migrations(self):
        """Run any pending database migrations."""
        mgr = MigrationManager(self.conn)
        pending = mgr.get_pending_migrations()
        if pending:
            mgr.migrate()

    def get_schema_version(self) -> int:
        """Get current schema version."""
        mgr = MigrationManager(self.conn)
        return mgr.get_current_version()

    def get_migration_status(self) -> dict:
        """Get migration status including pending migrations."""
        mgr = MigrationManager(self.conn)
        return mgr.status()

    def close(self):
        """Close database connection."""
        self.conn.close()

    @contextmanager
    def transaction(self):
        """Context manager for transactions."""
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # =========================================================================
    # KB Management
    # =========================================================================

    def register_kb(self, name: str, kb_type: KBType, path: str, description: str = "") -> None:
        """Register a KB in the index."""
        self.conn.execute(
            """
            INSERT INTO kb (name, kb_type, path, description)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                kb_type = excluded.kb_type,
                path = excluded.path,
                description = excluded.description
        """,
            (name, kb_type.value, path, description),
        )
        self.conn.commit()

    def unregister_kb(self, name: str) -> None:
        """Remove a KB and all its entries from the index."""
        self.conn.execute("DELETE FROM kb WHERE name = ?", (name,))
        self.conn.commit()

    def get_kb_stats(self, name: str) -> dict[str, Any] | None:
        """Get statistics for a KB."""
        row = self.conn.execute(
            """
            SELECT k.*, COUNT(e.id) as actual_count
            FROM kb k
            LEFT JOIN entry e ON k.name = e.kb_name
            WHERE k.name = ?
            GROUP BY k.name
        """,
            (name,),
        ).fetchone()
        return dict(row) if row else None

    def update_kb_indexed(self, name: str, entry_count: int) -> None:
        """Update KB last indexed time and count."""
        self.conn.execute(
            """
            UPDATE kb SET last_indexed = ?, entry_count = ?
            WHERE name = ?
        """,
            (datetime.now(UTC).isoformat(), entry_count, name),
        )
        self.conn.commit()

    # =========================================================================
    # Entry CRUD
    # =========================================================================

    def upsert_entry(self, entry_data: dict[str, Any]) -> None:
        """Insert or update an entry."""
        c = self.conn.cursor()

        # Main entry
        c.execute(
            """
            INSERT INTO entry (
                id, kb_name, entry_type, title, body, summary, file_path,
                date, importance, status, location,
                research_status, role, era,
                created_at, updated_at, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id, kb_name) DO UPDATE SET
                entry_type = excluded.entry_type,
                title = excluded.title,
                body = excluded.body,
                summary = excluded.summary,
                file_path = excluded.file_path,
                date = excluded.date,
                importance = excluded.importance,
                status = excluded.status,
                location = excluded.location,
                research_status = excluded.research_status,
                role = excluded.role,
                era = excluded.era,
                updated_at = excluded.updated_at,
                indexed_at = CURRENT_TIMESTAMP
        """,
            (
                entry_data.get("id"),
                entry_data.get("kb_name"),
                entry_data.get("entry_type"),
                entry_data.get("title"),
                entry_data.get("body"),
                entry_data.get("summary"),
                entry_data.get("file_path"),
                entry_data.get("date"),
                entry_data.get("importance"),
                entry_data.get("status"),
                entry_data.get("location"),
                entry_data.get("research_status"),
                entry_data.get("role"),
                entry_data.get("era"),
                entry_data.get("created_at"),
                entry_data.get("updated_at"),
            ),
        )

        entry_id = entry_data.get("id")
        kb_name = entry_data.get("kb_name")

        # Tags
        c.execute("DELETE FROM entry_tag WHERE entry_id = ? AND kb_name = ?", (entry_id, kb_name))
        for tag in entry_data.get("tags", []):
            c.execute("INSERT OR IGNORE INTO tag (name) VALUES (?)", (tag,))
            tag_id = c.execute("SELECT id FROM tag WHERE name = ?", (tag,)).fetchone()[0]
            c.execute(
                "INSERT INTO entry_tag (entry_id, kb_name, tag_id) VALUES (?, ?, ?)",
                (entry_id, kb_name, tag_id),
            )

        # Actors (for events)
        c.execute("DELETE FROM entry_actor WHERE entry_id = ? AND kb_name = ?", (entry_id, kb_name))
        for actor in entry_data.get("actors", []):
            c.execute(
                "INSERT INTO entry_actor (entry_id, kb_name, actor_name) VALUES (?, ?, ?)",
                (entry_id, kb_name, actor),
            )

        # Sources
        c.execute("DELETE FROM source WHERE entry_id = ? AND kb_name = ?", (entry_id, kb_name))
        for src in entry_data.get("sources", []):
            c.execute(
                """
                INSERT INTO source (entry_id, kb_name, title, url, outlet, date, verified)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    entry_id,
                    kb_name,
                    src.get("title", ""),
                    src.get("url", ""),
                    src.get("outlet", ""),
                    src.get("date", ""),
                    1 if src.get("verified") else 0,
                ),
            )

        # Links
        c.execute("DELETE FROM link WHERE source_id = ? AND source_kb = ?", (entry_id, kb_name))
        for link in entry_data.get("links", []):
            from ..schema import get_inverse_relation

            relation = link.get("relation", "related_to")
            inverse = get_inverse_relation(relation)
            target_kb = link.get("kb", kb_name)  # Default to same KB
            c.execute(
                """
                INSERT INTO link (source_id, source_kb, target_id, target_kb, relation, inverse_relation, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    entry_id,
                    kb_name,
                    link.get("target"),
                    target_kb,
                    relation,
                    inverse,
                    link.get("note", ""),
                ),
            )

        self.conn.commit()

    def delete_entry(self, entry_id: str, kb_name: str) -> bool:
        """Delete an entry. Returns True if deleted."""
        result = self.conn.execute(
            "DELETE FROM entry WHERE id = ? AND kb_name = ?", (entry_id, kb_name)
        )
        self.conn.commit()
        return result.rowcount > 0

    def get_entry(self, entry_id: str, kb_name: str) -> dict[str, Any] | None:
        """Get a single entry with all metadata."""
        row = self.conn.execute(
            "SELECT * FROM entry WHERE id = ? AND kb_name = ?", (entry_id, kb_name)
        ).fetchone()

        if not row:
            return None

        entry = dict(row)

        # Get tags
        entry["tags"] = [
            r["name"]
            for r in self.conn.execute(
                """
            SELECT t.name FROM tag t
            JOIN entry_tag et ON t.id = et.tag_id
            WHERE et.entry_id = ? AND et.kb_name = ?
        """,
                (entry_id, kb_name),
            ).fetchall()
        ]

        # Get actors
        entry["actors"] = [
            r["actor_name"]
            for r in self.conn.execute(
                "SELECT actor_name FROM entry_actor WHERE entry_id = ? AND kb_name = ?",
                (entry_id, kb_name),
            ).fetchall()
        ]

        # Get sources
        entry["sources"] = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM source WHERE entry_id = ? AND kb_name = ?", (entry_id, kb_name)
            ).fetchall()
        ]

        # Get outgoing links
        entry["links"] = [
            dict(r)
            for r in self.conn.execute(
                "SELECT target_id, target_kb, relation, note FROM link WHERE source_id = ? AND source_kb = ?",
                (entry_id, kb_name),
            ).fetchall()
        ]

        return entry

    # =========================================================================
    # Search
    # =========================================================================

    def search(
        self,
        query: str,
        kb_name: str | None = None,
        entry_type: str | None = None,
        tags: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Full-text search across entries.

        Args:
            query: FTS5 search query (supports AND, OR, NOT, phrases, prefix*)
            kb_name: Filter to specific KB
            entry_type: Filter by entry type (event, actor, organization, etc.)
            tags: Filter by tags (AND logic)
            date_from: Filter events from this date (YYYY-MM-DD)
            date_to: Filter events until this date (YYYY-MM-DD)
            limit: Max results
            offset: Pagination offset

        Returns:
            List of matching entries with snippets and rank
        """
        # Build the query
        sql = """
            SELECT
                e.*,
                snippet(entry_fts, 4, '<mark>', '</mark>', '...', 32) as snippet,
                bm25(entry_fts) as rank
            FROM entry_fts
            JOIN entry e ON entry_fts.rowid = e.rowid
            WHERE entry_fts MATCH ?
        """
        params: list[Any] = [query]

        if kb_name:
            sql += " AND e.kb_name = ?"
            params.append(kb_name)

        if entry_type:
            sql += " AND e.entry_type = ?"
            params.append(entry_type)

        if date_from:
            sql += " AND e.date >= ?"
            params.append(date_from)

        if date_to:
            sql += " AND e.date <= ?"
            params.append(date_to)

        if tags:
            # Subquery for tag filtering (AND logic - must have all tags)
            tag_placeholders = ",".join(["?"] * len(tags))
            sql += f"""
                AND e.id IN (
                    SELECT et.entry_id FROM entry_tag et
                    JOIN tag t ON et.tag_id = t.id
                    WHERE t.name IN ({tag_placeholders})
                    GROUP BY et.entry_id, et.kb_name
                    HAVING COUNT(DISTINCT t.name) = ?
                )
            """
            params.extend(tags)
            params.append(len(tags))

        sql += " ORDER BY rank LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def search_by_tag(
        self, tag: str, kb_name: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Search entries by tag."""
        sql = """
            SELECT e.* FROM entry e
            JOIN entry_tag et ON e.id = et.entry_id AND e.kb_name = et.kb_name
            JOIN tag t ON et.tag_id = t.id
            WHERE t.name = ?
        """
        params: list[Any] = [tag]

        if kb_name:
            sql += " AND e.kb_name = ?"
            params.append(kb_name)

        sql += " ORDER BY e.date DESC, e.title LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def search_by_actor(
        self, actor_name: str, kb_name: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Search entries mentioning an actor."""
        sql = """
            SELECT e.* FROM entry e
            JOIN entry_actor ea ON e.id = ea.entry_id AND e.kb_name = ea.kb_name
            WHERE ea.actor_name LIKE ?
        """
        params: list[Any] = [f"%{actor_name}%"]

        if kb_name:
            sql += " AND e.kb_name = ?"
            params.append(kb_name)

        sql += " ORDER BY e.date DESC, e.title LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def search_by_date_range(
        self, date_from: str, date_to: str, kb_name: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Search events within a date range."""
        sql = """
            SELECT * FROM entry
            WHERE date >= ? AND date <= ?
        """
        params: list[Any] = [date_from, date_to]

        if kb_name:
            sql += " AND kb_name = ?"
            params.append(kb_name)

        sql += " ORDER BY date ASC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # =========================================================================
    # Graph Queries (Links)
    # =========================================================================

    def get_backlinks(self, entry_id: str, kb_name: str) -> list[dict[str, Any]]:
        """Get entries that link TO this entry."""
        rows = self.conn.execute(
            """
            SELECT e.id, e.kb_name, e.title, e.entry_type, l.inverse_relation as relation, l.note
            FROM link l
            JOIN entry e ON l.source_id = e.id AND l.source_kb = e.kb_name
            WHERE l.target_id = ? AND l.target_kb = ?
        """,
            (entry_id, kb_name),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_outlinks(self, entry_id: str, kb_name: str) -> list[dict[str, Any]]:
        """Get entries that this entry links TO."""
        rows = self.conn.execute(
            """
            SELECT l.target_id as id, l.target_kb as kb_name, e.title, e.entry_type, l.relation, l.note
            FROM link l
            LEFT JOIN entry e ON l.target_id = e.id AND l.target_kb = e.kb_name
            WHERE l.source_id = ? AND l.source_kb = ?
        """,
            (entry_id, kb_name),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_related(self, entry_id: str, kb_name: str, depth: int = 1) -> list[dict[str, Any]]:
        """Get related entries (both directions) up to N hops."""
        # For now, just do 1 hop (direct connections)
        backlinks = self.get_backlinks(entry_id, kb_name)
        outlinks = self.get_outlinks(entry_id, kb_name)

        related = []
        seen = set()

        for link in backlinks + outlinks:
            key = (link.get("id"), link.get("kb_name"))
            if key not in seen and key != (entry_id, kb_name):
                seen.add(key)
                related.append(link)

        return related

    # =========================================================================
    # Analytics
    # =========================================================================

    def get_all_tags(self, kb_name: str | None = None) -> list[tuple[str, int]]:
        """Get all tags with counts."""
        if kb_name:
            rows = self.conn.execute(
                """
                SELECT t.name, COUNT(*) as count
                FROM tag t
                JOIN entry_tag et ON t.id = et.tag_id
                WHERE et.kb_name = ?
                GROUP BY t.name
                ORDER BY count DESC
            """,
                (kb_name,),
            ).fetchall()
        else:
            rows = self.conn.execute("""
                SELECT t.name, COUNT(*) as count
                FROM tag t
                JOIN entry_tag et ON t.id = et.tag_id
                GROUP BY t.name
                ORDER BY count DESC
            """).fetchall()
        return [(r["name"], r["count"]) for r in rows]

    def get_most_linked(self, kb_name: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Get entries with most incoming links (most referenced)."""
        sql = """
            SELECT e.id, e.kb_name, e.title, e.entry_type, COUNT(l.id) as link_count
            FROM entry e
            LEFT JOIN link l ON e.id = l.target_id AND e.kb_name = l.target_kb
        """
        params: list[Any] = []

        if kb_name:
            sql += " WHERE e.kb_name = ?"
            params.append(kb_name)

        sql += " GROUP BY e.id, e.kb_name ORDER BY link_count DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_orphans(self, kb_name: str | None = None) -> list[dict[str, Any]]:
        """Get entries with no links (neither incoming nor outgoing)."""
        sql = """
            SELECT e.id, e.kb_name, e.title, e.entry_type
            FROM entry e
            WHERE e.id NOT IN (SELECT source_id FROM link WHERE source_kb = e.kb_name)
              AND e.id NOT IN (SELECT target_id FROM link WHERE target_kb = e.kb_name)
        """
        params: list[Any] = []

        if kb_name:
            sql += " AND e.kb_name = ?"
            params.append(kb_name)

        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_timeline(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        min_importance: int = 1,
        kb_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get timeline events ordered by date."""
        sql = """
            SELECT id, kb_name, title, date, importance, location, summary
            FROM entry
            WHERE date IS NOT NULL AND importance >= ?
        """
        params: list[Any] = [min_importance]

        if kb_name:
            sql += " AND kb_name = ?"
            params.append(kb_name)

        if date_from:
            sql += " AND date >= ?"
            params.append(date_from)

        if date_to:
            sql += " AND date <= ?"
            params.append(date_to)

        sql += " ORDER BY date ASC"

        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
