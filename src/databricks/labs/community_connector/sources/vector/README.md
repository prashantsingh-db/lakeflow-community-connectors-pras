# Vector Community Connector

Ingest pipeline observability data from [Vector](https://vector.dev) into Databricks using Lakeflow Connect.

## Overview

This connector reads operational data from Vector's GraphQL API, providing visibility into your data pipeline topology, component-level throughput metrics, and health status directly within Databricks Delta tables.

## Architecture

```
Vector Instance (local/cloud)         Databricks
┌──────────────────────────┐          ┌──────────────────────────────────┐
│ GraphQL API (:8686)      │  ← PULL  │ Lakeflow Connect / SDP Pipeline  │
│                          │          │                                  │
│ ┌──────────┐             │          │ ┌──────────────────────────────┐ │
│ │ Sources  │ ndr_raw     │          │ │ topology        (snapshot)  │ │
│ │ Transforms│ ndr_enrich │          │ │ component_metrics (append)  │ │
│ │ Sinks    │ blackhole   │          │ │ health          (snapshot)  │ │
│ └──────────┘             │          │ └──────────────────────────────┘ │
└──────────────────────────┘          └──────────────────────────────────┘
```

## Prerequisites

- A running Vector instance with the API enabled
- Network connectivity from Databricks to the Vector API endpoint (use Cloudflare Tunnel for local instances)
- Vector 0.30+ (GraphQL API support)

## Vector Configuration

Enable the API in your Vector config (`vector.yaml`):

```yaml
api:
  enabled: true
  address: "0.0.0.0:8686"
```

### Tunneling for Local Vector Instances

If Vector runs locally and Databricks is in the cloud, use Cloudflare Tunnel (free, no auth):

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8686
# → https://<random>.trycloudflare.com
```

Then set `api_url` in the connector to the tunnel URL.

## Supported Tables

| Table | Ingestion Type | Primary Key | Description |
|-------|---------------|-------------|-------------|
| `topology` | snapshot | component_id | Pipeline components (sources, transforms, sinks) |
| `component_metrics` | append | component_id | Per-component event/byte totals over time |
| `health` | snapshot | hostname | Instance health, version info |

### topology

Full pipeline topology showing all configured components.

| Column | Type | Description |
|--------|------|-------------|
| component_id | STRING | Unique component identifier (e.g. `ndr_raw`) |
| component_type | STRING | Component type (e.g. `demo_logs`, `remap`, `blackhole`) |
| component_kind | STRING | One of: `source`, `transform`, `sink` |
| collected_at | TIMESTAMP | When the snapshot was taken |

### component_metrics

Point-in-time event and byte totals per component. Each pipeline run appends a new snapshot, enabling trend analysis.

| Column | Type | Description |
|--------|------|-------------|
| component_id | STRING | Component identifier |
| component_type | STRING | Component type |
| component_kind | STRING | source, transform, or sink |
| sent_events_total | DOUBLE | Cumulative events sent |
| received_events_total | DOUBLE | Cumulative events received |
| received_bytes_total | DOUBLE | Cumulative bytes received |
| errors_total | LONG | Cumulative error count |
| collected_at | TIMESTAMP | Metric collection timestamp |

### health

Instance-level health and metadata.

| Column | Type | Description |
|--------|------|-------------|
| hostname | STRING | Machine hostname |
| version | STRING | Vector version string |
| is_healthy | BOOLEAN | Overall health status |
| collected_at | TIMESTAMP | When health was checked |

## Connection Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `api_url` | Yes | Vector API URL (e.g. `http://vector-host:8686` or tunnel URL) |
| `api_token` | No | Bearer token if Vector API auth is enabled |

## Quick Start

### Option 1: Standalone Notebook

```python
# Connect to Vector and write to Delta tables
import requests
from datetime import datetime, timezone

VECTOR_URL = "https://your-tunnel.trycloudflare.com"
data = requests.post(f"{VECTOR_URL}/graphql", json={
    "query": """{ sources(first:100) { edges { node { componentId componentType } } } }"""
}).json()["data"]

# Create DataFrame and write to Delta
records = [{"component_id": e["node"]["componentId"], "component_type": e["node"]["componentType"]}
           for e in data["sources"]["edges"]]
spark.createDataFrame(records).write.mode("overwrite").saveAsTable("catalog.schema.topology")
```

### Option 2: Lakeflow Connect Pipeline

```python
from databricks.labs.community_connector.sparkpds.registry import register
from databricks.labs.community_connector.pipeline.ingestion_pipeline import ingest

register(spark, "vector")

pipeline_spec = {
    "connection_name": "vector_conn",
    "objects": [
        {"table": {"source_table": "topology"}},
        {"table": {"source_table": "component_metrics"}},
        {"table": {"source_table": "health"}},
    ]
}
ingest(spark, pipeline_spec)
```

## Verified With

- **Vector**: 0.53.0 (aarch64-apple-darwin)
- **Databricks Runtime**: 16.2.x (serverless)
- **Catalog**: Unity Catalog
- **Tunnel**: Cloudflare Tunnel (cloudflared)

## GraphQL API Reference

The connector uses these Vector GraphQL queries:

```graphql
# Topology + Metrics (per component kind)
{
  sources(first: 100) {
    edges { node { componentId componentType
      metrics { receivedEventsTotal { receivedEventsTotal }
                sentEventsTotal { sentEventsTotal }
                receivedBytesTotal { receivedBytesTotal } }
    } }
  }
  transforms(first: 100) { edges { node { componentId componentType
    metrics { receivedEventsTotal { receivedEventsTotal }
              sentEventsTotal { sentEventsTotal } }
  } } }
  sinks(first: 100) { edges { node { componentId componentType
    metrics { receivedEventsTotal { receivedEventsTotal }
              sentEventsTotal { sentEventsTotal } }
  } } }
}

# Health
{ meta { versionString hostname } health }
```

## Key Design Decisions

1. **Per-kind queries**: Vector's GraphQL schema exposes `sources`, `transforms`, and `sinks` as separate query roots with type-specific metric fields. The connector queries all three and derives `component_kind` from which query returned the data.

2. **No `componentKind` field**: Vector 0.53's `Component` interface only has `componentId` and `componentType`. The kind is inferred from the query root.

3. **Cumulative totals (not rates)**: The connector reads `sentEventsTotal` / `receivedEventsTotal` (cumulative counters), not throughput rates. This is more reliable for append-mode ingestion and enables accurate trend analysis in Databricks.

4. **Pull-based architecture**: Follows the Lakeflow Connect pattern where Databricks pulls data from the source on a schedule, rather than Vector pushing data.
