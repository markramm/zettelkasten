"""
Research Entry Model

For Research KB - unstructured research documents (actors, organizations, themes, etc.).
"""

from dataclasses import dataclass, field
from typing import Any

from ..schema import RESEARCH_SUBTYPES, FtMSchema, Provenance, ResearchStatus
from .base import Entry, parse_datetime, parse_links, parse_sources


@dataclass
class ResearchEntry(Entry):
    """
    A research knowledge base entry.

    Research entries are flexible documents that can represent:
    - actor: Person profiles
    - organization: Institution/company profiles
    - theme: Cross-cutting analytical frameworks
    - mechanism: How capture/resistance works
    - scene: Narrative prose reconstructions
    - victim: Human impact stories
    - statistic: Verified data points
    - document: Source document analysis
    - event: Event deep-dives (longer than timeline events)
    """
    # Research-specific fields
    entry_subtype: str = "actor"  # actor, organization, theme, mechanism, scene, victim, statistic, document, event
    role: str = ""  # For actors: architect, operative, enabler, etc.
    era: str = ""  # Time period covered
    importance: int = 5
    chapters: list[int] = field(default_factory=list)  # Book chapters referencing this
    research_status: ResearchStatus = ResearchStatus.STUB
    last_updated: str = ""  # YYYY-MM-DD

    # Organization-specific
    jurisdiction: str = ""
    founded: str = ""

    # Statistic-specific
    value: str = ""
    source_date: str = ""

    # Shared with events
    capture_lanes: list[str] = field(default_factory=list)

    @property
    def entry_type(self) -> str:
        return self.entry_subtype

    @property
    def ftm_schema(self) -> str | None:
        schema = RESEARCH_SUBTYPES.get(self.entry_subtype)
        return schema.value if schema else None

    def to_frontmatter(self) -> dict[str, Any]:
        """Convert to YAML frontmatter dictionary."""
        meta: dict[str, Any] = {
            'id': self.id,
            'title': self.title,
            'type': self.entry_subtype,
        }

        # Common optional fields
        if self.role:
            meta['role'] = self.role
        if self.era:
            meta['era'] = self.era
        if self.importance != 5:
            meta['importance'] = self.importance
        if self.chapters:
            meta['chapters'] = self.chapters
        if self.tags:
            meta['tags'] = self.tags
        if self.capture_lanes:
            meta['capture_lanes'] = self.capture_lanes

        # Subtype-specific fields
        if self.entry_subtype == 'organization':
            if self.jurisdiction:
                meta['jurisdiction'] = self.jurisdiction
            if self.founded:
                meta['founded'] = self.founded
        elif self.entry_subtype == 'statistic':
            if self.value:
                meta['value'] = self.value
            if self.source_date:
                meta['source_date'] = self.source_date

        # Sources
        if self.sources:
            meta['sources'] = [s.to_dict() for s in self.sources]

        # Links
        if self.links:
            meta['links'] = [l.to_dict() for l in self.links]

        # Status and dates
        if self.research_status != ResearchStatus.STUB:
            meta['research_status'] = self.research_status.value

        if self.last_updated:
            meta['last_updated'] = self.last_updated
        elif self.updated_at:
            meta['date'] = self.updated_at.strftime('%Y-%m-%d')

        # Provenance
        if self.provenance:
            prov = self.provenance.to_dict()
            if prov:
                meta['provenance'] = prov

        return meta

    @classmethod
    def from_frontmatter(cls, meta: dict[str, Any], body: str) -> 'ResearchEntry':
        """Create from parsed frontmatter and body."""
        # Parse research status
        status_str = meta.get('research_status', 'stub')
        try:
            research_status = ResearchStatus(status_str)
        except ValueError:
            research_status = ResearchStatus.STUB

        # Parse provenance
        prov_data = meta.get('provenance')
        provenance = Provenance.from_dict(prov_data) if prov_data else None

        # Determine subtype
        entry_subtype = meta.get('type', 'actor')

        # Handle various ID formats
        entry_id = meta.get('id', '')
        if not entry_id:
            # Generate ID from title
            import re
            entry_id = re.sub(r'[^a-z0-9]+', '-', meta.get('title', '').lower()).strip('-')

        return cls(
            id=entry_id,
            title=meta.get('title', ''),
            body=body,
            summary=meta.get('summary', ''),
            entry_subtype=entry_subtype,
            role=meta.get('role', ''),
            era=meta.get('era', ''),
            importance=int(meta.get('importance', 5)),
            chapters=meta.get('chapters', []) or [],
            tags=meta.get('tags', []) or [],
            capture_lanes=meta.get('capture_lanes', []) or [],
            sources=parse_sources(meta.get('sources')),
            links=parse_links(meta.get('links')),
            research_status=research_status,
            last_updated=meta.get('last_updated', meta.get('date', '')),
            jurisdiction=meta.get('jurisdiction', ''),
            founded=meta.get('founded', ''),
            value=meta.get('value', ''),
            source_date=meta.get('source_date', ''),
            provenance=provenance,
            created_at=parse_datetime(meta.get('created_at')),
            updated_at=parse_datetime(meta.get('updated_at', meta.get('date'))),
        )

    def validate(self) -> list[str]:
        """Validate research entry."""
        errors = super().validate()

        if self.entry_subtype not in RESEARCH_SUBTYPES:
            errors.append(f"Unknown entry subtype: {self.entry_subtype}")

        if self.entry_subtype == 'statistic' and not self.value:
            errors.append("Statistic entries must have a value")

        return errors

    def to_ftm(self) -> dict[str, Any] | None:
        """Export as FollowTheMoney entity."""
        ftm_schema = self.ftm_schema
        if not ftm_schema:
            return None

        properties: dict[str, list[str]] = {
            'name': [self.title],
        }

        if self.summary:
            properties['summary'] = [self.summary]

        # Person-specific
        if ftm_schema == FtMSchema.PERSON.value:
            if self.role:
                properties['position'] = [self.role]
            # Try to extract nationality, birthDate from body/metadata
            # (Would need more sophisticated parsing)

        # Organization-specific
        elif ftm_schema == FtMSchema.ORGANIZATION.value:
            if self.jurisdiction:
                properties['jurisdiction'] = [self.jurisdiction]
            if self.founded:
                properties['incorporationDate'] = [self.founded]

        # Document-specific
        elif ftm_schema == FtMSchema.DOCUMENT.value:
            if self.sources:
                properties['sourceUrl'] = [s.url for s in self.sources if s.url]

        return {
            'id': self.id,
            'schema': ftm_schema,
            'properties': properties,
        }

    @classmethod
    def create_actor(cls, name: str, **kwargs) -> 'ResearchEntry':
        """Create a new actor entry."""
        import re
        # Parse name into last-first format for ID
        parts = name.split()
        if len(parts) >= 2:
            entry_id = f"{parts[-1].lower()}-{'-'.join(parts[:-1]).lower()}"
        else:
            entry_id = name.lower()
        entry_id = re.sub(r'[^a-z0-9-]+', '', entry_id)

        return cls(
            id=entry_id,
            title=name,
            entry_subtype='actor',
            **kwargs
        )

    @classmethod
    def create_organization(cls, name: str, **kwargs) -> 'ResearchEntry':
        """Create a new organization entry."""
        import re
        entry_id = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')

        return cls(
            id=entry_id,
            title=name,
            entry_subtype='organization',
            **kwargs
        )
