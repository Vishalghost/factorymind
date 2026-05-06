"""Data Router Worker — writes validated readings to Timestream and DynamoDB.

Routes validated CNC sensor data to:
- Amazon Timestream (FactoryMindSensors.SensorReadings) for time-series analysis
- Amazon DynamoDB (FactoryMind_MachineState) for current state tracking
"""

from typing import Any

import structlog

from agents.shared.models.sensor import SensorReading
from agents.shared.utils.retry import with_retry

logger = structlog.get_logger()


@with_retry(max_retries=1, base_delay=0.5)
def write_to_timestream(
    readings: list[SensorReading],
    plant_id: str,
    client: Any = None,
) -> None:
    """Write sensor readings to Timestream.

    Args:
        readings: List of validated SensorReading objects.
        plant_id: Plant identifier.
        client: Optional pre-configured Timestream write client.
    """
    if client is None:
        from agents.shared.utils.aws_clients import get_timestream_write_client
        client = get_timestream_write_client()

    records = []
    for reading in readings:
        base_dimensions = [
            {"Name": "machine_id", "Value": reading.machine_id},
            {"Name": "plant_id", "Value": plant_id},
            {"Name": "part_id", "Value": reading.metadata.part_id},
            {"Name": "material", "Value": reading.metadata.material},
        ]

        # Write each telemetry value as a separate measure
        telemetry = reading.telemetry
        measures = [
            ("vibration_mms", str(telemetry.vibration_mms), "DOUBLE"),
            ("current_amps", str(telemetry.current_amps), "DOUBLE"),
            ("coolant_lmin", str(telemetry.coolant_lmin), "DOUBLE"),
            ("acoustic_db", str(telemetry.acoustic_db), "DOUBLE"),
        ]

        for measure_name, measure_value, measure_type in measures:
            records.append({
                "Dimensions": base_dimensions,
                "MeasureName": measure_name,
                "MeasureValue": measure_value,
                "MeasureValueType": measure_type,
                "Time": reading.timestamp,
                "TimeUnit": "MILLISECONDS",
            })

    if records:
        # Timestream accepts up to 100 records per write
        for i in range(0, len(records), 100):
            batch = records[i:i + 100]
            client.write_records(
                DatabaseName="FactoryMindSensors",
                TableName="SensorReadings",
                Records=batch,
            )

    logger.info("timestream_write_complete", record_count=len(readings))


@with_retry(max_retries=1, base_delay=0.5)
def update_machine_state(
    readings: list[SensorReading],
    plant_id: str,
    table: Any = None,
) -> None:
    """Update DynamoDB MachineState with latest readings.

    Args:
        readings: List of validated SensorReading objects.
        plant_id: Plant identifier.
        table: Optional pre-configured DynamoDB Table resource.
    """
    if table is None:
        from agents.shared.utils.aws_clients import get_dynamodb_resource
        dynamodb = get_dynamodb_resource()
        table = dynamodb.Table("FactoryMind_MachineState")

    # Group by machine_id and take the latest reading
    latest_by_machine: dict[str, SensorReading] = {}
    for reading in readings:
        existing = latest_by_machine.get(reading.machine_id)
        if existing is None or reading.timestamp > existing.timestamp:
            latest_by_machine[reading.machine_id] = reading

    from decimal import Decimal

    for machine_id, reading in latest_by_machine.items():
        telemetry_map = {
            "vibration_mms": Decimal(str(reading.telemetry.vibration_mms)),
            "current_amps": Decimal(str(reading.telemetry.current_amps)),
            "coolant_lmin": Decimal(str(reading.telemetry.coolant_lmin)),
            "acoustic_db": Decimal(str(reading.telemetry.acoustic_db)),
        }
        table.update_item(
            Key={"machine_id": machine_id},
            UpdateExpression=(
                "SET last_telemetry = :tel, "
                "last_reading_timestamp = :ts, "
                "updated_at = :ts, "
                "plant_id = :pid"
            ),
            ExpressionAttributeValues={
                ":tel": telemetry_map,
                ":ts": reading.timestamp,
                ":pid": plant_id,
            },
        )

    logger.info("dynamodb_update_complete", machines_updated=len(latest_by_machine))


def route_data(readings: list[SensorReading], plant_id: str) -> None:
    """Route validated readings to all storage targets.

    Timestream is best-effort: this workshop AWS account blocks Timestream via
    SCP, so a failure here must NOT prevent the DynamoDB write that the
    dashboard depends on. We log and continue.

    After DynamoDB is updated, we also fire the AppSync `updateMachineState`
    mutation so the dashboard's `onMachineStateUpdated` subscription gets a
    push (it's annotated `@aws_subscribe(mutations: ["updateMachineState"])`
    so it would otherwise stay silent on direct DDB writes).
    """
    try:
        write_to_timestream(readings, plant_id)
    except Exception as e:
        logger.warning("timestream_write_skipped", error=str(e)[:200])
    update_machine_state(readings, plant_id)
    try:
        publish_to_appsync(readings, plant_id)
    except Exception as e:
        logger.warning("appsync_publish_skipped", error=str(e)[:200])


def publish_to_appsync(readings: list[SensorReading], plant_id: str) -> None:
    """Fire AppSync `updateMachineState` so the subscription pushes to clients.

    Reads endpoint + key from env vars set on the Lambda configuration:
      APPSYNC_URL      — graphql endpoint
      APPSYNC_API_KEY  — daX-... key

    Best-effort: if either env var is missing, this is a no-op.
    """
    import json
    import os
    import urllib.request

    url = os.environ.get("APPSYNC_URL")
    api_key = os.environ.get("APPSYNC_API_KEY")
    if not url or not api_key:
        return

    # Take the latest reading per machine — same dedup as DynamoDB write.
    latest: dict[str, SensorReading] = {}
    for r in readings:
        existing = latest.get(r.machine_id)
        if existing is None or r.timestamp > existing.timestamp:
            latest[r.machine_id] = r

    mutation = (
        "mutation UpdateMachineState($input: MachineStateInput!) {\n"
        "  updateMachineState(input: $input) {\n"
        "    machine_id\n"
        "    plant_id\n"
        "    status\n"
        "    health_score\n"
        "    updated_at\n"
        "    last_telemetry { vibration_mms current_amps coolant_lmin acoustic_db }\n"
        "  }\n"
        "}"
    )

    for r in latest.values():
        body = json.dumps(
            {
                "query": mutation,
                "variables": {
                    "input": {
                        "machine_id": r.machine_id,
                        "plant_id": plant_id,
                        "status": "RUNNING",
                        "health_score": 1.0,
                        "updated_at": r.timestamp,
                        "last_telemetry": {
                            "vibration_mms": r.telemetry.vibration_mms,
                            "current_amps": r.telemetry.current_amps,
                            "coolant_lmin": r.telemetry.coolant_lmin,
                            "acoustic_db": r.telemetry.acoustic_db,
                        },
                    }
                },
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "x-api-key": api_key},
        )
        # 2 s timeout — IoT ingestion has a <500 ms SLA and we don't want to
        # block batch processing if AppSync is slow.
        try:
            urllib.request.urlopen(req, timeout=2).read()
        except Exception as e:
            logger.warning(
                "appsync_mutation_failed",
                machine_id=r.machine_id,
                error=str(e)[:200],
            )
