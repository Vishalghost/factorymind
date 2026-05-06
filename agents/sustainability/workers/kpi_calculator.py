"""KPI Calculator Worker — compute sustainability KPIs."""

from typing import Any

import structlog

from agents.shared.constants import CARBON_KG_PER_KWH

logger = structlog.get_logger()


def calculate_kpis(
    energy_metrics: list[dict[str, Any]],
    waste_data: dict[str, Any],
    carbon_data: dict[str, Any],
) -> dict[str, Any]:
    """Compute sustainability KPIs.

    Args:
        energy_metrics: Energy consumption metrics per machine.
        waste_data: Waste detection results.
        carbon_data: Carbon footprint calculations.

    Returns:
        Dict with energy_efficiency, carbon_footprint_kg, waste_index, overall_score.
    """
    # Energy efficiency: ratio of baseline to actual (1.0 = perfect)
    total_current = sum(m.get("current_kwh", 0) for m in energy_metrics)
    total_baseline = sum(m.get("baseline_kwh", 0) for m in energy_metrics)

    if total_current > 0 and total_baseline > 0:
        energy_efficiency = min(1.0, total_baseline / total_current)
    else:
        energy_efficiency = 1.0

    # Carbon footprint
    carbon_footprint_kg = total_current * CARBON_KG_PER_KWH

    # Waste index: proportion of energy wasted on idle machines
    waste_kwh = waste_data.get("total_waste_kwh", 0.0)
    waste_index = min(1.0, waste_kwh / max(total_current, 1.0))

    # Overall score: weighted composite (0-100)
    overall_score = (
        energy_efficiency * 40
        + (1.0 - waste_index) * 30
        + min(1.0, 1.0 - (carbon_footprint_kg / max(total_baseline * CARBON_KG_PER_KWH, 1.0))) * 30
    )
    overall_score = max(0.0, min(100.0, overall_score))

    kpis = {
        "energy_efficiency": round(energy_efficiency, 3),
        "carbon_footprint_kg": round(carbon_footprint_kg, 2),
        "waste_index": round(waste_index, 3),
        "overall_score": round(overall_score, 1),
    }

    logger.info("kpis_calculated", **kpis)
    return kpis
