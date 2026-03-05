"""Vector connector for monitoring Vector data pipelines.

Connects to Vector's GraphQL API to read pipeline topology,
component metrics, and health information into Databricks.
"""

import time
from datetime import datetime, timezone
from typing import Iterator

import requests
from pyspark.sql.types import StructType

from databricks.labs.community_connector.interface import LakeflowConnect
from databricks.labs.community_connector.sources.vector.vector_schemas import (
    TABLE_METADATA,
    TABLE_SCHEMAS,
)

RETRIABLE_STATUS_CODES = {429, 500, 502, 503}
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0

# Map component type to kind based on which query returned it
_KIND_SOURCE = "source"
_KIND_TRANSFORM = "transform"
_KIND_SINK = "sink"


class VectorLakeflowConnect(LakeflowConnect):
    """LakeflowConnect implementation for Vector observability data pipelines.

    Reads pipeline topology, component metrics, and health status
    from a running Vector instance via its GraphQL API (Vector 0.53+).
    """

    def __init__(self, options: dict[str, str]) -> None:
        super().__init__(options)
        self._api_url = options.get("api_url", "http://localhost:8686").rstrip("/")
        self._api_token = options.get("api_token", "")
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"
        if self._api_token:
            self._session.headers["Authorization"] = f"Bearer {self._api_token}"
        self._init_ts = datetime.now(timezone.utc).isoformat()

    def _graphql(self, query: str) -> dict:
        """Execute a GraphQL query against Vector's API with retry."""
        backoff = INITIAL_BACKOFF
        for attempt in range(MAX_RETRIES):
            resp = self._session.post(
                f"{self._api_url}/graphql", json={"query": query}
            )
            if resp.status_code not in RETRIABLE_STATUS_CODES:
                resp.raise_for_status()
                data = resp.json()
                if "errors" in data:
                    raise RuntimeError(f"Vector GraphQL error: {data['errors']}")
                return data["data"]
            if attempt < MAX_RETRIES - 1:
                time.sleep(backoff)
                backoff *= 2
        resp.raise_for_status()
        return {}

    def list_tables(self) -> list[str]:
        return list(TABLE_SCHEMAS.keys())

    def get_table_schema(
        self, table_name: str, table_options: dict[str, str]
    ) -> StructType:
        self._validate_table(table_name)
        return TABLE_SCHEMAS[table_name]

    def read_table_metadata(
        self, table_name: str, table_options: dict[str, str]
    ) -> dict:
        self._validate_table(table_name)
        return dict(TABLE_METADATA[table_name])

    def read_table(
        self, table_name: str, start_offset: dict, table_options: dict[str, str]
    ) -> tuple[Iterator[dict], dict]:
        self._validate_table(table_name)
        if table_name == "topology":
            return self._read_topology()
        elif table_name == "component_metrics":
            return self._read_component_metrics(start_offset)
        elif table_name == "health":
            return self._read_health()
        raise ValueError(f"Unknown table: {table_name}")

    def _validate_table(self, table_name: str) -> None:
        supported = self.list_tables()
        if table_name not in supported:
            raise ValueError(
                f"Table '{table_name}' is not supported. Supported: {supported}"
            )

    def _fetch_all_components(self) -> list[dict]:
        """Fetch all components with metrics using per-kind queries.

        Vector's GraphQL exposes sources/transforms/sinks as separate
        query roots with kind-specific metric fields.
        """
        query = """{
            sources(first: 100) {
                edges {
                    node {
                        componentId
                        componentType
                        metrics {
                            receivedEventsTotal { receivedEventsTotal }
                            sentEventsTotal { sentEventsTotal }
                            receivedBytesTotal { receivedBytesTotal }
                        }
                    }
                }
            }
            transforms(first: 100) {
                edges {
                    node {
                        componentId
                        componentType
                        metrics {
                            receivedEventsTotal { receivedEventsTotal }
                            sentEventsTotal { sentEventsTotal }
                        }
                    }
                }
            }
            sinks(first: 100) {
                edges {
                    node {
                        componentId
                        componentType
                        metrics {
                            receivedEventsTotal { receivedEventsTotal }
                            sentEventsTotal { sentEventsTotal }
                        }
                    }
                }
            }
        }"""
        data = self._graphql(query)
        components = []
        for kind, key in [
            (_KIND_SOURCE, "sources"),
            (_KIND_TRANSFORM, "transforms"),
            (_KIND_SINK, "sinks"),
        ]:
            for edge in data.get(key, {}).get("edges", []):
                node = edge["node"]
                metrics = node.get("metrics", {})
                components.append(
                    {
                        "component_id": node["componentId"],
                        "component_type": node["componentType"],
                        "component_kind": kind,
                        "received_events_total": (
                            metrics.get("receivedEventsTotal", {})
                            .get("receivedEventsTotal", 0.0)
                        ),
                        "sent_events_total": (
                            metrics.get("sentEventsTotal", {})
                            .get("sentEventsTotal", 0.0)
                        ),
                        "received_bytes_total": (
                            metrics.get("receivedBytesTotal", {})
                            .get("receivedBytesTotal", 0.0)
                        ),
                    }
                )
        return components

    def _read_topology(self) -> tuple[Iterator[dict], dict]:
        """Read Vector pipeline topology (snapshot)."""
        now = datetime.now(timezone.utc).isoformat()
        components = self._fetch_all_components()
        records = [
            {
                "component_id": c["component_id"],
                "component_type": c["component_type"],
                "component_kind": c["component_kind"],
                "collected_at": now,
            }
            for c in components
        ]
        return iter(records), {}

    def _read_component_metrics(
        self, start_offset: dict
    ) -> tuple[Iterator[dict], dict]:
        """Read per-component metrics (append). Each call produces a snapshot
        of current event/byte totals that gets appended to the table."""
        now = datetime.now(timezone.utc).isoformat()
        components = self._fetch_all_components()

        records = [
            {
                "component_id": c["component_id"],
                "component_type": c["component_type"],
                "component_kind": c["component_kind"],
                "sent_events_total": c["sent_events_total"],
                "received_events_total": c["received_events_total"],
                "received_bytes_total": c["received_bytes_total"],
                "errors_total": 0,
                "collected_at": now,
            }
            for c in components
        ]

        end_offset = {"cursor": now}
        if start_offset and start_offset == end_offset:
            return iter([]), start_offset
        return iter(records), end_offset

    def _read_health(self) -> tuple[Iterator[dict], dict]:
        """Read Vector health and meta info (snapshot)."""
        query = """{
            meta { versionString hostname }
            health
        }"""
        data = self._graphql(query)
        now = datetime.now(timezone.utc).isoformat()
        meta = data.get("meta", {})
        records = [
            {
                "hostname": meta.get("hostname", "unknown"),
                "version": meta.get("versionString", "unknown"),
                "is_healthy": data.get("health", False),
                "collected_at": now,
            }
        ]
        return iter(records), {}
