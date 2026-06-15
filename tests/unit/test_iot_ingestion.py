"""Unit tests for IoT Ingestion Manager."""

import pytest
from datetime import datetime, timezone, timedelta

from agents.iot_ingestion.workers.stream_validator import validate_reading
from agents.iot_ingestion.workers.anomaly_detector import detect_anomalies
from agents.shared.models.sensor import SensorReading


def _make_raw_reading(**overrides) -> dict:
    """Create a valid raw reading dict for testing."""
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
    for key, value in overrides.items():
        if key == "telemetry":
            base["telemetry"].update(value)
        else:
            base[key] = value
    return base


class TestStreamValidator:
    """Tests for stream_validator worker."""

    def test_valid_reading_passes(self):
        raw = _make_raw_reading()
        reading, error = validate_reading(raw)
        assert reading is not None
        assert error is None
        assert reading.machine_id == "CNC-AERO-01"

    def test_stale_timestamp_rejected(self):
        stale = (datetime.now(timezone.utc) - timedelta(seconds=120)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        raw = _make_raw_reading(timestamp=stale)
        reading, error = validate_reading(raw)
        assert reading is None
        assert "Stale" in error

    def test_vibration_above_physical_max_rejected(self):
        raw = _make_raw_reading(telemetry={"vibration_mms": 25.0})
        reading, error = validate_reading(raw)
        assert reading is None
        assert "vibration_mms" in error

    def test_current_above_physical_max_rejected(self):
        raw = _make_raw_reading(telemetry={"current_amps": 55.0})
        reading, error = validate_reading(raw)
        assert reading is None
        assert "current_amps" in error

    def test_coolant_above_physical_max_rejected(self):
        raw = _make_raw_reading(telemetry={"coolant_lmin": 85.0})
        reading, error = validate_reading(raw)
        assert reading is None
        assert "coolant_lmin" in error

    def test_acoustic_above_physical_max_rejected(self):
        raw = _make_raw_reading(telemetry={"acoustic_db": 125.0})
        reading, error = validate_reading(raw)
        assert reading is None
        assert "acoustic_db" in error

    def test_negative_values_rejected(self):
        raw = _make_raw_reading(telemetry={"vibration_mms": -1.0})
        reading, error = validate_reading(raw)
        assert reading is None

    def test_invalid_machine_id_rejected(self):
        raw = _make_raw_reading(machine_id="MCH-001")
        reading, error = validate_reading(raw)
        assert reading is None
        assert "CNC-AERO-" in error

    def test_boundary_values_accepted(self):
        """Values at exact boundaries should be accepted."""
        raw = _make_raw_reading(telemetry={
            "vibration_mms": 0.0,
            "current_amps": 50.0,
            "coolant_lmin": 0.0,
            "acoustic_db": 120.0,
        })
        reading, error = validate_reading(raw)
        assert reading is not None
        assert error is None


class TestAnomalyDetector:
    """Tests for anomaly_detector worker."""

    def _make_valid_sensor_reading(self, **telemetry_overrides) -> SensorReading:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        telemetry = {
            "vibration_mms": 3.4,
            "current_amps": 18.2,
            "coolant_lmin": 45.1,
            "acoustic_db": 78.5,
        }
        telemetry.update(telemetry_overrides)
        return SensorReading(
            reading_id="ING-abc12345",
            machine_id="CNC-AERO-01",
            timestamp=now,
            telemetry=telemetry,
            metadata={
                "part_id": "FUS-BRACKET-992",
                "material": "Ti-6Al-4V",
                "spindle_rpm": 3500,
            },
        )

    def test_normal_reading_no_anomaly(self):
        reading = self._make_valid_sensor_reading()
        result = detect_anomalies(reading, "ING-test123", publish=False)
        assert result is None

    def test_high_vibration_triggers_high(self):
        reading = self._make_valid_sensor_reading(vibration_mms=9.0)
        result = detect_anomalies(reading, "ING-test123", publish=False)
        assert result is not None
        assert result.severity == "HIGH"
        assert result.alert_type == "VIBRATION_ANOMALY"

    def test_low_coolant_triggers_critical(self):
        reading = self._make_valid_sensor_reading(coolant_lmin=25.0)
        result = detect_anomalies(reading, "ING-test123", publish=False)
        assert result is not None
        assert result.severity == "CRITICAL"
        assert result.alert_type == "COOLANT_FAILURE"

    def test_high_current_triggers_high(self):
        reading = self._make_valid_sensor_reading(current_amps=38.0)
        result = detect_anomalies(reading, "ING-test123", publish=False)
        assert result is not None
        assert result.severity == "HIGH"
        assert result.alert_type == "CURRENT_SPIKE"

    def test_high_acoustic_triggers_high(self):
        reading = self._make_valid_sensor_reading(acoustic_db=98.0)
        result = detect_anomalies(reading, "ING-test123", publish=False)
        assert result is not None
        assert result.severity == "HIGH"
        assert result.alert_type == "ACOUSTIC_ANOMALY"

    def test_compound_rule_triggers_critical(self):
        """vibration >8.0 AND coolant <30.0 → CRITICAL COMPOUND_FAILURE."""
        reading = self._make_valid_sensor_reading(
            vibration_mms=9.5,
            coolant_lmin=25.0,
        )
        result = detect_anomalies(reading, "ING-test123", publish=False)
        assert result is not None
        assert result.severity == "CRITICAL"
        assert result.alert_type == "COMPOUND_FAILURE"
        assert result.compound_rule_triggered is True
        assert result.anomaly_score == 1.0

    def test_compound_rule_not_triggered_single_condition(self):
        """Only vibration high but coolant normal → not compound."""
        reading = self._make_valid_sensor_reading(
            vibration_mms=9.5,
            coolant_lmin=45.0,  # Normal coolant
        )
        result = detect_anomalies(reading, "ING-test123", publish=False)
        assert result is not None
        assert result.alert_type == "VIBRATION_ANOMALY"
        assert result.compound_rule_triggered is False

    def test_anomaly_score_range(self):
        """Anomaly score should always be 0.0-1.0."""
        reading = self._make_valid_sensor_reading(vibration_mms=19.0)
        result = detect_anomalies(reading, "ING-test123", publish=False)
        assert result is not None
        assert 0.0 <= result.anomaly_score <= 1.0


def test_route_data_pushes_real_status(monkeypatch):
    """route_data derives real status/health and pushes it (not hardcoded RUNNING/1.0)."""
    from unittest.mock import patch
    from agents.iot_ingestion.workers.data_router import route_data

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    reading = SensorReading(
        reading_id="ING-routex", machine_id="CNC-AERO-01", timestamp=now,
        telemetry={"vibration_mms": 9.1, "current_amps": 20.0,
                   "coolant_lmin": 12.0, "acoustic_db": 80.0},
        metadata={"part_id": "P", "material": "Ti-6Al-4V", "spindle_rpm": 8400},
    )
    sent = {}

    def fake_pub(**kw):
        sent.update(kw)
        return True

    with patch("agents.iot_ingestion.workers.data_router.write_to_timestream"), \
         patch("agents.iot_ingestion.workers.data_router.update_machine_state"), \
         patch("agents.shared.utils.appsync.publish_machine_state", fake_pub):
        route_data([reading], "PLANT-001", severity_by_machine={"CNC-AERO-01": "CRITICAL"})

    assert sent["status"] == "FAULT"
    assert sent["health_score"] <= 0.2
