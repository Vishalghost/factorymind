"""Unit tests for shared Pydantic data models."""

import pytest
from datetime import datetime, timezone, timedelta
from pydantic import ValidationError

from agents.shared.models.sensor import SensorReading, TelemetryData, SensorMetadata
from agents.shared.models.machine import MachineStateRecord, VALID_TRANSITIONS
from agents.shared.models.events import AnomalyEvent, EventBridgeEnvelope
from agents.shared.models.work_order import WorkOrderRecord
from agents.shared.models.edge import EdgeResultRecord
from agents.shared.utils.id_generator import (
    generate_brain_id,
    generate_ingestion_id,
    generate_edge_id,
    generate_work_order_id,
)


class TestTelemetryData:
    """Tests for CNC telemetry validation."""

    def test_valid_telemetry(self):
        t = TelemetryData(
            vibration_mms=3.4,
            current_amps=18.2,
            coolant_lmin=45.1,
            acoustic_db=78.5,
        )
        assert t.vibration_mms == 3.4
        assert t.current_amps == 18.2

    def test_vibration_out_of_range(self):
        with pytest.raises(ValidationError, match="vibration_mms"):
            TelemetryData(
                vibration_mms=25.0,  # Max is 20.0
                current_amps=18.2,
                coolant_lmin=45.1,
                acoustic_db=78.5,
            )

    def test_current_out_of_range(self):
        with pytest.raises(ValidationError, match="current_amps"):
            TelemetryData(
                vibration_mms=3.4,
                current_amps=55.0,  # Max is 50.0
                coolant_lmin=45.1,
                acoustic_db=78.5,
            )

    def test_coolant_out_of_range(self):
        with pytest.raises(ValidationError, match="coolant_lmin"):
            TelemetryData(
                vibration_mms=3.4,
                current_amps=18.2,
                coolant_lmin=85.0,  # Max is 80.0
                acoustic_db=78.5,
            )

    def test_acoustic_out_of_range(self):
        with pytest.raises(ValidationError, match="acoustic_db"):
            TelemetryData(
                vibration_mms=3.4,
                current_amps=18.2,
                coolant_lmin=45.1,
                acoustic_db=125.0,  # Max is 120.0
            )

    def test_negative_values_rejected(self):
        with pytest.raises(ValidationError):
            TelemetryData(
                vibration_mms=-1.0,
                current_amps=18.2,
                coolant_lmin=45.1,
                acoustic_db=78.5,
            )


class TestSensorReading:
    """Tests for complete sensor reading validation."""

    def _make_valid_reading(self, **overrides) -> dict:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        base = {
            "reading_id": "ING-abc12345",
            "machine_id": "CNC-AERO-01",
            "timestamp": now,
            "telemetry": {
                "vibration_mms": 3.4,
                "current_amps": 18.2,
                "coolant_lmin": 45.1,
                "acoustic_db": 78.5,
            },
            "metadata": {
                "part_id": "FUS-BRACKET-992",
                "material": "Ti-6Al-4V",
                "spindle_rpm": 3500,
            },
        }
        base.update(overrides)
        return base

    def test_valid_reading(self):
        data = self._make_valid_reading()
        reading = SensorReading(**data)
        assert reading.machine_id == "CNC-AERO-01"
        assert reading.telemetry.vibration_mms == 3.4

    def test_stale_timestamp_rejected(self):
        stale_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        data = self._make_valid_reading(timestamp=stale_time)
        with pytest.raises(ValidationError, match="Stale reading"):
            SensorReading(**data)

    def test_invalid_reading_id_prefix(self):
        data = self._make_valid_reading(reading_id="BAD-abc12345")
        with pytest.raises(ValidationError, match="ING-"):
            SensorReading(**data)

    def test_invalid_machine_id_pattern(self):
        data = self._make_valid_reading(machine_id="MCH-001")
        with pytest.raises(ValidationError, match="CNC-AERO-"):
            SensorReading(**data)


class TestMachineStateRecord:
    """Tests for machine state transitions."""

    def test_valid_machine_state(self):
        record = MachineStateRecord(
            machine_id="CNC-AERO-01",
            plant_id="PLANT-001",
            machine_type="CNC_MILL",
            production_line="LINE-A",
            status="RUNNING",
            health_score=0.95,
            last_vibration_mms=3.4,
            last_current_amps=18.2,
            last_coolant_lmin=45.1,
            last_acoustic_db=78.5,
            last_reading_timestamp="2026-05-06T14:30:15Z",
            active_alerts=[],
            total_runtime_hours=1200.5,
            updated_at="2026-05-06T14:30:15Z",
        )
        assert record.status == "RUNNING"

    def test_invalid_status(self):
        with pytest.raises(ValidationError, match="Invalid status"):
            MachineStateRecord(
                machine_id="CNC-AERO-01",
                plant_id="PLANT-001",
                machine_type="CNC_MILL",
                production_line="LINE-A",
                status="BROKEN",
                health_score=0.5,
                last_vibration_mms=3.4,
                last_current_amps=18.2,
                last_coolant_lmin=45.1,
                last_acoustic_db=78.5,
                last_reading_timestamp="2026-05-06T14:30:15Z",
                active_alerts=[],
                total_runtime_hours=1200.5,
                updated_at="2026-05-06T14:30:15Z",
            )

    def test_health_score_out_of_range(self):
        with pytest.raises(ValidationError, match="health_score"):
            MachineStateRecord(
                machine_id="CNC-AERO-01",
                plant_id="PLANT-001",
                machine_type="CNC_MILL",
                production_line="LINE-A",
                status="RUNNING",
                health_score=1.5,
                last_vibration_mms=3.4,
                last_current_amps=18.2,
                last_coolant_lmin=45.1,
                last_acoustic_db=78.5,
                last_reading_timestamp="2026-05-06T14:30:15Z",
                active_alerts=[],
                total_runtime_hours=1200.5,
                updated_at="2026-05-06T14:30:15Z",
            )

    def test_valid_transitions(self):
        """Verify transition rules are correctly defined."""
        assert "IDLE" in VALID_TRANSITIONS["RUNNING"]
        assert "MAINTENANCE" in VALID_TRANSITIONS["RUNNING"]
        assert "FAULT" in VALID_TRANSITIONS["RUNNING"]
        assert "RUNNING" in VALID_TRANSITIONS["IDLE"]
        assert "MAINTENANCE" in VALID_TRANSITIONS["FAULT"]

    def test_invalid_production_line(self):
        with pytest.raises(ValidationError, match="Invalid production_line"):
            MachineStateRecord(
                machine_id="CNC-AERO-01",
                plant_id="PLANT-001",
                machine_type="CNC_MILL",
                production_line="LINE-Z",
                status="RUNNING",
                health_score=0.9,
                last_vibration_mms=3.4,
                last_current_amps=18.2,
                last_coolant_lmin=45.1,
                last_acoustic_db=78.5,
                last_reading_timestamp="2026-05-06T14:30:15Z",
                active_alerts=[],
                total_runtime_hours=1200.5,
                updated_at="2026-05-06T14:30:15Z",
            )


class TestWorkOrderRecord:
    """Tests for work order validation."""

    def test_valid_work_order(self):
        wo = WorkOrderRecord(
            work_order_id="WO-2291",
            machine_id="CNC-AERO-01",
            plant_id="PLANT-001",
            priority="HIGH",
            status="OPEN",
            failure_mode="TOOL_WEAR",
            predicted_by="lstm",
            probability=0.85,
            recommended_action="Replace end-mill before next shift",
            estimated_downtime_hours=2.0,
            parts_required=["Carbide end-mill 12mm", "Coolant filter"],
            scheduled_date="2026-05-07T06:00:00Z",
            created_at="2026-05-06T14:30:15Z",
            prediction_report_id="PRD-abc12345",
        )
        assert wo.work_order_id == "WO-2291"

    def test_critical_requires_consensus(self):
        with pytest.raises(ValidationError, match="consensus"):
            WorkOrderRecord(
                work_order_id="WO-2292",
                machine_id="CNC-AERO-01",
                plant_id="PLANT-001",
                priority="CRITICAL",
                status="OPEN",
                failure_mode="TOOL_WEAR",
                predicted_by="lstm",  # Should be "consensus" for CRITICAL
                probability=0.95,
                recommended_action="Immediate tool replacement",
                estimated_downtime_hours=4.0,
                parts_required=["Carbide end-mill 12mm"],
                scheduled_date="2026-05-07T06:00:00Z",
                created_at="2026-05-06T14:30:15Z",
                prediction_report_id="PRD-abc12345",
            )

    def test_critical_with_consensus_valid(self):
        wo = WorkOrderRecord(
            work_order_id="WO-2293",
            machine_id="CNC-AERO-01",
            plant_id="PLANT-001",
            priority="CRITICAL",
            status="OPEN",
            failure_mode="BEARING_FAILURE",
            predicted_by="consensus",
            probability=0.95,
            recommended_action="Immediate spindle bearing replacement",
            estimated_downtime_hours=8.0,
            parts_required=["Spindle bearing assembly"],
            scheduled_date="2026-05-07T06:00:00Z",
            created_at="2026-05-06T14:30:15Z",
            prediction_report_id="PRD-abc12345",
        )
        assert wo.priority == "CRITICAL"
        assert wo.predicted_by == "consensus"

    def test_negative_downtime_rejected(self):
        with pytest.raises(ValidationError, match="estimated_downtime_hours"):
            WorkOrderRecord(
                work_order_id="WO-2294",
                machine_id="CNC-AERO-01",
                plant_id="PLANT-001",
                priority="HIGH",
                status="OPEN",
                failure_mode="TOOL_WEAR",
                predicted_by="lstm",
                probability=0.85,
                recommended_action="Replace end-mill",
                estimated_downtime_hours=-1.0,
                parts_required=[],
                scheduled_date="2026-05-07T06:00:00Z",
                created_at="2026-05-06T14:30:15Z",
                prediction_report_id="PRD-abc12345",
            )


class TestIdGenerator:
    """Tests for ID generation utilities."""

    def test_brain_id_prefix(self):
        id_ = generate_brain_id()
        assert id_.startswith("BRN-")
        assert len(id_) == 12  # BRN- + 8 hex chars

    def test_ingestion_id_prefix(self):
        id_ = generate_ingestion_id()
        assert id_.startswith("ING-")

    def test_edge_id_prefix(self):
        id_ = generate_edge_id()
        assert id_.startswith("EDGR-")

    def test_work_order_id_sequential(self):
        id_ = generate_work_order_id(2291)
        assert id_ == "WO-2291"

    def test_ids_are_unique(self):
        ids = {generate_ingestion_id() for _ in range(100)}
        assert len(ids) == 100


class TestEventBridgeEnvelope:
    """Tests for EventBridge event envelope."""

    def test_valid_envelope(self):
        env = EventBridgeEnvelope(
            source="factorymind.iot.anomaly",
            detail_type="AnomalyDetected",
            detail={"machine_id": "CNC-AERO-01", "severity": "HIGH"},
        )
        assert env.event_bus_name == "factorymind-bus"

    def test_invalid_source_prefix(self):
        with pytest.raises(ValidationError, match="factorymind."):
            EventBridgeEnvelope(
                source="other.source",
                detail_type="SomeEvent",
                detail={},
            )


class TestAnomalyEvent:
    """Tests for anomaly event model."""

    def test_valid_anomaly_event(self):
        event = AnomalyEvent(
            ingestion_id="ING-abc12345",
            machine_id="CNC-AERO-01",
            alert_type="COMPOUND_FAILURE",
            severity="CRITICAL",
            anomaly_score=1.0,
            raw_sensor_snapshot={
                "vibration_mms": 12.0,
                "coolant_lmin": 10.0,
            },
            timestamp="2026-05-06T14:30:15Z",
            compound_rule_triggered=True,
        )
        assert event.compound_rule_triggered is True

    def test_anomaly_score_out_of_range(self):
        with pytest.raises(ValidationError, match="anomaly_score"):
            AnomalyEvent(
                ingestion_id="ING-abc12345",
                machine_id="CNC-AERO-01",
                alert_type="VIBRATION_ANOMALY",
                severity="HIGH",
                anomaly_score=1.5,
                raw_sensor_snapshot={},
                timestamp="2026-05-06T14:30:15Z",
            )
