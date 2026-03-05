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


class VectorLakeflowConnect(LakeflowConnect):
    """LakeflowConnect implementation for Vector observability data pipelines.

    Reads pipeline topology, component metrics, and health status
    from a running Vector instance via its GraphQL API.
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

    def _read_topology(self) -> tuple[Iterator[dict], dict]:
        """Read Vector pipeline topology (snapshot)."""
        query = """{
            components(first: 1000) {
                edges {
                    node {
                        componentId
                        componentType
                        componentKind
                    }
                }
            }
        }"""
        data = self._graphql(query)
        now = datetime.now(timezone.utc).isoformat()
        records = []
        for edge in data.get("components", {}).get("edges", []):
            node = edge["node"]
            records.append(
                {
                    "component_id": node["componentId"],
                    "component_type": node["componentType"],
                    "component_kind": node["componentKind"],
                    "collected_at": now,
                }
            )
        return iter(records), {}

    def _read_component_metrics(
        self, start_offset: dict
    ) -> tuple[Iterator[dict], dict]:
        """Read per-component metrics (append). Each call produces a snapshot
        of current throughput that gets appended to the table."""
        query = """{
            components(first: 1000) {
                edges {
                    node {
                        componentId
                        componentType
                        componentKind
                        on {
                            ... on Source {
                                outputs {
                                    sentEventsThroughput
                                    sentEventsBytesTotalThroughput
                                }
                                metrics {
                                    receivedEventsTotal {
                                        receivedEventsTotal as totalValue
                                    }
                                    sentEventsTotal {
                                        sentEventsTotal as totalValue
                                    }
                                }
                            }
                            ... on Transform {
                                outputs {
                                    sentEventsThroughput
                                    sentEventsBytesTotalThroughput
                                }
                                metrics {
                                    receivedEventsTotal {
                                        receivedEventsTotal as totalValue
                                    }
                                    sentEventsTotal {
                                        sentEventsTotal as totalValue
                                    }
                                }
                            }
                            ... on Sink {
                                metrics {
                                    receivedEventsTotal {
                                        receivedEventsTotal as totalValue
                                    }
                                    sentEventsTotal {
                                        sentEventsTotal as totalValue
                                    }
                                }
                            }
                        }
                    }
                }
            }
            componentErrorsTotals {
                componentId
                metric {
                    errorsTotalEvents
                }
            }
        }"""
        try:
            data = self._graphql(query)
        except Exception:
            # Fall back to simpler query if extended metrics aren't available
            return self._read_component_metrics_simple(start_offset)

        now = datetime.now(timezone.utc).isoformat()

        # Build error map
        error_map = {}
        for err in data.get("componentErrorsTotals", []):
            cid = err.get("componentId", "")
            total = err.get("metric", {}).get("errorsTotalEvents", 0)
            error_map[cid] = total

        records = []
        for edge in data.get("components", {}).get("edges", []):
            node = edge["node"]
            cid = node["componentId"]

            # Extract throughput from outputs
            on_data = node.get("on", {}) or {}
            outputs = on_data.get("outputs", []) or []
            sent_throughput = 0.0
            sent_bytes = 0.0
            for output in outputs:
                sent_throughput += output.get("sentEventsThroughput", 0.0) or 0.0
                sent_bytes += output.get("sentEventsBytesTotalThroughput", 0.0) or 0.0

            records.append(
                {
                    "component_id": cid,
                    "component_type": node["componentType"],
                    "component_kind": node["componentKind"],
                    "sent_events_throughput": sent_throughput,
                    "sent_bytes_throughput": sent_bytes,
                    "received_events_throughput": 0.0,
                    "received_bytes_throughput": 0.0,
                    "errors_total": error_map.get(cid, 0),
                    "collected_at": now,
                }
            )

        end_offset = {"cursor": now}
        if start_offset and start_offset == end_offset:
            return iter([]), start_offset
        return iter(records), end_offset

    def _read_component_metrics_simple(
        self, start_offset: dict
    ) -> tuple[Iterator[dict], dict]:
        """Simplified metrics read using basic GraphQL queries."""
        topo_query = """{
            components(first: 1000) {
                edges {
                    node {
                        componentId
                        componentType
                        componentKind
                    }
                }
            }
        }"""
        data = self._graphql(topo_query)
        now = datetime.now(timezone.utc).isoformat()

        records = []
        for edge in data.get("components", {}).get("edges", []):
            node = edge["node"]
            records.append(
                {
                    "component_id": node["componentId"],
                    "component_type": node["componentType"],
                    "component_kind": node["componentKind"],
                    "sent_events_throughput": 0.0,
                    "sent_bytes_throughput": 0.0,
                    "received_events_throughput": 0.0,
                    "received_bytes_throughput": 0.0,
                    "errors_total": 0,
                    "collected_at": now,
                }
            )

        end_offset = {"cursor": now}
        if start_offset and start_offset == end_offset:
            return iter([]), start_offset
        return iter(records), end_offset

    def _read_health(self) -> tuple[Iterator[dict], dict]:
        """Read Vector health and meta info (snapshot)."""
        query = """{
            meta {
                versionString
                hostname
                os
                arch
            }
            uptime
            health
        }"""
        data = self._graphql(query)
        now = datetime.now(timezone.utc).isoformat()
        meta = data.get("meta", {})
        records = [
            {
                "hostname": meta.get("hostname", "unknown"),
                "version": meta.get("versionString", "unknown"),
                "os": meta.get("os", "unknown"),
                "arch": meta.get("arch", "unknown"),
                "uptime_seconds": int(data.get("uptime", 0)),
                "is_healthy": data.get("health", False),
                "collected_at": now,
            }
        ]
        return iter(records), {}
