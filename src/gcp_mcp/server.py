"""FastMCP server exposing GCP tools."""

from __future__ import annotations

import base64
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import anyio
from mcp.server.fastmcp import Context, FastMCP

from gcp_mcp.clients import GCPClients, build_clients
from gcp_mcp.config import GCPConfig
from gcp_mcp.exceptions import APIError, NotFoundError

logger = logging.getLogger("gcp_mcp")


@dataclass
class AppContext:
    """Lifespan context shared across tool invocations."""

    config: GCPConfig
    clients: GCPClients


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[AppContext]:
    """Construct configuration and SDK clients once per server lifetime."""
    config = GCPConfig()
    clients = await anyio.to_thread.run_sync(build_clients, config)
    logger.info("GCP MCP server initialized (default_project_id=%s)", config.default_project_id)
    try:
        yield AppContext(config=config, clients=clients)
    finally:
        logger.info("GCP MCP server shutting down")


mcp = FastMCP(
    "gcp-mcp-server",
    lifespan=lifespan,
    instructions=(
        "Model Context Protocol server for Google Cloud Platform. Provides tools "
        "across Resource Manager, Compute Engine, Cloud Storage, BigQuery, "
        "Pub/Sub, and Cloud Logging. Authenticates via Application Default "
        "Credentials or an explicit service-account JSON (set GCP_CREDENTIALS_PATH)."
    ),
)


def _ctx(ctx: Context) -> AppContext:
    """Extract the ``AppContext`` from a FastMCP ``Context``."""
    return ctx.request_context.lifespan_context  # type: ignore[return-value]


def _require_project(ctx: Context, project_id: str | None) -> str:
    """Return an effective project id, falling back to config default."""
    app = _ctx(ctx)
    resolved = project_id or app.config.default_project_id
    if not resolved:
        raise APIError(
            "project_id is required and GCP_DEFAULT_PROJECT_ID is not set"
        )
    return resolved


async def _run(fn, *args, **kwargs):
    """Run a blocking SDK call in a worker thread."""

    def _call() -> Any:
        return fn(*args, **kwargs)

    return await anyio.to_thread.run_sync(_call)


# ---------------------------------------------------------------------------
# Resource Manager / IAM
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_projects(ctx: Context) -> list[dict[str, Any]]:
    """List GCP projects visible to the active credentials."""
    client = _ctx(ctx).clients.resource_manager_projects

    def _call() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for proj in client.search_projects():
            out.append(
                {
                    "project_id": getattr(proj, "project_id", None),
                    "name": getattr(proj, "display_name", None)
                    or getattr(proj, "name", None),
                    "state": str(getattr(proj, "state", "")),
                    "parent": getattr(proj, "parent", None),
                }
            )
        return out

    return await anyio.to_thread.run_sync(_call)


@mcp.tool()
async def get_project(ctx: Context, project_id: str) -> dict[str, Any]:
    """Fetch metadata for a single project."""
    client = _ctx(ctx).clients.resource_manager_projects

    def _call() -> dict[str, Any]:
        try:
            proj = client.get_project(name=f"projects/{project_id}")
        except Exception as exc:  # pragma: no cover - exercised via tests
            raise NotFoundError(f"Project {project_id!r} not found: {exc}") from exc
        return {
            "project_id": getattr(proj, "project_id", project_id),
            "name": getattr(proj, "display_name", None) or getattr(proj, "name", None),
            "state": str(getattr(proj, "state", "")),
            "parent": getattr(proj, "parent", None),
            "labels": dict(getattr(proj, "labels", {}) or {}),
        }

    return await anyio.to_thread.run_sync(_call)


@mcp.tool()
async def list_service_accounts(ctx: Context, project_id: str) -> list[dict[str, Any]]:
    """List IAM service accounts in a project.

    Uses the IAM Admin REST API via ``google-auth``. This avoids a hard
    dependency on ``google-cloud-iam`` while still providing coverage of
    IAM surface.
    """
    import google.auth.transport.requests

    credentials = _ctx(ctx).clients.credentials

    def _call() -> list[dict[str, Any]]:
        authed = google.auth.transport.requests.AuthorizedSession(credentials)
        url = (
            f"https://iam.googleapis.com/v1/projects/{project_id}/serviceAccounts"
        )
        resp = authed.get(url, timeout=_ctx(ctx).config.timeout)
        if resp.status_code == 404:
            raise NotFoundError(f"Project {project_id!r} not found")
        if resp.status_code >= 400:
            raise APIError(
                f"IAM API error {resp.status_code}: {resp.text[:500]}"
            )
        payload = resp.json() or {}
        return [
            {
                "email": sa.get("email"),
                "display_name": sa.get("displayName"),
                "unique_id": sa.get("uniqueId"),
                "disabled": sa.get("disabled", False),
            }
            for sa in payload.get("accounts", [])
        ]

    return await anyio.to_thread.run_sync(_call)


# ---------------------------------------------------------------------------
# Compute Engine
# ---------------------------------------------------------------------------


def _instance_to_dict(inst: Any) -> dict[str, Any]:
    return {
        "name": getattr(inst, "name", None),
        "id": str(getattr(inst, "id", "")) or None,
        "status": getattr(inst, "status", None),
        "machine_type": getattr(inst, "machine_type", None),
        "zone": getattr(inst, "zone", None),
        "cpu_platform": getattr(inst, "cpu_platform", None),
        "creation_timestamp": getattr(inst, "creation_timestamp", None),
    }


@mcp.tool()
async def list_instances(
    ctx: Context,
    project_id: str | None = None,
    zone: str | None = None,
) -> list[dict[str, Any]]:
    """List Compute Engine instances.

    If ``zone`` is omitted, returns an aggregated list across all zones.
    """
    project = _require_project(ctx, project_id)
    client = _ctx(ctx).clients.compute_instances

    def _call() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if zone:
            for inst in client.list(project=project, zone=zone):
                out.append(_instance_to_dict(inst))
            return out
        for zone_name, scoped in client.aggregated_list(project=project):
            instances = getattr(scoped, "instances", None) or []
            for inst in instances:
                entry = _instance_to_dict(inst)
                entry.setdefault("zone", zone_name)
                out.append(entry)
        return out

    return await anyio.to_thread.run_sync(_call)


@mcp.tool()
async def get_instance(
    ctx: Context, project_id: str, zone: str, name: str
) -> dict[str, Any]:
    """Get details for a single Compute Engine instance."""
    client = _ctx(ctx).clients.compute_instances

    def _call() -> dict[str, Any]:
        try:
            inst = client.get(project=project_id, zone=zone, instance=name)
        except Exception as exc:
            raise NotFoundError(
                f"Instance {name!r} not found in {project_id}/{zone}: {exc}"
            ) from exc
        return _instance_to_dict(inst)

    return await anyio.to_thread.run_sync(_call)


@mcp.tool()
async def start_instance(
    ctx: Context, project_id: str, zone: str, name: str
) -> dict[str, Any]:
    """Start a stopped Compute Engine instance."""
    client = _ctx(ctx).clients.compute_instances

    def _call() -> dict[str, Any]:
        op = client.start(project=project_id, zone=zone, instance=name)
        return {
            "name": getattr(op, "name", None),
            "status": str(getattr(op, "status", "")),
            "operation_type": getattr(op, "operation_type", "start"),
            "target_name": name,
            "zone": zone,
            "project_id": project_id,
        }

    return await anyio.to_thread.run_sync(_call)


@mcp.tool()
async def stop_instance(
    ctx: Context, project_id: str, zone: str, name: str
) -> dict[str, Any]:
    """Stop a running Compute Engine instance."""
    client = _ctx(ctx).clients.compute_instances

    def _call() -> dict[str, Any]:
        op = client.stop(project=project_id, zone=zone, instance=name)
        return {
            "name": getattr(op, "name", None),
            "status": str(getattr(op, "status", "")),
            "operation_type": getattr(op, "operation_type", "stop"),
            "target_name": name,
            "zone": zone,
            "project_id": project_id,
        }

    return await anyio.to_thread.run_sync(_call)


# ---------------------------------------------------------------------------
# Cloud Storage
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_buckets(ctx: Context, project_id: str | None = None) -> list[dict[str, Any]]:
    """List Cloud Storage buckets in a project."""
    project = _require_project(ctx, project_id)
    client = _ctx(ctx).clients.storage

    def _call() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for bucket in client.list_buckets(project=project):
            out.append(
                {
                    "name": bucket.name,
                    "location": getattr(bucket, "location", None),
                    "storage_class": getattr(bucket, "storage_class", None),
                    "created": getattr(bucket, "time_created", None).isoformat()
                    if getattr(bucket, "time_created", None)
                    else None,
                }
            )
        return out

    return await anyio.to_thread.run_sync(_call)


@mcp.tool()
async def list_objects(
    ctx: Context,
    bucket: str,
    prefix: str | None = None,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """List objects (blobs) in a Cloud Storage bucket."""
    client = _ctx(ctx).clients.storage

    def _call() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        iterator = client.list_blobs(
            bucket_or_name=bucket,
            prefix=prefix,
            max_results=max_results,
        )
        for blob in iterator:
            out.append(
                {
                    "name": blob.name,
                    "size": getattr(blob, "size", None),
                    "content_type": getattr(blob, "content_type", None),
                    "updated": getattr(blob, "updated", None).isoformat()
                    if getattr(blob, "updated", None)
                    else None,
                }
            )
        return out

    return await anyio.to_thread.run_sync(_call)


@mcp.tool()
async def get_object_metadata(ctx: Context, bucket: str, name: str) -> dict[str, Any]:
    """Return metadata for a single Cloud Storage object."""
    client = _ctx(ctx).clients.storage

    def _call() -> dict[str, Any]:
        bkt = client.bucket(bucket)
        blob = bkt.get_blob(name)
        if blob is None:
            raise NotFoundError(f"Object {name!r} not found in bucket {bucket!r}")
        return {
            "name": blob.name,
            "bucket": bucket,
            "size": getattr(blob, "size", None),
            "content_type": getattr(blob, "content_type", None),
            "md5_hash": getattr(blob, "md5_hash", None),
            "crc32c": getattr(blob, "crc32c", None),
            "storage_class": getattr(blob, "storage_class", None),
            "updated": getattr(blob, "updated", None).isoformat()
            if getattr(blob, "updated", None)
            else None,
            "generation": getattr(blob, "generation", None),
            "metadata": dict(getattr(blob, "metadata", {}) or {}),
        }

    return await anyio.to_thread.run_sync(_call)


# ---------------------------------------------------------------------------
# BigQuery
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_datasets(ctx: Context, project_id: str | None = None) -> list[dict[str, Any]]:
    """List BigQuery datasets in a project."""
    project = _require_project(ctx, project_id)
    client = _ctx(ctx).clients.bigquery

    def _call() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for ds in client.list_datasets(project=project):
            out.append(
                {
                    "dataset_id": ds.dataset_id,
                    "project": getattr(ds, "project", project),
                    "full_id": getattr(ds, "full_dataset_id", None),
                }
            )
        return out

    return await anyio.to_thread.run_sync(_call)


@mcp.tool()
async def list_tables(
    ctx: Context, project_id: str, dataset: str
) -> list[dict[str, Any]]:
    """List BigQuery tables in a dataset."""
    client = _ctx(ctx).clients.bigquery

    def _call() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        ref = f"{project_id}.{dataset}"
        for table in client.list_tables(ref):
            out.append(
                {
                    "table_id": table.table_id,
                    "dataset_id": table.dataset_id,
                    "project": getattr(table, "project", project_id),
                    "table_type": getattr(table, "table_type", None),
                }
            )
        return out

    return await anyio.to_thread.run_sync(_call)


@mcp.tool()
async def query_bigquery(
    ctx: Context,
    project_id: str,
    sql: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute a BigQuery SQL query.

    When ``dry_run=True``, returns only schema and estimated bytes processed.
    Otherwise returns the rows as a list of dicts.
    """
    client = _ctx(ctx).clients.bigquery

    def _call() -> dict[str, Any]:
        from google.cloud import bigquery

        job_config = bigquery.QueryJobConfig(dry_run=dry_run, use_query_cache=True)
        job = client.query(sql, project=project_id, job_config=job_config)
        if dry_run:
            schema = [
                {"name": f.name, "field_type": f.field_type, "mode": f.mode}
                for f in (getattr(job, "schema", None) or [])
            ]
            return {
                "dry_run": True,
                "total_bytes_processed": getattr(job, "total_bytes_processed", None),
                "schema": schema,
            }
        result = job.result()
        rows = [dict(row) for row in result]
        schema = [
            {"name": f.name, "field_type": f.field_type, "mode": f.mode}
            for f in (getattr(result, "schema", None) or [])
        ]
        return {
            "dry_run": False,
            "row_count": len(rows),
            "schema": schema,
            "rows": rows,
        }

    return await anyio.to_thread.run_sync(_call)


# ---------------------------------------------------------------------------
# Pub/Sub
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_topics(ctx: Context, project_id: str | None = None) -> list[dict[str, Any]]:
    """List Pub/Sub topics in a project."""
    project = _require_project(ctx, project_id)
    client = _ctx(ctx).clients.pubsub_publisher

    def _call() -> list[dict[str, Any]]:
        project_path = f"projects/{project}"
        out: list[dict[str, Any]] = []
        for topic in client.list_topics(request={"project": project_path}):
            out.append({"name": getattr(topic, "name", None)})
        return out

    return await anyio.to_thread.run_sync(_call)


@mcp.tool()
async def list_subscriptions(
    ctx: Context, project_id: str | None = None
) -> list[dict[str, Any]]:
    """List Pub/Sub subscriptions in a project."""
    project = _require_project(ctx, project_id)
    client = _ctx(ctx).clients.pubsub_subscriber

    def _call() -> list[dict[str, Any]]:
        project_path = f"projects/{project}"
        out: list[dict[str, Any]] = []
        for sub in client.list_subscriptions(request={"project": project_path}):
            out.append(
                {
                    "name": getattr(sub, "name", None),
                    "topic": getattr(sub, "topic", None),
                    "ack_deadline_seconds": getattr(sub, "ack_deadline_seconds", None),
                }
            )
        return out

    return await anyio.to_thread.run_sync(_call)


@mcp.tool()
async def publish_message(
    ctx: Context,
    project_id: str,
    topic: str,
    data: str,
    attributes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Publish a message to a Pub/Sub topic.

    ``data`` is accepted as a UTF-8 string. Callers that need to publish raw
    bytes can pass a base64-encoded payload (auto-decoded if prefixed with
    ``base64:``).
    """
    client = _ctx(ctx).clients.pubsub_publisher

    def _call() -> dict[str, Any]:
        if data.startswith("base64:"):
            payload = base64.b64decode(data[len("base64:") :])
        else:
            payload = data.encode("utf-8")
        topic_path = client.topic_path(project_id, topic)
        future = client.publish(topic_path, payload, **(attributes or {}))
        message_id = future.result(timeout=_ctx(ctx).config.timeout)
        return {
            "message_id": message_id,
            "topic": topic_path,
            "byte_size": len(payload),
        }

    return await anyio.to_thread.run_sync(_call)


# ---------------------------------------------------------------------------
# Cloud Logging
# ---------------------------------------------------------------------------


@mcp.tool()
async def read_logs(
    ctx: Context,
    project_id: str,
    filter: str,
    max_entries: int = 50,
) -> list[dict[str, Any]]:
    """Read log entries matching an advanced log filter.

    Example ``filter`` values:
      - ``resource.type="gce_instance"``
      - ``severity>=ERROR AND resource.type="cloud_run_revision"``
    """
    client = _ctx(ctx).clients.logging

    def _call() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        # Some google-cloud-logging versions don't accept a `project_ids` kwarg
        # on Client.list_entries; fall back if needed.
        try:
            iterator = client.list_entries(
                filter_=filter,
                page_size=max_entries,
                resource_names=[f"projects/{project_id}"],
            )
        except TypeError:
            iterator = client.list_entries(filter_=filter, page_size=max_entries)
        for i, entry in enumerate(iterator):
            if i >= max_entries:
                break
            ts = getattr(entry, "timestamp", None)
            payload = getattr(entry, "payload", None)
            if not isinstance(payload, str | dict | list | int | float | bool | type(None)):
                payload = str(payload)
            out.append(
                {
                    "timestamp": ts.isoformat() if ts is not None else None,
                    "severity": str(getattr(entry, "severity", "")),
                    "log_name": getattr(entry, "log_name", None),
                    "resource_type": getattr(getattr(entry, "resource", None), "type", None),
                    "payload": payload,
                }
            )
        return out

    return await anyio.to_thread.run_sync(_call)


__all__ = ["mcp", "lifespan", "AppContext"]
