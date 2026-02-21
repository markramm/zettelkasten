"""
cascade-research Server Layer

MCP server and REST API for AI agent and programmatic access.
"""

from .api import app as rest_api
from .mcp_server import CascadeMCPServer

__all__ = ['CascadeMCPServer', 'rest_api']
