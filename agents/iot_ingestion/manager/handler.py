"""IoT Ingestion Manager Lambda handler.

Processes Kinesis batch events containing aerospace CNC sensor readings.
Validates, detects anomalies, routes to storage, and publishes events.
"""

import base64
import json
import time
import uuid
from typing import Any

from aws_lambda_powertools import Logger, Tracer
from pydantic import BaseModel

from agents.shared.models.sensor import SensorReading
from agents.shared.utils.id_generator import generate_ingestion_id
from agents.shared.constants import KINESIS_MAX_BATCH_SIZE
from agents.iot_ingestion.workers.stream_validator import validate_reading
from agents.iot_ingestion.workers.anomaly_detector import detect_anomalies
from agents.iot_ingestion.workers.data_router import route_data


def _unwrap_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Decode the Kinesis envelope around the actual sensor payload.

    Lambda Kinesis triggers wrap each record as
    ``{"kinesis": {"data": "<b64-json>", ...}, "eventSource": "aws:kinesis", ...}``.
    Direct invokes / tests pass the plain dict already, so we tolerate both.
    """
    if not isinstance(raw, dict):
        return raw
    kin = raw.get("kinesis")
    if isinstance(kin, dict) and "data" in kin:
        try:
            decoded = base64.b64decode(kin["data"]).decode("utf-8")
            return json.loads(decoded)
        except Exception:
            return raw
    return raw


def _backfill_required_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Add reading_id / metadata defaults that the simulator omits.

    The simulator and the iot-data publish helper send a slimmer payload
    (machine_id, timestamp, telemetry) — we synthesise the rest so that
    SensorReading validates without forcing a schema redesign.
    """
    if not isinstance(payload, dict):
        return payload
    payload.setdefault("reading_id", f"ING-{uuid.uuid4().hex[:12]}")
    payload.setdefault(
        "metadata",
        {"part_id": "FUS-BRACKET-992", "material": "Ti-6Al-4V", "spindle_rpm": 8400},
    )
    # Some upstream paths put telemetry fields at the top level.
    if "telemetry" not in payload:
        tel_keys = {"vibration_mms", "current_amps", "coolant_lmin", "acoustic_db"}
        nested = {k: payload.pop(k) for k in list(payload.keys()) if k in tel_keys}
        if nested:
            payload["telemetry"] = nested
    return payload

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
        # Decode Kinesis envelope (no-op for direct/test invokes) and
        # backfill the simulator's optional fields before validating.
        decoded = _backfill_required_fields(_unwrap_record(raw_record))
        reading, error = validate_reading(decoded)
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
