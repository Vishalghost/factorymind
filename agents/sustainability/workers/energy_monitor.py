"""Energy Monitor Worker — query and compare energy consumption."""

from typing import Any, Optional

import structlog

from agents.shared.utils.retry import with_retry
from agents.shared.constants import ENERGY_COST_INR_PER_KWH

logger = structlog.get_logger()


@with_retry(max_retries=1, base_delay=0.5)
def monitor_energy(
    plant_id: str,
    machine_id: Optional[str] = None,
    timestream_client: Any = None,
    dynamodb_table: Any = None,
) -> list[dict[str, Any]]:
    """Query energy consumption and compare against baselines.

    Args:
        plant_id: Plant identifier.
        machine_id: Optional specific machine (None for plant-wide).
        timestream_client: Optional Timestream client.
        dynamodb_table: Optional DynamoDB table for baselines.

    Returns:
        List of energy metric dicts per machine.
    """
    # Query current energy from Timestream
    current_readings = _query_energy_readings(plant_id, machine_id, timestream_client)

    # Get baselines from DynamoDB
    baselines = _get_baselines(plant_id, machine_id, dynamodb_table)

    # Calculate deviations
    metrics = []
    for reading in current_readings:
        mid = reading.get("machine_id", "")
        current_kwh = reading.get("power_kwh", 0.0)
        baseline_kwh = baselines.get(mid, {}).get("baseline_kwh", current_kwh)

        deviation_pct = (
            ((current_kwh - baseline_kwh) / baseline_kwh * 100)
            if baseline_kwh > 0
            else 0.0
        )

        metrics.append({
            "machine_id": mid,
            "current_kwh": current_kwh,
            "baseline_kwh": baseline_kwh,
            "deviation_pct": round(deviation_pct, 2),
            "cost_inr": round(current_kwh * ENERGY_COST_INR_PER_KWH, 2),
        })

    return metrics


def _query_energy_readings(
    plant_id: str,
    machine_id: Optional[str],
    client: Any,
) -> list[dict]:
    """Query Timestream for energy readings."""
    if client is None:
        from agents.shared.utils.aws_clients import get_timestream_query_client
        client = get_timestream_query_client()

    try:
        query = f"""
        SELECT machine_id, AVG(measure_value::double) as power_kwh
        FROM "FactoryMindSensors"."EnergyReadings"
        WHERE time > ago(1h)
        GROUP BY machine_id
        """
        response = client.query(QueryString=query)
        return [{"machine_id": "CNC-AERO-01", "power_kwh": 12.5}]  # Placeholder
    except Exception:
        return []


def _get_baselines(
    plant_id: str,
    machine_id: Optional[str],
    table: Any,
) -> dict[str, dict]:
    """Get energy baselines from DynamoDB."""
    # In production, query FactoryMind_EnergyBaselines table
    return {}
