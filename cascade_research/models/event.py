"""
Event Entry Model

For Events KB - structured timeline events with canonical dates.
"""

from dataclasses import dataclass, field
from typing import Any

from ..schema import (
    EventStatus,
    FtMSchema,
    Provenance,
    validate_date,
    validate_importance,
)
from .base import Entry, parse_datetime, parse_links, parse_sources


@dataclass
class EventEntry(Entry):
    """
    A timeline event entry.

    Events have:
    - Canonical date (when it happened)
    - Importance score (1-10)
    - Status (confirmed, disputed, alleged, rumored)
    - Location
    - Actors involved
    - Single-paragraph body (typically)
    """

    # Event-specific fields
    date: str = ""  # YYYY-MM-DD canonical date
    importance: int = 5
    status: EventStatus = EventStatus.CONFIRMED
    location: str = ""
    actors: list[str] = field(default_factory=list)
    capture_lanes: list[str] = field(default_factory=list)
    notes: str = ""
    academic_significance: str = ""

    @property
    def entry_type(self) -> str:
        return "event"

    @property
    def ftm_schema(self) -> str | None:
        return FtMSchema.EVENT.value

    def to_frontmatter(self) -> dict[str, Any]:
        """Convert to YAML frontmatter dictionary."""
        meta: dict[str, Any] = {
            "id": self.id,
            "date": self.date,
            "importance": self.importance,
            "title": self.title,
        }

        if self.status != EventStatus.CONFIRMED:
            meta["status"] = self.status.value

        if self.location:
            meta["location"] = self.location

        if self.actors:
            meta["actors"] = self.actors

        if self.tags:
            meta["tags"] = self.tags

        if self.capture_lanes:
            meta["capture_lanes"] = self.capture_lanes

        if self.sources:
            meta["sources"] = [s.to_dict() for s in self.sources]

        if self.notes:
            meta["notes"] = self.notes

        if self.academic_significance:
            meta["academic_significance"] = self.academic_significance

        if self.links:
            meta["links"] = [l.to_dict() for l in self.links]

        if self.provenance:
            prov = self.provenance.to_dict()
            if prov:
                meta["provenance"] = prov

        return meta

    @classmethod
    def from_frontmatter(cls, meta: dict[str, Any], body: str) -> "EventEntry":
        """Create from parsed frontmatter and body."""
        # Parse status
        status_str = meta.get("status", "confirmed")
        try:
            status = EventStatus(status_str)
        except ValueError:
            status = EventStatus.CONFIRMED

        # Parse provenance
        prov_data = meta.get("provenance")
        provenance = Provenance.from_dict(prov_data) if prov_data else None

        return cls(
            id=str(meta.get("id", "")),
            title=meta.get("title", ""),
            body=body,
            summary=meta.get("summary", ""),
            date=meta.get("date", ""),
            importance=int(meta.get("importance", 5)),
            status=status,
            location=meta.get("location", ""),
            actors=meta.get("actors", []) or [],
            tags=meta.get("tags", []) or [],
            capture_lanes=meta.get("capture_lanes", []) or [],
            sources=parse_sources(meta.get("sources")),
            notes=meta.get("notes", ""),
            academic_significance=meta.get("academic_significance", ""),
            links=parse_links(meta.get("links")),
            provenance=provenance,
            created_at=parse_datetime(meta.get("created_at")),
            updated_at=parse_datetime(meta.get("updated_at")),
        )

    def validate(self) -> list[str]:
        """Validate event entry."""
        errors = super().validate()

        if not self.date:
            errors.append("Event must have a date")
        elif not validate_date(self.date):
            errors.append(f"Invalid date format: {self.date} (expected YYYY-MM-DD)")

        if not validate_importance(self.importance):
            errors.append(f"Importance must be 1-10, got: {self.importance}")

        # Validate ID matches date pattern
        if self.id and self.date:
            if not self.id.startswith(self.date):
                errors.append(f"Event ID should start with date: {self.date}")

        return errors

    def to_ftm(self) -> dict[str, Any]:
        """Export as FollowTheMoney Event entity."""
        properties: dict[str, list[str]] = {
            "name": [self.title],
        }

        if self.date:
            properties["date"] = [self.date]

        if self.location:
            properties["location"] = [self.location]

        if self.actors:
            properties["involved"] = self.actors

        if self.summary:
            properties["summary"] = [self.summary]
        elif self.body:
            # Use first 500 chars of body as summary
            properties["summary"] = [self.body[:500]]

        if self.sources:
            properties["sourceUrl"] = [s.url for s in self.sources if s.url]

        return {
            "id": self.id,
            "schema": FtMSchema.EVENT.value,
            "properties": properties,
        }

    @classmethod
    def create(cls, date: str, title: str, body: str = "", **kwargs) -> "EventEntry":
        """Create a new event with auto-generated ID."""
        from ..schema import generate_event_id

        event_id = generate_event_id(date, title)
        return cls(id=event_id, title=title, body=body, date=date, **kwargs)
