"""Dashboard Worker — publish state changes via AppSync.

Thin wrapper kept for the Digital Twin manager's existing call signature; the
actual publish is delegated to the single shared publisher in
`agents.shared.utils.appsync` so there is one mutation shape and one env
convention (APPSYNC_URL + APPSYNC_API_KEY) across all agents.
"""

from typing import Any

import structlog

from agents.shared.utils.appsync import publish_machine_state

logger = structlog.get_logger()

APPSYNC_MUTATION = "updateMachineState"


def publish_to_appsync(
    plant_id: str,
    machine_id: str,
    state_update: dict[str, Any],
    client: Any = None,
    api_url: str | None = None,
) -> bool:
    """Delegate to the shared AppSync publisher.

    Args:
        plant_id: Plant identifier.
        machine_id: CNC machine identifier.
        state_update: Current state payload (status / health_score / last_telemetry / updated_at).
        client: Unused (kept for signature compatibility).
        api_url: Unused (the shared publisher reads APPSYNC_URL from env).

    Returns:
        True if publish succeeded, False otherwise.
    """
    return publish_machine_state(
        machine_id=machine_id,
        plant_id=plant_id,
        status=state_update.get("status", "RUNNING"),
        health_score=float(state_update.get("health_score", 1.0)),
        telemetry=state_update.get("last_telemetry", {}),
        updated_at=state_update.get("updated_at", ""),
    )
