"""Static schemas and metadata for Vector connector tables."""

from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

TABLE_SCHEMAS = {
    "topology": StructType(
        [
            StructField("component_id", StringType(), False),
            StructField("component_type", StringType(), True),
            StructField("component_kind", StringType(), True),
            StructField("collected_at", TimestampType(), True),
        ]
    ),
    "component_metrics": StructType(
        [
            StructField("component_id", StringType(), False),
            StructField("component_type", StringType(), True),
            StructField("component_kind", StringType(), True),
            StructField("sent_events_throughput", DoubleType(), True),
            StructField("sent_bytes_throughput", DoubleType(), True),
            StructField("received_events_throughput", DoubleType(), True),
            StructField("received_bytes_throughput", DoubleType(), True),
            StructField("errors_total", LongType(), True),
            StructField("collected_at", TimestampType(), True),
        ]
    ),
    "health": StructType(
        [
            StructField("hostname", StringType(), False),
            StructField("version", StringType(), True),
            StructField("os", StringType(), True),
            StructField("arch", StringType(), True),
            StructField("uptime_seconds", LongType(), True),
            StructField("is_healthy", BooleanType(), True),
            StructField("collected_at", TimestampType(), True),
        ]
    ),
}

TABLE_METADATA = {
    "topology": {
        "primary_keys": ["component_id"],
        "cursor_field": None,
        "ingestion_type": "snapshot",
    },
    "component_metrics": {
        "primary_keys": ["component_id"],
        "cursor_field": "collected_at",
        "ingestion_type": "append",
    },
    "health": {
        "primary_keys": ["hostname"],
        "cursor_field": None,
        "ingestion_type": "snapshot",
    },
}
