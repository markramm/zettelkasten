"""
SQLite Database with FTS5 for Multi-KB Search

Uses SQLAlchemy ORM for standard tables and raw SQL for virtual tables
(FTS5, sqlite-vec). Provides full-text search across multiple knowledge
bases with KB-aware indexing.
"""

import sqlite3
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from .models import KB, Base
from .virtual_tables import create_fts_tables, create_vec_table

# Register explicit adapters to avoid Python 3.12+ deprecation warnings
sqlite3.register_adapter(datetime, lambda dt: dt.isoformat())
sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_converter("timestamp", lambda b: datetime.fromisoformat(b.decode()))


class PyriteDB:
    """
    SQLite database for indexing multiple knowledge bases.

    Uses SQLAlchemy ORM for standard tables and raw SQL for FTS5/sqlite-vec
    virtual tables. Provides full-text search, tag/actor analytics, link
    graph queries, and timeline operations.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create SQLAlchemy engine
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )

        # Set SQLite pragmas on every connection
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
            cursor.close()

        # Create ORM tables
        Base.metadata.create_all(self.engine)

        # Create session
        self.session = Session(self.engine)

        # Get raw connection for virtual tables and extensions
        raw_conn = self.engine.raw_connection()
        self._raw_conn = raw_conn.driver_connection
        self._raw_conn.row_factory = sqlite3.Row

        # Load extensions and create virtual tables
        self._load_extensions()
        create_fts_tables(self._raw_conn)
        if self.vec_available:
            create_vec_table(self._raw_conn)

        self._run_migrations()
        self._create_plugin_tables()

    def _create_plugin_tables(self):
        """Create custom tables defined by plugins."""
        try:
            from ..plugins import get_registry

            for table_def in get_registry().get_all_db_tables():
                self._create_table_from_def(table_def)
        except Exception:
            pass

    def _create_table_from_def(self, table_def: dict):
        """Create a single table from a plugin table definition."""
        name = table_def["name"]
        columns = table_def.get("columns", [])
        indexes = table_def.get("indexes", [])

        # Build column definitions
        col_defs = []
        for col in columns:
            parts = [col["name"], col["type"]]
            if col.get("primary_key"):
                parts.append("PRIMARY KEY")
                if col["type"] == "INTEGER":
                    parts.append("AUTOINCREMENT")
            if col.get("nullable") is False:
                parts.append("NOT NULL")
            if "default" in col:
                parts.append(f"DEFAULT {col['default']}")
            col_defs.append(" ".join(parts))

        # Foreign keys
        for fk in table_def.get("foreign_keys", []):
            col_defs.append(f"FOREIGN KEY ({fk['column']}) REFERENCES {fk['references']}")

        sql = f"CREATE TABLE IF NOT EXISTS {name} ({', '.join(col_defs)})"
        self._raw_conn.execute(sql)

        # Create indexes
        for idx in indexes:
            cols = ", ".join(idx["columns"])
            unique = "UNIQUE " if idx.get("unique") else ""
            idx_name = f"idx_{name}_{'_'.join(idx['columns'])}"
            self._raw_conn.execute(
                f"CREATE {unique}INDEX IF NOT EXISTS {idx_name} ON {name} ({cols})"
            )

        self._raw_conn.commit()

    @property
    def conn(self):
        """Backward-compat: returns raw sqlite3 connection for virtual table ops."""
        return self._raw_conn

    def _load_extensions(self):
        """Try to load sqlite-vec extension for vector search."""
        self.vec_available = False
        try:
            import sqlite_vec

            self._raw_conn.enable_load_extension(True)
            sqlite_vec.load(self._raw_conn)
            self._raw_conn.enable_load_extension(False)
            self.vec_available = True
        except (ImportError, Exception):
            pass

    def _run_migrations(self):
        """Run any pending database migrations using legacy MigrationManager."""
        # Bridge: apply legacy migrations if schema_version table exists or is needed
        from .migrations import MigrationManager

        mgr = MigrationManager(self._raw_conn)
        pending = mgr.get_pending_migrations()
        if pending:
            mgr.migrate()
        # Create vec_entry table if sqlite-vec is available and table doesn't exist
        if self.vec_available:
            create_vec_table(self._raw_conn)

    def get_schema_version(self) -> int:
        """Get current schema version."""
        from .migrations import MigrationManager

        mgr = MigrationManager(self._raw_conn)
        return mgr.get_current_version()

    def get_migration_status(self) -> dict:
        """Get migration status including pending migrations."""
        from .migrations import MigrationManager

        mgr = MigrationManager(self._raw_conn)
        return mgr.status()

    def close(self):
        """Close database connection."""
        self.session.close()
        self.engine.dispose()

    @contextmanager
    def transaction(self):
        """Context manager for transactions."""
        try:
            yield self.session
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    # =========================================================================
    # KB Management
    # =========================================================================

    def register_kb(self, name: str, kb_type: str, path: str, description: str = "") -> None:
        """Register a KB in the index."""
        # Accept either string or enum
        type_str = kb_type.value if hasattr(kb_type, "value") else kb_type
        existing = self.session.get(KB, name)
        if existing:
            existing.kb_type = type_str
            existing.path = path
            existing.description = description
        else:
            kb = KB(name=name, kb_type=type_str, path=path, description=description)
            self.session.add(kb)
        self.session.commit()

    def unregister_kb(self, name: str) -> None:
        """Remove a KB and all its entries from the index."""
        kb = self.session.get(KB, name)
        if kb:
            self.session.delete(kb)
            self.session.commit()

    def get_kb_stats(self, name: str) -> dict[str, Any] | None:
        """Get statistics for a KB."""
        row = self.session.execute(
            text("""
                SELECT k.*, COUNT(e.id) as actual_count
                FROM kb k
                LEFT JOIN entry e ON k.name = e.kb_name
                WHERE k.name = :name
                GROUP BY k.name
            """),
            {"name": name},
        ).fetchone()
        if row is None:
            return None
        return dict(row._mapping)

    def update_kb_indexed(self, name: str, entry_count: int) -> None:
        """Update KB last indexed time and count."""
        kb = self.session.get(KB, name)
        if kb:
            kb.last_indexed = datetime.now(UTC).isoformat()
            kb.entry_count = entry_count
            self.session.commit()

    # =========================================================================
    # Entry CRUD
    # =========================================================================

    def upsert_entry(self, entry_data: dict[str, Any]) -> None:
        """Insert or update an entry. Extension fields go into metadata JSON."""
        import json

        entry_id = entry_data.get("id")
        kb_name = entry_data.get("kb_name")

        # Serialize metadata dict to JSON
        metadata = entry_data.get("metadata", {})
        metadata_json = json.dumps(metadata) if metadata else "{}"

        # Use raw SQL for the main entry upsert
        self._raw_conn.execute(
            """
            INSERT INTO entry (
                id, kb_name, entry_type, title, body, summary, file_path,
                date, importance, status, location, metadata,
                created_at, updated_at, indexed_at,
                created_by, modified_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
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
                metadata = excluded.metadata,
                updated_at = excluded.updated_at,
                indexed_at = CURRENT_TIMESTAMP,
                created_by = COALESCE(entry.created_by, excluded.created_by),
                modified_by = COALESCE(excluded.modified_by, entry.modified_by)
            """,
            (
                entry_id,
                kb_name,
                entry_data.get("entry_type"),
                entry_data.get("title"),
                entry_data.get("body"),
                entry_data.get("summary"),
                entry_data.get("file_path"),
                entry_data.get("date"),
                entry_data.get("importance"),
                entry_data.get("status"),
                entry_data.get("location"),
                metadata_json,
                entry_data.get("created_at"),
                entry_data.get("updated_at"),
                entry_data.get("created_by"),
                entry_data.get("modified_by"),
            ),
        )

        # Tags
        self._raw_conn.execute(
            "DELETE FROM entry_tag WHERE entry_id = ? AND kb_name = ?", (entry_id, kb_name)
        )
        for tag_name in entry_data.get("tags", []):
            self._raw_conn.execute("INSERT OR IGNORE INTO tag (name) VALUES (?)", (tag_name,))
            tag_row = self._raw_conn.execute(
                "SELECT id FROM tag WHERE name = ?", (tag_name,)
            ).fetchone()
            tag_id = tag_row[0]
            self._raw_conn.execute(
                "INSERT INTO entry_tag (entry_id, kb_name, tag_id) VALUES (?, ?, ?)",
                (entry_id, kb_name, tag_id),
            )

        # Sources
        self._raw_conn.execute(
            "DELETE FROM source WHERE entry_id = ? AND kb_name = ?", (entry_id, kb_name)
        )
        for src in entry_data.get("sources", []):
            self._raw_conn.execute(
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
        self._raw_conn.execute(
            "DELETE FROM link WHERE source_id = ? AND source_kb = ?", (entry_id, kb_name)
        )
        for link in entry_data.get("links", []):
            from ..schema import get_inverse_relation

            relation = link.get("relation", "related_to")
            inverse = get_inverse_relation(relation)
            target_kb = link.get("kb", kb_name)
            self._raw_conn.execute(
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

        self._raw_conn.commit()

    def delete_entry(self, entry_id: str, kb_name: str) -> bool:
        """Delete an entry. Returns True if deleted."""
        result = self._raw_conn.execute(
            "DELETE FROM entry WHERE id = ? AND kb_name = ?", (entry_id, kb_name)
        )
        self._raw_conn.commit()
        return result.rowcount > 0

    def get_entry(self, entry_id: str, kb_name: str) -> dict[str, Any] | None:
        """Get a single entry with all metadata."""
        row = self._raw_conn.execute(
            "SELECT * FROM entry WHERE id = ? AND kb_name = ?", (entry_id, kb_name)
        ).fetchone()

        if not row:
            return None

        entry = dict(row)

        # Get tags
        entry["tags"] = [
            r["name"]
            for r in self._raw_conn.execute(
                """
                SELECT t.name FROM tag t
                JOIN entry_tag et ON t.id = et.tag_id
                WHERE et.entry_id = ? AND et.kb_name = ?
                """,
                (entry_id, kb_name),
            ).fetchall()
        ]

        # Get sources
        entry["sources"] = [
            dict(r)
            for r in self._raw_conn.execute(
                "SELECT * FROM source WHERE entry_id = ? AND kb_name = ?", (entry_id, kb_name)
            ).fetchall()
        ]

        # Get outgoing links
        entry["links"] = [
            dict(r)
            for r in self._raw_conn.execute(
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
        """Full-text search across entries using FTS5."""
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

        rows = self._raw_conn.execute(sql, params).fetchall()
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

        rows = self._raw_conn.execute(sql, params).fetchall()
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

        rows = self._raw_conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # =========================================================================
    # Graph Queries (Links)
    # =========================================================================

    def get_backlinks(self, entry_id: str, kb_name: str) -> list[dict[str, Any]]:
        """Get entries that link TO this entry."""
        rows = self._raw_conn.execute(
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
        rows = self._raw_conn.execute(
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
            rows = self._raw_conn.execute(
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
            rows = self._raw_conn.execute("""
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

        rows = self._raw_conn.execute(sql, params).fetchall()
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

        rows = self._raw_conn.execute(sql, params).fetchall()
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

        rows = self._raw_conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # =========================================================================
    # Convenience methods (replace external db.conn.execute() calls)
    # =========================================================================

    def count_entries(self, kb_name: str | None = None) -> int:
        """Count entries, optionally filtered by KB."""
        if kb_name:
            row = self._raw_conn.execute(
                "SELECT COUNT(*) FROM entry WHERE kb_name = ?", (kb_name,)
            ).fetchone()
        else:
            row = self._raw_conn.execute("SELECT COUNT(*) FROM entry").fetchone()
        return row[0] if row else 0

    def get_entries_for_indexing(self, kb_name: str) -> list[dict[str, Any]]:
        """Get entry id, file_path, indexed_at for incremental indexing."""
        rows = self._raw_conn.execute(
            "SELECT id, file_path, indexed_at FROM entry WHERE kb_name = ?", (kb_name,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_global_counts(self) -> dict[str, int]:
        """Get global tag and link counts."""
        tag_row = self._raw_conn.execute("SELECT COUNT(*) FROM tag").fetchone()
        link_row = self._raw_conn.execute("SELECT COUNT(*) FROM link").fetchone()
        return {
            "total_tags": tag_row[0] if tag_row else 0,
            "total_links": link_row[0] if link_row else 0,
        }

    def get_tags_as_dicts(
        self, kb_name: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get tags with counts as dicts, optionally filtered by KB."""
        if kb_name:
            rows = self._raw_conn.execute(
                """
                SELECT t.name, COUNT(*) as count
                FROM tag t
                JOIN entry_tag et ON t.id = et.tag_id
                WHERE et.kb_name = ?
                GROUP BY t.name
                ORDER BY count DESC
                LIMIT ?
                """,
                (kb_name, limit),
            ).fetchall()
        else:
            rows = self._raw_conn.execute(
                """
                SELECT t.name, COUNT(*) as count
                FROM tag t
                JOIN entry_tag et ON t.id = et.tag_id
                GROUP BY t.name
                ORDER BY count DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{"name": r["name"], "count": r["count"]} for r in rows]

    # =========================================================================
    # Collaboration (Phase 7)
    # =========================================================================

    def upsert_user(
        self,
        github_login: str,
        github_id: int,
        display_name: str = "",
        avatar_url: str = "",
        email: str = "",
    ) -> dict[str, Any]:
        """Insert or update a user. Returns user dict."""
        now = datetime.now(UTC).isoformat()
        self._raw_conn.execute(
            """
            INSERT INTO user (github_login, github_id, display_name, avatar_url, email, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(github_id) DO UPDATE SET
                github_login = excluded.github_login,
                display_name = excluded.display_name,
                avatar_url = excluded.avatar_url,
                email = excluded.email,
                last_seen = excluded.last_seen
            """,
            (github_login, github_id, display_name, avatar_url, email, now),
        )
        self._raw_conn.commit()
        row = self._raw_conn.execute(
            "SELECT * FROM user WHERE github_id = ?", (github_id,)
        ).fetchone()
        return dict(row) if row else {}

    def get_user(
        self, github_login: str | None = None, github_id: int | None = None
    ) -> dict[str, Any] | None:
        """Get user by login or ID."""
        if github_id is not None:
            row = self._raw_conn.execute(
                "SELECT * FROM user WHERE github_id = ?", (github_id,)
            ).fetchone()
        elif github_login is not None:
            row = self._raw_conn.execute(
                "SELECT * FROM user WHERE github_login = ?", (github_login,)
            ).fetchone()
        else:
            return None
        return dict(row) if row else None

    def get_local_user(self) -> dict[str, Any]:
        """Get the sentinel 'local' user."""
        row = self._raw_conn.execute("SELECT * FROM user WHERE github_id = 0").fetchone()
        if row:
            return dict(row)
        # Create if missing (shouldn't happen after migration)
        return self.upsert_user("local", 0, "Local User")

    def register_repo(
        self,
        name: str,
        local_path: str,
        remote_url: str | None = None,
        owner: str | None = None,
        visibility: str = "public",
        default_branch: str = "main",
        upstream_repo_id: int | None = None,
        is_fork: bool = False,
    ) -> dict[str, Any]:
        """Register a repo in the database. Returns repo dict."""
        self._raw_conn.execute(
            """
            INSERT INTO repo (name, local_path, remote_url, owner, visibility, default_branch,
                              upstream_repo_id, is_fork)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                local_path = excluded.local_path,
                remote_url = COALESCE(excluded.remote_url, repo.remote_url),
                owner = COALESCE(excluded.owner, repo.owner),
                visibility = excluded.visibility,
                default_branch = excluded.default_branch,
                upstream_repo_id = COALESCE(excluded.upstream_repo_id, repo.upstream_repo_id),
                is_fork = excluded.is_fork
            """,
            (
                name,
                local_path,
                remote_url,
                owner,
                visibility,
                default_branch,
                upstream_repo_id,
                1 if is_fork else 0,
            ),
        )
        self._raw_conn.commit()
        row = self._raw_conn.execute("SELECT * FROM repo WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else {}

    def get_repo(
        self, name: str | None = None, repo_id: int | None = None
    ) -> dict[str, Any] | None:
        """Get repo by name or ID."""
        if repo_id is not None:
            row = self._raw_conn.execute("SELECT * FROM repo WHERE id = ?", (repo_id,)).fetchone()
        elif name is not None:
            row = self._raw_conn.execute("SELECT * FROM repo WHERE name = ?", (name,)).fetchone()
        else:
            return None
        return dict(row) if row else None

    def list_repos(self) -> list[dict[str, Any]]:
        """List all repos."""
        rows = self._raw_conn.execute("SELECT * FROM repo ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def delete_repo(self, name: str) -> bool:
        """Delete a repo by name. Returns True if deleted."""
        result = self._raw_conn.execute("DELETE FROM repo WHERE name = ?", (name,))
        self._raw_conn.commit()
        return result.rowcount > 0

    def update_repo_synced(self, name: str, commit_hash: str) -> None:
        """Update repo's last synced commit and timestamp."""
        now = datetime.now(UTC).isoformat()
        self._raw_conn.execute(
            "UPDATE repo SET last_synced_commit = ?, last_synced = ? WHERE name = ?",
            (commit_hash, now, name),
        )
        self._raw_conn.commit()

    def add_workspace_repo(self, user_id: int, repo_id: int, role: str = "subscriber") -> None:
        """Add a repo to a user's workspace."""
        self._raw_conn.execute(
            """
            INSERT OR IGNORE INTO workspace_repo (user_id, repo_id, role)
            VALUES (?, ?, ?)
            """,
            (user_id, repo_id, role),
        )
        self._raw_conn.commit()

    def remove_workspace_repo(self, user_id: int, repo_id: int) -> bool:
        """Remove a repo from a user's workspace."""
        result = self._raw_conn.execute(
            "DELETE FROM workspace_repo WHERE user_id = ? AND repo_id = ?",
            (user_id, repo_id),
        )
        self._raw_conn.commit()
        return result.rowcount > 0

    def get_workspace_repos(self, user_id: int) -> list[dict[str, Any]]:
        """Get repos in a user's workspace."""
        rows = self._raw_conn.execute(
            """
            SELECT r.*, wr.role, wr.auto_sync, wr.added_at
            FROM repo r
            JOIN workspace_repo wr ON r.id = wr.repo_id
            WHERE wr.user_id = ?
            ORDER BY r.name
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_entry_version(
        self,
        entry_id: str,
        kb_name: str,
        commit_hash: str,
        author_name: str,
        author_email: str,
        commit_date: str,
        message: str = "",
        diff_summary: str = "",
        change_type: str = "modified",
        author_github_login: str | None = None,
    ) -> None:
        """Insert an entry version (from git log). Skips if commit already recorded."""
        self._raw_conn.execute(
            """
            INSERT OR IGNORE INTO entry_version
                (entry_id, kb_name, commit_hash, author_name, author_email,
                 author_github_login, commit_date, message, diff_summary, change_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                kb_name,
                commit_hash,
                author_name,
                author_email,
                author_github_login,
                commit_date,
                message,
                diff_summary,
                change_type,
            ),
        )
        self._raw_conn.commit()

    def get_entry_versions(
        self, entry_id: str, kb_name: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get version history for an entry."""
        rows = self._raw_conn.execute(
            """
            SELECT * FROM entry_version
            WHERE entry_id = ? AND kb_name = ?
            ORDER BY commit_date DESC
            LIMIT ?
            """,
            (entry_id, kb_name, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_contributors(self, kb_name: str | None = None) -> list[dict[str, Any]]:
        """Get contributors (from entry_version) with commit counts."""
        if kb_name:
            rows = self._raw_conn.execute(
                """
                SELECT author_name, author_email, author_github_login,
                       COUNT(DISTINCT commit_hash) as commits,
                       MAX(commit_date) as last_commit
                FROM entry_version
                WHERE kb_name = ?
                GROUP BY author_email
                ORDER BY commits DESC
                """,
                (kb_name,),
            ).fetchall()
        else:
            rows = self._raw_conn.execute("""
                SELECT author_name, author_email, author_github_login,
                       COUNT(DISTINCT commit_hash) as commits,
                       MAX(commit_date) as last_commit
                FROM entry_version
                GROUP BY author_email
                ORDER BY commits DESC
            """).fetchall()
        return [dict(r) for r in rows]
