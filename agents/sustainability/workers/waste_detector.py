"""Waste Detector Worker — detect idle CNC machines consuming power."""

from typing import Any

import structlog

logger = structlog.get_logger()

# Idle power threshold: if machine draws > 2 kWh while idle, it's waste
IDLE_POWER_THRESHOLD_KWH = 2.0


def detect_waste(
    energy_metrics: list[dict[str, Any]],
    machine_states: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Detect waste patterns (idle machines consuming power).

    Args:
        energy_metrics: Energy consumption metrics per machine.
        machine_states: Optional dict of machine_id → status.

    Returns:
        Waste detection results.
    """
    waste_machines = []
    total_waste_kwh = 0.0

    for metric in energy_metrics:
        machine_id = metric.get("machine_id", "")
        current_kwh = metric.get("current_kwh", 0.0)

        # Check if machine is idle but consuming significant power
        status = (machine_states or {}).get(machine_id, "UNKNOWN")
        deviation = metric.get("deviation_pct", 0.0)

        # Heuristic: high deviation with low baseline suggests idle waste
        if deviation > 20.0 and current_kwh > IDLE_POWER_THRESHOLD_KWH:
            waste_kwh = current_kwh - metric.get("baseline_kwh", 0.0)
            if waste_kwh > 0:
                waste_machines.append({
                    "machine_id": machine_id,
                    "waste_kwh": round(waste_kwh, 2),
                    "status": status,
                })
                total_waste_kwh += waste_kwh

    result = {
        "waste_machines": waste_machines,
        "total_waste_kwh": round(total_waste_kwh, 2),
        "waste_machine_count": len(waste_machines),
    }

    if waste_machines:
        logger.warning("waste_detected", count=len(waste_machines), total_kwh=total_waste_kwh)

    return result
