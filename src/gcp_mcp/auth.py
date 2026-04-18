"""GCP authentication helpers."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from gcp_mcp.exceptions import AuthenticationError

if TYPE_CHECKING:
    from google.auth.credentials import Credentials

    from gcp_mcp.config import GCPConfig


def get_credentials(config: GCPConfig) -> Credentials:
    """Resolve GCP credentials.

    If ``config.credentials_path`` is set, load a service account from that
    JSON file. Otherwise fall back to Application Default Credentials (ADC).
    """
    try:
        if config.credentials_path:
            if not os.path.exists(config.credentials_path):
                raise AuthenticationError(
                    f"Service account file not found: {config.credentials_path}"
                )
            from google.oauth2 import service_account

            credentials = service_account.Credentials.from_service_account_file(
                config.credentials_path
            )
            return credentials

        import google.auth

        credentials, _ = google.auth.default()
        return credentials
    except AuthenticationError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise AuthenticationError(f"Failed to obtain GCP credentials: {exc}") from exc
