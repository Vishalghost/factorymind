"""Sustainability monitoring data models."""

from pydantic import BaseModel, field_validator


class EnergyMetrics(BaseModel):
    """Energy consumption metrics for a CNC machine."""

    machine_id: str
    current_kwh: float
    baseline_kwh: float
    deviation_pct: float
    cost_inr: float  # Rs 7.50 per kWh


class SustainabilityKPI(BaseModel):
    """Daily sustainability KPI."""

    energy_efficiency: float  # 0.0 to 1.0
    carbon_footprint_kg: float  # 0.82 kg CO2/kWh
    waste_index: float  # 0.0 to 1.0
    overall_score: float  # Composite 0-100

    @field_validator("energy_efficiency")
    @classmethod
    def validate_efficiency(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"energy_efficiency must be 0.0-1.0, got: {v}")
        return v

    @field_validator("waste_index")
    @classmethod
    def validate_waste_index(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"waste_index must be 0.0-1.0, got: {v}")
        return v

    @field_validator("overall_score")
    @classmethod
    def validate_overall_score(cls, v: float) -> float:
        if not 0.0 <= v <= 100.0:
            raise ValueError(f"overall_score must be 0-100, got: {v}")
        return v
