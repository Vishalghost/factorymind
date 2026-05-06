"""Timestream Worker — query 72-hour rolling sensor window.

Detects gradual trends like current increasing +0.5A/hour indicating tool wear.
"""

from typing import Any

import structlog

from agents.shared.utils.retry import with_retry
from agents.shared.constants import TOOL_WEAR_WINDOW_HOURS

logger = structlog.get_logger()

QUERY_TEMPLATE = """
SELECT machine_id, measure_name, measure_value::double, time
FROM "FactoryMindSensors"."SensorReadings"
WHERE machine_id = '{machine_id}'
  AND time > ago({window_hours}h)
ORDER BY time ASC
"""


@with_retry(max_retries=1, base_delay=0.5)
def query_sensor_history(
    machine_id: str,
    window_hours: int = TOOL_WEAR_WINDOW_HOURS,
    client: Any = None,
) -> list[dict[str, Any]]:
    """Query Timestream for rolling sensor window.

    Args:
        machine_id: CNC machine identifier.
        window_hours: Hours of history to query (default 72).
        client: Optional pre-configured Timestream Query client.

    Returns:
        List of sensor reading records from Timestream.
    """
    if client is None:
        from agents.shared.utils.aws_clients import get_timestream_query_client
        client = get_timestream_query_client()

    query = QUERY_TEMPLATE.format(
        machine_id=machine_id,
        window_hours=window_hours,
    )

    logger.info("querying_timestream", machine_id=machine_id, window_hours=window_hours)

    try:
        response = client.query(QueryString=query)
        rows = response.get("Rows", [])
        records = _parse_timestream_rows(rows)
        logger.info("timestream_query_complete", record_count=len(records))
        return records
    except Exception as e:
        logger.error("timestream_query_failed", error=str(e))
        return []


def _parse_timestream_rows(rows: list[dict]) -> list[dict[str, Any]]:
    """Parse Timestream query response rows into dicts."""
    records = []
    for row in rows:
        data = row.get("Data", [])
        if len(data) >= 4:
            records.append({
                "machine_id": data[0].get("ScalarValue", ""),
                "measure_name": data[1].get("ScalarValue", ""),
                "value": float(data[2].get("ScalarValue", 0)),
                "time": data[3].get("ScalarValue", ""),
            })
    return records
