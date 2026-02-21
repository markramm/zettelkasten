import pytest


@pytest.fixture
def temp_env(monkeypatch, tmp_path):
    notes = tmp_path / "notes"
    dbdir = tmp_path / "db"
    notes.mkdir()
    dbdir.mkdir()
    monkeypatch.setenv("ZK_NOTES_DIR", str(notes))
    monkeypatch.setenv("ZK_DB_PATH", str(dbdir / "zk.db"))
    monkeypatch.setenv("ZK_LLM_PROVIDER", "stub")
    return {"notes": notes, "db": dbdir}
