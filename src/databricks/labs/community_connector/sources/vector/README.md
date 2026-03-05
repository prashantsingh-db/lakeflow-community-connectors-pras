# Vector Community Connector

Ingest pipeline observability data from [Vector](https://vector.dev) into Databricks using Lakeflow Connect.

## Overview

This connector reads operational data from Vector's GraphQL API, providing visibility into your data pipeline topology, component-level throughput metrics, and health status directly within Databricks.

## Prerequisites

- A running Vector instance with the API enabled (`api.enabled = true` in vector config)
- Network connectivity from Databricks to the Vector API endpoint
- Vector 0.30+ (GraphQL API support)

## Vector Configuration

Enable the API in your Vector config:

```yaml
api:
  enabled: true
  address: "0.0.0.0:8686"
```

## Supported Tables

| Table | Ingestion Type | Description |
|-------|---------------|-------------|
| `topology` | snapshot | Pipeline components (sources, transforms, sinks) |
| `component_metrics` | append | Per-component throughput and error metrics over time |
| `health` | snapshot | Instance health, version, uptime |

### topology

Full pipeline topology showing all configured components.

| Column | Type | Description |
|--------|------|-------------|
| component_id | STRING | Unique component identifier |
| component_type | STRING | Component type (e.g. `demo_logs`, `remap`, `http`) |
| component_kind | STRING | One of: source, transform, sink |
| collected_at | TIMESTAMP | When the snapshot was taken |

### component_metrics

Point-in-time throughput and error metrics per component. Each pipeline run appends a new snapshot.

| Column | Type | Description |
|--------|------|-------------|
| component_id | STRING | Component identifier |
| component_type | STRING | Component type |
| component_kind | STRING | source, transform, or sink |
| sent_events_throughput | DOUBLE | Events/sec sent by this component |
| sent_bytes_throughput | DOUBLE | Bytes/sec sent by this component |
| received_events_throughput | DOUBLE | Events/sec received |
| received_bytes_throughput | DOUBLE | Bytes/sec received |
| errors_total | LONG | Cumulative error count |
| collected_at | TIMESTAMP | Metric collection timestamp |

### health

Instance-level health and metadata.

| Column | Type | Description |
|--------|------|-------------|
| hostname | STRING | Machine hostname |
| version | STRING | Vector version |
| os | STRING | Operating system |
| arch | STRING | CPU architecture |
| uptime_seconds | LONG | Seconds since Vector started |
| is_healthy | BOOLEAN | Overall health status |
| collected_at | TIMESTAMP | When health was checked |

## Connection Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `api_url` | Yes | Vector API URL (e.g. `http://vector-host:8686`) |
| `api_token` | No | Bearer token if Vector API auth is enabled |

## Data Type Mapping

| Vector API Type | Spark Type |
|----------------|------------|
| String | StringType |
| Number (int) | LongType |
| Number (float) | DoubleType |
| Boolean | BooleanType |
| ISO 8601 timestamp | TimestampType |
