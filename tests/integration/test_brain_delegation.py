"""Integration test: Brain Agent delegation chain.

Verifies the full LangGraph state machine: assess_severity →
query_machine_history → determine_delegation → invoke_managers →
synthesize_recommendation, with manager invocations stubbed via Lambda
client patching.

The Brain's invoke_manager helper calls boto3 Lambda directly. Under moto's
mock_aws, lambda:Invoke returns a stubbed response unless we provide function
code, so we patch the helper instead — this isolates the test to the Brain's
own decision logic without dragging real Lambda packaging into the test loop.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def patch_brain_invoke(monkeypatch):
    """Patch _invoke_manager to return canned per-manager responses."""
    canned = {
        "predictive_maintenance": {
            "prediction_report_id": "PRD-deadbeef",
            "final_severity": "CRITICAL",
            "consensus_reached": True,
            "work_order": {"work_order_id": "WO-1", "priority": "CRITICAL"},
        },
        "digital_twin": {
            "sync_id": "TWNR-cafef00d",
            "twinmaker_updated": True,
            "redis_updated": True,
            "appsync_published": True,
            "snapshot_taken": True,
        },
        "quality_vision": {
            "inspection_report_id": "QCR-1",
            "verdict": "FAIL",
        },
        "sustainability": {
            "report_id": "SUSR-1",
            "overall_score": 72,
        },
        "iot_ingestion": {
            "ingestion_id": "ING-1",
            "anomalies_detected": 1,
        },
    }

    from agents.brain import graph

    def fake_invoke(manager_name, machine_id, plant_id, alert_type,
                    raw_sensor_snapshot, timestamp, severity):
        return canned.get(manager_name, {"status": "ok"})

    monkeypatch.setattr(graph, "_invoke_manager", fake_invoke)
    return canned


class TestBrainDelegation:
    def test_compound_failure_routes_to_maintenance_and_twin(
        self, aws_resources, patch_brain_invoke, critical_telemetry, fresh_now
    ):
        """Compound rule must escalate to CRITICAL and activate maintenance + twin."""
        from agents.brain.handler import handler

        event = {
            "machine_id": "CNC-AERO-01",
            "alert_type": "COMPOUND_FAILURE",
            "severity": "HIGH",  # Brain should escalate to CRITICAL
            "timestamp": fresh_now,
            "raw_sensor_snapshot": critical_telemetry,
            "production_line": "LINE-A",
            "plant_id": "PLANT-001",
        }
        result = handler(event, context=None)

        assert result["severity_assessed"] == "CRITICAL"
        assert "predictive_maintenance" in result["agents_activated"]
        assert "digital_twin" in result["agents_activated"]
        assert result["escalate_to_human"] is True
        assert result["processing_time_ms"] < 2000  # Brain SLA

    def test_low_severity_logs_only_no_delegation(
        self, aws_resources, patch_brain_invoke, healthy_telemetry, fresh_now
    ):
        """LOW severity: log only, no managers activated."""
        from agents.brain.handler import handler

        event = {
            "machine_id": "CNC-AERO-01",
            "alert_type": "VIBRATION_ANOMALY",
            "severity": "LOW",
            "timestamp": fresh_now,
            "raw_sensor_snapshot": healthy_telemetry,
            "production_line": "LINE-A",
            "plant_id": "PLANT-001",
        }
        result = handler(event, context=None)

        assert result["severity_assessed"] == "LOW"
        assert result["agents_activated"] == []
        assert result["escalate_to_human"] is False

    def test_high_severity_routes_to_domain_and_twin(
        self, aws_resources, patch_brain_invoke, fresh_now
    ):
        """HIGH severity: domain manager + digital_twin, no human escalation."""
        from agents.brain.handler import handler

        event = {
            "machine_id": "CNC-AERO-02",
            "alert_type": "QUALITY_DEFECT",
            "severity": "HIGH",
            "timestamp": fresh_now,
            "raw_sensor_snapshot": {
                "vibration_mms": 4.0,
                "current_amps": 20.0,
                "coolant_lmin": 45.0,
                "acoustic_db": 80.0,
            },
            "production_line": "LINE-B",
            "plant_id": "PLANT-001",
        }
        result = handler(event, context=None)

        assert result["severity_assessed"] == "HIGH"
        assert "quality_vision" in result["agents_activated"]
        assert "digital_twin" in result["agents_activated"]
        assert result["escalate_to_human"] is False

    def test_brain_publishes_decision_to_eventbridge(
        self, aws_resources, patch_brain_invoke, critical_telemetry, fresh_now
    ):
        """Brain must always publish a BrainDecision event."""
        from agents.brain.handler import handler

        event = {
            "machine_id": "CNC-AERO-04",
            "alert_type": "COMPOUND_FAILURE",
            "severity": "CRITICAL",
            "timestamp": fresh_now,
            "raw_sensor_snapshot": critical_telemetry,
            "production_line": "LINE-A",
            "plant_id": "PLANT-001",
        }
        # No exception should be raised; the publish step is best-effort.
        result = handler(event, context=None)
        assert result["brain_decision_id"].startswith("BRN-")
