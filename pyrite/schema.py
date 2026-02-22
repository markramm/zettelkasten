"""
KB Schema Definitions

Defines core types, validation, and extensible schema system.
Supports per-KB schema customization via kb.yaml.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


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


# Core entry types shipped with pyrite
CORE_TYPES: dict[str, dict[str, Any]] = {
    "note": {
        "description": "General-purpose knowledge note",
        "subdirectory": "notes",
        "fields": {"tags": "list[str]", "links": "list[Link]"},
    },
    "person": {
        "description": "An individual",
        "subdirectory": "people",
        "fields": {
            "role": "str",
            "affiliations": "list[str]",
        },
    },
    "organization": {
        "description": "A group, company, institution",
        "subdirectory": "organizations",
        "fields": {
            "org_type": "str",  # gov, ngo, corp, etc.
            "jurisdiction": "str",
            "founded": "str",
        },
    },
    "event": {
        "description": "Something that happened",
        "subdirectory": "events",
        "fields": {
            "date": "str",
            "location": "str",
            "importance": "int",
            "status": "EventStatus",
            "participants": "list[str]",
        },
    },
    "document": {
        "description": "A reference document",
        "subdirectory": "documents",
        "fields": {
            "date": "str",
            "author": "str",
            "document_type": "str",
            "url": "str",
        },
    },
    "topic": {
        "description": "A theme, subject area, or concept",
        "subdirectory": "topics",
        "fields": {},
    },
    "relationship": {
        "description": "A connection between entities",
        "subdirectory": "relationships",
        "fields": {
            "source": "str",
            "target": "str",
            "relationship_type": "str",
        },
    },
    "timeline": {
        "description": "An ordered sequence of events",
        "subdirectory": "timelines",
        "fields": {
            "date_range": "str",
        },
    },
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
    source_type: str = "news"
    verified: bool = False
    verified_date: str | None = None
    verified_by: str = ""
    archive_url: str = ""
    key_facts_confirmed: list[str] = field(default_factory=list)
    confidence: str = "unverified"  # high, medium, low, unverified
    access: str = "public"  # public, paywalled, restricted, offline

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {"title": self.title, "url": self.url}
        if self.outlet:
            result["outlet"] = self.outlet
        if self.date:
            result["date"] = self.date
        if self.author:
            result["author"] = self.author
        if self.source_type != "news":
            result["type"] = self.source_type
        if self.verified:
            result["verified"] = self.verified
            if self.verified_date:
                result["verified_date"] = self.verified_date
            if self.verified_by:
                result["verified_by"] = self.verified_by
        if self.archive_url:
            result["archive_url"] = self.archive_url
        if self.key_facts_confirmed:
            result["key_facts_confirmed"] = self.key_facts_confirmed
        if self.confidence != "unverified":
            result["confidence"] = self.confidence
        if self.access != "public":
            result["access"] = self.access
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Source":
        """Create from dictionary."""
        return cls(
            title=data.get("title", ""),
            url=data.get("url", ""),
            outlet=data.get("outlet", ""),
            date=data.get("date"),
            author=data.get("author", ""),
            source_type=data.get("type", "news"),
            verified=data.get("verified", False),
            verified_date=data.get("verified_date"),
            verified_by=data.get("verified_by", ""),
            archive_url=data.get("archive_url", ""),
            key_facts_confirmed=data.get("key_facts_confirmed", []),
            confidence=data.get("confidence", "unverified"),
            access=data.get("access", "public"),
        )


@dataclass
class Link:
    """
    Typed relationship between entries.

    Supports both Zettelkasten-style note links and entity relationships.
    """

    target: str  # Target entry ID or path
    relation: str  # Relationship type
    note: str = ""  # Optional description
    kb: str = ""  # Target KB (if cross-KB link)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {"target": self.target, "relation": self.relation}
        if self.note:
            result["note"] = self.note
        if self.kb:
            result["kb"] = self.kb
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Link":
        """Create from dictionary."""
        # Handle legacy format {to: id, type: relation}
        if "to" in data:
            return cls(
                target=data["to"],
                relation=data.get("type", "related"),
                note=data.get("description", ""),
            )
        return cls(
            target=data.get("target", ""),
            relation=data.get("relation", "related"),
            note=data.get("note", ""),
            kb=data.get("kb", ""),
        )


# Relationship types with inverses
RELATIONSHIP_TYPES: dict[str, dict[str, Any]] = {
    # Entity relationships
    "owns": {"inverse": "owned_by", "description": "Ownership relationship"},
    "owned_by": {"inverse": "owns", "description": "Owned by another entity"},
    "controls": {"inverse": "controlled_by", "description": "Control relationship"},
    "controlled_by": {"inverse": "controls", "description": "Controlled by another entity"},
    "directs": {"inverse": "directed_by", "description": "Directorship"},
    "directed_by": {"inverse": "directs", "description": "Directed by another entity"},
    "advises": {"inverse": "advised_by", "description": "Advisory relationship"},
    "advised_by": {"inverse": "advises", "description": "Advised by another entity"},
    "member_of": {"inverse": "has_member", "description": "Membership"},
    "has_member": {"inverse": "member_of", "description": "Has member"},
    "employed_by": {"inverse": "employs", "description": "Employment relationship"},
    "employs": {"inverse": "employed_by", "description": "Employs"},
    "funds": {"inverse": "funded_by", "description": "Funding relationship"},
    "funded_by": {"inverse": "funds", "description": "Funded by"},
    "authored": {"inverse": "authored_by", "description": "Authorship"},
    "authored_by": {"inverse": "authored", "description": "Authored by"},
    "mentions": {"inverse": "mentioned_by", "description": "Mentions"},
    "mentioned_by": {"inverse": "mentions", "description": "Mentioned by"},
    "involves": {"inverse": "involved_in", "description": "Involvement"},
    "involved_in": {"inverse": "involves", "description": "Involved in"},
    "located_at": {"inverse": "location_of", "description": "Location relationship"},
    "location_of": {"inverse": "located_at", "description": "Location of"},
    "related_to": {"inverse": "related_to", "description": "General relationship"},
    # Zettelkasten note relationships
    "supports": {"inverse": "supported_by", "description": "Evidence supporting a claim"},
    "supported_by": {"inverse": "supports", "description": "Supported by evidence"},
    "contradicts": {"inverse": "contradicted_by", "description": "Contradicting evidence"},
    "contradicted_by": {"inverse": "contradicts", "description": "Contradicted by"},
    "extends": {"inverse": "extended_by", "description": "Extends or elaborates on"},
    "extended_by": {"inverse": "extends", "description": "Extended by"},
    "refines": {"inverse": "refined_by", "description": "Refines or narrows"},
    "refined_by": {"inverse": "refines", "description": "Refined by"},
    "is_example_of": {"inverse": "has_example", "description": "Example of a concept"},
    "has_example": {"inverse": "is_example_of", "description": "Has example"},
    "causally_precedes": {"inverse": "causally_follows", "description": "Causal predecessor"},
    "causally_follows": {"inverse": "causally_precedes", "description": "Causal successor"},
    "asks_question": {"inverse": "answers_question", "description": "Poses a question"},
    "answers_question": {"inverse": "asks_question", "description": "Answers a question"},
    "is_part_of": {"inverse": "contains_part", "description": "Part of a larger whole"},
    "contains_part": {"inverse": "is_part_of", "description": "Contains a part"},
}


def get_all_relationship_types() -> dict[str, dict[str, Any]]:
    """Get all relationship types: core + plugin-provided."""
    all_types = dict(RELATIONSHIP_TYPES)
    try:
        from .plugins import get_registry

        all_types.update(get_registry().get_all_relationship_types())
    except Exception:
        pass
    return all_types


def get_inverse_relation(relation: str) -> str:
    """Get the inverse of a relationship type."""
    all_types = get_all_relationship_types()
    if relation in all_types:
        return all_types[relation]["inverse"]
    return "related_to"


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
            result["created_by"] = self.created_by
        if self.created_date:
            result["created_date"] = self.created_date
        if self.last_modified_by:
            result["last_modified_by"] = self.last_modified_by
        if self.last_modified_date:
            result["last_modified_date"] = self.last_modified_date
        if self.contributors:
            result["contributors"] = self.contributors
        if self.agent_version:
            result["agent_version"] = self.agent_version
            result["agent_confidence"] = self.agent_confidence
        if self.requires_human_review:
            result["requires_human_review"] = self.requires_human_review
        if self.auto_generated_fields:
            result["auto_generated_fields"] = self.auto_generated_fields
        if self.human_verified_fields:
            result["human_verified_fields"] = self.human_verified_fields
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Provenance":
        """Create from dictionary."""
        return cls(
            created_by=data.get("created_by", ""),
            created_date=data.get("created_date", ""),
            last_modified_by=data.get("last_modified_by", ""),
            last_modified_date=data.get("last_modified_date", ""),
            contributors=data.get("contributors", []),
            agent_version=data.get("agent_version", ""),
            agent_confidence=data.get("agent_confidence", 1.0),
            requires_human_review=data.get("requires_human_review", False),
            auto_generated_fields=data.get("auto_generated_fields", []),
            human_verified_fields=data.get("human_verified_fields", []),
        )


# Validation utilities


def validate_date(date_str: str) -> bool:
    """Validate date string format (YYYY-MM-DD)."""
    if not date_str:
        return False
    pattern = r"^\d{4}-\d{2}-\d{2}$"
    if not re.match(pattern, date_str):
        return False
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
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
    pattern = r"^\d{4}-\d{2}-\d{2}--[a-z0-9-]+$"
    return bool(re.match(pattern, event_id))


def generate_event_id(date: str, title: str) -> str:
    """Generate event ID from date and title."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50]
    return f"{date}--{slug}"


def generate_entry_id(title: str) -> str:
    """Generate entry ID from title."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


# =============================================================================
# Extensible Schema System
# =============================================================================


@dataclass
class TypeSchema:
    """Schema definition for an entry type (core or custom)."""

    name: str
    description: str = ""
    required: list[str] = field(default_factory=lambda: ["title"])
    optional: list[str] = field(default_factory=list)
    subdirectory: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"description": self.description}
        if self.required != ["title"]:
            result["required"] = self.required
        if self.optional:
            result["optional"] = self.optional
        if self.subdirectory:
            result["subdirectory"] = self.subdirectory
        return result


@dataclass
class KBSchema:
    """Schema for a knowledge base, loaded from kb.yaml."""

    name: str = ""
    description: str = ""
    types: dict[str, TypeSchema] = field(default_factory=dict)
    policies: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path) -> "KBSchema":
        """Load schema from kb.yaml file."""
        if not path.exists():
            return cls()

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KBSchema":
        """Create from dictionary."""
        types = {}
        for type_name, type_data in data.get("types", {}).items():
            if isinstance(type_data, dict):
                types[type_name] = TypeSchema(
                    name=type_name,
                    description=type_data.get("description", ""),
                    required=type_data.get("required", ["title"]),
                    optional=type_data.get("optional", []),
                    subdirectory=type_data.get("subdirectory", ""),
                )
            else:
                types[type_name] = TypeSchema(name=type_name)

        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            types=types,
            policies=data.get("policies", {}),
            validation=data.get("validation", {}),
        )

    def get_type_schema(self, entry_type: str) -> TypeSchema | None:
        """Get schema for a type, checking KB customizations then core types."""
        if entry_type in self.types:
            return self.types[entry_type]
        if entry_type in CORE_TYPES:
            core = CORE_TYPES[entry_type]
            return TypeSchema(
                name=entry_type,
                description=core["description"],
                subdirectory=core["subdirectory"],
            )
        return None

    def get_subdirectory(self, entry_type: str) -> str:
        """Get the subdirectory for an entry type."""
        type_schema = self.get_type_schema(entry_type)
        if type_schema and type_schema.subdirectory:
            return type_schema.subdirectory
        if entry_type in CORE_TYPES:
            return CORE_TYPES[entry_type]["subdirectory"]
        return f"{entry_type}s"  # Default: plural of type name

    def to_agent_schema(self) -> dict[str, Any]:
        """Export schema in agent-friendly format for kb_schema MCP tool."""
        types_dict = {}

        # Include core types
        for type_name, core_def in CORE_TYPES.items():
            type_info: dict[str, Any] = {
                "description": core_def["description"],
                "fields": core_def["fields"],
            }
            # Apply KB customizations
            if type_name in self.types:
                kb_type = self.types[type_name]
                if kb_type.required != ["title"]:
                    type_info["required"] = kb_type.required
                if kb_type.optional:
                    type_info["optional"] = kb_type.optional
            types_dict[type_name] = type_info

        # Include custom types
        for type_name, type_schema in self.types.items():
            if type_name not in CORE_TYPES:
                types_dict[type_name] = type_schema.to_dict()

        result: dict[str, Any] = {"types": types_dict}

        if self.policies:
            result["policies"] = self.policies

        # Include relationship types (core + plugin)
        all_rels = get_all_relationship_types()
        result["relationship_types"] = {
            name: info["description"]
            for name, info in all_rels.items()
            if info["inverse"] != name  # Skip self-inverse duplicates
        }

        return result

    def validate_entry(
        self,
        entry_type: str,
        fields: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate an entry against the schema. Returns structured validation result."""
        errors = []
        warnings = []

        type_schema = self.get_type_schema(entry_type)
        if not type_schema:
            # Unknown type is OK if validation isn't enforced
            if self.validation.get("enforce", False):
                errors.append(
                    {
                        "field": "entry_type",
                        "rule": "known_type",
                        "expected": list(CORE_TYPES.keys()) + list(self.types.keys()),
                        "got": entry_type,
                    }
                )
            # Don't return early — still run plugin validators below
        else:
            # Check required fields
            for req_field in type_schema.required:
                if req_field not in fields or not fields[req_field]:
                    errors.append(
                        {
                            "field": req_field,
                            "rule": "required",
                            "expected": "non-empty value",
                            "got": fields.get(req_field),
                        }
                    )

        # Check validation rules
        for rule in self.validation.get("rules", []):
            field_name = rule.get("field")
            if field_name not in fields:
                continue

            value = fields[field_name]

            if "range" in rule:
                low, high = rule["range"]
                try:
                    if not (low <= int(value) <= high):
                        item = {
                            "field": field_name,
                            "rule": "range",
                            "expected": rule["range"],
                            "got": value,
                        }
                        if self.validation.get("enforce", False):
                            errors.append(item)
                        else:
                            item["severity"] = "warning"
                            warnings.append(item)
                except (ValueError, TypeError):
                    pass

            if "format" in rule and rule["format"] == "ISO8601":
                if isinstance(value, str) and not validate_date(value):
                    item = {
                        "field": field_name,
                        "rule": "format",
                        "expected": "ISO8601 (YYYY-MM-DD)",
                        "got": value,
                    }
                    if self.validation.get("enforce", False):
                        errors.append(item)
                    else:
                        item["severity"] = "warning"
                        warnings.append(item)

        # Check policies
        min_sources = self.policies.get("minimum_sources", 0)
        if min_sources > 0:
            sources = fields.get("sources", [])
            if len(sources) < min_sources:
                item = {
                    "field": "sources",
                    "rule": "minimum_sources",
                    "expected": min_sources,
                    "got": len(sources),
                    "severity": "warning",
                }
                warnings.append(item)

        # Run plugin validators
        try:
            from .plugins import get_registry

            ctx = context or {}
            for validator in get_registry().get_all_validators():
                try:
                    results = validator(entry_type, fields, ctx)
                    for item in results or []:
                        if item.get("severity") == "warning":
                            warnings.append(item)
                        else:
                            errors.append(item)
                except TypeError:
                    # Fallback for validators with old (entry_type, data) signature
                    try:
                        results = validator(entry_type, fields)
                        for item in results or []:
                            if item.get("severity") == "warning":
                                warnings.append(item)
                            else:
                                errors.append(item)
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}
