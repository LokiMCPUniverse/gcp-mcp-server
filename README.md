# gcp-mcp-server

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-1.27-brightgreen.svg)](https://modelcontextprotocol.io/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

Model Context Protocol server for Google Cloud Platform. Built on the MCP
Python SDK (`mcp>=1.27`) using FastMCP, with tools that touch Resource
Manager, Compute Engine, Cloud Storage, BigQuery, Pub/Sub, and Cloud Logging.

## Features

- Application Default Credentials (ADC) or explicit service-account JSON auth
- Lazy-constructed Google Cloud SDK clients bound to resolved credentials
- Blocking SDK calls executed in worker threads via `anyio.to_thread.run_sync`
- Typed tools covering the most common GCP day-to-day operations
- Unit tests that mock the SDK clients end-to-end (no real API calls)

## Install

```bash
git clone https://github.com/asklokesh/gcp-mcp-server.git
cd gcp-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Requires Python 3.10 or newer.

## Authentication

The server resolves credentials in the following order:

1. If `GCP_CREDENTIALS_PATH` points to a service-account JSON file, that file
   is used.
2. Otherwise, Application Default Credentials (ADC) are loaded via
   `google.auth.default()`.

For ADC, the simplest path is:

```bash
gcloud auth application-default login
```

Or point `GOOGLE_APPLICATION_CREDENTIALS` at a service-account JSON file.

### Environment variables

All settings are optional and use the `GCP_` prefix:

| Variable | Description | Default |
| --- | --- | --- |
| `GCP_DEFAULT_PROJECT_ID` | Project id used when a tool doesn't receive one | unset |
| `GCP_CREDENTIALS_PATH` | Path to a service-account JSON file | unset (ADC) |
| `GCP_TIMEOUT` | Default per-request timeout in seconds | `60` |

## Claude Desktop configuration

Add an entry like this to your Claude Desktop `mcpServers` config:

```json
{
  "mcpServers": {
    "gcp": {
      "command": "gcp-mcp",
      "env": {
        "GCP_DEFAULT_PROJECT_ID": "my-gcp-project",
        "GCP_CREDENTIALS_PATH": "/absolute/path/to/service-account.json"
      }
    }
  }
}
```

If you prefer ADC, omit `GCP_CREDENTIALS_PATH` and ensure
`gcloud auth application-default login` was run as the same user that
launches Claude Desktop.

## Tools

### Resource Manager / IAM
- `list_projects()` - list visible GCP projects
- `get_project(project_id)` - fetch project metadata
- `list_service_accounts(project_id)` - list IAM service accounts via the IAM REST API

### Compute Engine
- `list_instances(project_id?, zone?)` - zonal or aggregated instance list
- `get_instance(project_id, zone, name)` - single instance details
- `start_instance(project_id, zone, name)` - start a VM
- `stop_instance(project_id, zone, name)` - stop a VM

### Cloud Storage
- `list_buckets(project_id?)` - list buckets in a project
- `list_objects(bucket, prefix?, max_results=100)` - list blobs
- `get_object_metadata(bucket, name)` - fetch blob metadata

### BigQuery
- `list_datasets(project_id?)` - list datasets
- `list_tables(project_id, dataset)` - list tables
- `query_bigquery(project_id, sql, dry_run=False)` - run a query; dry-run returns schema and estimated bytes

### Pub/Sub
- `list_topics(project_id?)` - list topics
- `list_subscriptions(project_id?)` - list subscriptions
- `publish_message(project_id, topic, data, attributes?)` - publish a message. `data` is UTF-8; prefix with `base64:` for binary payloads.

### Cloud Logging
- `read_logs(project_id, filter, max_entries=50)` - advanced log filter, e.g. `resource.type="gce_instance"`

## Required IAM roles

The caller's principal needs appropriate roles per surface. Minimal
recommended roles:

| Surface | Role(s) |
| --- | --- |
| Resource Manager | `roles/resourcemanager.projectViewer`, `roles/browser` |
| IAM | `roles/iam.serviceAccountViewer` |
| Compute | `roles/compute.viewer`, `roles/compute.instanceAdmin.v1` (for start/stop) |
| Cloud Storage | `roles/storage.objectViewer`, `roles/storage.bucketViewer` |
| BigQuery | `roles/bigquery.dataViewer`, `roles/bigquery.jobUser` |
| Pub/Sub | `roles/pubsub.viewer`, `roles/pubsub.publisher` |
| Cloud Logging | `roles/logging.viewer` (or `roles/logging.privateLogViewer`) |

Grant only what the caller actually needs.

## Development

Run the test suite:

```bash
source .venv/bin/activate
pytest -x --tb=short
```

Lint:

```bash
ruff check src/ tests/
```

Tests mock each Google Cloud client with `unittest.mock`, so no real
GCP APIs are called.

## Project layout

```
src/gcp_mcp/
  __init__.py       # main entry point
  auth.py           # ADC / service-account credential resolution
  clients.py        # lazy SDK client construction
  config.py         # pydantic-settings config (GCP_ env prefix)
  exceptions.py     # GCPError, AuthenticationError, APIError, NotFoundError
  server.py         # FastMCP server + @mcp.tool() definitions
tests/              # unit tests with mocked SDK clients
pyproject.toml
requirements.txt
```

## License

MIT.
