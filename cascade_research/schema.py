"""
KB Schema Definitions

Defines schemas for different KB types (events, research) and their subtypes.
Provides validation and FtM mapping.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class VerificationStatus(str, Enum):
    """Verification status for sources and claims."""
    UNVERIFIED = "unverified"
    CLAIMED = "claimed"
    REVIEWED = "reviewed"
    VERIFIED = "verified"
    DISPUTED = "disputed"


class EventStatus(str, Enum):
    """Status for timeline events."""
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    ALLEGED = "alleged"
    RUMORED = "rumored"


class ResearchStatus(str, Enum):
    """Research completion status."""
    STUB = "stub"
    PARTIAL = "partial"
    DRAFT = "draft"
    COMPLETE = "complete"
    PUBLISHED = "published"


class FtMSchema(str, Enum):
    """FollowTheMoney schema types for export."""
    PERSON = "Person"
    ORGANIZATION = "Organization"
    EVENT = "Event"
    DOCUMENT = "Document"
    PAYMENT = "Payment"
    OWNERSHIP = "Ownership"
    MEMBERSHIP = "Membership"
    DIRECTORSHIP = "Directorship"
    EMPLOYMENT = "Employment"
    UNKNOWN_LINK = "UnknownLink"


# Research KB subtypes and their FtM mappings
RESEARCH_SUBTYPES: dict[str, FtMSchema | None] = {
    "actor": FtMSchema.PERSON,
    "organization": FtMSchema.ORGANIZATION,
    "event": FtMSchema.EVENT,
    "document": FtMSchema.DOCUMENT,
    "theme": None,  # No FtM equivalent
    "mechanism": None,
    "scene": FtMSchema.DOCUMENT,
    "victim": FtMSchema.PERSON,
    "statistic": None,
    "source": FtMSchema.DOCUMENT,
}


@dataclass
class Source:
    """
    Source reference with verification metadata.

    This is a first-class object for tracking provenance.
    """
    title: str
    url: str
    outlet: str = ""
    date: str | None = None
    author: str = ""
    source_type: str = "news"  # news, academic, court_filing, government, leaked, interview, social_media
    verified: bool = False
    verified_date: str | None = None
    verified_by: str = ""
    archive_url: str = ""
    key_facts_confirmed: list[str] = field(default_factory=list)
    confidence: str = "unverified"  # high, medium, low, unverified
    access: str = "public"  # public, paywalled, restricted, offline

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {'title': self.title, 'url': self.url}
        if self.outlet:
            result['outlet'] = self.outlet
        if self.date:
            result['date'] = self.date
        if self.author:
            result['author'] = self.author
        if self.source_type != "news":
            result['type'] = self.source_type
        if self.verified:
            result['verified'] = self.verified
            if self.verified_date:
                result['verified_date'] = self.verified_date
            if self.verified_by:
                result['verified_by'] = self.verified_by
        if self.archive_url:
            result['archive_url'] = self.archive_url
        if self.key_facts_confirmed:
            result['key_facts_confirmed'] = self.key_facts_confirmed
        if self.confidence != "unverified":
            result['confidence'] = self.confidence
        if self.access != "public":
            result['access'] = self.access
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Source':
        """Create from dictionary."""
        return cls(
            title=data.get('title', ''),
            url=data.get('url', ''),
            outlet=data.get('outlet', ''),
            date=data.get('date'),
            author=data.get('author', ''),
            source_type=data.get('type', 'news'),
            verified=data.get('verified', False),
            verified_date=data.get('verified_date'),
            verified_by=data.get('verified_by', ''),
            archive_url=data.get('archive_url', ''),
            key_facts_confirmed=data.get('key_facts_confirmed', []),
            confidence=data.get('confidence', 'unverified'),
            access=data.get('access', 'public'),
        )


@dataclass
class Link:
    """
    Typed relationship between entries.

    Supports both Zettelkasten-style note links and FtM-compatible entity relationships.
    """
    target: str  # Target entry ID or path
    relation: str  # Relationship type
    note: str = ""  # Optional description
    kb: str = ""  # Target KB (if cross-KB link)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {'target': self.target, 'relation': self.relation}
        if self.note:
            result['note'] = self.note
        if self.kb:
            result['kb'] = self.kb
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Link':
        """Create from dictionary."""
        # Handle legacy format {to: id, type: relation}
        if 'to' in data:
            return cls(
                target=data['to'],
                relation=data.get('type', 'related'),
                note=data.get('description', ''),
            )
        return cls(
            target=data.get('target', ''),
            relation=data.get('relation', 'related'),
            note=data.get('note', ''),
            kb=data.get('kb', ''),
        )


# Relationship types with inverses and FtM mappings
RELATIONSHIP_TYPES: dict[str, dict[str, Any]] = {
    # Entity relationships (FtM-compatible)
    "owns": {"inverse": "owned_by", "ftm": FtMSchema.OWNERSHIP},
    "owned_by": {"inverse": "owns", "ftm": FtMSchema.OWNERSHIP},
    "controls": {"inverse": "controlled_by", "ftm": FtMSchema.OWNERSHIP},
    "controlled_by": {"inverse": "controls", "ftm": FtMSchema.OWNERSHIP},
    "directs": {"inverse": "directed_by", "ftm": FtMSchema.DIRECTORSHIP},
    "directed_by": {"inverse": "directs", "ftm": FtMSchema.DIRECTORSHIP},
    "advises": {"inverse": "advised_by", "ftm": FtMSchema.DIRECTORSHIP},
    "advised_by": {"inverse": "advises", "ftm": FtMSchema.DIRECTORSHIP},
    "member_of": {"inverse": "has_member", "ftm": FtMSchema.MEMBERSHIP},
    "has_member": {"inverse": "member_of", "ftm": FtMSchema.MEMBERSHIP},
    "employed_by": {"inverse": "employs", "ftm": FtMSchema.EMPLOYMENT},
    "employs": {"inverse": "employed_by", "ftm": FtMSchema.EMPLOYMENT},
    "funds": {"inverse": "funded_by", "ftm": FtMSchema.PAYMENT},
    "funded_by": {"inverse": "funds", "ftm": FtMSchema.PAYMENT},
    "paid_by": {"inverse": "pays", "ftm": FtMSchema.PAYMENT},
    "pays": {"inverse": "paid_by", "ftm": FtMSchema.PAYMENT},
    "authored": {"inverse": "authored_by", "ftm": None},
    "authored_by": {"inverse": "authored", "ftm": None},
    "mentions": {"inverse": "mentioned_by", "ftm": None},
    "mentioned_by": {"inverse": "mentions", "ftm": None},
    "involves": {"inverse": "involved_in", "ftm": None},
    "involved_in": {"inverse": "involves", "ftm": None},
    "located_at": {"inverse": "location_of", "ftm": None},
    "location_of": {"inverse": "located_at", "ftm": None},
    "related_to": {"inverse": "related_to", "ftm": FtMSchema.UNKNOWN_LINK},

    # Zettelkasten note relationships
    "supports": {"inverse": "supported_by", "ftm": None},
    "supported_by": {"inverse": "supports", "ftm": None},
    "contradicts": {"inverse": "contradicted_by", "ftm": None},
    "contradicted_by": {"inverse": "contradicts", "ftm": None},
    "extends": {"inverse": "extended_by", "ftm": None},
    "extended_by": {"inverse": "extends", "ftm": None},
    "refines": {"inverse": "refined_by", "ftm": None},
    "refined_by": {"inverse": "refines", "ftm": None},
    "is_example_of": {"inverse": "has_example", "ftm": None},
    "has_example": {"inverse": "is_example_of", "ftm": None},
    "causally_precedes": {"inverse": "causally_follows", "ftm": None},
    "causally_follows": {"inverse": "causally_precedes", "ftm": None},
    "asks_question": {"inverse": "answers_question", "ftm": None},
    "answers_question": {"inverse": "asks_question", "ftm": None},
    "is_part_of": {"inverse": "contains_part", "ftm": None},
    "contains_part": {"inverse": "is_part_of", "ftm": None},
}


def get_inverse_relation(relation: str) -> str:
    """Get the inverse of a relationship type."""
    if relation in RELATIONSHIP_TYPES:
        return RELATIONSHIP_TYPES[relation]["inverse"]
    return "related_to"


def get_ftm_schema_for_relation(relation: str) -> FtMSchema | None:
    """Get the FtM schema for a relationship type."""
    if relation in RELATIONSHIP_TYPES:
        return RELATIONSHIP_TYPES[relation].get("ftm")
    return None


@dataclass
class Provenance:
    """
    Provenance tracking for distributed research.

    Tracks who contributed what and when.
    """
    created_by: str = ""
    created_date: str = ""
    last_modified_by: str = ""
    last_modified_date: str = ""
    contributors: list[str] = field(default_factory=list)
    agent_version: str = ""  # For AI agent contributions
    agent_confidence: float = 1.0
    requires_human_review: bool = False
    auto_generated_fields: list[str] = field(default_factory=list)
    human_verified_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary (only non-empty fields)."""
        result = {}
        if self.created_by:
            result['created_by'] = self.created_by
        if self.created_date:
            result['created_date'] = self.created_date
        if self.last_modified_by:
            result['last_modified_by'] = self.last_modified_by
        if self.last_modified_date:
            result['last_modified_date'] = self.last_modified_date
        if self.contributors:
            result['contributors'] = self.contributors
        if self.agent_version:
            result['agent_version'] = self.agent_version
            result['agent_confidence'] = self.agent_confidence
        if self.requires_human_review:
            result['requires_human_review'] = self.requires_human_review
        if self.auto_generated_fields:
            result['auto_generated_fields'] = self.auto_generated_fields
        if self.human_verified_fields:
            result['human_verified_fields'] = self.human_verified_fields
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Provenance':
        """Create from dictionary."""
        return cls(
            created_by=data.get('created_by', ''),
            created_date=data.get('created_date', ''),
            last_modified_by=data.get('last_modified_by', ''),
            last_modified_date=data.get('last_modified_date', ''),
            contributors=data.get('contributors', []),
            agent_version=data.get('agent_version', ''),
            agent_confidence=data.get('agent_confidence', 1.0),
            requires_human_review=data.get('requires_human_review', False),
            auto_generated_fields=data.get('auto_generated_fields', []),
            human_verified_fields=data.get('human_verified_fields', []),
        )


# Validation utilities

def validate_date(date_str: str) -> bool:
    """Validate date string format (YYYY-MM-DD)."""
    if not date_str:
        return False
    pattern = r'^\d{4}-\d{2}-\d{2}$'
    if not re.match(pattern, date_str):
        return False
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return True
    except ValueError:
        return False


def validate_importance(importance: Any) -> bool:
    """Validate importance is 1-10."""
    try:
        val = int(importance)
        return 1 <= val <= 10
    except (ValueError, TypeError):
        return False


def validate_event_id(event_id: str) -> bool:
    """Validate event ID format (YYYY-MM-DD--slug)."""
    pattern = r'^\d{4}-\d{2}-\d{2}--[a-z0-9-]+$'
    return bool(re.match(pattern, event_id))


def generate_event_id(date: str, title: str) -> str:
    """Generate event ID from date and title."""
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:50]
    return f"{date}--{slug}"
