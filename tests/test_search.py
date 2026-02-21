from datetime import datetime

from zettelkasten_assistant.models.note import Note
from zettelkasten_assistant.storage.database import ZKDB
from zettelkasten_assistant.storage.repository import NoteRepository


def test_search_fts(temp_env):
    repo = NoteRepository(temp_env["notes"])
    db = ZKDB(temp_env["db"] / "zk.db")
    n1 = Note(
        id="1",
        title="Quantum Mechanics",
        body="Wave function and measurement",
        summary="Study of quantum mechanical principles",
        tags=["physics"],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    n2 = Note(
        id="2",
        title="Relativity",
        body="Spacetime and gravity",
        summary="Einstein's theory of relativity",
        tags=["physics"],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    repo.save(n1)
    db.upsert_note(n1)
    repo.save(n2)
    db.upsert_note(n2)

    # Search in body (using simple terms instead of proximity)
    res = db.search("wave function")
    assert any(r["id"] == "1" for r in res)

    # Search in summary
    res = db.search("Einstein")
    assert any(r["id"] == "2" for r in res)
