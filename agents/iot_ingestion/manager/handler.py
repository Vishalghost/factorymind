"""IoT Ingestion Manager Lambda handler.

Processes Kinesis batch events containing aerospace CNC sensor readings.
Validates, detects anomalies, routes to storage, and publishes events.
"""

import time
from typing import Any

from aws_lambda_powertools import Logger, Tracer
from pydantic import BaseModel

from agents.shared.models.sensor import SensorReading
from agents.shared.utils.id_generator import generate_ingestion_id
from agents.shared.constants import KINESIS_MAX_BATCH_SIZE
from agents.iot_ingestion.workers.stream_validator import validate_reading
from agents.iot_ingestion.workers.anomaly_detector import detect_anomalies
from agents.iot_ingestion.workers.data_router import route_data

logger = Logger(service="iot-ingestion-manager")
tracer = Tracer(service="iot-ingestion-manager")


class IngestionBatchInput(BaseModel):
    """Kinesis batch event input."""

    plant_id: str
    records: list[dict[str, Any]]  # Raw records from Kinesis


class IngestionOutput(BaseModel):
    """Output from IoT Ingestion Manager."""

    ingestion_id: str
    records_processed: int
    records_rejected: int
    anomalies_detected: int
    anomaly_events: list[dict[str, Any]]
    processing_time_ms: int


@tracer.capture_lambda_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for IoT Ingestion Manager.

    Triggered by Kinesis Data Stream with batches of up to 100 CNC sensor records.
    """
    start_time = time.time()
    ingestion_id = generate_ingestion_id()

    logger.info("ingestion_started", ingestion_id=ingestion_id)

    # Parse input records from Kinesis event
    raw_records = event.get("records", event.get("Records", []))
    plant_id = event.get("plant_id", "PLANT-001")

    records_processed = 0
    records_rejected = 0
    anomaly_events: list[dict[str, Any]] = []
    valid_readings: list[SensorReading] = []

    for raw_record in raw_records[:KINESIS_MAX_BATCH_SIZE]:
        # Validate each reading
        reading, error = validate_reading(raw_record)
        if error:
            records_rejected += 1
            logger.warning("reading_rejected", error=error, record=raw_record)
            continue

        valid_readings.append(reading)
        records_processed += 1

        # Detect anomalies on valid readings
        anomaly = detect_anomalies(reading, ingestion_id)
        if anomaly:
            anomaly_events.append(anomaly.model_dump())

    # Route valid data to storage (Timestream + DynamoDB)
    if valid_readings:
        route_data(valid_readings, plant_id)

    processing_time_ms = int((time.time() - start_time) * 1000)

    output = IngestionOutput(
        ingestion_id=ingestion_id,
        records_processed=records_processed,
        records_rejected=records_rejected,
        anomalies_detected=len(anomaly_events),
        anomaly_events=anomaly_events,
        processing_time_ms=processing_time_ms,
    )

    logger.info(
        "ingestion_completed",
        ingestion_id=ingestion_id,
        processed=records_processed,
        rejected=records_rejected,
        anomalies=len(anomaly_events),
        time_ms=processing_time_ms,
    )

    return output.model_dump()
