"""Static schemas and metadata for Vector connector tables."""

from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    IntegerType,
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
            StructField("sent_events_total", DoubleType(), True),
            StructField("received_events_total", DoubleType(), True),
            StructField("received_bytes_total", DoubleType(), True),
            StructField("errors_total", LongType(), True),
            StructField("collected_at", TimestampType(), True),
        ]
    ),
    "health": StructType(
        [
            StructField("hostname", StringType(), False),
            StructField("version", StringType(), True),
            StructField("is_healthy", BooleanType(), True),
            StructField("collected_at", TimestampType(), True),
        ]
    ),
    "ndr_events": StructType(
        [
            StructField("event_timestamp", TimestampType(), False),
            StructField("src_ip", StringType(), True),
            StructField("dst_ip", StringType(), True),
            StructField("src_port", IntegerType(), True),
            StructField("dst_port", IntegerType(), True),
            StructField("network_protocol", StringType(), True),
            StructField("event_type", StringType(), True),
            StructField("severity", StringType(), True),
            StructField("sensor_id", StringType(), True),
            StructField("message", StringType(), True),
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
    "ndr_events": {
        "primary_keys": ["event_timestamp", "src_ip", "src_port"],
        "cursor_field": "collected_at",
        "ingestion_type": "append",
    },
}
