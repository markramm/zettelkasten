from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..config import (
    OPENAI_API_BASE,
    OPENAI_API_KEY,
    ZK_DB_PATH,
    ZK_HOST,
    ZK_LLM_PROVIDER,
    ZK_NOTES_DIR,
    ZK_PORT,
    ZK_SUMMARY_MAX_LENGTH,
)
from ..services.llm import LLMClient
from ..services.workflow import CEQRC
from ..storage.database import ZKDB
from ..storage.repository import NoteRepository
from ..storage.utils import inverse_link_type

app = FastAPI(title="Zettelkasten Assistant", version="0.1.0")

repo = NoteRepository(ZK_NOTES_DIR)
db = ZKDB(ZK_DB_PATH)
llm = LLMClient(provider=ZK_LLM_PROVIDER, api_key=OPENAI_API_KEY, api_base=OPENAI_API_BASE)
flow = CEQRC(repo, db, llm)


class NoteIn(BaseModel):
    title: str
    body: str = ""
    summary: str = ""
    tags: list[str] | None = []


class NoteOut(BaseModel):
    id: str
    title: str
    body: str
    summary: str
    tags: list[str]
    links: list[dict[str, Any]]
    status: str


@app.post("/notes", response_model=NoteOut)
def create_note(n: NoteIn):
    note = flow.create_seed(n.title, n.body, n.tags or [])
    # Auto-generate summary if not provided
    if not n.summary and n.body:
        note.summary = llm.generate_summary(n.body, ZK_SUMMARY_MAX_LENGTH)
    else:
        note.summary = n.summary[:ZK_SUMMARY_MAX_LENGTH] if n.summary else ""
    repo.save(note)
    db.upsert_note(note)
    return NoteOut(
        id=note.id,
        title=note.title,
        body=note.body,
        summary=note.summary,
        tags=note.tags,
        links=note.links,
        status=note.status,
    )


@app.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: str):
    try:
        note = repo.load(note_id)
        return NoteOut(
            id=note.id,
            title=note.title,
            body=note.body,
            summary=note.summary,
            tags=note.tags,
            links=note.links,
            status=note.status,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")


@app.put("/notes/{note_id}", response_model=NoteOut)
def update_note(note_id: str, n: NoteIn):
    try:
        note = repo.load(note_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")
    note.title = n.title or note.title
    note.body = n.body if n.body is not None else note.body
    note.tags = n.tags or []

    # Handle summary update/generation
    if n.summary:
        note.summary = n.summary[:ZK_SUMMARY_MAX_LENGTH]
    elif n.body != note.body:  # If body changed but no summary provided, regenerate
        note.summary = llm.generate_summary(note.body, ZK_SUMMARY_MAX_LENGTH)

    repo.save(note)
    db.upsert_note(note)
    return NoteOut(
        id=note.id,
        title=note.title,
        body=note.body,
        summary=note.summary,
        tags=note.tags,
        links=note.links,
        status=note.status,
    )


@app.delete("/notes/{note_id}")
def delete_note(note_id: str):
    db.delete_note(note_id)
    repo.delete(note_id)
    return {"ok": True}


@app.get("/search")
def search(q: str, tag: str | None = None):
    return db.search(q, tag)


class SummaryRequest(BaseModel):
    text: str


@app.post("/generate-summary")
def generate_summary(request: SummaryRequest):
    """Generate a summary for the given text within character limits."""
    summary = llm.generate_summary(request.text, ZK_SUMMARY_MAX_LENGTH)
    return {"summary": summary, "max_length": ZK_SUMMARY_MAX_LENGTH, "length": len(summary)}


@app.get("/notes/{note_id}/backlinks")
def backlinks(note_id: str):
    return db.backlinks(note_id)


class LinkIn(BaseModel):
    target_id: str
    type: str = "related"
    description: str | None = ""


@app.post("/notes/{note_id}/links")
def create_link(note_id: str, l: LinkIn):
    inv = inverse_link_type(l.type)
    db.conn.execute(
        "INSERT INTO link(source_id,target_id,type,inverse_type,description,created_at) VALUES(?,?,?,?,?,datetime('now'))",
        (note_id, l.target_id, l.type, inv, l.description or ""),
    )
    db.conn.commit()
    try:
        note = repo.load(note_id)
        if not any(x.get("to") == l.target_id for x in note.links):
            note.links.append({"to": l.target_id, "type": l.type})
            repo.save(note)
            db.upsert_note(note)
    except FileNotFoundError:
        pass
    return {"ok": True}


@app.post("/notes/{note_id}/ceqrc")
def run_ceqrc(note_id: str):
    try:
        note = repo.load(note_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")
    probe = flow.probe(note)
    note = flow.crystallize(note)
    results = flow.connect(note)
    return {
        "probe": probe,
        "metadata": results["metadata"],
        "link_suggestions": results["link_suggestions"],
    }


def main():
    uvicorn.run(app, host=ZK_HOST, port=ZK_PORT)


if __name__ == "__main__":
    main()
