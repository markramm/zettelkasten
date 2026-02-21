from pathlib import Path

from ..models.note import Note


class NoteRepository:
    def __init__(self, notes_dir: Path):
        self.notes_dir = Path(notes_dir)
        self.notes_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, note_id: str) -> Path:
        return self.notes_dir / f"{note_id}.md"

    def save(self, note: Note) -> None:
        p = self._path(note.id)
        p.write_text(note.to_markdown(), encoding="utf-8")

    def load(self, note_id: str) -> Note:
        p = self._path(note_id)
        if not p.exists():
            raise FileNotFoundError(f"Note {note_id} not found")
        return Note.from_markdown(p.read_text(encoding="utf-8"))

    def delete(self, note_id: str) -> None:
        p = self._path(note_id)
        if p.exists():
            p.unlink()

    def list_all(self) -> list[Note]:
        notes = []
        for md in self.notes_dir.glob("*.md"):
            try:
                notes.append(Note.from_markdown(md.read_text(encoding="utf-8")))
            except Exception as e:
                # Skip malformed notes but continue
                print(f"[WARN] Could not parse {md.name}: {e}")
        return notes
