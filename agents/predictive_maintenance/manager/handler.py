"""Predictive Maintenance Manager Lambda handler.

Predicts CNC tool failures using LSTM + Lookout for Equipment with consensus.
Detects gradual tool wear trends (current increasing +0.5A/hour).
"""

import time
from typing import Any

from aws_lambda_powertools import Logger, Tracer
from pydantic import BaseModel

from agents.shared.utils.id_generator import generate_predictive_id
from agents.shared.constants import PLANT_ID
from agents.predictive_maintenance.workers.timestream_worker import query_sensor_history
from agents.predictive_maintenance.workers.lstm_worker import predict_with_lstm
from agents.predictive_maintenance.workers.lookout_worker import predict_with_lookout
from agents.predictive_maintenance.workers.scheduler_worker import apply_consensus
from agents.predictive_maintenance.workers.workorder_worker import create_work_order

logger = Logger(service="predictive-maintenance-manager")
tracer = Tracer(service="predictive-maintenance-manager")


class PredictiveMaintenanceInput(BaseModel):
    """Input to Predictive Maintenance Manager."""

    plant_id: str = PLANT_ID
    machine_id: str
    alert_type: str
    raw_sensor_snapshot: dict[str, Any]
    timestamp: str


class PredictiveMaintenanceOutput(BaseModel):
    """Output from Predictive Maintenance Manager."""

    prediction_report_id: str
    plant_id: str
    machine_id: str
    lstm_prediction: dict[str, Any]
    lookout_prediction: dict[str, Any]
    consensus_reached: bool
    final_severity: str
    work_order: dict[str, Any] | None
    processing_time_ms: int


@tracer.capture_lambda_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for Predictive Maintenance Manager.

    Pipeline: query history → parallel LSTM + Lookout → consensus → work order
    """
    start_time = time.time()
    prediction_id = generate_predictive_id()

    input_data = PredictiveMaintenanceInput(**event)
    logger.info("prediction_started", prediction_id=prediction_id, machine=input_data.machine_id)

    # Step 1: Query 72-hour rolling sensor window from Timestream
    sensor_history = query_sensor_history(
        machine_id=input_data.machine_id,
        window_hours=72,
    )

    # Step 2: Run LSTM and Lookout predictions (in parallel conceptually)
    lstm_result = predict_with_lstm(
        machine_id=input_data.machine_id,
        sensor_history=sensor_history,
        current_snapshot=input_data.raw_sensor_snapshot,
    )

    lookout_result = predict_with_lookout(
        machine_id=input_data.machine_id,
        sensor_history=sensor_history,
        current_snapshot=input_data.raw_sensor_snapshot,
    )

    # Step 3: Apply consensus rule
    consensus_reached, final_severity = apply_consensus(
        lstm_severity=lstm_result.get("severity", "LOW"),
        lookout_severity=lookout_result.get("severity", "LOW"),
    )

    # Step 4: Generate work order if HIGH or CRITICAL
    work_order = None
    if final_severity in ("CRITICAL", "HIGH"):
        predicted_by = "consensus" if consensus_reached else lstm_result.get("model", "lstm")
        work_order = create_work_order(
            machine_id=input_data.machine_id,
            plant_id=input_data.plant_id,
            priority=final_severity,
            failure_mode=lstm_result.get("failure_mode", "TOOL_WEAR"),
            predicted_by=predicted_by,
            probability=max(
                lstm_result.get("probability", 0.0),
                lookout_result.get("probability", 0.0),
            ),
            prediction_report_id=prediction_id,
        )

    processing_time_ms = int((time.time() - start_time) * 1000)

    output = PredictiveMaintenanceOutput(
        prediction_report_id=prediction_id,
        plant_id=input_data.plant_id,
        machine_id=input_data.machine_id,
        lstm_prediction=lstm_result,
        lookout_prediction=lookout_result,
        consensus_reached=consensus_reached,
        final_severity=final_severity,
        work_order=work_order,
        processing_time_ms=processing_time_ms,
    )

    logger.info(
        "prediction_completed",
        prediction_id=prediction_id,
        severity=final_severity,
        consensus=consensus_reached,
        time_ms=processing_time_ms,
    )
    return output.model_dump()
