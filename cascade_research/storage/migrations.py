"""
Schema Migration System for CascadeDB

Provides:
- Version tracking via schema_version table
- Forward migrations with rollback support
- Migration status reporting
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Current schema version
CURRENT_VERSION = 1


@dataclass
class Migration:
    """A single database migration."""

    version: int
    description: str
    up: str  # SQL to apply migration
    down: str  # SQL to rollback migration


# Migration registry - add new migrations here
MIGRATIONS: list[Migration] = [
    Migration(
        version=1,
        description="Initial schema with FTS5",
        up="""
        -- Version 1 is the baseline schema (no changes needed if tables exist)
        -- This migration exists to establish version tracking
        """,
        down="""
        -- Cannot rollback below version 1
        """,
    ),
    # Future migrations go here:
    # Migration(
    #     version=2,
    #     description="Add embedding column for vector search",
    #     up="ALTER TABLE entry ADD COLUMN embedding BLOB;",
    #     down="ALTER TABLE entry DROP COLUMN embedding;"
    # ),
]


class MigrationManager:
    """
    Manages database schema migrations.

    Usage:
        db = CascadeDB(path)
        mgr = MigrationManager(db.conn)
        mgr.migrate()  # Apply all pending migrations
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._ensure_version_table()

    def _ensure_version_table(self) -> None:
        """Create schema_version table if not exists."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
        """)
        self.conn.commit()

    def get_current_version(self) -> int:
        """Get the current schema version (0 if no migrations applied)."""
        row = self.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return row[0] if row[0] is not None else 0

    def get_applied_migrations(self) -> list[dict]:
        """Get list of applied migrations."""
        rows = self.conn.execute(
            "SELECT version, description, applied_at FROM schema_version ORDER BY version"
        ).fetchall()
        return [{"version": r[0], "description": r[1], "applied_at": r[2]} for r in rows]

    def get_pending_migrations(self) -> list[Migration]:
        """Get migrations that haven't been applied yet."""
        current = self.get_current_version()
        return [m for m in MIGRATIONS if m.version > current]

    def migrate(self, target_version: int | None = None) -> list[Migration]:
        """
        Apply pending migrations up to target_version.

        Args:
            target_version: Version to migrate to (default: latest)

        Returns:
            List of applied migrations
        """
        if target_version is None:
            target_version = CURRENT_VERSION

        current = self.get_current_version()
        if current >= target_version:
            return []

        applied = []
        pending = [m for m in MIGRATIONS if current < m.version <= target_version]

        for migration in sorted(pending, key=lambda m: m.version):
            self._apply_migration(migration)
            applied.append(migration)

        return applied

    def _apply_migration(self, migration: Migration) -> None:
        """Apply a single migration."""
        try:
            # Execute the migration SQL
            if migration.up.strip():
                self.conn.executescript(migration.up)

            # Record the migration
            self.conn.execute(
                """
                INSERT INTO schema_version (version, description, applied_at)
                VALUES (?, ?, ?)
                """,
                (migration.version, migration.description, datetime.now(UTC).isoformat()),
            )
            self.conn.commit()
            logger.info("Applied migration v%d: %s", migration.version, migration.description)
        except Exception as e:
            self.conn.rollback()
            raise MigrationError(f"Failed to apply migration v{migration.version}: {e}") from e

    def rollback(self, target_version: int = 0) -> list[Migration]:
        """
        Rollback migrations down to target_version.

        Args:
            target_version: Version to rollback to (default: 0, removes all)

        Returns:
            List of rolled back migrations
        """
        current = self.get_current_version()
        if current <= target_version:
            return []

        rolled_back = []
        to_rollback = [m for m in MIGRATIONS if target_version < m.version <= current]

        for migration in sorted(to_rollback, key=lambda m: m.version, reverse=True):
            self._rollback_migration(migration)
            rolled_back.append(migration)

        return rolled_back

    def _rollback_migration(self, migration: Migration) -> None:
        """Rollback a single migration."""
        try:
            # Execute the rollback SQL
            if migration.down.strip() and "Cannot rollback" not in migration.down:
                self.conn.executescript(migration.down)

            # Remove the migration record
            self.conn.execute("DELETE FROM schema_version WHERE version = ?", (migration.version,))
            self.conn.commit()
            logger.info("Rolled back migration v%d: %s", migration.version, migration.description)
        except Exception as e:
            self.conn.rollback()
            raise MigrationError(f"Failed to rollback migration v{migration.version}: {e}") from e

    def status(self) -> dict:
        """Get migration status summary."""
        return {
            "current_version": self.get_current_version(),
            "target_version": CURRENT_VERSION,
            "applied": self.get_applied_migrations(),
            "pending": [
                {"version": m.version, "description": m.description}
                for m in self.get_pending_migrations()
            ],
            "up_to_date": self.get_current_version() >= CURRENT_VERSION,
        }


class MigrationError(Exception):
    """Raised when a migration fails."""

    pass


def ensure_migrated(db_path: Path) -> None:
    """
    Ensure database is migrated to current version.

    Call this during application startup to auto-migrate.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        mgr = MigrationManager(conn)
        pending = mgr.get_pending_migrations()
        if pending:
            logger.info("Applying %d pending migration(s)...", len(pending))
            mgr.migrate()
            logger.info("Database now at version %d", mgr.get_current_version())
    finally:
        conn.close()
