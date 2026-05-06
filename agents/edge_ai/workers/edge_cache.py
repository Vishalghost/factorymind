"""Edge Cache Worker — Redis sliding window management.

Maintains last 10 readings per CNC machine for Edge AI inference context.
Key pattern: edge:window:{machine_id}
"""

import json
from typing import Any, Optional

import structlog

from agents.shared.constants import REDIS_EDGE_WINDOW_SIZE

logger = structlog.get_logger()


def get_sliding_window(
    machine_id: str,
    redis_client: Any,
) -> list[dict[str, Any]]:
    """Retrieve the sliding window of last 10 readings from Redis.

    Args:
        machine_id: CNC machine identifier.
        redis_client: Redis client instance.

    Returns:
        List of up to 10 most recent sensor reading dicts.
    """
    key = f"edge:window:{machine_id}"
    raw_values = redis_client.lrange(key, 0, REDIS_EDGE_WINDOW_SIZE - 1)

    readings = []
    for raw in raw_values:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        readings.append(json.loads(raw))

    return readings


def update_sliding_window(
    machine_id: str,
    sensor_values: dict[str, Any],
    redis_client: Any,
) -> int:
    """Add a new reading to the sliding window (FIFO, max 10).

    Args:
        machine_id: CNC machine identifier.
        sensor_values: Current telemetry values dict.
        redis_client: Redis client instance.

    Returns:
        Current window size after update.
    """
    key = f"edge:window:{machine_id}"
    payload = json.dumps(sensor_values)

    # Push to left (newest first)
    redis_client.lpush(key, payload)
    # Trim to keep only last N readings
    redis_client.ltrim(key, 0, REDIS_EDGE_WINDOW_SIZE - 1)

    window_size = redis_client.llen(key)
    return window_size
