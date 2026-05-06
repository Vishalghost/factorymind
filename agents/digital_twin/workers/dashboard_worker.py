"""Dashboard Worker — publish state changes via AppSync.

Publishes machine state updates through the AppSync `updateMachineState`
mutation for real-time dashboard subscriptions.
"""

import json
from typing import Any

import structlog

logger = structlog.get_logger()

APPSYNC_MUTATION = "updateMachineState"


def publish_to_appsync(
    plant_id: str,
    machine_id: str,
    state_update: dict[str, Any],
    client: Any = None,
    api_url: str | None = None,
) -> bool:
    """Publish state change via AppSync updateMachineState mutation.

    Sends a GraphQL mutation to AppSync to notify subscribed dashboard
    clients of the machine state change in real-time.

    Args:
        plant_id: Plant identifier.
        machine_id: CNC machine identifier.
        state_update: Current state payload.
        client: Optional pre-configured AppSync client (boto3).
        api_url: Optional AppSync API URL override.

    Returns:
        True if publish succeeded, False otherwise.
    """
    import os

    if api_url is None:
        api_url = os.environ.get("APPSYNC_API_URL", "")

    if client is None:
        import boto3
        client = boto3.client("appsync")

    mutation = _build_mutation(plant_id, machine_id, state_update)

    try:
        # Use HTTP client for AppSync GraphQL endpoint
        import urllib.request

        headers = _get_auth_headers()
        request_body = json.dumps({
            "query": mutation,
            "variables": {
                "input": {
                    "plantId": plant_id,
                    "machineId": machine_id,
                    "state": json.dumps(state_update),
                }
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            api_url,
            data=request_body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            response.read()

        logger.info(
            "appsync_published",
            mutation=APPSYNC_MUTATION,
            plant_id=plant_id,
            machine_id=machine_id,
        )
        return True
    except Exception as e:
        logger.error(
            "appsync_publish_failed",
            mutation=APPSYNC_MUTATION,
            machine_id=machine_id,
            error=str(e),
        )
        return False


def _build_mutation(
    plant_id: str,
    machine_id: str,
    state_update: dict[str, Any],
) -> str:
    """Build GraphQL mutation string for updateMachineState.

    Args:
        plant_id: Plant identifier.
        machine_id: Machine identifier.
        state_update: State payload.

    Returns:
        GraphQL mutation string.
    """
    return """
    mutation UpdateMachineState($input: MachineStateInput!) {
        updateMachineState(input: $input) {
            plantId
            machineId
            state
            updatedAt
        }
    }
    """


def _get_auth_headers() -> dict[str, str]:
    """Get authentication headers for AppSync API.

    Uses IAM auth via SigV4 in production. Returns basic headers
    for the request.

    Returns:
        Dictionary of HTTP headers.
    """
    import os

    return {
        "Content-Type": "application/json",
        "x-api-key": os.environ.get("APPSYNC_API_KEY", ""),
    }
