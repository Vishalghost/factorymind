"""Unit tests for Digital Twin Manager."""

import json
import time
from unittest.mock import patch, MagicMock, ANY

import pytest

from agents.shared.constants import REDIS_TWIN_TTL_SECONDS
from agents.shared.models.twin import TwinSyncInput, TwinSyncOutput
from agents.digital_twin.manager.handler import handler, _update_redis, _persist_dynamodb
from agents.digital_twin.workers.twinmaker_worker import sync_to_twinmaker, TWINMAKER_WORKSPACE_ID
from agents.digital_twin.workers.dashboard_worker import publish_to_appsync
from agents.digital_twin.workers.reconciler_worker import reconcile_state
from agents.digital_twin.workers.snapshot_worker import take_snapshot, SNAPSHOT_BUCKET


class FakeRedis:
    """Minimal fake Redis for testing Digital Twin cache operations."""

    def __init__(self):
        self._data: dict[str, str] = {}
        self._ttls: dict[str, int] = {}

    def setex(self, key: str, ttl: int, value: str) -> None:
        self._data[key] = value
        self._ttls[key] = ttl

    def get(self, key: str) -> str | None:
        return self._data.get(key)


class TestRedisCache:
    """Tests for Redis cache update with correct key pattern and TTL."""

    def test_redis_key_pattern(self):
        """Redis key follows twin:state:{plant_id}:{machine_id} pattern."""
        redis = FakeRedis()
        state_update = {"status": "RUNNING", "health_score": 0.95}

        with patch(
            "agents.shared.utils.aws_clients.get_redis_client",
            return_value=redis,
        ):
            result = _update_redis(
                redis_key="twin:state:PLANT-001:CNC-AERO-01",
                state_update=state_update,
                ttl=REDIS_TWIN_TTL_SECONDS,
            )

        assert result is True
        assert "twin:state:PLANT-001:CNC-AERO-01" in redis._data
        stored = json.loads(redis._data["twin:state:PLANT-001:CNC-AERO-01"])
        assert stored == state_update

    def test_redis_ttl_300_seconds(self):
        """Redis TTL is set to 300 seconds."""
        redis = FakeRedis()
        state_update = {"status": "IDLE"}

        with patch(
            "agents.shared.utils.aws_clients.get_redis_client",
            return_value=redis,
        ):
            _update_redis(
                redis_key="twin:state:PLANT-001:CNC-AERO-05",
                state_update=state_update,
                ttl=REDIS_TWIN_TTL_SECONDS,
            )

        assert redis._ttls["twin:state:PLANT-001:CNC-AERO-05"] == 300

    def test_redis_update_returns_false_on_failure(self):
        """Redis update returns False when connection fails."""
        mock_redis = MagicMock()
        mock_redis.setex.side_effect = ConnectionError("Redis unavailable")

        with patch(
            "agents.shared.utils.aws_clients.get_redis_client",
            return_value=mock_redis,
        ):
            result = _update_redis(
                redis_key="twin:state:PLANT-001:CNC-AERO-01",
                state_update={"status": "RUNNING"},
                ttl=300,
            )

        assert result is False


class TestDynamoDBPersistence:
    """Tests for DynamoDB TwinState persistence."""

    def test_dynamodb_put_item_called(self):
        """State is persisted to FactoryMind_TwinState table."""
        mock_table = MagicMock()
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        with patch(
            "agents.shared.utils.aws_clients.get_dynamodb_resource",
            return_value=mock_dynamodb,
        ):
            _persist_dynamodb(
                machine_id="CNC-AERO-01",
                plant_id="PLANT-001",
                state_update={"status": "RUNNING", "health_score": 0.9},
                source="iot_ingestion",
                sync_id="TWNR-abc123",
            )

        mock_dynamodb.Table.assert_called_once_with("FactoryMind_TwinState")
        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["machine_id"] == "CNC-AERO-01"
        assert item["plant_id"] == "PLANT-001"
        # Floats are converted to Decimal because DynamoDB rejects raw floats.
        from decimal import Decimal
        assert item["state"] == {"status": "RUNNING", "health_score": Decimal("0.9")}
        assert item["source"] == "iot_ingestion"
        assert item["sync_id"] == "TWNR-abc123"
        assert "updated_at" in item

    def test_dynamodb_persist_handles_error(self):
        """DynamoDB persist does not raise on failure (best-effort)."""
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.side_effect = Exception("DynamoDB unavailable")

        with patch(
            "agents.shared.utils.aws_clients.get_dynamodb_resource",
            return_value=mock_dynamodb,
        ):
            # Should not raise
            _persist_dynamodb(
                machine_id="CNC-AERO-01",
                plant_id="PLANT-001",
                state_update={"status": "FAULT"},
                source="brain_decision",
                sync_id="TWNR-xyz789",
            )


class TestTwinMakerSync:
    """Tests for TwinMaker sync invocation."""

    def test_twinmaker_sync_success(self):
        """TwinMaker sync calls update_entity with correct workspace and entity."""
        mock_client = MagicMock()
        mock_client.update_entity.return_value = {}

        result = sync_to_twinmaker(
            machine_id="CNC-AERO-01",
            state_update={"status": "RUNNING", "health_score": 0.95},
            client=mock_client,
        )

        assert result is True
        mock_client.update_entity.assert_called_once()
        call_kwargs = mock_client.update_entity.call_args[1]
        assert call_kwargs["workspaceId"] == "factorymind-workspace"
        assert call_kwargs["entityId"] == "CNC-AERO-01"
        assert "factorymind.machine.state" in call_kwargs["componentUpdates"]

    def test_twinmaker_sync_failure(self):
        """TwinMaker sync returns False on error."""
        mock_client = MagicMock()
        mock_client.update_entity.side_effect = Exception("TwinMaker error")

        result = sync_to_twinmaker(
            machine_id="CNC-AERO-01",
            state_update={"status": "FAULT"},
            client=mock_client,
        )

        assert result is False

    def test_twinmaker_property_entries_built(self):
        """TwinMaker property entries are built from state update."""
        mock_client = MagicMock()
        mock_client.update_entity.return_value = {}

        sync_to_twinmaker(
            machine_id="CNC-AERO-01",
            state_update={
                "health_score": 0.85,
                "status": "RUNNING",
                "is_active": True,
            },
            client=mock_client,
        )

        call_kwargs = mock_client.update_entity.call_args[1]
        component_updates = call_kwargs["componentUpdates"]["factorymind.machine.state"]
        property_updates = component_updates["propertyUpdates"]
        assert "health_score" in property_updates
        assert "status" in property_updates
        assert "is_active" in property_updates


class TestAppSyncPublish:
    """Tests for AppSync mutation publish."""

    def test_appsync_publish_delegates_to_shared(self):
        """publish_to_appsync delegates to the shared publisher with mapped fields."""
        captured = {}

        def fake_pub(**kw):
            captured.update(kw)
            return True

        with patch("agents.digital_twin.workers.dashboard_worker.publish_machine_state", fake_pub):
            result = publish_to_appsync(
                plant_id="PLANT-001",
                machine_id="CNC-AERO-01",
                state_update={"status": "RUNNING", "health_score": 0.9, "updated_at": "t"},
            )

        assert result is True
        assert captured["machine_id"] == "CNC-AERO-01"
        assert captured["plant_id"] == "PLANT-001"
        assert captured["status"] == "RUNNING"
        assert captured["health_score"] == 0.9

    def test_appsync_publish_failure(self):
        """AppSync publish returns False when the shared publisher fails/no-ops."""
        with patch("agents.digital_twin.workers.dashboard_worker.publish_machine_state", return_value=False):
            result = publish_to_appsync(
                plant_id="PLANT-001",
                machine_id="CNC-AERO-01",
                state_update={"status": "FAULT"},
            )

        assert result is False


class TestSnapshotOnCritical:
    """Tests for snapshot taken only on CRITICAL severity."""

    def test_snapshot_taken_on_critical(self):
        """Snapshot is stored to S3 when severity is CRITICAL."""
        mock_s3 = MagicMock()
        mock_s3.put_object.return_value = {}

        result = take_snapshot(
            sync_id="TWNR-abc123",
            plant_id="PLANT-001",
            machine_id="CNC-AERO-01",
            state_update={"status": "FAULT", "health_score": 0.1},
            source="iot_ingestion",
            s3_client=mock_s3,
        )

        assert result is True
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "factorymind-twin-snapshots"
        assert "CNC-AERO-01" in call_kwargs["Key"]
        assert "PLANT-001" in call_kwargs["Key"]
        body = json.loads(call_kwargs["Body"])
        assert body["sync_id"] == "TWNR-abc123"
        assert body["severity"] == "CRITICAL"

    def test_snapshot_not_taken_on_non_critical(self):
        """Handler does not call take_snapshot when severity is not CRITICAL."""
        event = {
            "plant_id": "PLANT-001",
            "machine_id": "CNC-AERO-01",
            "state_update": {"status": "RUNNING", "health_score": 0.8},
            "source": "iot_ingestion",
            "severity": "HIGH",
        }

        with patch("agents.digital_twin.manager.handler._update_redis", return_value=True), \
             patch("agents.digital_twin.manager.handler._persist_dynamodb"), \
             patch("agents.digital_twin.manager.handler.sync_to_twinmaker", return_value=True), \
             patch("agents.digital_twin.manager.handler.publish_to_appsync", return_value=True), \
             patch("agents.digital_twin.manager.handler.take_snapshot") as mock_snapshot:
            result = handler(event, None)

        mock_snapshot.assert_not_called()
        assert result["snapshot_taken"] is False

    def test_snapshot_taken_when_severity_critical(self):
        """Handler calls take_snapshot when severity is CRITICAL."""
        event = {
            "plant_id": "PLANT-001",
            "machine_id": "CNC-AERO-01",
            "state_update": {"status": "FAULT", "health_score": 0.1},
            "source": "iot_ingestion",
            "severity": "CRITICAL",
        }

        with patch("agents.digital_twin.manager.handler._update_redis", return_value=True), \
             patch("agents.digital_twin.manager.handler._persist_dynamodb"), \
             patch("agents.digital_twin.manager.handler.sync_to_twinmaker", return_value=True), \
             patch("agents.digital_twin.manager.handler.publish_to_appsync", return_value=True), \
             patch("agents.digital_twin.manager.handler.take_snapshot", return_value=True) as mock_snapshot:
            result = handler(event, None)

        mock_snapshot.assert_called_once()
        assert result["snapshot_taken"] is True

    def test_snapshot_not_taken_when_severity_none(self):
        """Handler does not call take_snapshot when severity is None."""
        event = {
            "plant_id": "PLANT-001",
            "machine_id": "CNC-AERO-01",
            "state_update": {"status": "IDLE"},
            "source": "maintenance",
        }

        with patch("agents.digital_twin.manager.handler._update_redis", return_value=True), \
             patch("agents.digital_twin.manager.handler._persist_dynamodb"), \
             patch("agents.digital_twin.manager.handler.sync_to_twinmaker", return_value=True), \
             patch("agents.digital_twin.manager.handler.publish_to_appsync", return_value=True), \
             patch("agents.digital_twin.manager.handler.take_snapshot") as mock_snapshot:
            result = handler(event, None)

        mock_snapshot.assert_not_called()
        assert result["snapshot_taken"] is False


class TestReconciliation:
    """Tests for reconciliation logic (DynamoDB wins on divergence)."""

    def test_reconcile_diverged_states(self):
        """When Redis and DynamoDB diverge, DynamoDB state overwrites Redis."""
        redis = FakeRedis()
        redis.setex(
            "twin:state:PLANT-001:CNC-AERO-01",
            300,
            json.dumps({"status": "RUNNING", "health_score": 0.9}),
        )

        mock_table = MagicMock()
        mock_table.get_item.return_value = {
            "Item": {
                "machine_id": "CNC-AERO-01",
                "state": {"status": "FAULT", "health_score": 0.3},
            }
        }
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        result = reconcile_state(
            plant_id="PLANT-001",
            machine_id="CNC-AERO-01",
            redis_client=redis,
            dynamodb_resource=mock_dynamodb,
        )

        assert result["diverged"] is True
        assert result["reconciled"] is True
        assert result["source_of_truth"] == "dynamodb"
        # Verify Redis was overwritten with DynamoDB state
        reconciled_state = json.loads(redis.get("twin:state:PLANT-001:CNC-AERO-01"))
        assert reconciled_state == {"status": "FAULT", "health_score": 0.3}

    def test_reconcile_consistent_states(self):
        """When Redis and DynamoDB are consistent, no reconciliation needed."""
        state = {"status": "RUNNING", "health_score": 0.95}
        redis = FakeRedis()
        redis.setex(
            "twin:state:PLANT-001:CNC-AERO-01",
            300,
            json.dumps(state),
        )

        mock_table = MagicMock()
        mock_table.get_item.return_value = {
            "Item": {
                "machine_id": "CNC-AERO-01",
                "state": state,
            }
        }
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        result = reconcile_state(
            plant_id="PLANT-001",
            machine_id="CNC-AERO-01",
            redis_client=redis,
            dynamodb_resource=mock_dynamodb,
        )

        assert result["diverged"] is False
        assert result["reconciled"] is False

    def test_reconcile_redis_empty_dynamo_has_state(self):
        """When Redis is empty but DynamoDB has state, reconcile."""
        redis = FakeRedis()  # No data in Redis

        mock_table = MagicMock()
        mock_table.get_item.return_value = {
            "Item": {
                "machine_id": "CNC-AERO-01",
                "state": {"status": "IDLE", "health_score": 0.8},
            }
        }
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        result = reconcile_state(
            plant_id="PLANT-001",
            machine_id="CNC-AERO-01",
            redis_client=redis,
            dynamodb_resource=mock_dynamodb,
        )

        assert result["diverged"] is True
        assert result["reconciled"] is True
        reconciled_state = json.loads(redis.get("twin:state:PLANT-001:CNC-AERO-01"))
        assert reconciled_state == {"status": "IDLE", "health_score": 0.8}

    def test_reconcile_both_empty(self):
        """When both Redis and DynamoDB are empty, no divergence."""
        redis = FakeRedis()

        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        result = reconcile_state(
            plant_id="PLANT-001",
            machine_id="CNC-AERO-01",
            redis_client=redis,
            dynamodb_resource=mock_dynamodb,
        )

        assert result["diverged"] is False
        assert result["reconciled"] is False


class TestProcessingTimeTracking:
    """Tests for processing time tracking."""

    def test_processing_time_included_in_output(self):
        """Handler output includes processing_time_ms."""
        event = {
            "plant_id": "PLANT-001",
            "machine_id": "CNC-AERO-01",
            "state_update": {"status": "RUNNING"},
            "source": "iot_ingestion",
            "severity": "LOW",
        }

        with patch("agents.digital_twin.manager.handler._update_redis", return_value=True), \
             patch("agents.digital_twin.manager.handler._persist_dynamodb"), \
             patch("agents.digital_twin.manager.handler.sync_to_twinmaker", return_value=True), \
             patch("agents.digital_twin.manager.handler.publish_to_appsync", return_value=True):
            result = handler(event, None)

        assert "processing_time_ms" in result
        assert isinstance(result["processing_time_ms"], int)
        assert result["processing_time_ms"] >= 0

    def test_processing_time_is_non_negative(self):
        """Processing time is always non-negative."""
        event = {
            "plant_id": "PLANT-001",
            "machine_id": "CNC-AERO-42",
            "state_update": {"status": "IDLE", "health_score": 0.7},
            "source": "maintenance",
        }

        with patch("agents.digital_twin.manager.handler._update_redis", return_value=True), \
             patch("agents.digital_twin.manager.handler._persist_dynamodb"), \
             patch("agents.digital_twin.manager.handler.sync_to_twinmaker", return_value=True), \
             patch("agents.digital_twin.manager.handler.publish_to_appsync", return_value=True):
            result = handler(event, None)

        assert result["processing_time_ms"] >= 0

    def test_output_has_twnr_prefix_sync_id(self):
        """Handler output sync_id starts with TWNR- prefix."""
        event = {
            "plant_id": "PLANT-001",
            "machine_id": "CNC-AERO-01",
            "state_update": {"status": "RUNNING"},
            "source": "iot_ingestion",
        }

        with patch("agents.digital_twin.manager.handler._update_redis", return_value=True), \
             patch("agents.digital_twin.manager.handler._persist_dynamodb"), \
             patch("agents.digital_twin.manager.handler.sync_to_twinmaker", return_value=True), \
             patch("agents.digital_twin.manager.handler.publish_to_appsync", return_value=True):
            result = handler(event, None)

        assert result["sync_id"].startswith("TWNR-")
