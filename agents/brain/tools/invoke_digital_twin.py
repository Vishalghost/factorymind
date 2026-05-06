"""Lambda invoke wrapper for Digital Twin Manager.

Invokes the factorymind-digital-twin-manager Lambda function
with the appropriate payload format. The Digital Twin Manager
expects a different payload structure (state_update instead of
raw_sensor_snapshot).
"""

import json
import time
from typing import Any

import structlog

from agents.shared.utils.aws_clients import get_lambda_client

logger = structlog.get_logger()

FUNCTION_NAME = "factorymind-digital-twin-manager"


def invoke_digital_twin(
    machine_id: str,
    plant_id: str,
    raw_sensor_snapshot: dict[str, Any],
    severity: str,
    source: str = "brain_decision",
    **kwargs: Any,
) -> dict[str, Any]:
    """Invoke the Digital Twin Manager Lambda function.

    The Digital Twin Manager expects a TwinSyncInput payload with
    state_update rather than the standard alert payload format.

    Args:
        machine_id: Target machine identifier (e.g., MCH-001).
        plant_id: Plant identifier (e.g., PLANT-001).
        raw_sensor_snapshot: Current sensor values used as state_update.
        severity: Assessed severity level.
        source: Source of the state update (default: brain_decision).
        **kwargs: Additional keyword arguments (ignored for compatibility).

    Returns:
        Response payload from the Digital Twin Manager.

    Raises:
        RuntimeError: If Lambda invocation fails or returns an error.
    """
    start_ms = time.time()

    payload = {
        "plant_id": plant_id,
        "machine_id": machine_id,
        "state_update": raw_sensor_snapshot,
        "source": source,
        "severity": severity,
    }

    logger.info(
        "invoking_digital_twin_manager",
        function_name=FUNCTION_NAME,
        machine_id=machine_id,
        severity=severity,
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
            "digital_twin_invocation_failed",
            function_name=FUNCTION_NAME,
            error=response_payload,
            elapsed_ms=elapsed_ms,
        )
        raise RuntimeError(
            f"Digital Twin Manager invocation failed: {response_payload}"
        )

    logger.info(
        "digital_twin_invocation_complete",
        function_name=FUNCTION_NAME,
        elapsed_ms=elapsed_ms,
    )

    return response_payload
