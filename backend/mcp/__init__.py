"""MCP server — exposes the platform's internals as tools for external agents.

The tool *logic* lives in tools.py as plain methods returning JSON-able dicts
(unit-testable, network-free). server.py is a thin FastMCP wrapper that registers
them. Clean-room reimplementation of the OpenAlice MCP-exposure concept.
"""
from .tools import Toolset

__all__ = ["Toolset"]
