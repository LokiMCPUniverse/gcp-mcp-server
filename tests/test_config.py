"""Tests for ``gcp_mcp.config``."""

from __future__ import annotations

from gcp_mcp.config import GCPConfig


def test_config_defaults(monkeypatch):
    for var in ("GCP_DEFAULT_PROJECT_ID", "GCP_CREDENTIALS_PATH", "GCP_TIMEOUT"):
        monkeypatch.delenv(var, raising=False)
    cfg = GCPConfig(_env_file=None)
    assert cfg.default_project_id is None
    assert cfg.credentials_path is None
    assert cfg.timeout == 60


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("GCP_DEFAULT_PROJECT_ID", "my-proj")
    monkeypatch.setenv("GCP_CREDENTIALS_PATH", "/tmp/sa.json")
    monkeypatch.setenv("GCP_TIMEOUT", "120")
    cfg = GCPConfig(_env_file=None)
    assert cfg.default_project_id == "my-proj"
    assert cfg.credentials_path == "/tmp/sa.json"
    assert cfg.timeout == 120


def test_config_case_insensitive(monkeypatch):
    monkeypatch.delenv("GCP_DEFAULT_PROJECT_ID", raising=False)
    monkeypatch.setenv("gcp_default_project_id", "lowercase-proj")
    cfg = GCPConfig(_env_file=None)
    assert cfg.default_project_id == "lowercase-proj"
