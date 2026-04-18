"""Unit tests for individual MCP tools."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import gcp_mcp.server as server
from gcp_mcp.exceptions import APIError, NotFoundError

# ---------------------------------------------------------------------------
# Resource Manager / IAM
# ---------------------------------------------------------------------------


async def test_list_projects(ctx, app_context):
    proj = SimpleNamespace(
        project_id="p1",
        display_name="Project One",
        state="ACTIVE",
        parent="organizations/123",
    )
    app_context.clients.resource_manager_projects.search_projects.return_value = [proj]

    result = await server.list_projects(ctx)
    assert result == [
        {
            "project_id": "p1",
            "name": "Project One",
            "state": "ACTIVE",
            "parent": "organizations/123",
        }
    ]
    app_context.clients.resource_manager_projects.search_projects.assert_called_once()


async def test_get_project(ctx, app_context):
    proj = SimpleNamespace(
        project_id="p1",
        display_name="Project One",
        state="ACTIVE",
        parent="organizations/123",
        labels={"env": "prod"},
    )
    app_context.clients.resource_manager_projects.get_project.return_value = proj

    result = await server.get_project(ctx, "p1")
    assert result["project_id"] == "p1"
    assert result["labels"] == {"env": "prod"}
    app_context.clients.resource_manager_projects.get_project.assert_called_once_with(
        name="projects/p1"
    )


async def test_get_project_not_found(ctx, app_context):
    app_context.clients.resource_manager_projects.get_project.side_effect = RuntimeError("missing")
    with pytest.raises(NotFoundError):
        await server.get_project(ctx, "nope")


async def test_list_service_accounts(ctx, app_context):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "accounts": [
            {
                "email": "svc@proj.iam.gserviceaccount.com",
                "displayName": "svc",
                "uniqueId": "123",
                "disabled": False,
            }
        ]
    }
    session = MagicMock()
    session.get.return_value = resp
    with patch("google.auth.transport.requests.AuthorizedSession", return_value=session):
        result = await server.list_service_accounts(ctx, "p1")

    assert result == [
        {
            "email": "svc@proj.iam.gserviceaccount.com",
            "display_name": "svc",
            "unique_id": "123",
            "disabled": False,
        }
    ]
    session.get.assert_called_once()
    called_url = session.get.call_args[0][0]
    assert "projects/p1/serviceAccounts" in called_url


async def test_list_service_accounts_api_error(ctx):
    resp = MagicMock()
    resp.status_code = 500
    resp.text = "boom"
    session = MagicMock()
    session.get.return_value = resp
    with patch("google.auth.transport.requests.AuthorizedSession", return_value=session):
        with pytest.raises(APIError):
            await server.list_service_accounts(ctx, "p1")


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------


def _mk_instance(name: str, status: str = "RUNNING", zone: str = "us-central1-a"):
    return SimpleNamespace(
        name=name,
        id=123,
        status=status,
        machine_type="zones/us-central1-a/machineTypes/e2-small",
        zone=f"projects/p/zones/{zone}",
        cpu_platform="Intel Cascade Lake",
        creation_timestamp="2026-01-01T00:00:00Z",
    )


async def test_list_instances_zone(ctx, app_context):
    app_context.clients.compute_instances.list.return_value = [_mk_instance("vm-a")]

    result = await server.list_instances(ctx, project_id="p1", zone="us-central1-a")
    assert len(result) == 1
    assert result[0]["name"] == "vm-a"
    app_context.clients.compute_instances.list.assert_called_once_with(
        project="p1", zone="us-central1-a"
    )


async def test_list_instances_aggregated(ctx, app_context):
    scoped = SimpleNamespace(instances=[_mk_instance("vm-a"), _mk_instance("vm-b")])
    app_context.clients.compute_instances.aggregated_list.return_value = iter(
        [("zones/us-central1-a", scoped), ("zones/us-east1-b", SimpleNamespace(instances=[]))]
    )

    result = await server.list_instances(ctx, project_id="p1")
    assert [r["name"] for r in result] == ["vm-a", "vm-b"]
    app_context.clients.compute_instances.aggregated_list.assert_called_once_with(project="p1")


async def test_list_instances_uses_default_project(ctx, app_context):
    # default_project_id is "test-project" via conftest
    app_context.clients.compute_instances.aggregated_list.return_value = iter([])
    result = await server.list_instances(ctx)
    assert result == []
    app_context.clients.compute_instances.aggregated_list.assert_called_once_with(
        project="test-project"
    )


async def test_list_instances_no_project_raises(app_context):
    from gcp_mcp.config import GCPConfig

    app_context.config = GCPConfig(default_project_id=None, _env_file=None)
    app_context.clients.config = app_context.config
    fake_ctx = type("C", (), {"request_context": SimpleNamespace(lifespan_context=app_context)})()

    with pytest.raises(APIError):
        await server.list_instances(fake_ctx)


async def test_get_instance(ctx, app_context):
    app_context.clients.compute_instances.get.return_value = _mk_instance("vm-a")
    result = await server.get_instance(ctx, "p1", "us-central1-a", "vm-a")
    assert result["name"] == "vm-a"
    app_context.clients.compute_instances.get.assert_called_once_with(
        project="p1", zone="us-central1-a", instance="vm-a"
    )


async def test_get_instance_not_found(ctx, app_context):
    app_context.clients.compute_instances.get.side_effect = RuntimeError("gone")
    with pytest.raises(NotFoundError):
        await server.get_instance(ctx, "p1", "us-central1-a", "vm-x")


async def test_start_instance(ctx, app_context):
    op = SimpleNamespace(name="op-start-1", status="RUNNING", operation_type="start")
    app_context.clients.compute_instances.start.return_value = op
    result = await server.start_instance(ctx, "p1", "us-central1-a", "vm-a")
    assert result["operation_type"] == "start"
    assert result["target_name"] == "vm-a"
    app_context.clients.compute_instances.start.assert_called_once_with(
        project="p1", zone="us-central1-a", instance="vm-a"
    )


async def test_stop_instance(ctx, app_context):
    op = SimpleNamespace(name="op-stop-1", status="RUNNING", operation_type="stop")
    app_context.clients.compute_instances.stop.return_value = op
    result = await server.stop_instance(ctx, "p1", "us-central1-a", "vm-a")
    assert result["operation_type"] == "stop"
    app_context.clients.compute_instances.stop.assert_called_once_with(
        project="p1", zone="us-central1-a", instance="vm-a"
    )


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


async def test_list_buckets(ctx, app_context):
    bucket = SimpleNamespace(
        name="b1",
        location="US",
        storage_class="STANDARD",
        time_created=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    app_context.clients.storage.list_buckets.return_value = [bucket]
    result = await server.list_buckets(ctx, project_id="p1")
    assert result[0]["name"] == "b1"
    assert result[0]["created"].startswith("2026-01-01")
    app_context.clients.storage.list_buckets.assert_called_once_with(project="p1")


async def test_list_objects(ctx, app_context):
    blob = SimpleNamespace(
        name="foo.txt",
        size=42,
        content_type="text/plain",
        updated=datetime(2026, 2, 2, tzinfo=timezone.utc),
    )
    app_context.clients.storage.list_blobs.return_value = [blob]
    result = await server.list_objects(ctx, "b1", prefix="foo/", max_results=10)
    assert result[0]["name"] == "foo.txt"
    app_context.clients.storage.list_blobs.assert_called_once_with(
        bucket_or_name="b1", prefix="foo/", max_results=10
    )


async def test_get_object_metadata(ctx, app_context):
    blob = SimpleNamespace(
        name="foo.txt",
        size=42,
        content_type="text/plain",
        md5_hash="md5",
        crc32c="crc",
        storage_class="STANDARD",
        updated=datetime(2026, 2, 2, tzinfo=timezone.utc),
        generation=1,
        metadata={"k": "v"},
    )
    bucket_obj = MagicMock()
    bucket_obj.get_blob.return_value = blob
    app_context.clients.storage.bucket.return_value = bucket_obj

    result = await server.get_object_metadata(ctx, "b1", "foo.txt")
    assert result["name"] == "foo.txt"
    assert result["metadata"] == {"k": "v"}
    bucket_obj.get_blob.assert_called_once_with("foo.txt")


async def test_get_object_metadata_missing(ctx, app_context):
    bucket_obj = MagicMock()
    bucket_obj.get_blob.return_value = None
    app_context.clients.storage.bucket.return_value = bucket_obj
    with pytest.raises(NotFoundError):
        await server.get_object_metadata(ctx, "b1", "ghost.txt")


# ---------------------------------------------------------------------------
# BigQuery
# ---------------------------------------------------------------------------


async def test_list_datasets(ctx, app_context):
    ds = SimpleNamespace(dataset_id="ds1", project="p1", full_dataset_id="p1:ds1")
    app_context.clients.bigquery.list_datasets.return_value = [ds]
    result = await server.list_datasets(ctx, "p1")
    assert result[0]["dataset_id"] == "ds1"
    app_context.clients.bigquery.list_datasets.assert_called_once_with(project="p1")


async def test_list_tables(ctx, app_context):
    t = SimpleNamespace(table_id="t1", dataset_id="ds1", project="p1", table_type="TABLE")
    app_context.clients.bigquery.list_tables.return_value = [t]
    result = await server.list_tables(ctx, "p1", "ds1")
    assert result[0]["table_id"] == "t1"
    app_context.clients.bigquery.list_tables.assert_called_once_with("p1.ds1")


async def test_query_bigquery_dry_run(ctx, app_context):
    schema = [SimpleNamespace(name="col", field_type="STRING", mode="NULLABLE")]
    job = MagicMock()
    job.total_bytes_processed = 1024
    job.schema = schema
    app_context.clients.bigquery.query.return_value = job

    result = await server.query_bigquery(ctx, "p1", "SELECT 1", dry_run=True)
    assert result["dry_run"] is True
    assert result["total_bytes_processed"] == 1024
    assert result["schema"][0]["name"] == "col"


async def test_query_bigquery_rows(ctx, app_context):
    row = {"col": "hello"}
    iter_rows = MagicMock()
    iter_rows.__iter__ = lambda self: iter([row])
    iter_rows.schema = [SimpleNamespace(name="col", field_type="STRING", mode="NULLABLE")]

    job = MagicMock()
    job.result.return_value = iter_rows
    app_context.clients.bigquery.query.return_value = job

    result = await server.query_bigquery(ctx, "p1", "SELECT 'hello'")
    assert result["dry_run"] is False
    assert result["row_count"] == 1
    assert result["rows"] == [row]


# ---------------------------------------------------------------------------
# Pub/Sub
# ---------------------------------------------------------------------------


async def test_list_topics(ctx, app_context):
    app_context.clients.pubsub_publisher.list_topics.return_value = [
        SimpleNamespace(name="projects/p1/topics/a")
    ]
    result = await server.list_topics(ctx, "p1")
    assert result == [{"name": "projects/p1/topics/a"}]
    app_context.clients.pubsub_publisher.list_topics.assert_called_once_with(
        request={"project": "projects/p1"}
    )


async def test_list_subscriptions(ctx, app_context):
    app_context.clients.pubsub_subscriber.list_subscriptions.return_value = [
        SimpleNamespace(
            name="projects/p1/subscriptions/s",
            topic="projects/p1/topics/a",
            ack_deadline_seconds=10,
        )
    ]
    result = await server.list_subscriptions(ctx, "p1")
    assert result[0]["name"] == "projects/p1/subscriptions/s"
    assert result[0]["ack_deadline_seconds"] == 10


async def test_publish_message_utf8(ctx, app_context):
    future = MagicMock()
    future.result.return_value = "msg-123"
    publisher = app_context.clients.pubsub_publisher
    publisher.topic_path.return_value = "projects/p1/topics/t"
    publisher.publish.return_value = future

    result = await server.publish_message(ctx, "p1", "t", "hello", {"k": "v"})
    assert result["message_id"] == "msg-123"
    assert result["byte_size"] == 5
    publisher.topic_path.assert_called_once_with("p1", "t")
    publisher.publish.assert_called_once()
    args, kwargs = publisher.publish.call_args
    assert args[0] == "projects/p1/topics/t"
    assert args[1] == b"hello"
    assert kwargs == {"k": "v"}


async def test_publish_message_base64(ctx, app_context):
    future = MagicMock()
    future.result.return_value = "msg-b64"
    publisher = app_context.clients.pubsub_publisher
    publisher.topic_path.return_value = "projects/p1/topics/t"
    publisher.publish.return_value = future

    import base64 as _b64

    encoded = "base64:" + _b64.b64encode(b"\x00\x01\x02").decode()
    result = await server.publish_message(ctx, "p1", "t", encoded)
    assert result["byte_size"] == 3
    args, _ = publisher.publish.call_args
    assert args[1] == b"\x00\x01\x02"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


async def test_read_logs(ctx, app_context):
    entry = SimpleNamespace(
        timestamp=datetime(2026, 3, 3, tzinfo=timezone.utc),
        severity="ERROR",
        log_name="projects/p1/logs/my-log",
        resource=SimpleNamespace(type="gce_instance"),
        payload={"message": "boom"},
    )
    app_context.clients.logging.list_entries.return_value = [entry]
    result = await server.read_logs(ctx, "p1", 'resource.type="gce_instance"', 10)
    assert result[0]["severity"] == "ERROR"
    assert result[0]["resource_type"] == "gce_instance"
    assert result[0]["payload"] == {"message": "boom"}
    app_context.clients.logging.list_entries.assert_called_once()


async def test_read_logs_fallback_when_resource_names_unsupported(ctx, app_context):
    calls = {"n": 0}

    def _list_entries(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1 and "resource_names" in kwargs:
            raise TypeError("unexpected kwarg resource_names")
        return iter([])

    app_context.clients.logging.list_entries.side_effect = _list_entries
    result = await server.read_logs(ctx, "p1", "severity>=ERROR", 5)
    assert result == []
    assert calls["n"] == 2
