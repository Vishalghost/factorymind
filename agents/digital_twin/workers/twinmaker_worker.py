"""TwinMaker Worker — sync state to IoT TwinMaker workspace.

Synchronizes machine state updates to the AWS IoT TwinMaker workspace
`factorymind-workspace` for 3D visualization and scene composition.
"""

from typing import Any

import structlog

logger = structlog.get_logger()

TWINMAKER_WORKSPACE_ID = "factorymind-workspace"
COMPONENT_TYPE = "factorymind.machine.state"


def sync_to_twinmaker(
    machine_id: str,
    state_update: dict[str, Any],
    client: Any = None,
) -> bool:
    """Sync machine state to IoT TwinMaker workspace.

    Updates the entity properties in the TwinMaker workspace to reflect
    the latest machine state. Uses batch property update for efficiency.

    Args:
        machine_id: CNC machine identifier (entity ID in TwinMaker).
        state_update: State payload with current machine properties.
        client: Optional pre-configured IoT TwinMaker client.

    Returns:
        True if sync succeeded, False otherwise.
    """
    if client is None:
        import boto3
        client = boto3.client("iottwinmaker")

    # Build property entries from state update
    property_entries = _build_property_entries(state_update)

    try:
        client.update_entity(
            workspaceId=TWINMAKER_WORKSPACE_ID,
            entityId=machine_id,
            componentUpdates={
                COMPONENT_TYPE: {
                    "updateType": "UPDATE",
                    "propertyUpdates": property_entries,
                }
            },
        )
        logger.info(
            "twinmaker_synced",
            workspace=TWINMAKER_WORKSPACE_ID,
            entity=machine_id,
            properties_count=len(property_entries),
        )
        return True
    except Exception as e:
        logger.error(
            "twinmaker_sync_failed",
            workspace=TWINMAKER_WORKSPACE_ID,
            entity=machine_id,
            error=str(e),
        )
        return False


def _build_property_entries(state_update: dict[str, Any]) -> dict[str, Any]:
    """Build TwinMaker property update entries from state dict.

    Converts flat state dict into TwinMaker property value format.

    Args:
        state_update: Flat dictionary of state values.

    Returns:
        Dictionary of property updates in TwinMaker format.
    """
    entries = {}
    for key, value in state_update.items():
        if isinstance(value, bool):
            entries[key] = {
                "value": {"booleanValue": value},
            }
        elif isinstance(value, (int, float)):
            entries[key] = {
                "value": {"doubleValue": float(value)},
            }
        elif isinstance(value, str):
            entries[key] = {
                "value": {"stringValue": value},
            }
        elif isinstance(value, list):
            entries[key] = {
                "value": {"listValue": [{"stringValue": str(v)} for v in value]},
            }
    return entries
