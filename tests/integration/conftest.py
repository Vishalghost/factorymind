"""Shared fixtures for integration tests.

These tests use moto to spin up in-memory AWS services and fakeredis to stand
in for ElastiCache. The agent code reaches AWS via boto3 and Redis via the
get_redis_client() factory; both are monkeypatched so the agents run end-to-end
without touching real infrastructure.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import boto3
import fakeredis
import pytest
from moto import mock_aws


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    """Force a fixed test region + dummy creds so boto3 doesn't pick up real ones."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "test")


@pytest.fixture
def mocked_aws():
    """Activate moto for all AWS services this test suite touches."""
    with mock_aws():
        yield


@pytest.fixture
def fake_redis(monkeypatch):
    """Replace get_redis_client() with a fakeredis instance.

    Both Edge AI and Digital Twin reach Redis via the shared aws_clients factory.
    Patching that factory once is enough for both agents.
    """
    server = fakeredis.FakeServer()
    client = fakeredis.FakeRedis(server=server, decode_responses=True)

    from agents.shared.utils import aws_clients

    monkeypatch.setattr(aws_clients, "get_redis_client", lambda: client)
    return client


@pytest.fixture
def aws_resources(mocked_aws):
    """Provision the subset of AWS resources the agents touch.

    Returns a dict with handles to the provisioned tables, buckets, queues,
    streams, and event bus so individual tests can assert on state.
    """
    region = "ap-south-1"

    # DynamoDB tables — same shape as StorageStack
    ddb = boto3.resource("dynamodb", region_name=region)
    table_specs = [
        ("FactoryMind_MachineState", "machine_id"),
        ("FactoryMind_MachineSpecs", "machine_id"),
        ("FactoryMind_QualityResults", "inspection_report_id"),
        ("FactoryMind_QualityThresholds", "product_type"),
        ("FactoryMind_Predictions", "prediction_report_id"),
        ("FactoryMind_WorkOrders", "work_order_id"),
        ("FactoryMind_EnergyBaselines", "machine_id"),
        ("FactoryMind_SustainabilityKPIs", "report_id"),
        ("FactoryMind_TwinState", "machine_id"),
        ("FactoryMind_FloorLayout", "plant_id"),
        ("FactoryMind_EdgeThresholds", "machine_id"),
        ("FactoryMind_EdgeResults", "edge_result_id"),
    ]
    tables = {}
    for name, pk in table_specs:
        tables[name] = ddb.create_table(
            TableName=name,
            KeySchema=[{"AttributeName": pk, "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": pk, "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

    # S3 buckets
    s3 = boto3.client("s3", region_name=region)
    buckets = [
        "factorymind-raw-data",
        "factorymind-product-images",
        "factorymind-defect-images",
        "factorymind-reports",
        "factorymind-twin-snapshots",
    ]
    for bucket in buckets:
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": region},
        )

    # EventBridge bus
    events = boto3.client("events", region_name=region)
    events.create_event_bus(Name="factorymind-bus")

    # SQS work order queue
    sqs = boto3.client("sqs", region_name=region)
    queue = sqs.create_queue(QueueName="factorymind-workorder-queue")

    # SNS alert topics
    sns = boto3.client("sns", region_name=region)
    sns.create_topic(Name="factorymind-quality-alerts")
    sns.create_topic(Name="factorymind-maintenance-alerts")

    # Kinesis sensor stream (used by event source mappings, not agents directly)
    kinesis = boto3.client("kinesis", region_name=region)
    kinesis.create_stream(StreamName="factorymind-sensor-stream", ShardCount=1)

    # Timestream — IoT Ingestion data router writes here.
    timestream = boto3.client("timestream-write", region_name=region)
    timestream.create_database(DatabaseName="FactoryMindSensors")
    timestream.create_table(
        DatabaseName="FactoryMindSensors",
        TableName="SensorReadings",
    )
    timestream.create_table(
        DatabaseName="FactoryMindSensors",
        TableName="EnergyReadings",
    )

    return {
        "tables": tables,
        "ddb_resource": ddb,
        "s3": s3,
        "events": events,
        "sqs": sqs,
        "queue_url": queue["QueueUrl"],
        "kinesis": kinesis,
        "timestream": timestream,
    }


@pytest.fixture(autouse=True)
def reset_onnx_cache():
    """Reset the cached ONNX session between tests so missing-model fallback
    is exercised on every run instead of getting stuck after the first failure.
    """
    from agents.edge_ai.workers import onnx_worker
    onnx_worker._model_session = None
    yield
    onnx_worker._model_session = None


@pytest.fixture(autouse=True)
def reset_boto_cache():
    """Clear the lru_cache on boto3 client factories so each test gets fresh
    clients bound to the active moto mock.
    """
    from agents.shared.utils import aws_clients
    for fn_name in (
        "get_dynamodb_client",
        "get_dynamodb_resource",
        "get_timestream_write_client",
        "get_timestream_query_client",
        "get_s3_client",
        "get_eventbridge_client",
        "get_sqs_client",
        "get_lambda_client",
        "get_sagemaker_runtime_client",
    ):
        getattr(aws_clients, fn_name).cache_clear()
    yield


@pytest.fixture
def fresh_now() -> str:
    """Return a fresh ISO timestamp that won't trip the 60-second staleness check."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def critical_telemetry() -> dict:
    """Compound-rule-triggering CNC telemetry payload."""
    return {
        "vibration_mms": 12.0,   # > 8.0 anomaly threshold
        "current_amps": 38.0,
        "coolant_lmin": 10.0,    # < 30.0 anomaly threshold
        "acoustic_db": 98.0,
    }


@pytest.fixture
def healthy_telemetry() -> dict:
    """Telemetry well within all normal ranges."""
    return {
        "vibration_mms": 3.4,
        "current_amps": 18.2,
        "coolant_lmin": 45.1,
        "acoustic_db": 78.5,
    }
