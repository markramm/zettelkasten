"""
cascade-research Server Layer

MCP server and REST API for AI agent and programmatic access.
"""


def __getattr__(name):
    if name == "rest_api":
        from .api import app

        return app
    if name == "CascadeMCPServer":
        from .mcp_server import CascadeMCPServer

        return CascadeMCPServer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["CascadeMCPServer", "rest_api"]
