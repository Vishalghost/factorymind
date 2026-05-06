"""Sustainability Manager Lambda handler.

Monitors energy consumption, calculates KPIs, detects waste,
computes carbon footprint, and generates AI optimization recommendations.
"""

import time
from typing import Any

from aws_lambda_powertools import Logger, Tracer
from pydantic import BaseModel

from agents.shared.utils.id_generator import generate_sustainability_id
from agents.shared.constants import PLANT_ID
from agents.sustainability.workers.energy_monitor import monitor_energy
from agents.sustainability.workers.kpi_calculator import calculate_kpis
from agents.sustainability.workers.waste_detector import detect_waste
from agents.sustainability.workers.carbon_calculator import calculate_carbon
from agents.sustainability.workers.genai_recommender import generate_recommendations

logger = Logger(service="sustainability-manager")
tracer = Tracer(service="sustainability-manager")


class SustainabilityInput(BaseModel):
    """Input to Sustainability Manager."""

    plant_id: str = PLANT_ID
    machine_id: str | None = None
    analysis_type: str = "real_time"  # real_time | daily_report | weekly_report
    timestamp: str = ""


class SustainabilityOutput(BaseModel):
    """Output from Sustainability Manager."""

    report_id: str
    plant_id: str
    energy_metrics: list[dict[str, Any]]
    kpis: dict[str, Any]
    recommendations: list[str]
    carbon_saved_kg: float
    cost_saved_inr: float
    processing_time_ms: int


@tracer.capture_lambda_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for Sustainability Manager."""
    start_time = time.time()
    report_id = generate_sustainability_id()

    input_data = SustainabilityInput(**event)
    logger.info("sustainability_started", report_id=report_id)

    # Step 1: Monitor energy consumption
    energy_metrics = monitor_energy(input_data.plant_id, input_data.machine_id)

    # Step 2: Detect waste patterns
    waste_data = detect_waste(energy_metrics)

    # Step 3: Calculate carbon footprint
    carbon_data = calculate_carbon(energy_metrics)

    # Step 4: Calculate KPIs
    kpis = calculate_kpis(energy_metrics, waste_data, carbon_data)

    # Step 5: Generate AI recommendations
    recommendations = generate_recommendations(
        energy_metrics=energy_metrics,
        kpis=kpis,
        waste_data=waste_data,
    )

    processing_time_ms = int((time.time() - start_time) * 1000)

    output = SustainabilityOutput(
        report_id=report_id,
        plant_id=input_data.plant_id,
        energy_metrics=energy_metrics,
        kpis=kpis,
        recommendations=recommendations,
        carbon_saved_kg=carbon_data.get("potential_savings_kg", 0.0),
        cost_saved_inr=carbon_data.get("potential_cost_savings_inr", 0.0),
        processing_time_ms=processing_time_ms,
    )

    logger.info("sustainability_completed", report_id=report_id, time_ms=processing_time_ms)
    return output.model_dump()
