---
inclusion: manual
---

# Skill: Test a FactoryMind Agent

## When to Use
Use this skill when writing unit tests, integration tests, or E2E tests for any FactoryMind agent.

## Unit Test Template (Worker Agent)

```python
"""
Unit tests for {Worker Name} Worker.
Uses mocked AWS services — no real infrastructure needed.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from agents.{agent_dir}.workers.{worker_name} import handler, WorkerInput, WorkerOutput


@pytest.fixture
def sample_input():
    return {
        "machine_id": "MCH-042",
        "plant_id": "PLANT-001",
        "timestamp": "2026-05-06T10:32:00Z",
        # Add worker-specific fields
    }


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.function_name = "factorymind-test-worker"
    ctx.memory_limit_in_mb = 512
    return ctx


class TestWorkerHandler:
    def test_successful_processing(self, sample_input, mock_context):
        """Worker processes valid input and returns SUCCESS."""
        result = handler(sample_input, mock_context)
        assert result["status"] == "SUCCESS"

    def test_invalid_input_raises(self, mock_context):
        """Worker rejects malformed input."""
        with pytest.raises(Exception):
            handler({}, mock_context)

    @patch("boto3.resource")
    def test_dynamodb_write(self, mock_boto, sample_input, mock_context):
        """Worker writes results to DynamoDB."""
        mock_table = MagicMock()
        mock_boto.return_value.Table.return_value = mock_table
        
        handler(sample_input, mock_context)
        
        mock_table.put_item.assert_called_once()
```

## Unit Test Template (Manager Agent)

```python
"""
Unit tests for {Manager Name} Manager Agent.
Tests delegation logic and result aggregation.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from agents.{agent_dir}.manager.handler import handler


@pytest.fixture
def sample_event():
    return {
        "request_id": "TEST-001",
        "plant_id": "PLANT-001",
        "machine_id": "MCH-042",
        "timestamp": "2026-05-06T10:32:00Z",
    }


class TestManagerDelegation:
    @patch("boto3.client")
    def test_delegates_to_workers(self, mock_client, sample_event):
        """Manager invokes correct worker Lambdas."""
        mock_lambda = MagicMock()
        mock_lambda.invoke.return_value = {
            "Payload": MagicMock(read=lambda: json.dumps({"status": "SUCCESS"}).encode())
        }
        mock_client.return_value = mock_lambda
        
        result = handler(sample_event, MagicMock())
        
        assert mock_lambda.invoke.called
        assert result["processing_time_ms"] > 0

    @patch("boto3.client")
    def test_publishes_eventbridge_on_critical(self, mock_client, sample_event):
        """Manager publishes to EventBridge for critical findings."""
        # Setup mock to return critical result from worker
        mock_eb = MagicMock()
        mock_client.return_value = mock_eb
        
        sample_event["severity"] = "CRITICAL"
        handler(sample_event, MagicMock())
        
        # Verify EventBridge put_events was called
        mock_eb.put_events.assert_called()

    @patch("boto3.client")
    def test_retry_on_worker_failure(self, mock_client, sample_event):
        """Manager retries once on worker failure, then escalates."""
        mock_lambda = MagicMock()
        mock_lambda.invoke.side_effect = [
            Exception("Timeout"),  # First attempt fails
            {"Payload": MagicMock(read=lambda: json.dumps({"status": "SUCCESS"}).encode())},
        ]
        mock_client.return_value = mock_lambda
        
        result = handler(sample_event, MagicMock())
        assert mock_lambda.invoke.call_count == 2
```

## Integration Test Template

```python
"""
Integration tests for {Agent Name}.
Requires LocalStack running: docker-compose up localstack
"""
import boto3
import pytest
from testcontainers.localstack import LocalStackContainer


@pytest.fixture(scope="session")
def localstack():
    with LocalStackContainer(image="localstack/localstack:3.0") as ls:
        yield ls


@pytest.fixture
def dynamodb_table(localstack):
    """Create test DynamoDB table."""
    client = boto3.resource(
        "dynamodb",
        endpoint_url=localstack.get_url(),
        region_name="us-east-1",
    )
    table = client.create_table(
        TableName="FactoryMind_MachineState",
        KeySchema=[{"AttributeName": "machine_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "machine_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


class TestIntegration:
    def test_full_pipeline(self, dynamodb_table):
        """Test complete Manager → Worker → DynamoDB flow."""
        # Seed initial state
        dynamodb_table.put_item(Item={
            "machine_id": "MCH-042",
            "operational_status": "RUNNING",
        })
        
        # Invoke manager with test event
        # Assert DynamoDB was updated correctly
        pass
```

## Edge AI Latency Test

```python
"""
Latency tests for Edge AI Manager.
Verifies sub-10ms inference SLA.
"""
import time
import pytest
from agents.edge_ai.manager.handler import handler


class TestEdgeLatency:
    @pytest.mark.parametrize("iteration", range(100))
    def test_inference_under_10ms(self, iteration):
        """Edge inference must complete in under 10ms."""
        event = {
            "edge_request_id": f"EDG-test-{iteration}",
            "machine_id": "MCH-042",
            "plant_id": "PLANT-001",
            "timestamp": "2026-05-06T10:32:00.000Z",
            "sensor_reading": {
                "temperature_c": 72.0,
                "vibration_hz": 115.0,
                "pressure_bar": 6.2,
                "power_kw": 35.0,
                "rpm": 2750,
            },
        }
        
        start = time.perf_counter_ns()
        result = handler(event, None)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        
        assert elapsed_ms < 10.0, f"Inference took {elapsed_ms:.2f}ms (SLA: <10ms)"
        assert result["sla_met"] is True

    def test_anomaly_escalation(self):
        """ANOMALY classification triggers cloud escalation."""
        event = {
            "edge_request_id": "EDG-test-anomaly",
            "machine_id": "MCH-042",
            "plant_id": "PLANT-001",
            "timestamp": "2026-05-06T10:32:00.000Z",
            "sensor_reading": {
                "temperature_c": 92.0,
                "vibration_hz": 155.0,
                "pressure_bar": 8.5,
                "power_kw": 48.0,
                "rpm": 3100,
            },
        }
        
        result = handler(event, None)
        assert result["inference_result"]["classification"] == "ANOMALY"
        assert result["escalation_sent"] is True
```

## Test Configuration (conftest.py)

```python
"""Shared test fixtures for FactoryMind."""
import os
import pytest

# Force tests to use mocked AWS
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["POWERTOOLS_SERVICE_NAME"] = "test"
os.environ["POWERTOOLS_METRICS_NAMESPACE"] = "FactoryMindTest"


@pytest.fixture
def machine_ids():
    return [f"MCH-{i:03d}" for i in range(1, 51)]


@pytest.fixture
def normal_reading():
    return {
        "temperature_c": 72.0,
        "vibration_hz": 115.0,
        "pressure_bar": 6.2,
        "power_kw": 35.0,
        "rpm": 2750,
        "oil_level_pct": 82.0,
    }


@pytest.fixture
def anomaly_reading():
    return {
        "temperature_c": 87.4,
        "vibration_hz": 143.2,
        "pressure_bar": 6.8,
        "power_kw": 42.1,
        "rpm": 2840,
        "oil_level_pct": 72.3,
    }
```

## Running Tests

```bash
# All unit tests
pytest tests/unit/ -v --tb=short

# Single agent tests
pytest tests/unit/test_edge_ai/ -v

# Integration tests (LocalStack required)
docker-compose up -d localstack
pytest tests/integration/ -v

# Latency tests only
pytest tests/unit/ -k "latency" -v

# With coverage
pytest tests/ --cov=agents --cov-report=html
```
