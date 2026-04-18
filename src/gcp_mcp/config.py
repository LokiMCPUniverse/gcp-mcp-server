"""Configuration for the GCP MCP server."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GCPConfig(BaseSettings):
    """Configuration loaded from environment variables (prefix ``GCP_``).

    Attributes:
        default_project_id: Default GCP project id used when a tool does not
            explicitly receive one. Optional.
        credentials_path: Path to a service account JSON file. When set, this
            takes precedence over Application Default Credentials.
        timeout: Default timeout, in seconds, applied to outbound GCP API
            requests where supported.
    """

    model_config = SettingsConfigDict(
        env_prefix="GCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    default_project_id: str | None = Field(default=None)
    credentials_path: str | None = Field(default=None)
    timeout: int = Field(default=60, ge=1, le=3600)
