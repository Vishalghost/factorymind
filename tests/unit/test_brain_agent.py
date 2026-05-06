"""Unit tests for Brain Agent LangGraph state machine."""

import time
from unittest.mock import patch, MagicMock, ANY

import pytest

from agents.brain.graph import (
    BrainState,
    assess_severity,
    query_machine_history,
    determine_delegation,
    invoke_managers,
    synthesize_recommendation,
    build_brain_graph,
    _resolve_domain_manager,
)
from agents.brain.handler import BrainInput, BrainOutput, handler
from agents.shared.constants import (
    COMPOUND_RULE_VIBRATION_THRESHOLD,
    COMPOUND_RULE_COOLANT_THRESHOLD,
)


def _make_state(**overrides) -> BrainState:
    """Create a default BrainState for testing."""
    defaults: BrainState = {
        "brain_decision_id": "BRN-test1234",
        "plant_id": "PLANT-001",
        "machine_id": "CNC-AERO-01",
        "alert_type": "VIBRATION_ANOMALY",
        "initial_severity": "MEDIUM",
        "timestamp": "2024-01-15T10:30:00Z",
        "raw_sensor_snapshot": {
            "vibration": 5.0,
            "current": 20.0,
            "coolant_flow": 45.0,
            "acoustic": 80.0,
        },
        "production_line": "LINE-A",
        "severity_assessed": "MEDIUM",
        "compound_anomaly_detected": False,
        "machine_history": {},
        "delegation_targets": [],
        "escalate_to_human": False,
        "manager_results": {},
        "unified_recommendation": "",
        "agents_activated": [],
    }
    defaults.update(overrides)
    return defaults


class TestAssessSeverity:
    """Tests for severity assessment logic."""

    def test_compound_anomaly_escalates_to_critical(self):
        """Vibration >8.0 AND coolant <30.0 → CRITICAL."""
        state = _make_state(
            initial_severity="MEDIUM",
            raw_sensor_snapshot={
                "vibration": 9.5,
                "coolant_flow": 25.0,
                "current": 20.0,
                "acoustic": 80.0,
            },
        )

        result = assess_severity(state)

        assert result["severity_assessed"] == "CRITICAL"
        assert result["compound_anomaly_detected"] is True

    def test_no_compound_when_vibration_below_threshold(self):
        """Vibration <=8.0 does not trigger compound rule."""
        state = _make_state(
            initial_severity="MEDIUM",
            raw_sensor_snapshot={
                "vibration": 7.5,
                "coolant_flow": 25.0,
                "current": 20.0,
                "acoustic": 80.0,
            },
        )

        result = assess_severity(state)

        assert result["compound_anomaly_detected"] is False
        assert result["severity_assessed"] != "CRITICAL"

    def test_no_compound_when_coolant_above_threshold(self):
        """Coolant >=30.0 does not trigger compound rule."""
        state = _make_state(
            initial_severity="MEDIUM",
            raw_sensor_snapshot={
                "vibration": 9.5,
                "coolant_flow": 35.0,
                "current": 20.0,
                "acoustic": 80.0,
            },
        )

        result = assess_severity(state)

        assert result["compound_anomaly_detected"] is False

    def test_multiple_sensors_breaching_escalates_to_high(self):
        """Two or more sensors breaching thresholds escalates MEDIUM → HIGH."""
        state = _make_state(
            initial_severity="MEDIUM",
            raw_sensor_snapshot={
                "vibration": 9.0,
                "current": 36.0,
                "coolant_flow": 45.0,
                "acoustic": 80.0,
            },
        )

        result = assess_severity(state)

        assert result["severity_assessed"] == "HIGH"

    def test_normal_values_no_escalation(self):
        """Normal sensor values do not change severity."""
        state = _make_state(
            initial_severity="LOW",
            raw_sensor_snapshot={
                "vibration": 3.0,
                "current": 18.0,
                "coolant_flow": 45.0,
                "acoustic": 78.0,
            },
        )

        result = assess_severity(state)

        assert result["severity_assessed"] == "LOW"
        assert result["compound_anomaly_detected"] is False

    def test_compound_rule_exact_boundary_not_triggered(self):
        """Vibration exactly 8.0 and coolant exactly 30.0 do NOT trigger compound rule."""
        state = _make_state(
            initial_severity="MEDIUM",
            raw_sensor_snapshot={
                "vibration": 8.0,
                "coolant_flow": 30.0,
                "current": 20.0,
                "acoustic": 80.0,
            },
        )

        result = assess_severity(state)

        assert result["compound_anomaly_detected"] is False

    def test_already_critical_stays_critical(self):
        """If initial severity is CRITICAL, it stays CRITICAL."""
        state = _make_state(
            initial_severity="CRITICAL",
            severity_assessed="CRITICAL",
            raw_sensor_snapshot={
                "vibration": 3.0,
                "current": 18.0,
                "coolant_flow": 45.0,
                "acoustic": 78.0,
            },
        )

        result = assess_severity(state)

        assert result["severity_assessed"] == "CRITICAL"


class TestDetermineDelgation:
    """Tests for delegation routing logic."""

    def test_critical_delegates_to_maintenance_and_twin_with_escalation(self):
        """CRITICAL → Predictive Maintenance + Digital Twin + human escalation."""
        state = _make_state(severity_assessed="CRITICAL")

        result = determine_delegation(state)

        assert "predictive_maintenance" in result["delegation_targets"]
        assert "digital_twin" in result["delegation_targets"]
        assert result["escalate_to_human"] is True
        assert result["agents_activated"] == result["delegation_targets"]

    def test_high_delegates_to_domain_and_twin(self):
        """HIGH → relevant domain manager + Digital Twin."""
        state = _make_state(
            severity_assessed="HIGH",
            alert_type="VIBRATION_ANOMALY",
        )

        result = determine_delegation(state)

        assert "predictive_maintenance" in result["delegation_targets"]
        assert "digital_twin" in result["delegation_targets"]
        assert result["escalate_to_human"] is False

    def test_medium_delegates_to_domain_only(self):
        """MEDIUM → relevant domain manager only."""
        state = _make_state(
            severity_assessed="MEDIUM",
            alert_type="VIBRATION_ANOMALY",
        )

        result = determine_delegation(state)

        assert result["delegation_targets"] == ["predictive_maintenance"]
        assert result["escalate_to_human"] is False

    def test_low_no_delegation(self):
        """LOW → log only, no delegation."""
        state = _make_state(severity_assessed="LOW")

        result = determine_delegation(state)

        assert result["delegation_targets"] == []
        assert result["escalate_to_human"] is False
        assert result["agents_activated"] == []

    def test_acoustic_anomaly_routes_to_quality_vision(self):
        """ACOUSTIC_ANOMALY alert routes to quality_vision manager."""
        state = _make_state(
            severity_assessed="MEDIUM",
            alert_type="ACOUSTIC_ANOMALY",
        )

        result = determine_delegation(state)

        assert result["delegation_targets"] == ["quality_vision"]

    def test_energy_spike_routes_to_sustainability(self):
        """ENERGY_SPIKE alert routes to sustainability manager."""
        state = _make_state(
            severity_assessed="MEDIUM",
            alert_type="ENERGY_SPIKE",
        )

        result = determine_delegation(state)

        assert result["delegation_targets"] == ["sustainability"]


class TestInvokeManagers:
    """Tests for manager invocation logic."""

    def test_no_targets_returns_empty_results(self):
        """No delegation targets → empty manager results."""
        state = _make_state(delegation_targets=[])

        result = invoke_managers(state)

        assert result["manager_results"] == {}

    @patch("agents.brain.graph._invoke_manager")
    def test_invokes_all_targets(self, mock_invoke):
        """All delegation targets are invoked."""
        mock_invoke.return_value = {"status": "success"}
        state = _make_state(
            delegation_targets=["predictive_maintenance", "digital_twin"],
        )

        result = invoke_managers(state)

        assert mock_invoke.call_count == 2
        assert "predictive_maintenance" in result["manager_results"]
        assert "digital_twin" in result["manager_results"]

    @patch("agents.brain.graph._invoke_manager")
    def test_manager_failure_recorded_not_raised(self, mock_invoke):
        """Manager invocation failure is recorded, not raised."""
        mock_invoke.side_effect = Exception("Lambda timeout")
        state = _make_state(delegation_targets=["predictive_maintenance"])

        result = invoke_managers(state)

        assert result["manager_results"]["predictive_maintenance"]["status"] == "failed"
        assert "Lambda timeout" in result["manager_results"]["predictive_maintenance"]["error"]


class TestSynthesizeRecommendation:
    """Tests for recommendation synthesis."""

    def test_low_severity_no_delegation_message(self):
        """LOW severity produces 'no delegation required' message."""
        state = _make_state(
            severity_assessed="LOW",
            delegation_targets=[],
            manager_results={},
        )

        result = synthesize_recommendation(state)

        assert "No delegation required" in result["unified_recommendation"]

    def test_critical_with_compound_includes_spindle_stop(self):
        """CRITICAL with compound anomaly recommends spindle stop."""
        state = _make_state(
            severity_assessed="CRITICAL",
            compound_anomaly_detected=True,
            delegation_targets=["predictive_maintenance", "digital_twin"],
            agents_activated=["predictive_maintenance", "digital_twin"],
            escalate_to_human=True,
            manager_results={
                "predictive_maintenance": {"final_severity": "CRITICAL", "consensus_reached": True},
                "digital_twin": {"twinmaker_synced": True},
            },
        )

        result = synthesize_recommendation(state)

        assert "COMPOUND ANOMALY" in result["unified_recommendation"]
        assert "spindle stop" in result["unified_recommendation"]
        assert "HUMAN ESCALATION" in result["unified_recommendation"]

    def test_recommendation_includes_activated_agents(self):
        """Recommendation lists activated agents."""
        state = _make_state(
            severity_assessed="HIGH",
            delegation_targets=["predictive_maintenance", "digital_twin"],
            agents_activated=["predictive_maintenance", "digital_twin"],
            manager_results={
                "predictive_maintenance": {"final_severity": "HIGH"},
                "digital_twin": {"twinmaker_synced": True},
            },
        )

        result = synthesize_recommendation(state)

        assert "predictive_maintenance" in result["unified_recommendation"]
        assert "digital_twin" in result["unified_recommendation"]

    def test_failed_manager_noted_in_recommendation(self):
        """Failed manager invocation is noted in recommendation."""
        state = _make_state(
            severity_assessed="HIGH",
            delegation_targets=["predictive_maintenance"],
            agents_activated=["predictive_maintenance"],
            manager_results={
                "predictive_maintenance": {"status": "failed", "error": "timeout"},
            },
        )

        result = synthesize_recommendation(state)

        assert "FAILED" in result["unified_recommendation"]


class TestResolveDomainManager:
    """Tests for alert type to domain manager mapping."""

    def test_vibration_anomaly_maps_to_predictive(self):
        assert _resolve_domain_manager("VIBRATION_ANOMALY") == "predictive_maintenance"

    def test_current_spike_maps_to_predictive(self):
        assert _resolve_domain_manager("CURRENT_SPIKE") == "predictive_maintenance"

    def test_coolant_failure_maps_to_predictive(self):
        assert _resolve_domain_manager("COOLANT_FAILURE") == "predictive_maintenance"

    def test_acoustic_anomaly_maps_to_quality_vision(self):
        assert _resolve_domain_manager("ACOUSTIC_ANOMALY") == "quality_vision"

    def test_energy_spike_maps_to_sustainability(self):
        assert _resolve_domain_manager("ENERGY_SPIKE") == "sustainability"

    def test_unknown_alert_defaults_to_predictive(self):
        assert _resolve_domain_manager("UNKNOWN_TYPE") == "predictive_maintenance"


class TestBrainInput:
    """Tests for BrainInput model validation."""

    def test_valid_input(self):
        """Valid BrainInput is accepted."""
        inp = BrainInput(
            machine_id="CNC-AERO-01",
            alert_type="VIBRATION_ANOMALY",
            severity="HIGH",
            timestamp="2024-01-15T10:30:00Z",
            raw_sensor_snapshot={"vibration": 9.0},
            production_line="LINE-A",
        )
        assert inp.severity == "HIGH"

    def test_invalid_severity_rejected(self):
        """Invalid severity raises ValueError."""
        with pytest.raises(ValueError, match="Invalid severity"):
            BrainInput(
                machine_id="CNC-AERO-01",
                alert_type="VIBRATION_ANOMALY",
                severity="EXTREME",
                timestamp="2024-01-15T10:30:00Z",
                raw_sensor_snapshot={"vibration": 9.0},
            )


class TestBrainHandler:
    """Tests for the Brain Agent Lambda handler."""

    @patch("agents.brain.handler.publish_event")
    @patch("agents.brain.graph.query_machine_history")
    @patch("agents.brain.graph._invoke_manager")
    def test_handler_low_severity_no_delegation(self, mock_invoke, mock_history, mock_publish):
        """LOW severity event results in no delegation."""
        mock_history.side_effect = lambda state: state

        event = {
            "machine_id": "CNC-AERO-01",
            "alert_type": "VIBRATION_ANOMALY",
            "severity": "LOW",
            "timestamp": "2024-01-15T10:30:00Z",
            "raw_sensor_snapshot": {
                "vibration": 3.0,
                "current": 18.0,
                "coolant_flow": 45.0,
                "acoustic": 78.0,
            },
            "production_line": "LINE-A",
        }

        result = handler(event, None)

        assert result["severity_assessed"] == "LOW"
        assert result["agents_activated"] == []
        assert result["escalate_to_human"] is False
        assert result["brain_decision_id"].startswith("BRN-")
        assert "processing_time_ms" in result
        mock_invoke.assert_not_called()

    @patch("agents.brain.handler.publish_event")
    @patch("agents.brain.graph.query_machine_history")
    @patch("agents.brain.graph._invoke_manager")
    def test_handler_critical_compound_anomaly(self, mock_invoke, mock_history, mock_publish):
        """Compound anomaly escalates to CRITICAL with human escalation."""
        mock_history.side_effect = lambda state: state
        mock_invoke.return_value = {"status": "success"}

        event = {
            "machine_id": "CNC-AERO-05",
            "alert_type": "COMPOUND_FAILURE",
            "severity": "MEDIUM",
            "timestamp": "2024-01-15T10:30:00Z",
            "raw_sensor_snapshot": {
                "vibration": 9.5,
                "coolant_flow": 25.0,
                "current": 20.0,
                "acoustic": 80.0,
            },
            "production_line": "LINE-B",
        }

        result = handler(event, None)

        assert result["severity_assessed"] == "CRITICAL"
        assert result["escalate_to_human"] is True
        assert "predictive_maintenance" in result["agents_activated"]
        assert "digital_twin" in result["agents_activated"]

    @patch("agents.brain.handler.publish_event")
    @patch("agents.brain.graph.query_machine_history")
    @patch("agents.brain.graph._invoke_manager")
    def test_handler_eventbridge_envelope(self, mock_invoke, mock_history, mock_publish):
        """Handler extracts detail from EventBridge envelope."""
        mock_history.side_effect = lambda state: state

        event = {
            "source": "factorymind.iot.anomaly",
            "detail-type": "AnomalyDetected",
            "detail": {
                "machine_id": "CNC-AERO-01",
                "alert_type": "VIBRATION_ANOMALY",
                "severity": "LOW",
                "timestamp": "2024-01-15T10:30:00Z",
                "raw_sensor_snapshot": {
                    "vibration": 4.0,
                    "current": 18.0,
                    "coolant_flow": 45.0,
                    "acoustic": 78.0,
                },
                "production_line": "LINE-A",
            },
        }

        result = handler(event, None)

        assert result["machine_id"] == "CNC-AERO-01"
        assert result["brain_decision_id"].startswith("BRN-")

    @patch("agents.brain.handler.publish_event")
    @patch("agents.brain.graph.query_machine_history")
    @patch("agents.brain.graph._invoke_manager")
    def test_handler_publishes_brain_decision_event(self, mock_invoke, mock_history, mock_publish):
        """Handler publishes BrainDecision event to EventBridge."""
        mock_history.side_effect = lambda state: state

        event = {
            "machine_id": "CNC-AERO-01",
            "alert_type": "VIBRATION_ANOMALY",
            "severity": "LOW",
            "timestamp": "2024-01-15T10:30:00Z",
            "raw_sensor_snapshot": {"vibration": 3.0, "coolant_flow": 45.0},
            "production_line": "LINE-A",
        }

        handler(event, None)

        mock_publish.assert_called_once_with(
            source="factorymind.brain.decision",
            detail_type="BrainDecision",
            detail=ANY,
        )

    @patch("agents.brain.handler.publish_event")
    @patch("agents.brain.graph.query_machine_history")
    @patch("agents.brain.graph._invoke_manager")
    def test_handler_processing_time_tracked(self, mock_invoke, mock_history, mock_publish):
        """Handler includes processing_time_ms in output."""
        mock_history.side_effect = lambda state: state

        event = {
            "machine_id": "CNC-AERO-01",
            "alert_type": "VIBRATION_ANOMALY",
            "severity": "LOW",
            "timestamp": "2024-01-15T10:30:00Z",
            "raw_sensor_snapshot": {"vibration": 3.0, "coolant_flow": 45.0},
            "production_line": "LINE-A",
        }

        result = handler(event, None)

        assert "processing_time_ms" in result
        assert isinstance(result["processing_time_ms"], int)
        assert result["processing_time_ms"] >= 0


class TestBuildBrainGraph:
    """Tests for the LangGraph state machine construction."""

    def test_graph_compiles_successfully(self):
        """Brain graph compiles without errors."""
        graph = build_brain_graph()
        assert graph is not None

    @patch("agents.brain.graph.query_machine_history")
    def test_full_graph_execution_low_severity(self, mock_history):
        """Full graph execution for LOW severity produces correct output."""
        mock_history.side_effect = lambda state: state
        graph = build_brain_graph()

        initial_state: BrainState = _make_state(
            initial_severity="LOW",
            severity_assessed="LOW",
            raw_sensor_snapshot={
                "vibration": 3.0,
                "current": 18.0,
                "coolant_flow": 45.0,
                "acoustic": 78.0,
            },
        )

        result = graph.invoke(initial_state)

        assert result["severity_assessed"] == "LOW"
        assert result["delegation_targets"] == []
        assert result["escalate_to_human"] is False
        assert "No delegation required" in result["unified_recommendation"]

    @patch("agents.brain.graph._invoke_manager")
    @patch("agents.brain.graph.query_machine_history")
    def test_full_graph_execution_critical_compound(self, mock_history, mock_invoke):
        """Full graph execution for compound anomaly escalates to CRITICAL."""
        mock_history.side_effect = lambda state: state
        mock_invoke.return_value = {"status": "success"}
        graph = build_brain_graph()

        initial_state: BrainState = _make_state(
            initial_severity="MEDIUM",
            severity_assessed="MEDIUM",
            raw_sensor_snapshot={
                "vibration": 10.0,
                "current": 20.0,
                "coolant_flow": 20.0,
                "acoustic": 80.0,
            },
        )

        result = graph.invoke(initial_state)

        assert result["severity_assessed"] == "CRITICAL"
        assert result["compound_anomaly_detected"] is True
        assert result["escalate_to_human"] is True
        assert "predictive_maintenance" in result["agents_activated"]
        assert "digital_twin" in result["agents_activated"]
