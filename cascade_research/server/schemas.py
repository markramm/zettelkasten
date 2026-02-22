"""
Pydantic models for the cascade-research REST API.

Extracted from api.py to reduce file size and improve organization.
"""

from pydantic import BaseModel, Field

# =============================================================================
# Knowledge Bases
# =============================================================================


class KBInfo(BaseModel):
    """Knowledge base information."""

    name: str
    type: str
    path: str
    entries: int
    indexed: bool


class KBListResponse(BaseModel):
    """Response for listing knowledge bases."""

    kbs: list[KBInfo]
    total: int


# =============================================================================
# Search
# =============================================================================


class SearchResult(BaseModel):
    """Single search result."""

    id: str
    kb_name: str
    entry_type: str
    title: str
    snippet: str | None = None
    date: str | None = None
    importance: int | None = None
    tags: list[str] = []


class SearchResponse(BaseModel):
    """Response for search queries."""

    query: str
    count: int
    results: list[SearchResult]


# =============================================================================
# Entries
# =============================================================================


class EntryBase(BaseModel):
    """Base fields for entries."""

    title: str
    body: str | None = None
    tags: list[str] = []
    importance: int | None = Field(None, ge=1, le=10)


class EventCreate(EntryBase):
    """Fields for creating an event."""

    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    actors: list[str] = []
    status: str = "confirmed"


class ActorCreate(EntryBase):
    """Fields for creating an actor."""

    role: str | None = None


class EntryResponse(BaseModel):
    """Full entry response."""

    id: str
    kb_name: str
    entry_type: str
    title: str
    body: str | None = None
    summary: str | None = None
    date: str | None = None
    importance: int | None = None
    status: str | None = None
    tags: list[str] = []
    actors: list[str] = []
    sources: list[dict] = []
    outlinks: list[dict] = []
    backlinks: list[dict] = []
    file_path: str
    created_at: str | None = None
    updated_at: str | None = None


# =============================================================================
# Timeline
# =============================================================================


class TimelineEvent(BaseModel):
    """Timeline event."""

    id: str
    date: str
    title: str
    importance: int
    actors: list[str] = []
    tags: list[str] = []


class TimelineResponse(BaseModel):
    """Response for timeline queries."""

    count: int
    date_from: str | None
    date_to: str | None
    events: list[TimelineEvent]


# =============================================================================
# Tags & Actors
# =============================================================================


class TagCount(BaseModel):
    """Tag with count."""

    name: str
    count: int


class TagsResponse(BaseModel):
    """Response for tags list."""

    count: int
    tags: list[TagCount]


class ActorCount(BaseModel):
    """Actor with mention count."""

    name: str
    mentions: int


class ActorsResponse(BaseModel):
    """Response for actors list."""

    count: int
    actors: list[ActorCount]


# =============================================================================
# Admin
# =============================================================================


class StatsResponse(BaseModel):
    """Index statistics."""

    total_entries: int
    kbs: dict = {}
    total_tags: int = 0
    total_links: int = 0


class CreateResponse(BaseModel):
    """Response for create operations."""

    created: bool
    id: str
    kb_name: str
    file_path: str


class UpdateResponse(BaseModel):
    """Response for update operations."""

    updated: bool
    id: str


class DeleteResponse(BaseModel):
    """Response for delete operations."""

    deleted: bool
    id: str


class SyncResponse(BaseModel):
    """Response for index sync."""

    synced: bool
    added: int
    updated: int
    removed: int


class ErrorResponse(BaseModel):
    """Error response."""

    code: str
    message: str
    hint: str | None = None
