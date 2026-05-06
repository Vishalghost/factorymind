"""EventBridge publishing utilities."""

import json
from typing import Any

import structlog

from agents.shared.constants import EVENT_BUS_NAME
from agents.shared.utils.aws_clients import get_eventbridge_client

logger = structlog.get_logger()


def publish_event(
    source: str,
    detail_type: str,
    detail: dict[str, Any],
    event_bus_name: str = EVENT_BUS_NAME,
    client: Any = None,
) -> dict[str, Any]:
    """Publish a structured event to EventBridge.

    Constructs a proper EventBridge PutEvents payload with source,
    detail-type, and JSON-serialized detail.

    Args:
        source: Event source (e.g., factorymind.brain.decision)
        detail_type: Event type (e.g., AnomalyDetected)
        detail: Event payload dictionary
        event_bus_name: Target event bus name
        client: Optional pre-configured boto3 client

    Returns:
        EventBridge PutEvents response
    """
    if client is None:
        client = get_eventbridge_client()

    entry = {
        "Source": source,
        "DetailType": detail_type,
        "Detail": json.dumps(detail),
        "EventBusName": event_bus_name,
    }

    logger.info(
        "publishing_event",
        source=source,
        detail_type=detail_type,
        event_bus=event_bus_name,
    )

    response = client.put_events(Entries=[entry])
    return response
