"""Exceptions for the GCP MCP server."""

from __future__ import annotations


class GCPError(Exception):
    """Base exception for the GCP MCP server."""


class AuthenticationError(GCPError):
    """Raised when authentication with GCP fails."""


class APIError(GCPError):
    """Raised when a GCP API call fails."""


class NotFoundError(GCPError):
    """Raised when a requested GCP resource is not found."""
