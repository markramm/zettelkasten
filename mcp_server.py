#!/usr/bin/env python3
"""
Zettelkasten MCP Server

A Model Context Protocol server that provides AI assistants with access to a comprehensive
Zettelkasten knowledge management system. Features include atomic note creation, full-text
search, AI-powered summarization, and intelligent link discovery.

Author: JoshChen
License: MIT
"""

import asyncio
import json
from typing import Any

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.types import Tool

from zettelkasten_assistant.config import (
    OPENAI_API_BASE,
    OPENAI_API_KEY,
    ZK_DB_PATH,
    ZK_LLM_PROVIDER,
    ZK_NOTES_DIR,
)
from zettelkasten_assistant.services.llm import LLMClient
from zettelkasten_assistant.services.workflow import CEQRC
from zettelkasten_assistant.storage.database import ZKDB
from zettelkasten_assistant.storage.repository import NoteRepository

# Initialize components
repo = NoteRepository(ZK_NOTES_DIR)
db = ZKDB(ZK_DB_PATH)
llm = LLMClient(provider=ZK_LLM_PROVIDER, api_key=OPENAI_API_KEY, api_base=OPENAI_API_BASE)
workflow = CEQRC(repo, db, llm)

# Create MCP server instance
server = Server("zettelkasten")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available Zettelkasten tools."""
    return [
        Tool(
            name="zk_create_note",
            description="Create a new atomic note in the Zettelkasten with AI-generated summary",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The title of the note"},
                    "body": {"type": "string", "description": "The main content of the note"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags to categorize the note",
                    },
                    "generate_summary": {
                        "type": "boolean",
                        "description": "Whether to auto-generate AI summary (default: true)",
                        "default": True,
                    },
                },
                "required": ["title", "body"],
            },
        ),
        Tool(
            name="zk_search_notes",
            description="Search notes using full-text search across title, body, and summary",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (supports FTS5 syntax like NEAR/N, quotes for phrases)",
                    },
                    "tag": {
                        "type": "string",
                        "description": "Optional tag filter to narrow results",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 10)",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="zk_get_note",
            description="Retrieve a specific note by ID with all metadata and links",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "string", "description": "The unique ID of the note"},
                    "include_backlinks": {
                        "type": "boolean",
                        "description": "Include notes that link to this note (default: true)",
                        "default": True,
                    },
                },
                "required": ["note_id"],
            },
        ),
        Tool(
            name="zk_run_ceqrc_workflow",
            description="Run the CEQRC workflow (Capture→Explain→Question→Refine→Connect) on a note",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "string", "description": "The ID of the note to process"},
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["explain", "question", "refine", "connect"],
                        },
                        "description": "Specific workflow steps to run (default: all)",
                        "default": ["explain", "question", "refine", "connect"],
                    },
                },
                "required": ["note_id"],
            },
        ),
        Tool(
            name="zk_suggest_links",
            description="Find and suggest connections between notes based on content similarity",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {
                        "type": "string",
                        "description": "The note to find connections for",
                    },
                    "max_suggestions": {
                        "type": "integer",
                        "description": "Maximum number of suggestions (default: 5)",
                        "default": 5,
                    },
                },
                "required": ["note_id"],
            },
        ),
        Tool(
            name="zk_create_link",
            description="Create a typed relationship between two notes",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "description": "The ID of the source note"},
                    "target_id": {"type": "string", "description": "The ID of the target note"},
                    "link_type": {
                        "type": "string",
                        "enum": [
                            "supports",
                            "refines",
                            "extends",
                            "contradicts",
                            "is_example_of",
                            "related",
                        ],
                        "description": "The type of relationship between the notes",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description of the relationship",
                    },
                },
                "required": ["source_id", "target_id", "link_type"],
            },
        ),
        Tool(
            name="zk_generate_summary",
            description="Generate an AI summary for existing note content",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to summarize"},
                    "max_length": {
                        "type": "integer",
                        "description": "Maximum length of summary in characters (default: 280)",
                        "default": 280,
                    },
                },
                "required": ["text"],
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    """Handle tool calls from MCP clients."""

    try:
        if name == "zk_create_note":
            title = arguments.get("title", "(untitled)")
            body = arguments.get("body", "")
            tags = arguments.get("tags", [])
            generate_summary = arguments.get("generate_summary", True)

            # Create note using workflow
            note = workflow.create_seed(title, body, tags)

            result = {
                "success": True,
                "note": {
                    "id": note.id,
                    "title": note.title,
                    "summary": note.summary,
                    "tags": note.tags,
                    "created_at": note.created_at.isoformat(),
                    "status": note.status,
                },
            }
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "zk_search_notes":
            query = arguments.get("query", "*")
            tag = arguments.get("tag")
            limit = arguments.get("limit", 10)

            results = db.search(query, tag, limit=limit)

            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "success": True,
                            "query": query,
                            "tag_filter": tag,
                            "total_results": len(results),
                            "results": results,
                        },
                        indent=2,
                    ),
                )
            ]

        elif name == "zk_get_note":
            note_id = arguments.get("note_id")
            include_backlinks = arguments.get("include_backlinks", True)

            try:
                note = repo.get_note(note_id)
                if not note:
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(
                                {"success": False, "error": f"Note {note_id} not found"}
                            ),
                        )
                    ]

                result = {
                    "success": True,
                    "note": {
                        "id": note.id,
                        "title": note.title,
                        "body": note.body,
                        "summary": note.summary,
                        "tags": note.tags,
                        "links": [
                            {"to": link.to_id, "type": link.type, "description": link.description}
                            for link in note.links
                        ],
                        "created_at": note.created_at.isoformat(),
                        "updated_at": note.updated_at.isoformat(),
                        "status": note.status,
                    },
                }

                if include_backlinks:
                    backlinks = db.get_backlinks(note_id)
                    result["backlinks"] = backlinks

                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            except Exception as e:
                return [
                    types.TextContent(
                        type="text", text=json.dumps({"success": False, "error": str(e)})
                    )
                ]

        elif name == "zk_run_ceqrc_workflow":
            note_id = arguments.get("note_id")
            steps = arguments.get("steps", ["explain", "question", "refine", "connect"])

            try:
                note = repo.get_note(note_id)
                if not note:
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(
                                {"success": False, "error": f"Note {note_id} not found"}
                            ),
                        )
                    ]

                # Run workflow steps
                results = []
                if "explain" in steps:
                    enhanced = workflow.enhance_content(note)
                    results.append({"step": "explain", "completed": True})

                if "question" in steps:
                    questions = workflow.generate_questions(note)
                    results.append({"step": "question", "questions": questions})

                if "refine" in steps:
                    refined = workflow.refine_note(note)
                    results.append({"step": "refine", "completed": True})

                if "connect" in steps:
                    suggestions = workflow.suggest_connections(note)
                    results.append({"step": "connect", "suggestions": suggestions})

                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {"success": True, "note_id": note_id, "workflow_results": results},
                            indent=2,
                        ),
                    )
                ]

            except Exception as e:
                return [
                    types.TextContent(
                        type="text", text=json.dumps({"success": False, "error": str(e)})
                    )
                ]

        elif name == "zk_suggest_links":
            note_id = arguments.get("note_id")
            max_suggestions = arguments.get("max_suggestions", 5)

            try:
                note = repo.get_note(note_id)
                if not note:
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(
                                {"success": False, "error": f"Note {note_id} not found"}
                            ),
                        )
                    ]

                suggestions = workflow.suggest_connections(note, limit=max_suggestions)

                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {"success": True, "note_id": note_id, "suggestions": suggestions},
                            indent=2,
                        ),
                    )
                ]

            except Exception as e:
                return [
                    types.TextContent(
                        type="text", text=json.dumps({"success": False, "error": str(e)})
                    )
                ]

        elif name == "zk_create_link":
            source_id = arguments.get("source_id")
            target_id = arguments.get("target_id")
            link_type = arguments.get("link_type")
            description = arguments.get("description", "")

            try:
                # Verify both notes exist
                source_note = repo.get_note(source_id)
                target_note = repo.get_note(target_id)

                if not source_note:
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(
                                {"success": False, "error": f"Source note {source_id} not found"}
                            ),
                        )
                    ]

                if not target_note:
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(
                                {"success": False, "error": f"Target note {target_id} not found"}
                            ),
                        )
                    ]

                # Create the link
                db.create_link(source_id, target_id, link_type, description)

                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "success": True,
                                "link": {
                                    "source_id": source_id,
                                    "target_id": target_id,
                                    "type": link_type,
                                    "description": description,
                                },
                            },
                            indent=2,
                        ),
                    )
                ]

            except Exception as e:
                return [
                    types.TextContent(
                        type="text", text=json.dumps({"success": False, "error": str(e)})
                    )
                ]

        elif name == "zk_generate_summary":
            text = arguments.get("text")
            max_length = arguments.get("max_length", 280)

            try:
                summary = llm.generate_summary(text, max_length=max_length)

                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "success": True,
                                "original_length": len(text),
                                "summary_length": len(summary),
                                "summary": summary,
                            },
                            indent=2,
                        ),
                    )
                ]

            except Exception as e:
                return [
                    types.TextContent(
                        type="text", text=json.dumps({"success": False, "error": str(e)})
                    )
                ]

        else:
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"success": False, "error": f"Unknown tool: {name}"}),
                )
            ]

    except Exception as e:
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"success": False, "error": f"Tool execution failed: {str(e)}"}),
            )
        ]


async def main():
    """Main entry point for the MCP server."""
    # Import here to avoid issues with event loop
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="zettelkasten",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(), experimental_capabilities={}
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
