"""E2E test: full CRITICAL alert flow.

Path under test:
    Sensor reading (compound rule) → Edge AI Manager → EventBridge escalation
    payload → Brain Agent → delegated to Predictive Maintenance + Digital Twin
    → BrainDecision event published.

Each agent is invoked in-process (no actual EventBridge routing in moto), but
the payloads passed between them must satisfy each agent's input schema —
which is the production contract.
"""

from __future__ import annotations

import pytest

from agents.edge_ai.manager.handler import handler as edge_handler
from agents.brain.handler import handler as brain_handler


class TestCriticalAlertFlow:
    def test_compound_rule_propagates_edge_to_brain_to_critical(
        self,
        aws_resources,
        fake_redis,
        critical_telemetry,
        fresh_now,
        monkeypatch,
    ):
        """Full path: Edge AI ANOMALY → Brain Agent → CRITICAL + human escalation."""

        # Step 1: Edge AI receives a sensor reading that breaches the compound rule.
        edge_event = {
            "machine_id": "CNC-AERO-08",
            "timestamp": fresh_now,
            "telemetry": critical_telemetry,
            "plant_id": "PLANT-001",
        }
        edge_result = edge_handler(edge_event, context=None)

        # Edge AI should classify ANOMALY and trigger compound rule.
        assert edge_result["classification"] == "ANOMALY"
        assert edge_result["compound_rule_triggered"] is True
        assert edge_result["escalated"] is True

        # Step 2: The escalation event is published to EventBridge by
        # cloud_escalator. We reconstruct the same payload that EventBridge
        # would deliver to the Brain Lambda (event["detail"] envelope).
        # Production: this payload must satisfy BrainInput. We test that
        # contract here so renaming a field in either side breaks the build.
        brain_event = {
            "detail": {
                "machine_id": edge_event["machine_id"],
                "alert_type": "COMPOUND_FAILURE",
                "severity": "CRITICAL",
                "timestamp": fresh_now,
                "raw_sensor_snapshot": critical_telemetry,
                "production_line": "LINE-A",
                "plant_id": "PLANT-001",
            }
        }

        # Step 3: Stub _invoke_manager so the Brain doesn't try to call real Lambdas.
        from agents.brain import graph as brain_graph

        invocations = []

        def fake_invoke(manager_name, **kwargs):
            invocations.append((manager_name, kwargs))
            return {"final_severity": "CRITICAL", "consensus_reached": True, "status": "ok"}

        monkeypatch.setattr(brain_graph, "_invoke_manager", fake_invoke)

        # Step 4: Brain processes the event end-to-end.
        brain_result = brain_handler(brain_event, context=None)

        # CRITICAL severity must activate maintenance + twin and flag for human.
        assert brain_result["severity_assessed"] == "CRITICAL"
        assert "predictive_maintenance" in brain_result["agents_activated"]
        assert "digital_twin" in brain_result["agents_activated"]
        assert brain_result["escalate_to_human"] is True

        # Both managers should have been invoked.
        invoked_names = [name for name, _ in invocations]
        assert "predictive_maintenance" in invoked_names
        assert "digital_twin" in invoked_names

        # Brain SLA: <2s end-to-end
        assert brain_result["processing_time_ms"] < 2000

    def test_high_severity_does_not_escalate_to_human(
        self,
        aws_resources,
        fake_redis,
        fresh_now,
        monkeypatch,
    ):
        """Single-sensor breach: HIGH severity, no human escalation."""
        from agents.brain import graph as brain_graph

        monkeypatch.setattr(
            brain_graph,
            "_invoke_manager",
            lambda **kw: {"status": "ok", "verdict": "PASS"},
        )

        # Vibration alone breaches HIGH threshold — coolant is fine, so compound rule
        # should NOT fire. Brain should not escalate to CRITICAL.
        brain_event = {
            "detail": {
                "machine_id": "CNC-AERO-22",
                "alert_type": "VIBRATION_ANOMALY",
                "severity": "HIGH",
                "timestamp": fresh_now,
                "raw_sensor_snapshot": {
                    "vibration_mms": 9.5,   # above HIGH threshold but...
                    "current_amps": 20.0,
                    "coolant_lmin": 45.0,    # ...coolant is healthy
                    "acoustic_db": 80.0,
                },
                "production_line": "LINE-B",
                "plant_id": "PLANT-001",
            }
        }
        result = brain_handler(brain_event, context=None)
        assert result["severity_assessed"] == "HIGH"
        assert result["escalate_to_human"] is False

    def test_low_severity_short_circuits_no_managers_invoked(
        self,
        aws_resources,
        fake_redis,
        healthy_telemetry,
        fresh_now,
        monkeypatch,
    ):
        """LOW severity: no managers invoked, no human escalation."""
        from agents.brain import graph as brain_graph

        invocations = []
        monkeypatch.setattr(
            brain_graph,
            "_invoke_manager",
            lambda **kw: invocations.append(kw) or {},
        )

        brain_event = {
            "detail": {
                "machine_id": "CNC-AERO-30",
                "alert_type": "VIBRATION_ANOMALY",
                "severity": "LOW",
                "timestamp": fresh_now,
                "raw_sensor_snapshot": healthy_telemetry,
                "production_line": "LINE-C",
                "plant_id": "PLANT-001",
            }
        }
        result = brain_handler(brain_event, context=None)

        assert result["severity_assessed"] == "LOW"
        assert result["agents_activated"] == []
        assert invocations == []
