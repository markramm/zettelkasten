from datetime import datetime

import typer
from rich import print

from .config import OPENAI_API_BASE, OPENAI_API_KEY, ZK_DB_PATH, ZK_LLM_PROVIDER, ZK_NOTES_DIR
from .services.llm import LLMClient
from .services.workflow import CEQRC
from .storage.database import ZKDB
from .storage.repository import NoteRepository
from .storage.utils import inverse_link_type

app = typer.Typer(add_completion=False, help="Zettelkasten Assistant CLI")

repo = NoteRepository(ZK_NOTES_DIR)
db = ZKDB(ZK_DB_PATH)
llm = LLMClient(provider=ZK_LLM_PROVIDER, api_key=OPENAI_API_KEY, api_base=OPENAI_API_BASE)
flow = CEQRC(repo, db, llm)


@app.command()
def new(
    title: str = typer.Argument(..., help="Note title"),
    content: str = typer.Option("", "--content", "-c", help="Initial content"),
    tags: str = typer.Option("", "--tags", "-t", help="Comma-separated tags"),
):
    """Create a new seed note."""
    taglist = [t.strip() for t in tags.split(",") if t.strip()]
    note = flow.create_seed(title, content, taglist)
    print(f"[green]Created[/green] note [bold]{note.id}[/bold]: {note.title}")


@app.command()
def show(note_id: str):
    """Show a note."""
    try:
        note = repo.load(note_id)
        print(f"[bold]{note.title}[/bold]  ([cyan]{note.id}[/cyan])")
        print(f"Tags: {', '.join(note.tags)}")
        print(note.body)
        backs = db.backlinks(note_id)
        if backs:
            print(f"Backlinks: {backs}")
    except FileNotFoundError:
        print(f"[red]Note {note_id} not found[/red]")


@app.command()
def update(
    note_id: str,
    title: str = typer.Option(None),
    content: str = typer.Option(None),
    tags: str = typer.Option(None),
):
    """Update note fields."""
    try:
        note = repo.load(note_id)
    except FileNotFoundError:
        print("[red]Not found[/red]")
        raise typer.Exit(code=1)
    if title is not None:
        note.title = title
    if content is not None:
        note.body = content
    if tags is not None:
        note.tags = [t.strip() for t in tags.split(",") if t.strip()]
    note.updated_at = datetime.utcnow()
    repo.save(note)
    db.upsert_note(note)
    print("[green]Updated[/green].")


@app.command()
def delete(note_id: str):
    """Delete a note by ID."""
    db.delete_note(note_id)
    repo.delete(note_id)
    print("[yellow]Deleted[/yellow].")


@app.command()
def search(q: str = typer.Argument(..., help="FTS5 query"), tag: str = typer.Option(None, "--tag")):
    """Full-text search notes."""
    res = db.search(q, tag)
    for r in res:
        print(f"[bold]{r['id']}[/bold] {r['title']}")
        print(r["snippet"])
        print("-" * 60)


@app.command()
def link(source_id: str, target_id: str, type: str = "related"):
    """Create a typed link from source to target."""
    inv = inverse_link_type(type)
    db.conn.execute(
        "INSERT INTO link(source_id,target_id,type,inverse_type,created_at) VALUES(?,?,?,?,datetime('now'))",
        (source_id, target_id, type, inv),
    )
    db.conn.commit()
    try:
        note = repo.load(source_id)
        if not any(l.get("to") == target_id for l in note.links):
            note.links.append({"to": target_id, "type": type})
            repo.save(note)
            db.upsert_note(note)
    except FileNotFoundError:
        pass
    print("[green]Linked[/green].")


@app.command()
def ceqrc(note_id: str):
    """Run a minimal CEQRC flow: probe → crystallize → connect (non-interactive)."""
    note = repo.load(note_id)
    q = flow.probe(note)
    print(f"[cyan]Probe:[/cyan] {q}")
    note = flow.crystallize(note)
    out = flow.connect(note)
    print("[green]Crystallized[/green]. Metadata suggestion:", out["metadata"])
    print("Link suggestions:", out["link_suggestions"])


if __name__ == "__main__":
    app()
