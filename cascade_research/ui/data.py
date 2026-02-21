"""
Data loading utilities for cascade-research UI.

Provides cached access to knowledge base data via the REST API or direct DB access.
"""

from typing import Any

import streamlit as st

# Try to import from cascade_research, fall back to API calls
try:
    from cascade_research.config import load_config
    from cascade_research.storage.database import CascadeDB
    from cascade_research.storage.index import IndexManager

    DIRECT_ACCESS = True
except ImportError:
    DIRECT_ACCESS = False


@st.cache_resource
def _get_db():
    """Get database connection (cached as resource)."""
    if not DIRECT_ACCESS:
        return None
    config = load_config()
    return CascadeDB(config.settings.index_path)


@st.cache_resource
def _get_config():
    """Get configuration (cached as resource)."""
    if not DIRECT_ACCESS:
        return None
    return load_config()


@st.cache_resource
def _get_index_mgr():
    """Get index manager (cached as resource)."""
    if not DIRECT_ACCESS:
        return None
    return IndexManager(_get_db(), _get_config())


@st.cache_data(ttl=300)
def get_kb_list() -> list[dict[str, Any]]:
    """Get list of knowledge bases."""
    db = _get_db()
    config = _get_config()

    if not db or not config:
        return []

    kbs = []
    for kb in config.knowledge_bases:
        stats = db.get_kb_stats(kb.name)
        kbs.append(
            {
                "name": kb.name,
                "type": kb.kb_type.value,
                "path": str(kb.path),
                "entries": stats.get("entry_count", 0) if stats else 0,
                "indexed": bool(stats.get("last_indexed")) if stats else False,
            }
        )
    return kbs


@st.cache_data(ttl=300)
def get_stats() -> dict[str, Any]:
    """Get index statistics."""
    index_mgr = _get_index_mgr()
    if not index_mgr:
        return {"total_entries": 0, "total_tags": 0, "total_links": 0}
    return index_mgr.get_index_stats()


@st.cache_data(ttl=60)
def search(
    query: str,
    kb_name: str | None = None,
    entry_type: str | None = None,
    tags: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Full-text search."""
    db = _get_db()
    if not db:
        return []

    # Sanitize query for FTS5 (quote hyphenated terms)
    import re

    sanitized = query
    if not any(op in query.upper() for op in [" AND ", " OR ", " NOT ", '"']):
        sanitized = re.sub(r"(\S*-\S*)", r'"\1"', query)

    try:
        return db.search(
            query=sanitized,
            kb_name=kb_name if kb_name != "All KBs" else None,
            entry_type=entry_type,
            tags=tags,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
    except Exception as e:
        st.error(f"Search error: {e}")
        return []


@st.cache_data(ttl=60)
def get_timeline(
    date_from: str | None = None,
    date_to: str | None = None,
    min_importance: int = 1,
    actor: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get timeline events."""
    db = _get_db()
    if not db:
        return []

    results = db.get_timeline(date_from=date_from, date_to=date_to, min_importance=min_importance)

    if actor:
        actor_lower = actor.lower()
        results = [
            r for r in results if any(actor_lower in a.lower() for a in (r.get("actors") or []))
        ]

    return results[:limit]


@st.cache_data(ttl=300)
def get_tags(kb_name: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Get tags with counts."""
    db = _get_db()
    if not db:
        return []

    query = """
        SELECT t.name, COUNT(*) as count
        FROM tag t
        JOIN entry_tag et ON t.id = et.tag_id
        {} GROUP BY t.name ORDER BY count DESC LIMIT ?
    """.format("WHERE et.kb_name = ?" if kb_name and kb_name != "All KBs" else "")

    params = (kb_name, limit) if kb_name and kb_name != "All KBs" else (limit,)
    rows = db.conn.execute(query, params).fetchall()

    return [{"name": r["name"], "count": r["count"]} for r in rows]


@st.cache_data(ttl=300)
def get_actors(limit: int = 100) -> list[dict[str, Any]]:
    """Get actors with mention counts."""
    db = _get_db()
    if not db:
        return []

    query = """
        SELECT actor_name, COUNT(*) as mentions
        FROM entry_actor
        GROUP BY actor_name
        ORDER BY mentions DESC
        LIMIT ?
    """
    rows = db.conn.execute(query, (limit,)).fetchall()

    return [{"name": r["actor_name"], "mentions": r["mentions"]} for r in rows]


@st.cache_data(ttl=60)
def get_entry(entry_id: str, kb_name: str | None = None) -> dict[str, Any] | None:
    """Get entry by ID."""
    db = _get_db()
    config = _get_config()
    if not db or not config:
        return None

    if kb_name and kb_name != "All KBs":
        result = db.get_entry(entry_id, kb_name)
    else:
        result = None
        for kb in config.knowledge_bases:
            result = db.get_entry(entry_id, kb.name)
            if result:
                break

    if result:
        result["outlinks"] = db.get_outlinks(entry_id, result["kb_name"])
        result["backlinks"] = db.get_backlinks(entry_id, result["kb_name"])

    return result


def clear_cache():
    """Clear all cached data."""
    st.cache_data.clear()
