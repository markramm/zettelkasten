"""
cascade-research Server Layer

MCP server and REST API for AI agent and programmatic access.
"""

from .mcp_server import CascadeMCPServer
from .api import app as rest_api

__all__ = ['CascadeMCPServer', 'rest_api']
