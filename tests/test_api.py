from fastapi.testclient import TestClient

from zettelkasten_assistant.server.api import app


def test_api_lifecycle(temp_env, monkeypatch):
    # Reimport app with temp env is complicated; rely on endpoints not using global env after import.
    client = TestClient(app)
    # Create with summary
    r = client.post(
        "/notes",
        json={
            "title": "API Note",
            "body": "body text",
            "summary": "A test summary",
            "tags": ["t1"],
        },
    )
    assert r.status_code == 200
    data = r.json()
    nid = data["id"]
    assert data["summary"] == "A test summary"

    # Get
    r = client.get(f"/notes/{nid}")
    assert r.status_code == 200
    assert r.json()["summary"] == "A test summary"

    # Search
    r = client.get("/search", params={"q": "body"})
    assert r.status_code == 200

    # Test generate summary endpoint
    r = client.post(
        "/generate-summary",
        json={
            "text": "This is a longer piece of text that needs to be summarized for the note system"
        },
    )
    assert r.status_code == 200
    assert "summary" in r.json()
    assert len(r.json()["summary"]) <= r.json()["max_length"]

    # CEQRC
    r = client.post(f"/notes/{nid}/ceqrc")
    assert r.status_code == 200
