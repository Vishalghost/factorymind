"""Single AppSync publisher for machine-state updates.

Fires the `updateMachineState` mutation so the dashboard's
`onMachineStateUpdated` subscription pushes to clients. Best-effort:
a no-op (returns False) if APPSYNC_URL / APPSYNC_API_KEY are unset.
"""
import json
import os
import urllib.request
from typing import Any

import structlog

logger = structlog.get_logger()

_MUTATION = (
    "mutation UpdateMachineState($input: MachineStateInput!) {\n"
    "  updateMachineState(input: $input) {\n"
    "    machine_id plant_id status health_score updated_at\n"
    "    last_telemetry { vibration_mms current_amps coolant_lmin acoustic_db }\n"
    "  }\n"
    "}"
)


def publish_machine_state(
    machine_id: str,
    plant_id: str,
    status: str,
    health_score: float,
    telemetry: dict[str, Any],
    updated_at: str,
    timeout: float = 2.0,
) -> bool:
    """Publish one machine-state update. Returns True on success, False on no-op/failure."""
    url = os.environ.get("APPSYNC_URL")
    api_key = os.environ.get("APPSYNC_API_KEY")
    if not url or not api_key:
        logger.warning("appsync_skip_no_env", machine_id=machine_id)
        return False

    body = json.dumps({
        "query": _MUTATION,
        "variables": {"input": {
            "machine_id": machine_id,
            "plant_id": plant_id,
            "status": status,
            "health_score": health_score,
            "updated_at": updated_at,
            "last_telemetry": {
                "vibration_mms": telemetry.get("vibration_mms"),
                "current_amps": telemetry.get("current_amps"),
                "coolant_lmin": telemetry.get("coolant_lmin"),
                "acoustic_db": telemetry.get("acoustic_db"),
            },
        }},
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "x-api-key": api_key},
    )
    try:
        urllib.request.urlopen(req, timeout=timeout).read()
        logger.info("appsync_published", machine_id=machine_id, status=status)
        return True
    except Exception as e:
        logger.warning("appsync_publish_failed", machine_id=machine_id, error=str(e)[:200])
        return False
