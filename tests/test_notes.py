from datetime import datetime

from zettelkasten_assistant.models.note import Note
from zettelkasten_assistant.storage.database import ZKDB
from zettelkasten_assistant.storage.repository import NoteRepository


def test_create_and_load_note(temp_env):
    repo = NoteRepository(temp_env["notes"])
    db = ZKDB(temp_env["db"] / "zk.db")
    n = Note(
        id="20250101010101",
        title="Test",
        body="Hello world",
        summary="A test note",
        tags=["x", "y"],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        status="SEED",
    )
    repo.save(n)
    db.upsert_note(n)
    m = repo.load("20250101010101")
    assert m.title == "Test"
    assert "Hello world" in m.body
    assert m.summary == "A test note"
    # DB retrieval
    got = db.get_note("20250101010101")
    assert got is not None
    assert got.title == "Test"
    assert got.summary == "A test note"


def test_summary_in_search(temp_env):
    repo = NoteRepository(temp_env["notes"])
    db = ZKDB(temp_env["db"] / "zk.db")
    n = Note(
        id="search_test",
        title="Test Note",
        body="Some content here",
        summary="This note is about testing search functionality",
        tags=["test"],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    repo.save(n)
    db.upsert_note(n)

    # Search should find text in summary
    results = db.search("functionality")
    assert len(results) > 0
    assert any(r["id"] == "search_test" for r in results)
