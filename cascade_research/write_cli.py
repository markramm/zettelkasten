#!/usr/bin/env python3
"""
crk: Full-access Knowledge Base CLI

Complete CLI for cascade-research with read, write, and admin operations.
For researcher-owned KBs where you have full control.

For read-only access (safe for untrusted agents), use 'crk-read'.

Documentation: https://github.com/markramm/zettelkasten/blob/main/docs/ARCHITECTURE.md
"""

import argparse
import json
import sqlite3
import sys
from typing import Any

DOCS_URL = "https://github.com/markramm/zettelkasten/blob/main/docs"
VERSION = "0.1.0"

# Exit codes
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_NOT_FOUND = 2
EXIT_KB_NOT_FOUND = 3
EXIT_PERMISSION = 4
EXIT_VALIDATION = 5
EXIT_INDEX = 10
EXIT_ERROR = 99


def get_config():
    from .config import load_config

    return load_config()


def get_db(config):
    from .storage.database import CascadeDB

    return CascadeDB(config.settings.index_path)


def get_index_mgr(db, config):
    from .storage.index import IndexManager

    return IndexManager(db, config)


def get_repo(kb_config):
    from .storage.repository import KBRepository

    return KBRepository(kb_config)


class FullAccessCLI:
    """Full-access CLI for researcher-owned KBs."""

    def __init__(self):
        self.config = None
        self.db = None

    def _ensure_db(self):
        if not self.config:
            self.config = get_config()
        if not self.db:
            self.db = get_db(self.config)

    def output(self, data: dict[str, Any], exit_code: int = EXIT_OK) -> int:
        """Output JSON result."""
        result = {"ok": exit_code == EXIT_OK, "code": exit_code}
        if exit_code == EXIT_OK:
            result["data"] = data
        else:
            result["error"] = data.get("error", {})
        print(json.dumps(result, indent=2, default=str))
        return exit_code

    def error(
        self,
        code: str,
        message: str,
        doc_path: str | None = None,
        hint: str | None = None,
        exit_code: int = EXIT_ERROR,
    ) -> int:
        """Output structured error with docs link."""
        err = {"error": {"code": code, "message": message}}
        if doc_path:
            err["error"]["docs"] = f"{DOCS_URL}/{doc_path}"
        if hint:
            err["error"]["hint"] = hint
        return self.output(err, exit_code)

    # =========================================================================
    # READ COMMANDS
    # =========================================================================

    def cmd_list(self, args) -> int:
        """List knowledge bases."""
        self._ensure_db()
        kbs = []
        for kb in self.config.knowledge_bases:
            stats = self.db.get_kb_stats(kb.name)
            kbs.append(
                {
                    "name": kb.name,
                    "type": kb.kb_type.value,
                    "path": str(kb.path),
                    "entries": stats.get("entry_count", 0) if stats else 0,
                    "indexed": bool(stats.get("last_indexed")) if stats else False,
                    "read_only": kb.read_only,
                }
            )
        return self.output({"kbs": kbs, "total": len(kbs)})

    def cmd_search(self, args) -> int:
        """Full-text search."""
        self._ensure_db()

        if not args.query:
            return self.error(
                "MISSING_QUERY",
                "Search query required",
                hint="crk search 'your query'",
                exit_code=EXIT_USAGE,
            )

        if self.db.count_entries() == 0:
            return self.error(
                "INDEX_EMPTY",
                "Index empty - build it first",
                doc_path="ARCHITECTURE.md#indexing",
                hint="crk index build",
                exit_code=EXIT_INDEX,
            )

        try:
            tags = args.tags.split(",") if args.tags else None
            mode = getattr(args, "mode", "keyword") or "keyword"

            from .services.search_service import SearchService

            expand = getattr(args, "expand", False)
            search_svc = SearchService(self.db, settings=self.config.settings)
            results = search_svc.search(
                query=args.query,
                kb_name=args.kb,
                entry_type=args.type,
                tags=tags,
                date_from=args.date_from,
                date_to=args.date_to,
                limit=args.limit,
                mode=mode,
                expand=expand,
            )
            return self.output({"query": args.query, "count": len(results), "results": results})
        except (sqlite3.OperationalError, ValueError) as e:
            return self.error(
                "SEARCH_FAILED",
                str(e),
                hint="Try simpler query or use quotes for phrases",
                exit_code=EXIT_ERROR,
            )

    def cmd_get(self, args) -> int:
        """Get entry by ID."""
        self._ensure_db()

        result = None
        if args.kb:
            result = self.db.get_entry(args.entry_id, args.kb)
        else:
            for kb in self.config.knowledge_bases:
                result = self.db.get_entry(args.entry_id, kb.name)
                if result:
                    break

        if not result:
            return self.error(
                "NOT_FOUND",
                f"Entry '{args.entry_id}' not found",
                hint=f"crk search '{args.entry_id}'",
                exit_code=EXIT_NOT_FOUND,
            )

        if args.with_links:
            result["outlinks"] = self.db.get_outlinks(args.entry_id, result["kb_name"])
            result["backlinks"] = self.db.get_backlinks(args.entry_id, result["kb_name"])

        return self.output({"entry": result})

    def cmd_timeline(self, args) -> int:
        """Get timeline events."""
        self._ensure_db()

        results = self.db.get_timeline(
            date_from=args.date_from, date_to=args.date_to, min_importance=args.min_importance or 1
        )

        if args.actor:
            actor_lower = args.actor.lower()
            results = [
                r for r in results if any(actor_lower in a.lower() for a in (r.get("actors") or []))
            ]

        return self.output({"count": len(results[: args.limit]), "events": results[: args.limit]})

    def cmd_tags(self, args) -> int:
        """Get tags with counts."""
        self._ensure_db()
        tags = self.db.get_tags_as_dicts(kb_name=args.kb, limit=args.limit)
        return self.output({"tags": tags})

    def cmd_actors(self, args) -> int:
        """Get actors with counts."""
        self._ensure_db()
        actors = self.db.get_actors_with_counts(limit=args.limit)
        return self.output({"actors": actors})

    def cmd_backlinks(self, args) -> int:
        """Get backlinks to entry."""
        self._ensure_db()
        if not args.kb:
            return self.error(
                "MISSING_KB", "KB required for backlinks", hint="--kb <name>", exit_code=EXIT_USAGE
            )
        backlinks = self.db.get_backlinks(args.entry_id, args.kb)
        return self.output({"entry": args.entry_id, "backlinks": backlinks})

    # =========================================================================
    # WRITE COMMANDS
    # =========================================================================

    def cmd_create(self, args) -> int:
        """Create new entry."""
        self._ensure_db()

        kb_config = self.config.get_kb(args.kb)
        if not kb_config:
            return self.error(
                "KB_NOT_FOUND",
                f"KB '{args.kb}' not found",
                hint="crk list",
                exit_code=EXIT_KB_NOT_FOUND,
            )
        if kb_config.read_only:
            return self.error(
                "READ_ONLY", f"KB '{args.kb}' is read-only", exit_code=EXIT_PERMISSION
            )

        if args.type == "event" and not args.date:
            return self.error(
                "MISSING_DATE",
                "Events require --date",
                hint="--date YYYY-MM-DD",
                exit_code=EXIT_VALIDATION,
            )

        from .models import EventEntry, ResearchEntry

        repo = get_repo(kb_config)

        try:
            if args.type == "event":
                entry = EventEntry.create(
                    date=args.date,
                    title=args.title,
                    body=args.body or "",
                    importance=args.importance or 5,
                )
                if args.tags:
                    entry.tags = args.tags.split(",")
                if args.actors:
                    entry.actors = args.actors.split(",")

            elif args.type == "actor":
                entry = ResearchEntry.create_actor(
                    name=args.title, role=args.role or "", importance=args.importance or 5
                )
                entry.body = args.body or ""
                if args.tags:
                    entry.tags = args.tags.split(",")

            elif args.type == "organization":
                entry = ResearchEntry.create_organization(
                    name=args.title, description=args.role or "", importance=args.importance or 5
                )
                entry.body = args.body or ""
                if args.tags:
                    entry.tags = args.tags.split(",")

            else:
                entry = ResearchEntry(
                    id=args.title.lower().replace(" ", "-"),
                    title=args.title,
                    body=args.body or "",
                    entry_subtype=args.type or "theme",
                )
                if args.tags:
                    entry.tags = args.tags.split(",")

            file_path = repo.save(entry)
            get_index_mgr(self.db, self.config).index_entry(entry, args.kb, file_path)

            return self.output(
                {"created": True, "id": entry.id, "path": str(file_path), "kb": args.kb}
            )
        except Exception as e:
            return self.error("CREATE_FAILED", str(e), exit_code=EXIT_ERROR)

    def cmd_update(self, args) -> int:
        """Update existing entry."""
        self._ensure_db()

        kb_config = self.config.get_kb(args.kb)
        if not kb_config:
            return self.error(
                "KB_NOT_FOUND", f"KB '{args.kb}' not found", exit_code=EXIT_KB_NOT_FOUND
            )
        if kb_config.read_only:
            return self.error(
                "READ_ONLY", f"KB '{args.kb}' is read-only", exit_code=EXIT_PERMISSION
            )

        repo = get_repo(kb_config)
        entry = repo.load(args.entry_id)
        if not entry:
            return self.error(
                "NOT_FOUND", f"Entry '{args.entry_id}' not found", exit_code=EXIT_NOT_FOUND
            )

        # Update fields
        if args.title:
            entry.title = args.title
        if args.body:
            entry.body = args.body
        if args.importance:
            entry.importance = args.importance
        if args.tags:
            entry.tags = args.tags.split(",")
        if args.actors and hasattr(entry, "actors"):
            entry.actors = args.actors.split(",")

        file_path = repo.save(entry)
        get_index_mgr(self.db, self.config).index_entry(entry, args.kb, file_path)

        return self.output({"updated": True, "id": entry.id, "path": str(file_path)})

    def cmd_delete(self, args) -> int:
        """Delete entry."""
        self._ensure_db()

        kb_config = self.config.get_kb(args.kb)
        if not kb_config:
            return self.error(
                "KB_NOT_FOUND", f"KB '{args.kb}' not found", exit_code=EXIT_KB_NOT_FOUND
            )
        if kb_config.read_only:
            return self.error(
                "READ_ONLY", f"KB '{args.kb}' is read-only", exit_code=EXIT_PERMISSION
            )

        repo = get_repo(kb_config)
        if not repo.exists(args.entry_id):
            return self.error(
                "NOT_FOUND", f"Entry '{args.entry_id}' not found", exit_code=EXIT_NOT_FOUND
            )

        repo.delete(args.entry_id)
        get_index_mgr(self.db, self.config).remove_entry(args.entry_id, args.kb)

        return self.output({"deleted": True, "id": args.entry_id, "kb": args.kb})

    # =========================================================================
    # ADMIN COMMANDS
    # =========================================================================

    def cmd_index_build(self, args) -> int:
        """Build search index."""
        self._ensure_db()
        index_mgr = get_index_mgr(self.db, self.config)

        try:
            if args.kb:
                count = index_mgr.index_kb(args.kb)
                return self.output({"action": "build", "kb": args.kb, "indexed": count})
            else:
                results = index_mgr.index_all()
                return self.output(
                    {"action": "build", "kbs": results, "total": sum(results.values())}
                )
        except Exception as e:
            return self.error("INDEX_FAILED", str(e), exit_code=EXIT_INDEX)

    def cmd_index_sync(self, args) -> int:
        """Incremental index sync."""
        self._ensure_db()
        index_mgr = get_index_mgr(self.db, self.config)

        results = index_mgr.sync_incremental(args.kb)
        return self.output(
            {
                "action": "sync",
                "added": results["added"],
                "updated": results["updated"],
                "removed": results["removed"],
            }
        )

    def cmd_index_stats(self, args) -> int:
        """Index statistics."""
        self._ensure_db()
        stats = get_index_mgr(self.db, self.config).get_index_stats()
        return self.output(stats)

    def cmd_index_health(self, args) -> int:
        """Check index health."""
        self._ensure_db()
        health = get_index_mgr(self.db, self.config).check_health()
        is_healthy = not (
            health["missing_files"] or health["unindexed_files"] or health["stale_entries"]
        )
        return self.output(
            {
                "healthy": is_healthy,
                "missing": len(health["missing_files"]),
                "unindexed": len(health["unindexed_files"]),
                "stale": len(health["stale_entries"]),
                "details": health if args.verbose else None,
            }
        )


def main():
    parser = argparse.ArgumentParser(
        prog="crk",
        description="cascade-research KB CLI (full access)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Read Commands:
  list                    List all knowledge bases
  search QUERY            Full-text search (FTS5 syntax)
  get ID                  Get entry by ID
  timeline                Get timeline events
  tags                    Get tags with counts
  actors                  Get actors with counts
  backlinks ID            Get entries linking to ID

Write Commands:
  create                  Create new entry
  update ID               Update existing entry
  delete ID               Delete entry

Admin Commands:
  index build             Build/rebuild search index
  index sync              Incremental index sync
  index stats             Index statistics
  index health            Check index health

Examples:
  crk list
  crk search "immigration policy" --kb=timeline
  crk get miller-stephen --with-links
  crk timeline --from=2025-01-01 --actor=Miller
  crk create --kb=timeline --type=event --title="Event" --date=2025-01-20
  crk index build

For read-only access (safe for agents): crk-read
Docs: {DOCS_URL}/ARCHITECTURE.md
""",
    )
    parser.add_argument("--version", action="version", version=f"crk {VERSION}")

    subs = parser.add_subparsers(dest="command", metavar="COMMAND")

    # READ: list
    subs.add_parser("list", help="List KBs")

    # READ: search
    p = subs.add_parser("search", help="Search entries")
    p.add_argument("query", nargs="?")
    p.add_argument("--kb")
    p.add_argument("--type")
    p.add_argument("--tags")
    p.add_argument("--from", dest="date_from")
    p.add_argument("--to", dest="date_to")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument(
        "--mode",
        choices=["keyword", "semantic", "hybrid"],
        default="keyword",
        help="Search mode (keyword, semantic, hybrid)",
    )
    p.add_argument(
        "--expand",
        "-x",
        action="store_true",
        default=False,
        help="Use AI query expansion for additional search terms",
    )

    # READ: get
    p = subs.add_parser("get", help="Get entry")
    p.add_argument("entry_id")
    p.add_argument("--kb")
    p.add_argument("--with-links", action="store_true")

    # READ: timeline
    p = subs.add_parser("timeline", help="Timeline events")
    p.add_argument("--from", dest="date_from")
    p.add_argument("--to", dest="date_to")
    p.add_argument("--min-importance", type=int)
    p.add_argument("--actor")
    p.add_argument("--limit", type=int, default=50)

    # READ: tags
    p = subs.add_parser("tags", help="List tags")
    p.add_argument("--kb")
    p.add_argument("--limit", type=int, default=100)

    # READ: actors
    p = subs.add_parser("actors", help="List actors")
    p.add_argument("--limit", type=int, default=100)

    # READ: backlinks
    p = subs.add_parser("backlinks", help="Get backlinks")
    p.add_argument("entry_id")
    p.add_argument("--kb", required=True)

    # WRITE: create
    p = subs.add_parser("create", help="Create entry")
    p.add_argument("--kb", required=True)
    p.add_argument("--type", required=True, help="event|actor|organization|theme")
    p.add_argument("--title", required=True)
    p.add_argument("--body")
    p.add_argument("--date", help="YYYY-MM-DD (required for events)")
    p.add_argument("--importance", type=int)
    p.add_argument("--tags")
    p.add_argument("--actors")
    p.add_argument("--role")

    # WRITE: update
    p = subs.add_parser("update", help="Update entry")
    p.add_argument("entry_id")
    p.add_argument("--kb", required=True)
    p.add_argument("--title")
    p.add_argument("--body")
    p.add_argument("--importance", type=int)
    p.add_argument("--tags")
    p.add_argument("--actors")

    # WRITE: delete
    p = subs.add_parser("delete", help="Delete entry")
    p.add_argument("entry_id")
    p.add_argument("--kb", required=True)

    # ADMIN: index
    p = subs.add_parser("index", help="Index management")
    idx_subs = p.add_subparsers(dest="index_cmd")

    pb = idx_subs.add_parser("build", help="Build index")
    pb.add_argument("--kb")

    ps = idx_subs.add_parser("sync", help="Sync index")
    ps.add_argument("--kb")

    idx_subs.add_parser("stats", help="Index stats")

    ph = idx_subs.add_parser("health", help="Index health")
    ph.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(EXIT_USAGE)

    cli = FullAccessCLI()

    handlers = {
        "list": cli.cmd_list,
        "search": cli.cmd_search,
        "get": cli.cmd_get,
        "timeline": cli.cmd_timeline,
        "tags": cli.cmd_tags,
        "actors": cli.cmd_actors,
        "backlinks": cli.cmd_backlinks,
        "create": cli.cmd_create,
        "update": cli.cmd_update,
        "delete": cli.cmd_delete,
    }

    if args.command == "index":
        if not args.index_cmd:
            parser.parse_args(["index", "--help"])
        idx_handlers = {
            "build": cli.cmd_index_build,
            "sync": cli.cmd_index_sync,
            "stats": cli.cmd_index_stats,
            "health": cli.cmd_index_health,
        }
        sys.exit(idx_handlers[args.index_cmd](args))
    else:
        sys.exit(handlers[args.command](args))


if __name__ == "__main__":
    main()
