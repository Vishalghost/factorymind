"""Integration test: Digital Twin Manager end-to-end.

Verifies Redis cache update, DynamoDB persistence, and snapshot-on-CRITICAL
behavior with moto-backed AWS services and fakeredis-backed Redis.
"""

from __future__ import annotations

import pytest

from agents.digital_twin.manager.handler import handler


class TestDigitalTwinChain:
    def test_routine_update_writes_redis_and_dynamodb(
        self, aws_resources, fake_redis, healthy_telemetry, fresh_now
    ):
        """Non-critical update: Redis + DynamoDB written, no snapshot."""
        event = {
            "plant_id": "PLANT-001",
            "machine_id": "CNC-AERO-02",
            "state_update": healthy_telemetry,
            "source": "iot_ingestion",
            "severity": "MEDIUM",
        }
        result = handler(event, context=None)

        assert result["redis_updated"] is True
        assert result["snapshot_taken"] is False
        # processing time SLA: <500ms
        assert result["processing_time_ms"] < 500

        # Redis cache populated
        cache_key = "twin:state:PLANT-001:CNC-AERO-02"
        assert fake_redis.get(cache_key) is not None

        # DynamoDB row exists
        table = aws_resources["tables"]["FactoryMind_TwinState"]
        item = table.get_item(Key={"machine_id": "CNC-AERO-02"}).get("Item")
        assert item is not None
        assert item["plant_id"] == "PLANT-001"

    def test_critical_severity_takes_snapshot_to_s3(
        self, aws_resources, fake_redis, critical_telemetry, fresh_now
    ):
        """CRITICAL severity → snapshot written to factorymind-twin-snapshots."""
        event = {
            "plant_id": "PLANT-001",
            "machine_id": "CNC-AERO-09",
            "state_update": critical_telemetry,
            "source": "brain_decision",
            "severity": "CRITICAL",
        }
        result = handler(event, context=None)

        assert result["snapshot_taken"] is True

        # Snapshot bucket has at least one object
        s3 = aws_resources["s3"]
        listing = s3.list_objects_v2(Bucket="factorymind-twin-snapshots")
        assert listing.get("KeyCount", 0) >= 1

    def test_redis_ttl_set_to_300s(
        self, aws_resources, fake_redis, healthy_telemetry
    ):
        """Spec requires Redis TTL of 300s on twin:state:* keys."""
        event = {
            "plant_id": "PLANT-001",
            "machine_id": "CNC-AERO-15",
            "state_update": healthy_telemetry,
            "source": "iot_ingestion",
            "severity": "MEDIUM",
        }
        handler(event, context=None)

        ttl = fake_redis.ttl("twin:state:PLANT-001:CNC-AERO-15")
        assert 0 < ttl <= 300
