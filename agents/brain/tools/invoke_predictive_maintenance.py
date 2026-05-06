"""Lambda invoke wrapper for Predictive Maintenance Manager.

Invokes the factorymind-predictive-maintenance-manager Lambda function
with the appropriate payload format.
"""

import json
import time
from typing import Any

import structlog

from agents.shared.utils.aws_clients import get_lambda_client

logger = structlog.get_logger()

FUNCTION_NAME = "factorymind-predictive-maintenance-manager"


def invoke_predictive_maintenance(
    machine_id: str,
    plant_id: str,
    alert_type: str,
    raw_sensor_snapshot: dict[str, Any],
    timestamp: str,
    severity: str,
) -> dict[str, Any]:
    """Invoke the Predictive Maintenance Manager Lambda function.

    Args:
        machine_id: Target machine identifier (e.g., MCH-001).
        plant_id: Plant identifier (e.g., PLANT-001).
        alert_type: Type of alert triggering invocation.
        raw_sensor_snapshot: Current sensor values.
        timestamp: ISO 8601 timestamp of the event.
        severity: Assessed severity level.

    Returns:
        Response payload from the Predictive Maintenance Manager.

    Raises:
        RuntimeError: If Lambda invocation fails or returns an error.
    """
    start_ms = time.time()

    payload = {
        "plant_id": plant_id,
        "machine_id": machine_id,
        "alert_type": alert_type,
        "raw_sensor_snapshot": raw_sensor_snapshot,
        "timestamp": timestamp,
        "severity": severity,
    }

    logger.info(
        "invoking_predictive_maintenance_manager",
        function_name=FUNCTION_NAME,
        machine_id=machine_id,
        alert_type=alert_type,
    )

    client = get_lambda_client()
    response = client.invoke(
        FunctionName=FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload),
    )

    response_payload = json.loads(response["Payload"].read())
    elapsed_ms = int((time.time() - start_ms) * 1000)

    if response.get("FunctionError"):
        logger.error(
            "predictive_maintenance_invocation_failed",
            function_name=FUNCTION_NAME,
            error=response_payload,
            elapsed_ms=elapsed_ms,
        )
        raise RuntimeError(
            f"Predictive Maintenance Manager invocation failed: {response_payload}"
        )

    logger.info(
        "predictive_maintenance_invocation_complete",
        function_name=FUNCTION_NAME,
        elapsed_ms=elapsed_ms,
    )

    return response_payload
