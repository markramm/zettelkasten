"""
Base Entry Model

Abstract base for all KB entry types.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
import re
import yaml

from ..schema import Source, Link, Provenance


@dataclass
class Entry(ABC):
    """
    Abstract base class for all KB entries.

    All entries share:
    - ID and title
    - Body content
    - Tags and links
    - Sources and provenance
    - Timestamps
    """
    id: str
    title: str
    body: str = ""
    summary: str = ""
    tags: List[str] = field(default_factory=list)
    links: List[Link] = field(default_factory=list)
    sources: List[Source] = field(default_factory=list)
    provenance: Optional[Provenance] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    # KB reference (set when loaded)
    kb_name: str = ""
    file_path: Optional[Path] = None

    @property
    @abstractmethod
    def entry_type(self) -> str:
        """Return the entry type (events, actor, organization, etc.)."""
        pass

    @property
    @abstractmethod
    def ftm_schema(self) -> Optional[str]:
        """Return the FtM schema for export, or None if not exportable."""
        pass

    @abstractmethod
    def to_frontmatter(self) -> Dict[str, Any]:
        """Convert to YAML frontmatter dictionary."""
        pass

    @classmethod
    @abstractmethod
    def from_frontmatter(cls, meta: Dict[str, Any], body: str) -> 'Entry':
        """Create from parsed frontmatter and body."""
        pass

    def to_markdown(self) -> str:
        """Convert to markdown string with YAML frontmatter."""
        meta = self.to_frontmatter()
        yaml_front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{yaml_front}\n---\n\n{self.body}\n"

    @classmethod
    def from_markdown(cls, text: str) -> 'Entry':
        """Parse from markdown string with YAML frontmatter."""
        parts = re.split(r'^---\s*$', text, flags=re.MULTILINE, maxsplit=2)
        if len(parts) < 3:
            raise ValueError("Invalid entry format: missing YAML frontmatter")

        meta = yaml.safe_load(parts[1]) or {}
        body = parts[2].strip()

        return cls.from_frontmatter(meta, body)

    @classmethod
    def load(cls, path: Path) -> 'Entry':
        """Load entry from file."""
        text = path.read_text(encoding='utf-8')
        entry = cls.from_markdown(text)
        entry.file_path = path
        return entry

    def save(self, path: Optional[Path] = None) -> Path:
        """Save entry to file."""
        if path is None:
            path = self.file_path
        if path is None:
            raise ValueError("No path specified and no file_path set")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_markdown(), encoding='utf-8')
        self.file_path = path
        return path

    def add_link(self, target: str, relation: str, note: str = "", kb: str = "") -> None:
        """Add a link to another entry."""
        self.links.append(Link(target=target, relation=relation, note=note, kb=kb))

    def add_source(self, title: str, url: str, **kwargs) -> None:
        """Add a source reference."""
        self.sources.append(Source(title=title, url=url, **kwargs))

    def validate(self) -> List[str]:
        """Validate entry. Returns list of errors."""
        errors = []
        if not self.id:
            errors.append("Entry must have an ID")
        if not self.title:
            errors.append("Entry must have a title")
        return errors

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.id!r}, title={self.title!r})"


def parse_datetime(s: Any) -> datetime:
    """Parse datetime from various formats."""
    if isinstance(s, datetime):
        return s
    if not s:
        return datetime.utcnow()
    try:
        # Try ISO format
        if isinstance(s, str):
            s = s.replace('Z', '+00:00')
            return datetime.fromisoformat(s)
    except Exception:
        pass
    return datetime.utcnow()


def parse_sources(sources_data: Any) -> List[Source]:
    """Parse sources from various formats."""
    if not sources_data:
        return []
    if isinstance(sources_data, list):
        return [Source.from_dict(s) if isinstance(s, dict) else Source(title=str(s), url='') for s in sources_data]
    return []


def parse_links(links_data: Any) -> List[Link]:
    """Parse links from various formats."""
    if not links_data:
        return []
    if isinstance(links_data, list):
        return [Link.from_dict(l) if isinstance(l, dict) else Link(target=str(l), relation='related') for l in links_data]
    return []
