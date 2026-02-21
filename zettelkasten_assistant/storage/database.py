import sqlite3
from datetime import datetime
from pathlib import Path

from ..models.note import Note
from .utils import inverse_link_type


class ZKDB:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        c = self.conn.cursor()
        c.execute("PRAGMA foreign_keys = ON;")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS zettel(
            id TEXT PRIMARY KEY,
            title TEXT,
            body TEXT,
            summary TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS tag(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS zettel_tag(
            zettel_id TEXT,
            tag_id INTEGER,
            PRIMARY KEY(zettel_id, tag_id),
            FOREIGN KEY(zettel_id) REFERENCES zettel(id) ON DELETE CASCADE,
            FOREIGN KEY(tag_id) REFERENCES tag(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS link(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            type TEXT NOT NULL,
            inverse_type TEXT NOT NULL,
            description TEXT,
            created_at TEXT,
            FOREIGN KEY(source_id) REFERENCES zettel(id) ON DELETE CASCADE,
            FOREIGN KEY(target_id) REFERENCES zettel(id) ON DELETE CASCADE
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS zettel_fts
        USING fts5(title, body, summary, content='zettel', content_rowid='rowid');
        CREATE TRIGGER IF NOT EXISTS zettel_ai AFTER INSERT ON zettel BEGIN
          INSERT INTO zettel_fts(rowid, title, body, summary)
          VALUES (new.rowid, new.title, new.body, COALESCE(new.summary,''));
        END;
        CREATE TRIGGER IF NOT EXISTS zettel_ad AFTER DELETE ON zettel BEGIN
          INSERT INTO zettel_fts(zettel_fts, rowid, title, body, summary)
          VALUES('delete', old.rowid, old.title, old.body, COALESCE(old.summary,''));
        END;
        CREATE TRIGGER IF NOT EXISTS zettel_au AFTER UPDATE ON zettel BEGIN
          INSERT INTO zettel_fts(zettel_fts, rowid, title, body, summary)
          VALUES('delete', old.rowid, old.title, old.body, COALESCE(old.summary,''));
          INSERT INTO zettel_fts(rowid, title, body, summary)
          VALUES (new.rowid, new.title, new.body, COALESCE(new.summary,''));
        END;
        CREATE INDEX IF NOT EXISTS idx_tag_name ON tag(name);
        CREATE INDEX IF NOT EXISTS idx_zettag_z ON zettel_tag(zettel_id);
        CREATE INDEX IF NOT EXISTS idx_zettag_t ON zettel_tag(tag_id);
        CREATE INDEX IF NOT EXISTS idx_link_from ON link(source_id);
        CREATE INDEX IF NOT EXISTS idx_link_to ON link(target_id);
        CREATE INDEX IF NOT EXISTS idx_link_type ON link(type);
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        """)
        self.conn.commit()

    # ------------------- Note CRUD -------------------
    def upsert_note(self, note: Note):
        c = self.conn.cursor()
        c.execute(
            """
            INSERT INTO zettel(id, title, body, summary, created_at, updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                body=excluded.body,
                summary=excluded.summary,
                updated_at=excluded.updated_at
        """,
            (
                note.id,
                note.title,
                note.body,
                note.summary,
                note.created_at.isoformat(),
                note.updated_at.isoformat(),
            ),
        )
        # Tags
        c.execute("DELETE FROM zettel_tag WHERE zettel_id=?", (note.id,))
        for t in note.tags:
            c.execute("INSERT OR IGNORE INTO tag(name) VALUES(?)", (t,))
            tid = c.execute("SELECT id FROM tag WHERE name=?", (t,)).fetchone()["id"]
            c.execute("INSERT INTO zettel_tag(zettel_id, tag_id) VALUES(?,?)", (note.id, tid))
        # Links (outgoing)
        c.execute("DELETE FROM link WHERE source_id=?", (note.id,))
        for l in note.links:
            to = l.get("to")
            typ = l.get("type", "related")
            inv = inverse_link_type(typ)
            c.execute(
                "INSERT INTO link(source_id, target_id, type, inverse_type, created_at) VALUES(?,?,?,?,?)",
                (note.id, to, typ, inv, datetime.utcnow().isoformat()),
            )
        self.conn.commit()

    def delete_note(self, note_id: str):
        self.conn.execute("DELETE FROM zettel WHERE id=?", (note_id,))
        self.conn.commit()

    def get_note(self, note_id: str) -> Note | None:
        c = self.conn.cursor()
        r = c.execute("SELECT * FROM zettel WHERE id=?", (note_id,)).fetchone()
        if not r:
            return None
        # tags
        tags = [
            row["name"]
            for row in c.execute(
                "SELECT t.name FROM tag t JOIN zettel_tag zt ON t.id=zt.tag_id WHERE zt.zettel_id=?",
                (note_id,),
            ).fetchall()
        ]
        # links (outgoing)
        links = [
            {"to": row["target_id"], "type": row["type"]}
            for row in c.execute(
                "SELECT target_id, type FROM link WHERE source_id=?", (note_id,)
            ).fetchall()
        ]
        from datetime import datetime

        try:
            created = datetime.fromisoformat(r["created_at"])
        except Exception:
            created = datetime.utcnow()
        try:
            updated = datetime.fromisoformat(r["updated_at"])
        except Exception:
            updated = created
        return Note(
            id=r["id"],
            title=r["title"],
            body=r["body"],
            summary=r["summary"] or "",
            tags=tags,
            links=links,
            created_at=created,
            updated_at=updated,
            status="PERMANENT",
        )

    # ------------------- Search & Analytics -------------------
    def search(self, query: str, tag: str | None = None) -> list:
        c = self.conn.cursor()
        if tag:
            sql = """
            SELECT z.id, z.title,
                   snippet(zettel_fts, 1, '<mark>', '</mark>', ' ... ', 10) AS snippet
            FROM zettel_fts
            JOIN zettel z ON zettel_fts.rowid = z.rowid
            JOIN zettel_tag zt ON z.id = zt.zettel_id
            JOIN tag t ON zt.tag_id = t.id
            WHERE t.name = ? AND zettel_fts MATCH ?
            ORDER BY rank
            """
            rows = c.execute(sql, (tag, query)).fetchall()
        else:
            sql = """
            SELECT z.id, z.title,
                   snippet(zettel_fts, 1, '<mark>', '</mark>', ' ... ', 10) AS snippet
            FROM zettel_fts
            JOIN zettel z ON zettel_fts.rowid = z.rowid
            WHERE zettel_fts MATCH ?
            ORDER BY rank
            """
            rows = c.execute(sql, (query,)).fetchall()
        return [dict(r) for r in rows]

    def backlinks(self, note_id: str) -> list:
        rows = self.conn.execute(
            "SELECT source_id, inverse_type as type FROM link WHERE target_id=?", (note_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def central_notes(self, top_n: int = 5) -> list:
        rows = self.conn.execute(
            """
            SELECT z.id, z.title,
                   (SELECT COUNT(*) FROM link WHERE source_id=z.id OR target_id=z.id) AS degree
            FROM zettel z
            ORDER BY degree DESC
            LIMIT ?
        """,
            (top_n,),
        ).fetchall()
        return [dict(r) for r in rows]

    def orphaned_notes(self) -> list:
        rows = self.conn.execute("""
            SELECT z.id, z.title FROM zettel z
            WHERE z.id NOT IN (SELECT source_id FROM link)
              AND z.id NOT IN (SELECT target_id FROM link)
        """).fetchall()
        return [dict(r) for r in rows]
