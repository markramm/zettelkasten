from __future__ import annotations

from datetime import datetime

from ..models.note import Note
from ..storage.database import ZKDB
from ..storage.repository import NoteRepository
from .llm import LLMClient
from .metadata import naive_link_candidates


class CEQRC:
    """Capture → Explain → Question → Refine → Connect workflow."""

    def __init__(self, repo: NoteRepository, db: ZKDB, llm: LLMClient):
        self.repo = repo
        self.db = db
        self.llm = llm

    def create_seed(
        self, title: str, raw: str, tags: list[str] | None = None, summary: str = ""
    ) -> Note:
        now = datetime.utcnow()
        nid = now.strftime("%Y%m%d%H%M%S")
        # Auto-generate summary if not provided and body exists
        if not summary and raw:
            from ..config import ZK_SUMMARY_MAX_LENGTH

            summary = self.llm.generate_summary(raw, ZK_SUMMARY_MAX_LENGTH)
        note = Note(
            id=nid,
            title=title or "(untitled)",
            body=raw or "",
            summary=summary,
            tags=tags or [],
            created_at=now,
            updated_at=now,
            status="SEED",
        )
        self.repo.save(note)
        self.db.upsert_note(note)
        return note

    def simplify(self, note: Note, user_explanation: str) -> Note:
        note.body = (user_explanation or "").strip()
        note.status = "DRAFT"
        note.updated_at = datetime.utcnow()
        self.repo.save(note)
        self.db.upsert_note(note)
        return note

    def probe(self, note: Note) -> str:
        q = self.llm.feynman_probe(concept=note.title or "concept", explanation=note.body)
        return q

    def crystallize(self, note: Note) -> Note:
        refined = self.llm.refine(note.body)
        if refined:
            note.body = refined
        note.status = "REFINED"
        note.updated_at = datetime.utcnow()
        self.repo.save(note)
        self.db.upsert_note(note)
        return note

    def connect(self, note: Note) -> dict:
        # Suggest metadata
        meta = self.llm.suggest_metadata(note.body)
        title = meta.get("title") or note.title
        tags = list({*(note.tags or []), *[t for t in meta.get("tags", []) if t]})
        summary = meta.get("summary", "")
        # Update note
        note.title = title
        note.tags = tags
        if summary and not note.summary:  # Only update if note doesn't already have a summary
            note.summary = summary
        note.status = "PERMANENT"
        note.updated_at = datetime.utcnow()
        self.repo.save(note)
        self.db.upsert_note(note)
        # Suggest links
        corpus = []
        for r in self.db.conn.execute(
            "SELECT id, title, body FROM zettel WHERE id!=?", (note.id,)
        ).fetchall():
            corpus.append({"id": r["id"], "title": r["title"], "body": r["body"]})
        links = naive_link_candidates(note.body, corpus, max_suggestions=5)
        return {
            "metadata": {"title": title, "tags": tags, "summary": summary},
            "link_suggestions": links,
        }
