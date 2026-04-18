"""Shared test fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gcp_mcp.config import GCPConfig


@dataclass
class FakeClients:
    """Stand-in for :class:`gcp_mcp.clients.GCPClients`."""

    credentials: object
    storage: MagicMock
    compute_instances: MagicMock
    compute_zones: MagicMock
    bigquery: MagicMock
    pubsub_publisher: MagicMock
    pubsub_subscriber: MagicMock
    logging: MagicMock
    resource_manager_projects: MagicMock
    config: GCPConfig


def _make_app_context(config: GCPConfig | None = None):
    from gcp_mcp.server import AppContext

    cfg = config or GCPConfig(default_project_id="test-project")
    clients = FakeClients(
        credentials=MagicMock(name="credentials"),
        storage=MagicMock(name="storage"),
        compute_instances=MagicMock(name="compute_instances"),
        compute_zones=MagicMock(name="compute_zones"),
        bigquery=MagicMock(name="bigquery"),
        pubsub_publisher=MagicMock(name="pubsub_publisher"),
        pubsub_subscriber=MagicMock(name="pubsub_subscriber"),
        logging=MagicMock(name="logging"),
        resource_manager_projects=MagicMock(name="resource_manager_projects"),
        config=cfg,
    )
    return AppContext(config=cfg, clients=clients)  # type: ignore[arg-type]


class FakeContext:
    """Minimal Context duck-type with a ``request_context.lifespan_context``."""

    def __init__(self, app_context):
        self.request_context = SimpleNamespace(lifespan_context=app_context)


@pytest.fixture
def app_context():
    return _make_app_context()


@pytest.fixture
def ctx(app_context):
    return FakeContext(app_context)
