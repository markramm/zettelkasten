"""
MCP (Model Context Protocol) Server for cascade-research

Exposes knowledge base operations as MCP tools for AI agents like Claude Code.
Supports stdio transport for direct integration.

Tools exposed:
- kb_list: List all mounted knowledge bases
- kb_search: Full-text search across KBs
- kb_get: Get entry by ID
- kb_create: Create new entry
- kb_update: Update existing entry
- kb_timeline: Get timeline events by date range
- kb_backlinks: Get entries that link to a given entry
- kb_tags: Get all tags with counts
- kb_actors: Get all actors mentioned in events
"""

import json
import sys
from typing import Any

from ..config import CascadeConfig, load_config
from ..models import EventEntry, ResearchEntry
from ..storage.database import CascadeDB
from ..storage.index import IndexManager
from ..storage.repository import KBRepository, MultiKBRepository


class CascadeMCPServer:
    """
    MCP Server for cascade-research.

    Provides tool-based access to knowledge bases for AI agents.
    """

    def __init__(self, config: CascadeConfig | None = None):
        self.config = config or load_config()
        self.db = CascadeDB(self.config.settings.index_path)
        self.repos = MultiKBRepository(self.config.knowledge_bases)
        self.index_mgr = IndexManager(self.db, self.config)

        # Tool registry
        self.tools = {
            "kb_list": {
                "description": "List all mounted knowledge bases with their types and entry counts",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
                "handler": self._kb_list,
            },
            "kb_search": {
                "description": "Full-text search across knowledge bases. Supports FTS5 query syntax (AND, OR, NOT, phrases in quotes). Returns entries with snippets ranked by relevance.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (FTS5 syntax supported)",
                        },
                        "kb_name": {
                            "type": "string",
                            "description": "Limit search to specific KB (optional)",
                        },
                        "entry_type": {
                            "type": "string",
                            "description": "Filter by entry type: event, actor, organization, theme, etc.",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by tags (entries must have ALL specified tags)",
                        },
                        "date_from": {
                            "type": "string",
                            "description": "Start date for events (YYYY-MM-DD)",
                        },
                        "date_to": {
                            "type": "string",
                            "description": "End date for events (YYYY-MM-DD)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum results to return (default 20)",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["keyword", "semantic", "hybrid"],
                            "description": "Search mode: keyword (FTS5), semantic (vector), or hybrid (both combined). Default: keyword",
                        },
                    },
                    "required": ["query"],
                },
                "handler": self._kb_search,
            },
            "kb_get": {
                "description": "Get a specific entry by its ID. Returns full content including body, metadata, sources, and links.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entry_id": {
                            "type": "string",
                            "description": "The entry ID (e.g., '2025-01-20--event-slug' or 'miller-stephen')",
                        },
                        "kb_name": {
                            "type": "string",
                            "description": "KB name (optional - will search all KBs if not provided)",
                        },
                    },
                    "required": ["entry_id"],
                },
                "handler": self._kb_get,
            },
            "kb_create": {
                "description": "Create a new entry in a knowledge base. For events KB, creates timeline events. For research KB, creates actor/organization/theme entries.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "kb_name": {"type": "string", "description": "Target KB name"},
                        "entry_type": {
                            "type": "string",
                            "description": "Entry type: event, actor, organization, theme, mechanism",
                        },
                        "title": {"type": "string", "description": "Entry title"},
                        "body": {"type": "string", "description": "Entry body content (markdown)"},
                        "date": {
                            "type": "string",
                            "description": "Event date (YYYY-MM-DD) - required for events",
                        },
                        "importance": {
                            "type": "integer",
                            "description": "Importance score 1-10 (default 5)",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tags for categorization",
                        },
                        "actors": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Actors involved (for events)",
                        },
                        "role": {"type": "string", "description": "Role description (for actors)"},
                    },
                    "required": ["kb_name", "entry_type", "title"],
                },
                "handler": self._kb_create,
            },
            "kb_update": {
                "description": "Update an existing entry. Only provided fields are updated.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entry_id": {"type": "string", "description": "Entry ID to update"},
                        "kb_name": {"type": "string", "description": "KB name"},
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "importance": {"type": "integer"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "actors": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["entry_id", "kb_name"],
                },
                "handler": self._kb_update,
            },
            "kb_timeline": {
                "description": "Get timeline events within a date range, optionally filtered by importance or actor.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "date_from": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                        "date_to": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                        "min_importance": {
                            "type": "integer",
                            "description": "Minimum importance score (1-10)",
                        },
                        "actor": {"type": "string", "description": "Filter by actor name"},
                        "limit": {"type": "integer", "description": "Maximum results (default 50)"},
                    },
                    "required": [],
                },
                "handler": self._kb_timeline,
            },
            "kb_backlinks": {
                "description": "Get all entries that link TO a given entry (reverse link lookup).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entry_id": {
                            "type": "string",
                            "description": "Entry ID to find backlinks for",
                        },
                        "kb_name": {"type": "string", "description": "KB name"},
                    },
                    "required": ["entry_id", "kb_name"],
                },
                "handler": self._kb_backlinks,
            },
            "kb_tags": {
                "description": "Get all tags with their usage counts, optionally filtered by KB.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "kb_name": {
                            "type": "string",
                            "description": "Filter to specific KB (optional)",
                        },
                        "prefix": {
                            "type": "string",
                            "description": "Filter tags starting with prefix",
                        },
                    },
                    "required": [],
                },
                "handler": self._kb_tags,
            },
            "kb_actors": {
                "description": "Get all actors mentioned in timeline events with their mention counts.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum actors to return (default 100)",
                        }
                    },
                    "required": [],
                },
                "handler": self._kb_actors,
            },
            "kb_index_sync": {
                "description": "Sync the search index with file changes. Use after editing files directly.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "kb_name": {
                            "type": "string",
                            "description": "Sync specific KB (optional - syncs all if not provided)",
                        }
                    },
                    "required": [],
                },
                "handler": self._kb_index_sync,
            },
        }

    # Tool handlers

    def _kb_list(self, args: dict[str, Any]) -> dict[str, Any]:
        """List all knowledge bases."""
        kbs = []
        for kb in self.config.knowledge_bases:
            stats = self.db.get_kb_stats(kb.name)
            kbs.append(
                {
                    "name": kb.name,
                    "type": kb.kb_type.value,
                    "path": str(kb.path),
                    "description": kb.description,
                    "entry_count": stats.get("entry_count", 0) if stats else 0,
                    "read_only": kb.read_only,
                }
            )
        return {"knowledge_bases": kbs}

    def _kb_search(self, args: dict[str, Any]) -> dict[str, Any]:
        """Full-text search with optional semantic/hybrid mode."""
        from ..services.search_service import SearchService

        query = args.get("query", "")
        kb_name = args.get("kb_name")
        entry_type = args.get("entry_type")
        tags = args.get("tags")
        date_from = args.get("date_from")
        date_to = args.get("date_to")
        limit = args.get("limit", 20)
        mode = args.get("mode", "keyword")

        search_svc = SearchService(self.db)
        results = search_svc.search(
            query=query,
            kb_name=kb_name,
            entry_type=entry_type,
            tags=tags,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            mode=mode,
        )

        return {"query": query, "count": len(results), "results": results}

    def _kb_get(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get entry by ID."""
        entry_id = args.get("entry_id")
        kb_name = args.get("kb_name")

        if kb_name:
            result = self.db.get_entry(entry_id, kb_name)
        else:
            # Search all KBs
            result = None
            for kb in self.config.knowledge_bases:
                result = self.db.get_entry(entry_id, kb.name)
                if result:
                    break

        if not result:
            return {"error": f"Entry '{entry_id}' not found"}

        # Get links
        outlinks = self.db.get_outlinks(entry_id, result["kb_name"])
        backlinks = self.db.get_backlinks(entry_id, result["kb_name"])

        result["outlinks"] = outlinks
        result["backlinks"] = backlinks

        return {"entry": result}

    def _kb_create(self, args: dict[str, Any]) -> dict[str, Any]:
        """Create a new entry."""
        kb_name = args.get("kb_name")
        entry_type = args.get("entry_type")
        title = args.get("title")
        body = args.get("body", "")

        kb_config = self.config.get_kb(kb_name)
        if not kb_config:
            return {"error": f"KB '{kb_name}' not found"}

        if kb_config.read_only:
            return {"error": f"KB '{kb_name}' is read-only"}

        repo = KBRepository(kb_config)

        # Create appropriate entry type
        if entry_type == "event":
            date = args.get("date")
            if not date:
                return {"error": "Date is required for events"}

            entry = EventEntry.create(
                date=date, title=title, body=body, importance=args.get("importance", 5)
            )
            entry.tags = args.get("tags", [])
            entry.actors = args.get("actors", [])

        elif entry_type == "actor":
            entry = ResearchEntry.create_actor(
                name=title, role=args.get("role", ""), importance=args.get("importance", 5)
            )
            entry.body = body
            entry.tags = args.get("tags", [])

        elif entry_type == "organization":
            entry = ResearchEntry.create_organization(
                name=title, description=args.get("role", ""), importance=args.get("importance", 5)
            )
            entry.body = body
            entry.tags = args.get("tags", [])

        else:
            # Generic research entry
            entry = ResearchEntry(
                id=title.lower().replace(" ", "-"),
                title=title,
                body=body,
                entry_subtype=entry_type or "theme",
            )
            entry.tags = args.get("tags", [])

        # Save to file
        file_path = repo.save(entry)

        # Index
        self.index_mgr.index_entry(entry, kb_name, file_path)

        return {"created": True, "entry_id": entry.id, "file_path": str(file_path)}

    def _kb_update(self, args: dict[str, Any]) -> dict[str, Any]:
        """Update an existing entry."""
        entry_id = args.get("entry_id")
        kb_name = args.get("kb_name")

        kb_config = self.config.get_kb(kb_name)
        if not kb_config:
            return {"error": f"KB '{kb_name}' not found"}

        if kb_config.read_only:
            return {"error": f"KB '{kb_name}' is read-only"}

        repo = KBRepository(kb_config)
        entry = repo.load(entry_id)

        if not entry:
            return {"error": f"Entry '{entry_id}' not found in {kb_name}"}

        # Update fields
        if "title" in args:
            entry.title = args["title"]
        if "body" in args:
            entry.body = args["body"]
        if "importance" in args:
            entry.importance = args["importance"]
        if "tags" in args:
            entry.tags = args["tags"]
        if "actors" in args and hasattr(entry, "actors"):
            entry.actors = args["actors"]

        # Save
        file_path = repo.save(entry)

        # Re-index
        self.index_mgr.index_entry(entry, kb_name, file_path)

        return {"updated": True, "entry_id": entry.id, "file_path": str(file_path)}

    def _kb_timeline(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get timeline events."""
        date_from = args.get("date_from")
        date_to = args.get("date_to")
        min_importance = args.get("min_importance", 1)
        actor = args.get("actor")
        limit = args.get("limit", 50)

        results = self.db.get_timeline(
            date_from=date_from, date_to=date_to, min_importance=min_importance
        )

        # Filter by actor if specified
        if actor:
            actor_lower = actor.lower()
            results = [
                r for r in results if any(actor_lower in a.lower() for a in (r.get("actors") or []))
            ]

        # Apply limit
        results = results[:limit]

        return {"count": len(results), "events": results}

    def _kb_backlinks(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get backlinks to an entry."""
        entry_id = args.get("entry_id")
        kb_name = args.get("kb_name")

        backlinks = self.db.get_backlinks(entry_id, kb_name)

        return {"entry_id": entry_id, "backlink_count": len(backlinks), "backlinks": backlinks}

    def _kb_tags(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get all tags with counts."""
        kb_name = args.get("kb_name")
        prefix = args.get("prefix", "")

        # Query tags
        if kb_name:
            query = """
                SELECT t.name, COUNT(*) as count
                FROM tag t
                JOIN entry_tag et ON t.id = et.tag_id
                WHERE et.kb_name = ?
                GROUP BY t.name
                ORDER BY count DESC
            """
            rows = self.db.conn.execute(query, (kb_name,)).fetchall()
        else:
            query = """
                SELECT t.name, COUNT(*) as count
                FROM tag t
                JOIN entry_tag et ON t.id = et.tag_id
                GROUP BY t.name
                ORDER BY count DESC
            """
            rows = self.db.conn.execute(query).fetchall()

        tags = [
            {"tag": row["name"], "count": row["count"]}
            for row in rows
            if row["name"].startswith(prefix)
        ]

        return {"tag_count": len(tags), "tags": tags}

    def _kb_actors(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get all actors with mention counts."""
        limit = args.get("limit", 100)

        query = """
            SELECT actor_name, COUNT(*) as mentions
            FROM entry_actor
            GROUP BY actor_name
            ORDER BY mentions DESC
            LIMIT ?
        """
        rows = self.db.conn.execute(query, (limit,)).fetchall()

        actors = [{"actor": row["actor_name"], "mentions": row["mentions"]} for row in rows]

        return {"actor_count": len(actors), "actors": actors}

    def _kb_index_sync(self, args: dict[str, Any]) -> dict[str, Any]:
        """Sync index with file changes."""
        kb_name = args.get("kb_name")

        results = self.index_mgr.sync_incremental(kb_name)

        return {
            "synced": True,
            "added": results["added"],
            "updated": results["updated"],
            "removed": results["removed"],
        }

    # MCP Protocol Implementation

    def get_tools_list(self) -> list[dict[str, Any]]:
        """Return list of available tools in MCP format."""
        return [
            {"name": name, "description": meta["description"], "inputSchema": meta["inputSchema"]}
            for name, meta in self.tools.items()
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool and return result."""
        if name not in self.tools:
            return {"error": f"Unknown tool: {name}"}

        try:
            handler = self.tools[name]["handler"]
            return handler(arguments)
        except Exception as e:
            return {"error": str(e)}

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Handle an MCP protocol message."""
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "cascade-research", "version": "0.1.0"},
                },
            }

        elif method == "tools/list":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": self.get_tools_list()}}

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            result = self.call_tool(tool_name, arguments)

            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]
                },
            }

        else:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

    def run_stdio(self):
        """Run the MCP server over stdio."""
        print("cascade-research MCP server starting...", file=sys.stderr)

        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break

                message = json.loads(line)
                response = self.handle_message(message)

                print(json.dumps(response), flush=True)

            except json.JSONDecodeError as e:
                print(f"JSON decode error: {e}", file=sys.stderr)
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)

    def close(self):
        """Clean up resources."""
        self.db.close()


def main():
    """Entry point for MCP server."""
    server = CascadeMCPServer()
    try:
        server.run_stdio()
    finally:
        server.close()


if __name__ == "__main__":
    main()
