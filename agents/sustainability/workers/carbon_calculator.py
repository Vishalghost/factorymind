"""Carbon Calculator Worker — compute carbon footprint and cost."""

from typing import Any

import structlog

from agents.shared.constants import CARBON_KG_PER_KWH, ENERGY_COST_INR_PER_KWH

logger = structlog.get_logger()


def calculate_carbon(
    energy_metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate carbon footprint using India grid conversion factor.

    Conversion: 0.82 kg CO2 per kWh
    Cost: Rs 7.50 per kWh

    Args:
        energy_metrics: Energy consumption metrics per machine.

    Returns:
        Carbon calculation results.
    """
    total_kwh = sum(m.get("current_kwh", 0.0) for m in energy_metrics)
    baseline_kwh = sum(m.get("baseline_kwh", 0.0) for m in energy_metrics)

    total_carbon_kg = total_kwh * CARBON_KG_PER_KWH
    baseline_carbon_kg = baseline_kwh * CARBON_KG_PER_KWH

    total_cost_inr = total_kwh * ENERGY_COST_INR_PER_KWH
    baseline_cost_inr = baseline_kwh * ENERGY_COST_INR_PER_KWH

    # Potential savings if we reduce to baseline
    excess_kwh = max(0.0, total_kwh - baseline_kwh)
    potential_savings_kg = excess_kwh * CARBON_KG_PER_KWH
    potential_cost_savings_inr = excess_kwh * ENERGY_COST_INR_PER_KWH

    result = {
        "total_kwh": round(total_kwh, 2),
        "total_carbon_kg": round(total_carbon_kg, 2),
        "total_cost_inr": round(total_cost_inr, 2),
        "baseline_carbon_kg": round(baseline_carbon_kg, 2),
        "excess_kwh": round(excess_kwh, 2),
        "potential_savings_kg": round(potential_savings_kg, 2),
        "potential_cost_savings_inr": round(potential_cost_savings_inr, 2),
    }

    logger.info("carbon_calculated", total_kg=total_carbon_kg, savings_kg=potential_savings_kg)
    return result
