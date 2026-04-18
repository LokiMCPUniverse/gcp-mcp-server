"""GCP MCP Server package."""

from __future__ import annotations


def main() -> None:
    """Entry point for the gcp-mcp console script."""
    from gcp_mcp.server import mcp

    mcp.run()


__all__ = ["main"]
