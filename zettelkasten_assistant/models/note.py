from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Note:
    id: str
    title: str
    body: str
    summary: str = ""  # Concise summary of the note content
    tags: list[str] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)  # {to: str, type: str}
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "SEED"  # SEED|DRAFT|REFINED|PERMANENT

    def to_markdown(self) -> str:
        import yaml

        meta = {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "tags": self.tags,
            "links": self.links,
            "created_at": self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated_at": self.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": self.status,
        }
        yaml_front = yaml.safe_dump(meta, sort_keys=False).strip()
        return f"---\n{yaml_front}\n---\n{self.body}\n"

    @staticmethod
    def from_markdown(text: str) -> "Note":
        import re

        import yaml

        parts = re.split(r"^---\s*$", text, flags=re.MULTILINE)
        if len(parts) < 3:
            raise ValueError("Invalid note format: missing YAML frontmatter.")
        meta = yaml.safe_load(parts[1]) or {}
        body = parts[2].strip()
        from datetime import datetime

        def parse_dt(s):
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except Exception:
                return datetime.utcnow()

        return Note(
            id=str(meta.get("id")),
            title=meta.get("title", ""),
            body=body,
            summary=meta.get("summary", ""),
            tags=meta.get("tags", []) or [],
            links=meta.get("links", []) or [],
            created_at=parse_dt(meta.get("created_at", "")),
            updated_at=parse_dt(meta.get("updated_at", "")),
            status=meta.get("status", "PERMANENT"),
        )
