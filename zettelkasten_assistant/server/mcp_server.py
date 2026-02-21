"""MCP (Model Context Protocol) tool registration scaffold.
This module attempts to register tools if an MCP library is available.
If not installed, it provides a no-op start() with instructions.
"""

from typing import Any

from ..config import OPENAI_API_BASE, OPENAI_API_KEY, ZK_DB_PATH, ZK_LLM_PROVIDER, ZK_NOTES_DIR
from ..services.llm import LLMClient
from ..services.workflow import CEQRC
from ..storage.database import ZKDB
from ..storage.repository import NoteRepository

repo = NoteRepository(ZK_NOTES_DIR)
db = ZKDB(ZK_DB_PATH)
llm = LLMClient(provider=ZK_LLM_PROVIDER, api_key=OPENAI_API_KEY, api_base=OPENAI_API_BASE)
flow = CEQRC(repo, db, llm)


def _create_note(args: dict[str, Any]) -> dict[str, Any]:
    title = args.get("title", "(untitled)")
    body = args.get("body", "")
    tags = args.get("tags") or []
    note = flow.create_seed(title, body, tags)
    return {"id": note.id, "title": note.title}


def _search(args: dict[str, Any]) -> dict[str, Any]:
    q = args.get("q", "*")
    tag = args.get("tag")
    return {"results": db.search(q, tag)}


TOOLS = {
    "zk_create_note": {
        "description": "Create a new Zettelkasten note",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        },
        "handler": _create_note,
    },
    "zk_search": {
        "description": "Search notes using SQLite FTS5",
        "input_schema": {
            "type": "object",
            "properties": {"q": {"type": "string"}, "tag": {"type": ["string", "null"]}},
        },
        "handler": _search,
    },
}


def start():
    try:
        # Example using a hypothetical MCP lib
        from fastmcp import MCP

        mcp = MCP(name="zk-assistant", version="0.1.0")
        for name, meta in TOOLS.items():
            mcp.register_tool(
                name=name,
                description=meta["description"],
                input_schema=meta["input_schema"],
                handler=meta["handler"],
            )
        print("[MCP] Starting MCP server...")
        mcp.run()
    except Exception as e:
        print("[MCP] Library not installed or failed to start:", e)
        print("You can still use the FastAPI server. See docs/MCP_INTEGRATION.md for details.")
