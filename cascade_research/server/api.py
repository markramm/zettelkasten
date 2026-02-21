"""
FastAPI REST Server for cascade-research

Provides HTTP API access to knowledge bases for web applications and external integrations.

Endpoints:
- GET /kbs - List all knowledge bases
- GET /search - Full-text search
- GET /entries/{id} - Get entry by ID
- POST /entries - Create new entry
- PUT /entries/{id} - Update entry
- DELETE /entries/{id} - Delete entry
- GET /timeline - Get timeline events
- GET /tags - Get tags with counts
- GET /actors - Get actors with counts
- GET /stats - Get index statistics
- POST /index/sync - Trigger index sync
"""

from typing import Optional, List
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ..config import load_config, CascadeConfig, KBType
from ..storage.database import CascadeDB
from ..storage.repository import KBRepository
from ..storage.index import IndexManager
from ..models import EventEntry, ResearchEntry


# =============================================================================
# Pydantic Models for API
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
    kbs: List[KBInfo]
    total: int


class SearchResult(BaseModel):
    """Single search result."""
    id: str
    kb_name: str
    entry_type: str
    title: str
    snippet: Optional[str] = None
    date: Optional[str] = None
    importance: Optional[int] = None
    tags: List[str] = []


class SearchResponse(BaseModel):
    """Response for search queries."""
    query: str
    count: int
    results: List[SearchResult]


class EntryBase(BaseModel):
    """Base fields for entries."""
    title: str
    body: Optional[str] = None
    tags: List[str] = []
    importance: Optional[int] = Field(None, ge=1, le=10)


class EventCreate(EntryBase):
    """Fields for creating an event."""
    date: str = Field(..., pattern=r'^\d{4}-\d{2}-\d{2}$')
    actors: List[str] = []
    status: str = "confirmed"


class ActorCreate(EntryBase):
    """Fields for creating an actor."""
    role: Optional[str] = None


class EntryResponse(BaseModel):
    """Full entry response."""
    id: str
    kb_name: str
    entry_type: str
    title: str
    body: Optional[str] = None
    summary: Optional[str] = None
    date: Optional[str] = None
    importance: Optional[int] = None
    status: Optional[str] = None
    tags: List[str] = []
    actors: List[str] = []
    sources: List[dict] = []
    outlinks: List[dict] = []
    backlinks: List[dict] = []
    file_path: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TimelineEvent(BaseModel):
    """Timeline event."""
    id: str
    date: str
    title: str
    importance: int
    actors: List[str] = []
    tags: List[str] = []


class TimelineResponse(BaseModel):
    """Response for timeline queries."""
    count: int
    date_from: Optional[str]
    date_to: Optional[str]
    events: List[TimelineEvent]


class TagCount(BaseModel):
    """Tag with count."""
    name: str
    count: int


class TagsResponse(BaseModel):
    """Response for tags list."""
    count: int
    tags: List[TagCount]


class ActorCount(BaseModel):
    """Actor with mention count."""
    name: str
    mentions: int


class ActorsResponse(BaseModel):
    """Response for actors list."""
    count: int
    actors: List[ActorCount]


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
    hint: Optional[str] = None


# =============================================================================
# Application Setup
# =============================================================================

app = FastAPI(
    title="cascade-research API",
    description="REST API for multi-KB research infrastructure",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS for web frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Dependencies
# =============================================================================

_config: Optional[CascadeConfig] = None
_db: Optional[CascadeDB] = None
_index_mgr: Optional[IndexManager] = None


def get_config() -> CascadeConfig:
    """Get or load configuration."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_db() -> CascadeDB:
    """Get or create database connection."""
    global _db
    if _db is None:
        config = get_config()
        _db = CascadeDB(config.settings.index_path)
    return _db


def get_index_mgr() -> IndexManager:
    """Get or create index manager."""
    global _index_mgr
    if _index_mgr is None:
        _index_mgr = IndexManager(get_db(), get_config())
    return _index_mgr


# =============================================================================
# Endpoints
# =============================================================================

@app.get("/kbs", response_model=KBListResponse, tags=["Knowledge Bases"])
def list_kbs(
    config: CascadeConfig = Depends(get_config),
    db: CascadeDB = Depends(get_db)
):
    """List all configured knowledge bases."""
    kbs = []
    for kb in config.knowledge_bases:
        stats = db.get_kb_stats(kb.name)
        kbs.append(KBInfo(
            name=kb.name,
            type=kb.kb_type.value,
            path=str(kb.path),
            entries=stats.get('entry_count', 0) if stats else 0,
            indexed=bool(stats.get('last_indexed')) if stats else False
        ))
    return KBListResponse(kbs=kbs, total=len(kbs))


@app.get("/search", response_model=SearchResponse, tags=["Search"])
def search(
    q: str = Query(..., min_length=1, description="Search query"),
    kb: Optional[str] = Query(None, description="Limit to specific KB"),
    type: Optional[str] = Query(None, description="Filter by entry type"),
    tags: Optional[str] = Query(None, description="Comma-separated tags"),
    date_from: Optional[str] = Query(None, pattern=r'^\d{4}-\d{2}-\d{2}$'),
    date_to: Optional[str] = Query(None, pattern=r'^\d{4}-\d{2}-\d{2}$'),
    limit: int = Query(20, ge=1, le=100),
    db: CascadeDB = Depends(get_db)
):
    """Full-text search across knowledge bases."""
    # Check index has entries
    row = db.conn.execute("SELECT COUNT(*) FROM entry").fetchone()
    if row[0] == 0:
        raise HTTPException(
            status_code=503,
            detail={"code": "INDEX_EMPTY", "message": "Search index is empty", "hint": "Run: crk index build"}
        )

    # Sanitize query for FTS5 (quote hyphenated terms)
    import re
    sanitized_query = q
    if not any(op in q.upper() for op in [' AND ', ' OR ', ' NOT ', '"']):
        sanitized_query = re.sub(r'(\S*-\S*)', r'"\1"', q)

    tag_list = tags.split(",") if tags else None

    try:
        results = db.search(
            query=sanitized_query,
            kb_name=kb,
            entry_type=type,
            tags=tag_list,
            date_from=date_from,
            date_to=date_to,
            limit=limit
        )

        return SearchResponse(
            query=q,
            count=len(results),
            results=[SearchResult(**r) for r in results]
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail={"code": "SEARCH_FAILED", "message": str(e)})


@app.get("/entries/{entry_id}", response_model=EntryResponse, tags=["Entries"])
def get_entry(
    entry_id: str,
    kb: Optional[str] = Query(None, description="KB name (optional)"),
    with_links: bool = Query(False, description="Include links"),
    config: CascadeConfig = Depends(get_config),
    db: CascadeDB = Depends(get_db)
):
    """Get entry by ID."""
    result = None
    if kb:
        result = db.get_entry(entry_id, kb)
    else:
        for kb_config in config.knowledge_bases:
            result = db.get_entry(entry_id, kb_config.name)
            if result:
                break

    if not result:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Entry '{entry_id}' not found", "hint": f"Search: /search?q={entry_id}"}
        )

    if with_links:
        result['outlinks'] = db.get_outlinks(entry_id, result['kb_name'])
        result['backlinks'] = db.get_backlinks(entry_id, result['kb_name'])
    else:
        result.setdefault('outlinks', [])
        result.setdefault('backlinks', [])

    result.setdefault('sources', [])
    result.setdefault('actors', [])
    result.setdefault('tags', [])

    return EntryResponse(**result)


@app.post("/entries", response_model=CreateResponse, tags=["Entries"])
def create_entry(
    kb: str = Query(..., description="KB name"),
    entry_type: str = Query(..., description="Entry type: event, actor, organization, theme"),
    title: str = Query(..., description="Entry title"),
    body: Optional[str] = Query(None),
    date: Optional[str] = Query(None, pattern=r'^\d{4}-\d{2}-\d{2}$'),
    importance: Optional[int] = Query(None, ge=1, le=10),
    tags: Optional[str] = Query(None, description="Comma-separated tags"),
    actors: Optional[str] = Query(None, description="Comma-separated actors"),
    role: Optional[str] = Query(None, description="Role (for actor entries)"),
    config: CascadeConfig = Depends(get_config),
    db: CascadeDB = Depends(get_db),
    index_mgr: IndexManager = Depends(get_index_mgr)
):
    """Create a new entry."""
    # Find KB
    kb_config = None
    for kbc in config.knowledge_bases:
        if kbc.name == kb:
            kb_config = kbc
            break

    if not kb_config:
        raise HTTPException(
            status_code=404,
            detail={"code": "KB_NOT_FOUND", "message": f"KB '{kb}' not found"}
        )

    repo = KBRepository(kb_config)
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    actor_list = [a.strip() for a in actors.split(",")] if actors else []

    # Create entry based on type
    if entry_type == "event":
        if not date:
            raise HTTPException(status_code=400, detail={"code": "MISSING_DATE", "message": "Events require a date"})
        entry = EventEntry.create(
            date=date,
            title=title,
            body=body or "",
            importance=importance or 5
        )
        entry.tags = tag_list
        entry.actors = actor_list
    else:
        entry = ResearchEntry.create_actor(
            name=title,
            role=role or "",
            importance=importance or 5
        ) if entry_type == "actor" else ResearchEntry.create(
            entry_type=entry_type,
            title=title,
            body=body or "",
            importance=importance or 5
        )
        entry.tags = tag_list

    file_path = repo.save(entry)
    index_mgr.index_entry(entry, kb_config)

    return CreateResponse(
        created=True,
        id=entry.id,
        kb_name=kb,
        file_path=str(file_path)
    )


@app.put("/entries/{entry_id}", response_model=UpdateResponse, tags=["Entries"])
def update_entry(
    entry_id: str,
    kb: str = Query(..., description="KB name"),
    title: Optional[str] = Query(None),
    body: Optional[str] = Query(None),
    importance: Optional[int] = Query(None, ge=1, le=10),
    tags: Optional[str] = Query(None),
    config: CascadeConfig = Depends(get_config),
    db: CascadeDB = Depends(get_db),
    index_mgr: IndexManager = Depends(get_index_mgr)
):
    """Update an existing entry."""
    # Find KB
    kb_config = None
    for kbc in config.knowledge_bases:
        if kbc.name == kb:
            kb_config = kbc
            break

    if not kb_config:
        raise HTTPException(status_code=404, detail={"code": "KB_NOT_FOUND", "message": f"KB '{kb}' not found"})

    repo = KBRepository(kb_config)
    entry = repo.get(entry_id)

    if not entry:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Entry '{entry_id}' not found"})

    # Update fields
    if title is not None:
        entry.title = title
    if body is not None:
        entry.body = body
    if importance is not None:
        entry.importance = importance
    if tags is not None:
        entry.tags = [t.strip() for t in tags.split(",")]

    entry.updated_at = datetime.utcnow()
    repo.save(entry)
    index_mgr.index_entry(entry, kb_config)

    return UpdateResponse(updated=True, id=entry_id)


@app.delete("/entries/{entry_id}", response_model=DeleteResponse, tags=["Entries"])
def delete_entry(
    entry_id: str,
    kb: str = Query(..., description="KB name"),
    config: CascadeConfig = Depends(get_config),
    db: CascadeDB = Depends(get_db)
):
    """Delete an entry."""
    kb_config = None
    for kbc in config.knowledge_bases:
        if kbc.name == kb:
            kb_config = kbc
            break

    if not kb_config:
        raise HTTPException(status_code=404, detail={"code": "KB_NOT_FOUND", "message": f"KB '{kb}' not found"})

    repo = KBRepository(kb_config)
    if not repo.delete(entry_id):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Entry '{entry_id}' not found"})

    db.delete_entry(entry_id, kb)

    return DeleteResponse(deleted=True, id=entry_id)


@app.get("/timeline", response_model=TimelineResponse, tags=["Timeline"])
def get_timeline(
    date_from: Optional[str] = Query(None, pattern=r'^\d{4}-\d{2}-\d{2}$'),
    date_to: Optional[str] = Query(None, pattern=r'^\d{4}-\d{2}-\d{2}$'),
    min_importance: Optional[int] = Query(None, ge=1, le=10),
    actor: Optional[str] = Query(None, description="Filter by actor"),
    limit: int = Query(50, ge=1, le=500),
    db: CascadeDB = Depends(get_db)
):
    """Get timeline events."""
    results = db.get_timeline(
        date_from=date_from,
        date_to=date_to,
        min_importance=min_importance or 1
    )

    if actor:
        actor_lower = actor.lower()
        results = [r for r in results if any(actor_lower in a.lower() for a in (r.get('actors') or []))]

    results = results[:limit]

    return TimelineResponse(
        count=len(results),
        date_from=date_from,
        date_to=date_to,
        events=[TimelineEvent(
            id=r['id'],
            date=r['date'],
            title=r['title'],
            importance=r.get('importance', 5),
            actors=r.get('actors', []),
            tags=r.get('tags', [])
        ) for r in results]
    )


@app.get("/tags", response_model=TagsResponse, tags=["Tags & Actors"])
def get_tags(
    kb: Optional[str] = Query(None, description="Filter by KB"),
    limit: int = Query(100, ge=1, le=1000),
    db: CascadeDB = Depends(get_db)
):
    """Get tags with usage counts."""
    query = """
        SELECT t.name, COUNT(*) as count
        FROM tag t
        JOIN entry_tag et ON t.id = et.tag_id
        {} GROUP BY t.name ORDER BY count DESC LIMIT ?
    """.format("WHERE et.kb_name = ?" if kb else "")

    params = (kb, limit) if kb else (limit,)
    rows = db.conn.execute(query, params).fetchall()

    return TagsResponse(
        count=len(rows),
        tags=[TagCount(name=r['name'], count=r['count']) for r in rows]
    )


@app.get("/actors", response_model=ActorsResponse, tags=["Tags & Actors"])
def get_actors(
    limit: int = Query(100, ge=1, le=1000),
    db: CascadeDB = Depends(get_db)
):
    """Get actors with mention counts."""
    query = """
        SELECT actor_name, COUNT(*) as mentions
        FROM entry_actor
        GROUP BY actor_name
        ORDER BY mentions DESC
        LIMIT ?
    """
    rows = db.conn.execute(query, (limit,)).fetchall()

    return ActorsResponse(
        count=len(rows),
        actors=[ActorCount(name=r['actor_name'], mentions=r['mentions']) for r in rows]
    )


@app.get("/stats", response_model=StatsResponse, tags=["Admin"])
def get_stats(
    index_mgr: IndexManager = Depends(get_index_mgr)
):
    """Get index statistics."""
    stats = index_mgr.get_index_stats()
    return StatsResponse(**stats)


@app.post("/index/sync", response_model=SyncResponse, tags=["Admin"])
def sync_index(
    index_mgr: IndexManager = Depends(get_index_mgr)
):
    """Trigger incremental index sync."""
    result = index_mgr.sync_incremental()
    return SyncResponse(
        synced=True,
        added=result.get('added', 0),
        updated=result.get('updated', 0),
        removed=result.get('removed', 0)
    )


@app.get("/health", tags=["Admin"])
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# =============================================================================
# Main
# =============================================================================

def main():
    """Run the API server."""
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8088)


if __name__ == "__main__":
    main()
