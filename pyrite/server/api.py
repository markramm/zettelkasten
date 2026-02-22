"""
FastAPI REST Server for pyrite

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
- GET /stats - Get index statistics
- POST /index/sync - Trigger index sync
"""

import sqlite3
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from ..config import PyriteConfig, load_config
from ..models import EventEntry
from ..models.core_types import (
    ENTRY_TYPE_REGISTRY,
    OrganizationEntry,
    PersonEntry,
)
from ..models.generic import GenericEntry
from ..schema import generate_entry_id
from ..storage.database import PyriteDB
from ..storage.index import IndexManager
from ..storage.repository import KBRepository
from .schemas import (
    CreateResponse,
    DeleteResponse,
    EntryResponse,
    KBInfo,
    KBListResponse,
    SearchResponse,
    SearchResult,
    StatsResponse,
    SyncResponse,
    TagCount,
    TagsResponse,
    TimelineEvent,
    TimelineResponse,
    UpdateResponse,
)

# =============================================================================
# Application Setup
# =============================================================================

app = FastAPI(
    title="pyrite API",
    description="REST API for pyrite knowledge management",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
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

_config: PyriteConfig | None = None
_db: PyriteDB | None = None
_index_mgr: IndexManager | None = None


def get_config() -> PyriteConfig:
    """Get or load configuration."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_db() -> PyriteDB:
    """Get or create database connection."""
    global _db
    if _db is None:
        config = get_config()
        _db = PyriteDB(config.settings.index_path)
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
def list_kbs(config: PyriteConfig = Depends(get_config), db: PyriteDB = Depends(get_db)):
    """List all configured knowledge bases."""
    kbs = []
    for kb in config.knowledge_bases:
        stats = db.get_kb_stats(kb.name)
        kbs.append(
            KBInfo(
                name=kb.name,
                type=kb.kb_type,
                path=str(kb.path),
                entries=stats.get("entry_count", 0) if stats else 0,
                indexed=bool(stats.get("last_indexed")) if stats else False,
            )
        )
    return KBListResponse(kbs=kbs, total=len(kbs))


@app.get("/search", response_model=SearchResponse, tags=["Search"])
def search(
    q: str = Query(..., min_length=1, description="Search query"),
    kb: str | None = Query(None, description="Limit to specific KB"),
    type: str | None = Query(None, description="Filter by entry type"),
    tags: str | None = Query(None, description="Comma-separated tags"),
    date_from: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(20, ge=1, le=100),
    mode: str = Query("keyword", description="Search mode: keyword, semantic, hybrid"),
    expand: bool = Query(False, description="Use AI query expansion for additional search terms"),
    db: PyriteDB = Depends(get_db),
):
    """Full-text search across knowledge bases."""
    if db.count_entries() == 0:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "INDEX_EMPTY",
                "message": "Search index is empty",
                "hint": "Run: pyrite-admin index build",
            },
        )

    tag_list = tags.split(",") if tags else None

    try:
        from ..services.search_service import SearchService

        config = get_config()
        search_svc = SearchService(db, settings=config.settings)
        results = search_svc.search(
            query=q,
            kb_name=kb,
            entry_type=type,
            tags=tag_list,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            mode=mode,
            expand=expand,
        )

        return SearchResponse(
            query=q, count=len(results), results=[SearchResult(**r) for r in results]
        )
    except (sqlite3.OperationalError, ValueError) as e:
        raise HTTPException(status_code=400, detail={"code": "SEARCH_FAILED", "message": str(e)})


@app.get("/entries/{entry_id}", response_model=EntryResponse, tags=["Entries"])
def get_entry(
    entry_id: str,
    kb: str | None = Query(None, description="KB name (optional)"),
    with_links: bool = Query(False, description="Include links"),
    config: PyriteConfig = Depends(get_config),
    db: PyriteDB = Depends(get_db),
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
            detail={
                "code": "NOT_FOUND",
                "message": f"Entry '{entry_id}' not found",
                "hint": f"Search: /search?q={entry_id}",
            },
        )

    if with_links:
        result["outlinks"] = db.get_outlinks(entry_id, result["kb_name"])
        result["backlinks"] = db.get_backlinks(entry_id, result["kb_name"])
    else:
        result.setdefault("outlinks", [])
        result.setdefault("backlinks", [])

    result.setdefault("sources", [])
    result.setdefault("tags", [])

    return EntryResponse(**result)


@app.post("/entries", response_model=CreateResponse, tags=["Entries"])
def create_entry(
    kb: str = Query(..., description="KB name"),
    entry_type: str = Query(..., description="Entry type: event, person, organization, note, etc."),
    title: str = Query(..., description="Entry title"),
    body: str | None = Query(None),
    date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    importance: int | None = Query(None, ge=1, le=10),
    tags: str | None = Query(None, description="Comma-separated tags"),
    participants: str | None = Query(None, description="Comma-separated participants"),
    role: str | None = Query(None, description="Role (for person entries)"),
    config: PyriteConfig = Depends(get_config),
    db: PyriteDB = Depends(get_db),
    index_mgr: IndexManager = Depends(get_index_mgr),
):
    """Create a new entry."""
    kb_config = None
    for kbc in config.knowledge_bases:
        if kbc.name == kb:
            kb_config = kbc
            break

    if not kb_config:
        raise HTTPException(
            status_code=404, detail={"code": "KB_NOT_FOUND", "message": f"KB '{kb}' not found"}
        )

    repo = KBRepository(kb_config)
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    participant_list = [a.strip() for a in participants.split(",")] if participants else []

    entry_id = generate_entry_id(title)

    if entry_type == "event":
        if not date:
            raise HTTPException(
                status_code=400, detail={"code": "MISSING_DATE", "message": "Events require a date"}
            )
        entry = EventEntry(
            id=entry_id,
            title=title,
            body=body or "",
            date=date,
            importance=importance or 5,
            participants=participant_list,
            tags=tag_list,
        )
    elif entry_type == "person":
        entry = PersonEntry(
            id=entry_id,
            title=title,
            body=body or "",
            role=role or "",
            importance=importance or 5,
            tags=tag_list,
        )
    elif entry_type == "organization":
        entry = OrganizationEntry(
            id=entry_id,
            title=title,
            body=body or "",
            importance=importance or 5,
            tags=tag_list,
        )
    elif entry_type in ENTRY_TYPE_REGISTRY:
        cls = ENTRY_TYPE_REGISTRY[entry_type]
        entry = cls(id=entry_id, title=title, body=body or "", tags=tag_list)
    else:
        entry = GenericEntry(
            id=entry_id,
            title=title,
            body=body or "",
            _entry_type=entry_type,
            tags=tag_list,
        )

    file_path = repo.save(entry)
    index_mgr.index_entry(entry, kb, file_path)

    return CreateResponse(created=True, id=entry.id, kb_name=kb, file_path=str(file_path))


@app.put("/entries/{entry_id}", response_model=UpdateResponse, tags=["Entries"])
def update_entry(
    entry_id: str,
    kb: str = Query(..., description="KB name"),
    title: str | None = Query(None),
    body: str | None = Query(None),
    importance: int | None = Query(None, ge=1, le=10),
    tags: str | None = Query(None),
    config: PyriteConfig = Depends(get_config),
    db: PyriteDB = Depends(get_db),
    index_mgr: IndexManager = Depends(get_index_mgr),
):
    """Update an existing entry."""
    kb_config = None
    for kbc in config.knowledge_bases:
        if kbc.name == kb:
            kb_config = kbc
            break

    if not kb_config:
        raise HTTPException(
            status_code=404, detail={"code": "KB_NOT_FOUND", "message": f"KB '{kb}' not found"}
        )

    repo = KBRepository(kb_config)
    entry = repo.load(entry_id)

    if not entry:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Entry '{entry_id}' not found"},
        )

    if title is not None:
        entry.title = title
    if body is not None:
        entry.body = body
    if importance is not None and hasattr(entry, "importance"):
        entry.importance = importance
    if tags is not None:
        entry.tags = [t.strip() for t in tags.split(",")]

    entry.updated_at = datetime.now(UTC)
    file_path = repo.save(entry)
    index_mgr.index_entry(entry, kb, file_path)

    return UpdateResponse(updated=True, id=entry_id)


@app.delete("/entries/{entry_id}", response_model=DeleteResponse, tags=["Entries"])
def delete_entry(
    entry_id: str,
    kb: str = Query(..., description="KB name"),
    config: PyriteConfig = Depends(get_config),
    db: PyriteDB = Depends(get_db),
):
    """Delete an entry."""
    kb_config = None
    for kbc in config.knowledge_bases:
        if kbc.name == kb:
            kb_config = kbc
            break

    if not kb_config:
        raise HTTPException(
            status_code=404, detail={"code": "KB_NOT_FOUND", "message": f"KB '{kb}' not found"}
        )

    repo = KBRepository(kb_config)
    if not repo.delete(entry_id):
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Entry '{entry_id}' not found"},
        )

    db.delete_entry(entry_id, kb)

    return DeleteResponse(deleted=True, id=entry_id)


@app.get("/timeline", response_model=TimelineResponse, tags=["Timeline"])
def get_timeline(
    date_from: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    min_importance: int | None = Query(None, ge=1, le=10),
    limit: int = Query(50, ge=1, le=500),
    db: PyriteDB = Depends(get_db),
):
    """Get timeline events."""
    results = db.get_timeline(
        date_from=date_from, date_to=date_to, min_importance=min_importance or 1
    )

    results = results[:limit]

    return TimelineResponse(
        count=len(results),
        date_from=date_from,
        date_to=date_to,
        events=[
            TimelineEvent(
                id=r["id"],
                date=r["date"],
                title=r["title"],
                importance=r.get("importance", 5),
                tags=r.get("tags", []),
            )
            for r in results
        ],
    )


@app.get("/tags", response_model=TagsResponse, tags=["Tags"])
def get_tags(
    kb: str | None = Query(None, description="Filter by KB"),
    limit: int = Query(100, ge=1, le=1000),
    db: PyriteDB = Depends(get_db),
):
    """Get tags with usage counts."""
    tags = db.get_tags_as_dicts(kb_name=kb, limit=limit)

    return TagsResponse(
        count=len(tags), tags=[TagCount(name=t["name"], count=t["count"]) for t in tags]
    )


@app.get("/stats", response_model=StatsResponse, tags=["Admin"])
def get_stats(index_mgr: IndexManager = Depends(get_index_mgr)):
    """Get index statistics."""
    stats = index_mgr.get_index_stats()
    return StatsResponse(**stats)


@app.post("/index/sync", response_model=SyncResponse, tags=["Admin"])
def sync_index(index_mgr: IndexManager = Depends(get_index_mgr)):
    """Trigger incremental index sync."""
    result = index_mgr.sync_incremental()
    return SyncResponse(
        synced=True,
        added=result.get("added", 0),
        updated=result.get("updated", 0),
        removed=result.get("removed", 0),
    )


@app.get("/health", tags=["Admin"])
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}


# =============================================================================
# Main
# =============================================================================


def main():
    """Run the API server."""
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8088)


if __name__ == "__main__":
    main()
