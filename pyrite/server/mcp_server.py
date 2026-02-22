"""
MCP (Model Context Protocol) Server for pyrite

Three-tier MCP server supporting read, write, and admin access levels.
Each tier is a separate server instance with appropriate tools.

Tiers:
- read:  Search, browse, retrieve entries. Safe for any agent.
- write: Read + create/update/delete entries. For trusted agents/users.
- admin: Write + KB management, index rebuild, repo sync, config.
"""

import json
import sys
from typing import Any

from ..config import PyriteConfig, load_config
from ..models.core_types import (
    ENTRY_TYPE_REGISTRY,
    EventEntry,
    OrganizationEntry,
    PersonEntry,
)
from ..models.generic import GenericEntry
from ..schema import KBSchema, generate_entry_id
from ..storage.database import PyriteDB
from ..storage.index import IndexManager
from ..storage.repository import KBRepository, MultiKBRepository


class PyriteMCPServer:
    """
    Three-tier MCP Server for pyrite.

    Provides tool-based access to knowledge bases for AI agents.
    Tier controls which tools are available.
    """

    VALID_TIERS = ("read", "write", "admin")

    def __init__(self, config: PyriteConfig | None = None, tier: str = "read"):
        if tier not in self.VALID_TIERS:
            raise ValueError(f"Invalid tier '{tier}'. Must be one of {self.VALID_TIERS}")

        self.config = config or load_config()
        self.tier = tier
        self.db = PyriteDB(self.config.settings.index_path)
        self.repos = MultiKBRepository(self.config.knowledge_bases)
        self.index_mgr = IndexManager(self.db, self.config)

        # Build tool registry based on tier
        self.tools = {}
        self._build_read_tools()
        if tier in ("write", "admin"):
            self._build_write_tools()
        if tier == "admin":
            self._build_admin_tools()

        # Register plugin tools for this tier
        self._register_plugin_tools()

    # =========================================================================
    # Tool registration by tier
    # =========================================================================

    def _build_read_tools(self):
        """Register read-only tools (available in all tiers)."""
        self.tools.update(
            {
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
                                "description": "Filter by entry type: note, person, organization, event, document, topic, etc.",
                            },
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Filter by tags (entries must have ALL specified tags)",
                            },
                            "date_from": {
                                "type": "string",
                                "description": "Start date (YYYY-MM-DD)",
                            },
                            "date_to": {
                                "type": "string",
                                "description": "End date (YYYY-MM-DD)",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum results to return (default 20)",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["keyword", "semantic", "hybrid"],
                                "description": "Search mode: keyword (FTS5), semantic (vector), or hybrid. Default: keyword",
                            },
                            "expand": {
                                "type": "boolean",
                                "description": "Use AI query expansion for additional search terms. Default: false",
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
                                "description": "The entry ID (e.g., '2025-01-20--event-slug' or 'alice-smith')",
                            },
                            "kb_name": {
                                "type": "string",
                                "description": "KB name (optional - searches all KBs if not provided)",
                            },
                        },
                        "required": ["entry_id"],
                    },
                    "handler": self._kb_get,
                },
                "kb_timeline": {
                    "description": "Get timeline events within a date range, optionally filtered by importance.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "date_from": {
                                "type": "string",
                                "description": "Start date (YYYY-MM-DD)",
                            },
                            "date_to": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                            "min_importance": {
                                "type": "integer",
                                "description": "Minimum importance score (1-10)",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum results (default 50)",
                            },
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
                "kb_stats": {
                    "description": "Get index statistics: entry counts, tag counts, link counts per KB.",
                    "inputSchema": {"type": "object", "properties": {}, "required": []},
                    "handler": self._kb_stats,
                },
                "kb_schema": {
                    "description": "Get the schema for a knowledge base. Returns available entry types, required/optional fields, validation rules, and relationship types. Essential for agents creating entries.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "kb_name": {
                                "type": "string",
                                "description": "KB name to get schema for",
                            },
                        },
                        "required": ["kb_name"],
                    },
                    "handler": self._kb_schema,
                },
            }
        )

    def _build_write_tools(self):
        """Register write tools (available in write and admin tiers)."""
        self.tools.update(
            {
                "kb_create": {
                    "description": "Create a new entry in a knowledge base. Use kb_schema first to discover valid types and fields.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "kb_name": {"type": "string", "description": "Target KB name"},
                            "entry_type": {
                                "type": "string",
                                "description": "Entry type: note, person, organization, event, document, topic, relationship, timeline, or custom type from kb.yaml",
                            },
                            "title": {"type": "string", "description": "Entry title"},
                            "body": {
                                "type": "string",
                                "description": "Entry body content (markdown)",
                            },
                            "date": {
                                "type": "string",
                                "description": "Date (YYYY-MM-DD) - required for events",
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
                            "participants": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Participants involved (for events)",
                            },
                            "role": {
                                "type": "string",
                                "description": "Role description (for person entries)",
                            },
                            "metadata": {
                                "type": "object",
                                "description": "Additional fields for custom types or extension fields",
                            },
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
                            "metadata": {
                                "type": "object",
                                "description": "Extension fields to update",
                            },
                        },
                        "required": ["entry_id", "kb_name"],
                    },
                    "handler": self._kb_update,
                },
                "kb_delete": {
                    "description": "Delete an entry from a knowledge base.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "entry_id": {"type": "string", "description": "Entry ID to delete"},
                            "kb_name": {"type": "string", "description": "KB name"},
                        },
                        "required": ["entry_id", "kb_name"],
                    },
                    "handler": self._kb_delete,
                },
            }
        )

    def _build_admin_tools(self):
        """Register admin tools (available only in admin tier)."""
        self.tools.update(
            {
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
                "kb_manage": {
                    "description": "Manage knowledge bases: add, remove, discover, validate.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["discover", "validate"],
                                "description": "Management action",
                            },
                            "kb_name": {"type": "string", "description": "KB name (for validate)"},
                        },
                        "required": ["action"],
                    },
                    "handler": self._kb_manage,
                },
            }
        )

    def _register_plugin_tools(self):
        """Register MCP tools from plugins for the current tier."""
        try:
            from ..plugins import get_registry

            plugin_tools = get_registry().get_all_mcp_tools(self.tier)
            self.tools.update(plugin_tools)
        except Exception:
            pass  # Plugin loading shouldn't break the MCP server

    # =========================================================================
    # Read handlers
    # =========================================================================

    def _kb_list(self, args: dict[str, Any]) -> dict[str, Any]:
        """List all knowledge bases."""
        kbs = []
        for kb in self.config.knowledge_bases:
            stats = self.db.get_kb_stats(kb.name)
            kbs.append(
                {
                    "name": kb.name,
                    "type": kb.kb_type,
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
        search_svc = SearchService(self.db, settings=self.config.settings)
        results = search_svc.search(
            query=query,
            kb_name=args.get("kb_name"),
            entry_type=args.get("entry_type"),
            tags=args.get("tags"),
            date_from=args.get("date_from"),
            date_to=args.get("date_to"),
            limit=args.get("limit", 20),
            mode=args.get("mode", "keyword"),
            expand=args.get("expand", False),
        )

        return {"query": query, "count": len(results), "results": results}

    def _kb_get(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get entry by ID."""
        entry_id = args.get("entry_id")
        kb_name = args.get("kb_name")

        if kb_name:
            result = self.db.get_entry(entry_id, kb_name)
        else:
            result = None
            for kb in self.config.knowledge_bases:
                result = self.db.get_entry(entry_id, kb.name)
                if result:
                    break

        if not result:
            return {"error": f"Entry '{entry_id}' not found"}

        result["outlinks"] = self.db.get_outlinks(entry_id, result["kb_name"])
        result["backlinks"] = self.db.get_backlinks(entry_id, result["kb_name"])

        return {"entry": result}

    def _kb_timeline(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get timeline events."""
        results = self.db.get_timeline(
            date_from=args.get("date_from"),
            date_to=args.get("date_to"),
            min_importance=args.get("min_importance", 1),
        )
        results = results[: args.get("limit", 50)]
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
        tag_dicts = self.db.get_tags_as_dicts(kb_name=kb_name)
        tags = [
            {"tag": t["name"], "count": t["count"]}
            for t in tag_dicts
            if t["name"].startswith(prefix)
        ]
        return {"tag_count": len(tags), "tags": tags}

    def _kb_stats(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get index statistics."""
        stats = self.index_mgr.get_index_stats()
        return stats

    def _kb_schema(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get KB schema for agent discoverability."""
        kb_name = args.get("kb_name")
        kb_config = self.config.get_kb(kb_name)
        if not kb_config:
            return {"error": f"KB '{kb_name}' not found"}

        schema = KBSchema.from_yaml(kb_config.path / "kb.yaml")
        return schema.to_agent_schema()

    # =========================================================================
    # Write handlers
    # =========================================================================

    def _kb_create(self, args: dict[str, Any]) -> dict[str, Any]:
        """Create a new entry."""
        kb_name = args.get("kb_name")
        entry_type = args.get("entry_type", "note")
        title = args.get("title")
        body = args.get("body", "")

        kb_config = self.config.get_kb(kb_name)
        if not kb_config:
            return {"error": f"KB '{kb_name}' not found"}
        if kb_config.read_only:
            return {"error": f"KB '{kb_name}' is read-only"}

        repo = KBRepository(kb_config)

        # Validate against schema
        schema = KBSchema.from_yaml(kb_config.path / "kb.yaml")
        validation = schema.validate_entry(entry_type, args)
        warnings = [e for e in validation.get("errors", []) if e.get("severity") == "warning"]

        # Build entry from type
        entry_id = generate_entry_id(title)

        if entry_type == "event":
            date = args.get("date")
            if not date:
                return {"error": "Date is required for events"}
            entry = EventEntry(
                id=entry_id,
                title=title,
                body=body,
                date=date,
                importance=args.get("importance", 5),
                participants=args.get("participants", []),
                tags=args.get("tags", []),
            )
        elif entry_type == "person":
            entry = PersonEntry(
                id=entry_id,
                title=title,
                body=body,
                role=args.get("role", ""),
                importance=args.get("importance", 5),
                tags=args.get("tags", []),
            )
        elif entry_type == "organization":
            entry = OrganizationEntry(
                id=entry_id,
                title=title,
                body=body,
                importance=args.get("importance", 5),
                tags=args.get("tags", []),
            )
        elif entry_type in ENTRY_TYPE_REGISTRY:
            cls = ENTRY_TYPE_REGISTRY[entry_type]
            entry = cls(id=entry_id, title=title, body=body, tags=args.get("tags", []))
        else:
            # Check plugin registry, then fall back to GenericEntry
            from ..models.core_types import get_entry_class

            resolved_cls = get_entry_class(entry_type)
            if resolved_cls is not GenericEntry:
                entry = resolved_cls.from_frontmatter(
                    {
                        "id": entry_id,
                        "title": title,
                        "type": entry_type,
                        "tags": args.get("tags", []),
                        **(args.get("metadata") or {}),
                    },
                    body,
                )
            else:
                entry = GenericEntry(
                    id=entry_id,
                    title=title,
                    body=body,
                    _entry_type=entry_type,
                    metadata=args.get("metadata", {}),
                    tags=args.get("tags", []),
                )

        file_path = repo.save(entry)
        self.index_mgr.index_entry(entry, kb_name, file_path)

        result = {"created": True, "entry_id": entry.id, "file_path": str(file_path)}
        if warnings:
            result["warnings"] = warnings
        return result

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

        if "title" in args:
            entry.title = args["title"]
        if "body" in args:
            entry.body = args["body"]
        if "importance" in args and hasattr(entry, "importance"):
            entry.importance = args["importance"]
        if "tags" in args:
            entry.tags = args["tags"]
        if "participants" in args and hasattr(entry, "participants"):
            entry.participants = args["participants"]
        if "metadata" in args and hasattr(entry, "metadata"):
            entry.metadata.update(args["metadata"])

        file_path = repo.save(entry)
        self.index_mgr.index_entry(entry, kb_name, file_path)

        return {"updated": True, "entry_id": entry.id, "file_path": str(file_path)}

    def _kb_delete(self, args: dict[str, Any]) -> dict[str, Any]:
        """Delete an entry."""
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

        repo.delete(entry_id)
        self.db.delete_entry(entry_id, kb_name)

        return {"deleted": True, "entry_id": entry_id}

    # =========================================================================
    # Admin handlers
    # =========================================================================

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

    def _kb_manage(self, args: dict[str, Any]) -> dict[str, Any]:
        """Manage knowledge bases."""
        action = args.get("action")

        if action == "discover":
            discovered = self.config.auto_discover_kbs()
            return {"discovered": len(discovered), "kbs": [str(p) for p in discovered]}
        elif action == "validate":
            kb_name = args.get("kb_name")
            if not kb_name:
                return {"error": "kb_name required for validate"}
            kb_config = self.config.get_kb(kb_name)
            if not kb_config:
                return {"error": f"KB '{kb_name}' not found"}
            schema = KBSchema.from_yaml(kb_config.path / "kb.yaml")
            return {"valid": True, "types": list(schema.types.keys())}

        return {"error": f"Unknown action: {action}"}

    # =========================================================================
    # MCP Protocol
    # =========================================================================

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
                    "serverInfo": {
                        "name": f"pyrite-{self.tier}",
                        "version": "0.2.0",
                    },
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
        print(f"pyrite-{self.tier} MCP server starting...", file=sys.stderr)

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
    """Entry point for MCP server. Supports --tier flag."""
    import argparse

    parser = argparse.ArgumentParser(prog="pyrite-server", description="Pyrite MCP Server")
    parser.add_argument(
        "--tier",
        choices=["read", "write", "admin"],
        default="read",
        help="Access tier (default: read)",
    )
    args = parser.parse_args()

    server = PyriteMCPServer(tier=args.tier)
    try:
        server.run_stdio()
    finally:
        server.close()


if __name__ == "__main__":
    main()
