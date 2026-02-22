"""
Search Service

Unified search operations with FTS5 query sanitization and hybrid search.
Used by API, CLI, and UI layers.
"""

import re
from enum import Enum
from typing import Any

from ..storage.database import CascadeDB


class SearchMode(str, Enum):
    """Search mode for queries."""

    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class SearchService:
    """
    Service for search operations.

    Provides:
    - FTS5 query sanitization (handles hyphens, special chars)
    - Full-text search with filters
    - Timeline queries
    - Tag and actor analytics
    """

    def __init__(self, db: CascadeDB):
        self.db = db

    # =========================================================================
    # Query Sanitization
    # =========================================================================

    @staticmethod
    def sanitize_fts_query(query: str) -> str:
        """
        Sanitize a search query for FTS5.

        FTS5 interprets hyphens as NOT operators, which breaks searches for
        hyphenated terms like "alex-jones" or "2024-01-15".

        This method:
        - Quotes hyphenated words to treat them as literals
        - Preserves explicit FTS5 operators (AND, OR, NOT)
        - Preserves quoted phrases

        Examples:
            "alex-jones" -> '"alex-jones"'
            "alex jones" -> "alex jones" (unchanged)
            'alex AND "not-here"' -> 'alex AND "not-here"' (preserved)
        """
        # If query already contains FTS5 operators or quotes, assume user knows what they're doing
        if any(op in query.upper() for op in [" AND ", " OR ", " NOT ", '"']):
            return query

        # Quote hyphenated terms to prevent FTS5 interpreting hyphens as NOT
        sanitized = re.sub(r"(\S*-\S*)", r'"\1"', query)
        return sanitized

    # =========================================================================
    # Search Operations
    # =========================================================================

    def search(
        self,
        query: str,
        kb_name: str | None = None,
        entry_type: str | None = None,
        tags: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
        sanitize: bool = True,
        mode: str | SearchMode = SearchMode.KEYWORD,
    ) -> list[dict[str, Any]]:
        """
        Search across entries.

        Args:
            query: Search query
            kb_name: Filter to specific KB (None for all)
            entry_type: Filter by type (event, actor, etc.)
            tags: Filter by tags (AND logic)
            date_from: Filter from date (YYYY-MM-DD)
            date_to: Filter to date (YYYY-MM-DD)
            limit: Max results
            offset: Pagination offset
            sanitize: Whether to sanitize query for FTS5 (default True)
            mode: Search mode - keyword, semantic, or hybrid

        Returns:
            List of matching entries with snippets and rank
        """
        # Normalize mode
        if isinstance(mode, str):
            try:
                mode = SearchMode(mode)
            except ValueError:
                mode = SearchMode.KEYWORD

        # Normalize "All KBs" to None
        if kb_name == "All KBs":
            kb_name = None

        if mode == SearchMode.SEMANTIC:
            return self._semantic_search(query, kb_name, limit)
        elif mode == SearchMode.HYBRID:
            return self._hybrid_search(
                query, kb_name, entry_type, tags, date_from, date_to, limit, offset, sanitize
            )

        # Default: keyword search
        if sanitize:
            query = self.sanitize_fts_query(query)

        return self.db.search(
            query=query,
            kb_name=kb_name,
            entry_type=entry_type,
            tags=tags,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )

    def _semantic_search(
        self,
        query: str,
        kb_name: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Pure semantic vector search."""
        from .embedding_service import EmbeddingService, is_available

        if not is_available() or not self.db.vec_available:
            return []

        svc = EmbeddingService(self.db)
        if not svc.has_embeddings():
            return []

        return svc.search_similar(query, kb_name=kb_name, limit=limit)

    def _hybrid_search(
        self,
        query: str,
        kb_name: str | None = None,
        entry_type: str | None = None,
        tags: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
        sanitize: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Hybrid search using Reciprocal Rank Fusion (RRF).

        Combines FTS5 keyword results with vector similarity results.
        Falls back to keyword-only if no embeddings exist.
        """
        # Get keyword results
        kw_query = self.sanitize_fts_query(query) if sanitize else query
        keyword_results = self.db.search(
            query=kw_query,
            kb_name=kb_name,
            entry_type=entry_type,
            tags=tags,
            date_from=date_from,
            date_to=date_to,
            limit=limit * 2,
            offset=0,
        )

        # Try to get semantic results
        semantic_results = self._semantic_search(query, kb_name, limit=limit * 2)

        if not semantic_results:
            # No embeddings — fall back to keyword only
            return keyword_results[offset : offset + limit]

        # Reciprocal Rank Fusion
        k = 60  # RRF constant
        scores: dict[tuple[str, str], float] = {}
        entries: dict[tuple[str, str], dict[str, Any]] = {}

        for rank, result in enumerate(keyword_results):
            key = (result["id"], result["kb_name"])
            scores[key] = scores.get(key, 0) + 1.0 / (k + rank)
            entries[key] = result

        for rank, result in enumerate(semantic_results):
            key = (result["id"], result["kb_name"])
            scores[key] = scores.get(key, 0) + 1.0 / (k + rank)
            if key not in entries:
                entries[key] = result

        # Sort by RRF score descending
        sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)

        results = []
        for key in sorted_keys[offset : offset + limit]:
            entry = entries[key]
            entry["rrf_score"] = scores[key]
            results.append(entry)

        return results

    def search_by_tag(
        self, tag: str, kb_name: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Search entries by tag."""
        if kb_name == "All KBs":
            kb_name = None
        return self.db.search_by_tag(tag, kb_name, limit)

    def search_by_actor(
        self, actor_name: str, kb_name: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Search entries mentioning an actor."""
        if kb_name == "All KBs":
            kb_name = None
        return self.db.search_by_actor(actor_name, kb_name, limit)

    # =========================================================================
    # Timeline
    # =========================================================================

    def get_timeline(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        min_importance: int = 1,
        actor: str | None = None,
        kb_name: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get timeline events.

        Args:
            date_from: Filter from date
            date_to: Filter to date
            min_importance: Minimum importance level (1-5)
            actor: Filter by actor name
            kb_name: Filter to specific KB
            limit: Max results
        """
        if kb_name == "All KBs":
            kb_name = None

        results = self.db.get_timeline(
            date_from=date_from, date_to=date_to, min_importance=min_importance, kb_name=kb_name
        )

        # Add actors to each result
        for result in results:
            actors = self.db.conn.execute(
                "SELECT actor_name FROM entry_actor WHERE entry_id = ? AND kb_name = ?",
                (result["id"], result["kb_name"]),
            ).fetchall()
            result["actors"] = [a["actor_name"] for a in actors]

        # Filter by actor if specified
        if actor:
            actor_lower = actor.lower()
            results = [
                r for r in results if any(actor_lower in a.lower() for a in r.get("actors", []))
            ]

        return results[:limit]

    # =========================================================================
    # Analytics
    # =========================================================================

    def get_tags(self, kb_name: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Get tags with counts."""
        if kb_name == "All KBs":
            kb_name = None

        tags = self.db.get_all_tags(kb_name)
        return [{"name": name, "count": count} for name, count in tags[:limit]]

    def get_actors(self, kb_name: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Get actors with mention counts."""
        if kb_name == "All KBs":
            kb_name = None

        if kb_name:
            query = """
                SELECT actor_name, COUNT(*) as mentions
                FROM entry_actor
                WHERE kb_name = ?
                GROUP BY actor_name
                ORDER BY mentions DESC
                LIMIT ?
            """
            rows = self.db.conn.execute(query, (kb_name, limit)).fetchall()
        else:
            query = """
                SELECT actor_name, COUNT(*) as mentions
                FROM entry_actor
                GROUP BY actor_name
                ORDER BY mentions DESC
                LIMIT ?
            """
            rows = self.db.conn.execute(query, (limit,)).fetchall()

        return [{"name": r["actor_name"], "mentions": r["mentions"]} for r in rows]

    def get_most_linked(self, kb_name: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Get most referenced entries."""
        if kb_name == "All KBs":
            kb_name = None
        return self.db.get_most_linked(kb_name, limit)

    def get_orphans(self, kb_name: str | None = None) -> list[dict[str, Any]]:
        """Get entries with no links."""
        if kb_name == "All KBs":
            kb_name = None
        return self.db.get_orphans(kb_name)
