"""Tests for ``gcp_mcp.auth``."""

from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from gcp_mcp.auth import get_credentials
from gcp_mcp.config import GCPConfig
from gcp_mcp.exceptions import AuthenticationError


def test_get_credentials_uses_adc_when_no_path(monkeypatch):
    cfg = GCPConfig(default_project_id="p", credentials_path=None, _env_file=None)
    sentinel = MagicMock(name="adc_creds")
    with patch("google.auth.default", return_value=(sentinel, "p")) as default_mock:
        creds = get_credentials(cfg)
    assert creds is sentinel
    default_mock.assert_called_once()


def test_get_credentials_uses_service_account_when_path_set(tmp_path, monkeypatch):
    sa_file = tmp_path / "sa.json"
    sa_file.write_text(json.dumps({"type": "service_account", "client_email": "x@y"}))
    cfg = GCPConfig(credentials_path=str(sa_file), _env_file=None)

    # Inject a fake google.oauth2.service_account to avoid real parsing.
    fake_module = types.ModuleType("google.oauth2.service_account")
    fake_creds = MagicMock(name="sa_creds")
    fake_module.Credentials = MagicMock()
    fake_module.Credentials.from_service_account_file = MagicMock(return_value=fake_creds)
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", fake_module)

    creds = get_credentials(cfg)
    assert creds is fake_creds
    fake_module.Credentials.from_service_account_file.assert_called_once_with(str(sa_file))


def test_get_credentials_missing_sa_file_raises(tmp_path):
    cfg = GCPConfig(credentials_path=str(tmp_path / "does-not-exist.json"), _env_file=None)
    with pytest.raises(AuthenticationError):
        get_credentials(cfg)
