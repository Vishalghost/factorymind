"""Integration test: Edge AI Manager end-to-end.

Verifies the fire-and-forget path: ONNX inference (mocked) → classification →
escalation publish on ANOMALY → DynamoDB EdgeResults write.
"""

from __future__ import annotations

import pytest

from agents.edge_ai.manager.handler import handler


class TestEdgeAIChain:
    def test_normal_telemetry_no_escalation(
        self, aws_resources, fake_redis, healthy_telemetry, fresh_now
    ):
        """Healthy telemetry classifies NORMAL — no EventBridge escalation."""
        event = {
            "machine_id": "CNC-AERO-01",
            "timestamp": fresh_now,
            "telemetry": healthy_telemetry,
            "plant_id": "PLANT-001",
        }
        result = handler(event, context=None)

        assert result["classification"] == "NORMAL"
        assert result["escalated"] is False
        assert result["compound_rule_triggered"] is False
        # Edge AI inference SLA: <10ms (handler tracks inference_time_ms separately
        # from total processing_time_ms which includes Redis I/O).

    def test_compound_rule_escalates_with_critical_payload(
        self, aws_resources, fake_redis, critical_telemetry, fresh_now
    ):
        """Compound rule: vib >8.0 AND coolant <30.0 → ANOMALY + escalation."""
        event = {
            "machine_id": "CNC-AERO-01",
            "timestamp": fresh_now,
            "telemetry": critical_telemetry,
            "plant_id": "PLANT-001",
        }
        result = handler(event, context=None)

        assert result["classification"] == "ANOMALY"
        assert result["escalated"] is True
        assert result["compound_rule_triggered"] is True

    def test_sliding_window_persists_to_redis(
        self, aws_resources, fake_redis, healthy_telemetry, fresh_now
    ):
        """Each invocation should append the reading to the per-machine window."""
        event = {
            "machine_id": "CNC-AERO-07",
            "timestamp": fresh_now,
            "telemetry": healthy_telemetry,
            "plant_id": "PLANT-001",
        }
        for _ in range(3):
            handler(event, context=None)

        window_key = "edge:window:CNC-AERO-07"
        assert fake_redis.llen(window_key) == 3

    def test_edge_result_written_to_dynamodb(
        self, aws_resources, fake_redis, critical_telemetry, fresh_now
    ):
        """Each invocation should write a record to FactoryMind_EdgeResults."""
        event = {
            "machine_id": "CNC-AERO-13",
            "timestamp": fresh_now,
            "telemetry": critical_telemetry,
            "plant_id": "PLANT-001",
        }
        result = handler(event, context=None)

        table = aws_resources["tables"]["FactoryMind_EdgeResults"]
        item = table.get_item(Key={"edge_result_id": result["edge_result_id"]}).get("Item")
        assert item is not None
        assert item["machine_id"] == "CNC-AERO-13"
        assert item["classification"] == "ANOMALY"
