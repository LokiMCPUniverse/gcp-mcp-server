"""Lazy-construct GCP SDK clients bound to resolved credentials."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from gcp_mcp.auth import get_credentials

if TYPE_CHECKING:
    from google.auth.credentials import Credentials

    from gcp_mcp.config import GCPConfig


@dataclass
class GCPClients:
    """Holds lazily-constructed GCP SDK clients.

    Clients are created on first access and cached for subsequent calls to
    avoid re-authenticating / re-instantiating on every tool invocation.
    """

    config: GCPConfig
    credentials: Credentials

    _storage: Any = None
    _compute_instances: Any = None
    _compute_zones: Any = None
    _bigquery: Any = None
    _pubsub_publisher: Any = None
    _pubsub_subscriber: Any = None
    _logging: Any = None
    _resource_manager_projects: Any = None

    @property
    def storage(self) -> Any:
        if self._storage is None:
            from google.cloud import storage

            self._storage = storage.Client(credentials=self.credentials)
        return self._storage

    @property
    def compute_instances(self) -> Any:
        if self._compute_instances is None:
            from google.cloud import compute_v1

            self._compute_instances = compute_v1.InstancesClient(credentials=self.credentials)
        return self._compute_instances

    @property
    def compute_zones(self) -> Any:
        if self._compute_zones is None:
            from google.cloud import compute_v1

            self._compute_zones = compute_v1.ZonesClient(credentials=self.credentials)
        return self._compute_zones

    @property
    def bigquery(self) -> Any:
        if self._bigquery is None:
            from google.cloud import bigquery

            self._bigquery = bigquery.Client(credentials=self.credentials)
        return self._bigquery

    @property
    def pubsub_publisher(self) -> Any:
        if self._pubsub_publisher is None:
            from google.cloud import pubsub_v1

            self._pubsub_publisher = pubsub_v1.PublisherClient(credentials=self.credentials)
        return self._pubsub_publisher

    @property
    def pubsub_subscriber(self) -> Any:
        if self._pubsub_subscriber is None:
            from google.cloud import pubsub_v1

            self._pubsub_subscriber = pubsub_v1.SubscriberClient(credentials=self.credentials)
        return self._pubsub_subscriber

    @property
    def logging(self) -> Any:
        if self._logging is None:
            from google.cloud import logging as gcp_logging

            self._logging = gcp_logging.Client(credentials=self.credentials)
        return self._logging

    @property
    def resource_manager_projects(self) -> Any:
        if self._resource_manager_projects is None:
            from google.cloud import resourcemanager_v3

            self._resource_manager_projects = resourcemanager_v3.ProjectsClient(
                credentials=self.credentials
            )
        return self._resource_manager_projects


def build_clients(config: GCPConfig) -> GCPClients:
    """Build a :class:`GCPClients` bundle for the given config."""
    credentials = get_credentials(config)
    return GCPClients(config=config, credentials=credentials)
