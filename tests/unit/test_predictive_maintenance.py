"""Unit tests for Predictive Maintenance Manager."""

import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from agents.predictive_maintenance.workers.timestream_worker import (
    query_sensor_history,
    _parse_timestream_rows,
    QUERY_TEMPLATE,
)
from agents.predictive_maintenance.workers.lstm_worker import predict_with_lstm
from agents.predictive_maintenance.workers.lookout_worker import (
    predict_with_lookout,
    _parse_lookout_result,
    _assess_from_snapshot,
)
from agents.predictive_maintenance.workers.scheduler_worker import apply_consensus
from agents.predictive_maintenance.workers.workorder_worker import (
    create_work_order,
    _get_parts_for_failure,
)


class TestTimestreamWorker:
    """Tests for timestream_worker — 72-hour query construction for CNC telemetry."""

    def test_query_template_contains_72_hour_window(self):
        """Query template should use 72-hour window by default."""
        query = QUERY_TEMPLATE.format(machine_id="CNC-AERO-01", window_hours=72)
        assert "ago(72h)" in query
        assert "CNC-AERO-01" in query
        assert "FactoryMindSensors" in query
        assert "SensorReadings" in query

    def test_query_template_uses_correct_table(self):
        """Query should target the correct Timestream database and table."""
        query = QUERY_TEMPLATE.format(machine_id="CNC-AERO-05", window_hours=72)
        assert '"FactoryMindSensors"."SensorReadings"' in query

    def test_query_orders_by_time_ascending(self):
        """Query should order results by time ASC for trend analysis."""
        query = QUERY_TEMPLATE.format(machine_id="CNC-AERO-01", window_hours=72)
        assert "ORDER BY time ASC" in query

    def test_query_sensor_history_returns_parsed_records(self):
        """query_sensor_history should return parsed records from Timestream."""
        mock_client = MagicMock()
        mock_client.query.return_value = {
            "Rows": [
                {
                    "Data": [
                        {"ScalarValue": "CNC-AERO-01"},
                        {"ScalarValue": "current_amps"},
                        {"ScalarValue": "18.5"},
                        {"ScalarValue": "2026-05-06T14:30:00Z"},
                    ]
                },
                {
                    "Data": [
                        {"ScalarValue": "CNC-AERO-01"},
                        {"ScalarValue": "vibration_mms"},
                        {"ScalarValue": "3.8"},
                        {"ScalarValue": "2026-05-06T14:30:00Z"},
                    ]
                },
            ]
        }

        records = query_sensor_history(
            machine_id="CNC-AERO-01", window_hours=72, client=mock_client
        )

        assert len(records) == 2
        assert records[0]["machine_id"] == "CNC-AERO-01"
        assert records[0]["measure_name"] == "current_amps"
        assert records[0]["value"] == 18.5
        assert records[1]["measure_name"] == "vibration_mms"
        assert records[1]["value"] == 3.8

    def test_query_sensor_history_empty_on_failure(self):
        """query_sensor_history should return empty list on Timestream error."""
        mock_client = MagicMock()
        mock_client.query.side_effect = Exception("Timestream unavailable")

        records = query_sensor_history(
            machine_id="CNC-AERO-01", window_hours=72, client=mock_client
        )
        assert records == []

    def test_parse_timestream_rows_handles_incomplete_data(self):
        """Rows with fewer than 4 data fields should be skipped."""
        rows = [
            {"Data": [{"ScalarValue": "CNC-AERO-01"}, {"ScalarValue": "current_amps"}]},
            {
                "Data": [
                    {"ScalarValue": "CNC-AERO-01"},
                    {"ScalarValue": "vibration_mms"},
                    {"ScalarValue": "4.2"},
                    {"ScalarValue": "2026-05-06T14:30:00Z"},
                ]
            },
        ]
        records = _parse_timestream_rows(rows)
        assert len(records) == 1
        assert records[0]["measure_name"] == "vibration_mms"

    def test_trend_detection_current_increasing_over_12_hours(self):
        """Simulate current increasing steadily over 12 hours for trend detection."""
        # Generate 12 hours of data at 1 reading per hour, current increasing by 0.5A/hour
        rows = []
        base_current = 18.0
        for hour in range(12):
            current_value = base_current + (hour * 0.5)
            rows.append(
                {
                    "Data": [
                        {"ScalarValue": "CNC-AERO-01"},
                        {"ScalarValue": "current_amps"},
                        {"ScalarValue": str(current_value)},
                        {"ScalarValue": f"2026-05-06T{hour:02d}:00:00Z"},
                    ]
                }
            )

        records = _parse_timestream_rows(rows)
        assert len(records) == 12

        # Verify the trend: first reading ~18.0, last reading ~23.5
        assert records[0]["value"] == 18.0
        assert records[-1]["value"] == 23.5

        # Verify monotonically increasing (trend detection)
        values = [r["value"] for r in records]
        for i in range(1, len(values)):
            assert values[i] > values[i - 1], "Current should be steadily increasing"


class TestLSTMWorker:
    """Tests for lstm_worker — LSTM prediction parsing."""

    def test_lstm_prediction_success(self):
        """LSTM worker should parse successful SageMaker response."""
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(
            {
                "severity": "CRITICAL",
                "failure_mode": "TOOL_WEAR",
                "probability": 0.92,
                "remaining_useful_life_hours": 8.5,
                "confidence_interval": [0.85, 0.97],
            }
        )
        mock_client.invoke_endpoint.return_value = {"Body": mock_body}

        result = predict_with_lstm(
            machine_id="CNC-AERO-01",
            sensor_history=[{"value": 18.5}],
            current_snapshot={"vibration_mms": 9.0, "current_amps": 36.0},
            client=mock_client,
        )

        assert result["model"] == "lstm"
        assert result["severity"] == "CRITICAL"
        assert result["failure_mode"] == "TOOL_WEAR"
        assert result["probability"] == 0.92
        assert result["rul_hours"] == 8.5
        assert result["confidence_interval"] == [0.85, 0.97]

    def test_lstm_prediction_low_severity(self):
        """LSTM worker should parse LOW severity response."""
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(
            {
                "severity": "LOW",
                "failure_mode": "NONE",
                "probability": 0.05,
                "remaining_useful_life_hours": 500,
                "confidence_interval": [0.01, 0.1],
            }
        )
        mock_client.invoke_endpoint.return_value = {"Body": mock_body}

        result = predict_with_lstm(
            machine_id="CNC-AERO-01",
            sensor_history=[],
            current_snapshot={"vibration_mms": 3.4, "current_amps": 18.2},
            client=mock_client,
        )

        assert result["severity"] == "LOW"
        assert result["probability"] == 0.05
        assert result["rul_hours"] == 500

    def test_lstm_prediction_failure_returns_safe_defaults(self):
        """LSTM worker should return safe defaults on SageMaker failure."""
        mock_client = MagicMock()
        mock_client.invoke_endpoint.side_effect = Exception("Endpoint unavailable")

        result = predict_with_lstm(
            machine_id="CNC-AERO-01",
            sensor_history=[],
            current_snapshot={"vibration_mms": 3.4},
            client=mock_client,
        )

        assert result["model"] == "lstm"
        assert result["severity"] == "LOW"
        assert result["failure_mode"] == "UNKNOWN"
        assert result["probability"] == 0.0
        assert result["rul_hours"] == 999

    def test_lstm_sends_last_500_readings(self):
        """LSTM worker should send at most last 500 readings to SageMaker."""
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(
            {"severity": "LOW", "failure_mode": "NONE", "probability": 0.0}
        )
        mock_client.invoke_endpoint.return_value = {"Body": mock_body}

        # Create 600 readings
        sensor_history = [{"value": i} for i in range(600)]

        predict_with_lstm(
            machine_id="CNC-AERO-01",
            sensor_history=sensor_history,
            current_snapshot={"vibration_mms": 3.4},
            client=mock_client,
        )

        # Verify the payload sent to SageMaker
        call_args = mock_client.invoke_endpoint.call_args
        body = json.loads(call_args[1]["Body"])
        assert len(body["sensor_history"]) == 500


class TestLookoutWorker:
    """Tests for lookout_worker — Lookout prediction parsing."""

    def test_lookout_prediction_from_execution(self):
        """Lookout worker should parse successful inference execution."""
        mock_client = MagicMock()
        mock_client.list_inference_executions.return_value = {
            "InferenceExecutionSummaries": [
                {
                    "Status": "SUCCESS",
                    "severity": "HIGH",
                    "failure_mode": "TOOL_WEAR",
                    "anomaly_score": 0.82,
                    "rul_hours": 24,
                }
            ]
        }

        result = predict_with_lookout(
            machine_id="CNC-AERO-01",
            sensor_history=[],
            current_snapshot={"vibration_mms": 3.4, "current_amps": 18.2, "coolant_lmin": 45.0},
            client=mock_client,
        )

        assert result["model"] == "lookout"
        assert result["severity"] == "HIGH"
        assert result["failure_mode"] == "TOOL_WEAR"
        assert result["probability"] == 0.82

    def test_lookout_fallback_to_snapshot_on_no_executions(self):
        """Lookout worker should fall back to snapshot assessment when no executions."""
        mock_client = MagicMock()
        mock_client.list_inference_executions.return_value = {
            "InferenceExecutionSummaries": []
        }

        result = predict_with_lookout(
            machine_id="CNC-AERO-01",
            sensor_history=[],
            current_snapshot={"vibration_mms": 9.0, "current_amps": 18.2, "coolant_lmin": 25.0},
            client=mock_client,
        )

        # High vibration + low coolant → COMPOUND_FAILURE CRITICAL
        assert result["model"] == "lookout"
        assert result["severity"] == "CRITICAL"
        assert result["failure_mode"] == "COMPOUND_FAILURE"

    def test_lookout_fallback_on_exception(self):
        """Lookout worker should fall back to snapshot on API error."""
        mock_client = MagicMock()
        mock_client.list_inference_executions.side_effect = Exception("API error")

        result = predict_with_lookout(
            machine_id="CNC-AERO-01",
            sensor_history=[],
            current_snapshot={"vibration_mms": 3.4, "current_amps": 18.2, "coolant_lmin": 45.0},
            client=mock_client,
        )

        assert result["model"] == "lookout"
        assert result["severity"] == "LOW"

    def test_assess_from_snapshot_critical_coolant(self):
        """Low coolant alone should trigger CRITICAL COOLANT_BLOCKAGE."""
        result = _assess_from_snapshot(
            {"vibration_mms": 3.4, "current_amps": 18.2, "coolant_lmin": 25.0}
        )
        assert result["severity"] == "CRITICAL"
        assert result["failure_mode"] == "COOLANT_BLOCKAGE"

    def test_assess_from_snapshot_high_vibration(self):
        """High vibration alone should trigger HIGH TOOL_WEAR."""
        result = _assess_from_snapshot(
            {"vibration_mms": 9.0, "current_amps": 18.2, "coolant_lmin": 45.0}
        )
        assert result["severity"] == "HIGH"
        assert result["failure_mode"] == "TOOL_WEAR"

    def test_assess_from_snapshot_high_current(self):
        """High current alone should trigger HIGH TOOL_WEAR."""
        result = _assess_from_snapshot(
            {"vibration_mms": 3.4, "current_amps": 36.0, "coolant_lmin": 45.0}
        )
        assert result["severity"] == "HIGH"
        assert result["failure_mode"] == "TOOL_WEAR"

    def test_assess_from_snapshot_normal(self):
        """Normal values should return LOW severity."""
        result = _assess_from_snapshot(
            {"vibration_mms": 3.4, "current_amps": 18.2, "coolant_lmin": 45.0}
        )
        assert result["severity"] == "LOW"
        assert result["failure_mode"] == "NONE"

    def test_parse_lookout_result_structure(self):
        """_parse_lookout_result should extract correct fields."""
        execution = {
            "Status": "SUCCESS",
            "severity": "CRITICAL",
            "failure_mode": "BEARING_FAILURE",
            "anomaly_score": 0.95,
            "rul_hours": 4,
        }
        result = _parse_lookout_result(execution)
        assert result["model"] == "lookout"
        assert result["severity"] == "CRITICAL"
        assert result["failure_mode"] == "BEARING_FAILURE"
        assert result["probability"] == 0.95
        assert result["rul_hours"] == 4


class TestSchedulerWorker:
    """Tests for scheduler_worker — consensus rule application."""

    def test_both_critical_consensus_reached(self):
        """Both CRITICAL → consensus_reached=True, final_severity=CRITICAL."""
        consensus_reached, final_severity = apply_consensus("CRITICAL", "CRITICAL")
        assert consensus_reached is True
        assert final_severity == "CRITICAL"

    def test_one_critical_lstm_no_consensus(self):
        """LSTM CRITICAL + Lookout HIGH → consensus_reached=False, final_severity=HIGH."""
        consensus_reached, final_severity = apply_consensus("CRITICAL", "HIGH")
        assert consensus_reached is False
        assert final_severity == "HIGH"

    def test_one_critical_lookout_no_consensus(self):
        """LSTM HIGH + Lookout CRITICAL → consensus_reached=False, final_severity=HIGH."""
        consensus_reached, final_severity = apply_consensus("HIGH", "CRITICAL")
        assert consensus_reached is False
        assert final_severity == "HIGH"

    def test_both_high(self):
        """Both HIGH → consensus_reached=False, final_severity=HIGH."""
        consensus_reached, final_severity = apply_consensus("HIGH", "HIGH")
        assert consensus_reached is False
        assert final_severity == "HIGH"

    def test_one_high_one_medium(self):
        """HIGH + MEDIUM → final_severity=HIGH."""
        consensus_reached, final_severity = apply_consensus("HIGH", "MEDIUM")
        assert consensus_reached is False
        assert final_severity == "HIGH"

    def test_both_medium(self):
        """Both MEDIUM → final_severity=MEDIUM."""
        consensus_reached, final_severity = apply_consensus("MEDIUM", "MEDIUM")
        assert consensus_reached is False
        assert final_severity == "MEDIUM"

    def test_both_low(self):
        """Both LOW → final_severity=LOW."""
        consensus_reached, final_severity = apply_consensus("LOW", "LOW")
        assert consensus_reached is False
        assert final_severity == "LOW"

    def test_one_medium_one_low(self):
        """MEDIUM + LOW → final_severity=MEDIUM."""
        consensus_reached, final_severity = apply_consensus("MEDIUM", "LOW")
        assert consensus_reached is False
        assert final_severity == "MEDIUM"

    def test_critical_with_low_no_consensus(self):
        """CRITICAL + LOW → consensus_reached=False, final_severity=HIGH."""
        consensus_reached, final_severity = apply_consensus("CRITICAL", "LOW")
        assert consensus_reached is False
        assert final_severity == "HIGH"


class TestWorkOrderWorker:
    """Tests for workorder_worker — work order generation and SQS publish."""

    def test_work_order_critical_has_consensus_predicted_by(self):
        """CRITICAL work order should have predicted_by='consensus'."""
        mock_sqs = MagicMock()
        mock_table = MagicMock()

        work_order = create_work_order(
            machine_id="CNC-AERO-01",
            plant_id="PLANT-001",
            priority="CRITICAL",
            failure_mode="COMPOUND_FAILURE",
            predicted_by="consensus",
            probability=0.95,
            prediction_report_id="PRD-abc12345",
            sqs_client=mock_sqs,
            dynamodb_table=mock_table,
        )

        assert work_order["predicted_by"] == "consensus"
        assert work_order["priority"] == "CRITICAL"

    def test_work_order_has_correct_fields(self):
        """Work order should contain all required fields."""
        mock_sqs = MagicMock()
        mock_table = MagicMock()

        work_order = create_work_order(
            machine_id="CNC-AERO-01",
            plant_id="PLANT-001",
            priority="HIGH",
            failure_mode="TOOL_WEAR",
            predicted_by="lstm",
            probability=0.85,
            prediction_report_id="PRD-def67890",
            sqs_client=mock_sqs,
            dynamodb_table=mock_table,
        )

        assert work_order["work_order_id"].startswith("WO-")
        assert work_order["machine_id"] == "CNC-AERO-01"
        assert work_order["plant_id"] == "PLANT-001"
        assert work_order["priority"] == "HIGH"
        assert work_order["status"] == "OPEN"
        assert work_order["failure_mode"] == "TOOL_WEAR"
        assert work_order["predicted_by"] == "lstm"
        assert work_order["probability"] == 0.85
        assert work_order["recommended_action"] != ""
        assert work_order["estimated_downtime_hours"] > 0
        assert isinstance(work_order["parts_required"], list)
        assert work_order["scheduled_date"] != ""
        assert work_order["created_at"] != ""
        assert work_order["prediction_report_id"] == "PRD-def67890"

    def test_work_order_critical_scheduled_within_1_hour(self):
        """CRITICAL work order should be scheduled within 1 hour."""
        mock_sqs = MagicMock()
        mock_table = MagicMock()

        work_order = create_work_order(
            machine_id="CNC-AERO-01",
            plant_id="PLANT-001",
            priority="CRITICAL",
            failure_mode="COMPOUND_FAILURE",
            predicted_by="consensus",
            probability=0.95,
            prediction_report_id="PRD-abc12345",
            sqs_client=mock_sqs,
            dynamodb_table=mock_table,
        )

        created = datetime.fromisoformat(work_order["created_at"])
        scheduled = datetime.fromisoformat(work_order["scheduled_date"])
        diff_hours = (scheduled - created).total_seconds() / 3600
        # CRITICAL should be scheduled within ~1 hour
        assert diff_hours <= 1.1

    def test_work_order_high_scheduled_within_8_hours(self):
        """HIGH work order should be scheduled within 8 hours (end of shift)."""
        mock_sqs = MagicMock()
        mock_table = MagicMock()

        work_order = create_work_order(
            machine_id="CNC-AERO-01",
            plant_id="PLANT-001",
            priority="HIGH",
            failure_mode="TOOL_WEAR",
            predicted_by="lstm",
            probability=0.80,
            prediction_report_id="PRD-abc12345",
            sqs_client=mock_sqs,
            dynamodb_table=mock_table,
        )

        created = datetime.fromisoformat(work_order["created_at"])
        scheduled = datetime.fromisoformat(work_order["scheduled_date"])
        diff_hours = (scheduled - created).total_seconds() / 3600
        assert diff_hours <= 8.1

    def test_work_order_critical_downtime_4_hours(self):
        """CRITICAL work order should have 4 hours estimated downtime."""
        mock_sqs = MagicMock()
        mock_table = MagicMock()

        work_order = create_work_order(
            machine_id="CNC-AERO-01",
            plant_id="PLANT-001",
            priority="CRITICAL",
            failure_mode="COMPOUND_FAILURE",
            predicted_by="consensus",
            probability=0.95,
            prediction_report_id="PRD-abc12345",
            sqs_client=mock_sqs,
            dynamodb_table=mock_table,
        )

        assert work_order["estimated_downtime_hours"] == 4.0

    def test_work_order_high_downtime_2_hours(self):
        """HIGH work order should have 2 hours estimated downtime."""
        mock_sqs = MagicMock()
        mock_table = MagicMock()

        work_order = create_work_order(
            machine_id="CNC-AERO-01",
            plant_id="PLANT-001",
            priority="HIGH",
            failure_mode="TOOL_WEAR",
            predicted_by="lstm",
            probability=0.80,
            prediction_report_id="PRD-abc12345",
            sqs_client=mock_sqs,
            dynamodb_table=mock_table,
        )

        assert work_order["estimated_downtime_hours"] == 2.0

    def test_sqs_queue_publish(self):
        """Work order should be published to SQS queue."""
        mock_sqs = MagicMock()
        mock_table = MagicMock()

        work_order = create_work_order(
            machine_id="CNC-AERO-01",
            plant_id="PLANT-001",
            priority="HIGH",
            failure_mode="TOOL_WEAR",
            predicted_by="lstm",
            probability=0.80,
            prediction_report_id="PRD-abc12345",
            sqs_client=mock_sqs,
            dynamodb_table=mock_table,
        )

        # Verify SQS send_message was called
        mock_sqs.send_message.assert_called_once()
        call_kwargs = mock_sqs.send_message.call_args[1]
        assert "factorymind-workorder-queue" in call_kwargs["QueueUrl"]

        # Verify message body contains the work order
        body = json.loads(call_kwargs["MessageBody"])
        assert body["work_order_id"] == work_order["work_order_id"]
        assert body["machine_id"] == "CNC-AERO-01"

        # Verify message attributes
        attrs = call_kwargs["MessageAttributes"]
        assert attrs["priority"]["StringValue"] == "HIGH"
        assert attrs["machine_id"]["StringValue"] == "CNC-AERO-01"

    def test_dynamodb_persist(self):
        """Work order should be persisted to DynamoDB."""
        mock_sqs = MagicMock()
        mock_table = MagicMock()

        work_order = create_work_order(
            machine_id="CNC-AERO-01",
            plant_id="PLANT-001",
            priority="HIGH",
            failure_mode="TOOL_WEAR",
            predicted_by="lstm",
            probability=0.80,
            prediction_report_id="PRD-abc12345",
            sqs_client=mock_sqs,
            dynamodb_table=mock_table,
        )

        mock_table.put_item.assert_called_once()
        put_item_kwargs = mock_table.put_item.call_args[1]
        assert put_item_kwargs["Item"]["work_order_id"] == work_order["work_order_id"]

    def test_parts_required_for_tool_wear(self):
        """TOOL_WEAR failure mode should include correct parts."""
        parts = _get_parts_for_failure("TOOL_WEAR")
        assert "Carbide end-mill 12mm" in parts
        assert "Tool holder collet" in parts

    def test_parts_required_for_compound_failure(self):
        """COMPOUND_FAILURE should include parts from multiple failure modes."""
        parts = _get_parts_for_failure("COMPOUND_FAILURE")
        assert "Carbide end-mill 12mm" in parts
        assert "Coolant filter" in parts
        assert "Spindle bearing assembly" in parts

    def test_parts_required_for_unknown_failure(self):
        """Unknown failure mode should return general maintenance kit."""
        parts = _get_parts_for_failure("UNKNOWN_FAILURE")
        assert parts == ["General maintenance kit"]


class TestNoWorkOrderForLowSeverity:
    """Tests verifying no work order is generated for MEDIUM/LOW severity."""

    def test_medium_severity_no_work_order(self):
        """MEDIUM final_severity should not generate a work order in the handler."""
        # The handler only generates work orders for CRITICAL or HIGH
        # Test the consensus rule produces MEDIUM
        consensus_reached, final_severity = apply_consensus("MEDIUM", "MEDIUM")
        assert final_severity == "MEDIUM"
        # In the handler, work_order is only created if final_severity in ("CRITICAL", "HIGH")
        assert final_severity not in ("CRITICAL", "HIGH")

    def test_low_severity_no_work_order(self):
        """LOW final_severity should not generate a work order in the handler."""
        consensus_reached, final_severity = apply_consensus("LOW", "LOW")
        assert final_severity == "LOW"
        assert final_severity not in ("CRITICAL", "HIGH")

    @patch("agents.predictive_maintenance.workers.timestream_worker.query_sensor_history")
    @patch("agents.predictive_maintenance.workers.lstm_worker.predict_with_lstm")
    @patch("agents.predictive_maintenance.workers.lookout_worker.predict_with_lookout")
    def test_handler_no_work_order_for_low(
        self, mock_lookout, mock_lstm, mock_timestream
    ):
        """Full handler should return work_order=None for LOW severity predictions."""
        mock_timestream.return_value = []
        mock_lstm.return_value = {
            "model": "lstm",
            "severity": "LOW",
            "failure_mode": "NONE",
            "probability": 0.05,
            "rul_hours": 999,
        }
        mock_lookout.return_value = {
            "model": "lookout",
            "severity": "LOW",
            "failure_mode": "NONE",
            "probability": 0.03,
            "rul_hours": 999,
        }

        from agents.predictive_maintenance.manager.handler import handler

        event = {
            "plant_id": "PLANT-001",
            "machine_id": "CNC-AERO-01",
            "alert_type": "VIBRATION_ANOMALY",
            "raw_sensor_snapshot": {
                "vibration_mms": 3.4,
                "current_amps": 18.2,
                "coolant_lmin": 45.0,
                "acoustic_db": 78.5,
            },
            "timestamp": "2026-05-06T14:30:15Z",
        }

        result = handler(event, None)

        assert result["work_order"] is None
        assert result["final_severity"] == "LOW"
        assert result["consensus_reached"] is False
