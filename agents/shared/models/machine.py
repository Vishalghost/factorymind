"""Machine state data models for aerospace CNC machines."""

from typing import Optional
from pydantic import BaseModel, field_validator


VALID_STATUSES = {"RUNNING", "IDLE", "MAINTENANCE", "FAULT"}
VALID_TRANSITIONS = {
    "RUNNING": {"IDLE", "MAINTENANCE", "FAULT"},
    "IDLE": {"RUNNING", "MAINTENANCE", "FAULT"},
    "MAINTENANCE": {"RUNNING", "IDLE", "FAULT"},
    "FAULT": {"MAINTENANCE", "IDLE"},
}


class MachineStateRecord(BaseModel):
    """DynamoDB: FactoryMind_MachineState (PK: machine_id)."""

    machine_id: str  # CNC-AERO-01 through CNC-AERO-50
    plant_id: str  # PLANT-001
    machine_type: str  # CNC_MILL
    production_line: str  # LINE-A | LINE-B | LINE-C
    status: str  # RUNNING | IDLE | MAINTENANCE | FAULT
    health_score: float  # 0.0 to 1.0
    last_vibration_mms: float
    last_current_amps: float
    last_coolant_lmin: float
    last_acoustic_db: float
    last_reading_timestamp: str  # ISO 8601
    active_alerts: list[str]  # List of alert IDs
    maintenance_due_date: Optional[str] = None
    total_runtime_hours: float
    updated_at: str  # ISO 8601

    @field_validator("machine_id")
    @classmethod
    def validate_machine_id(cls, v: str) -> str:
        if not v.startswith("CNC-AERO-"):
            raise ValueError(f"machine_id must match CNC-AERO-XX, got: {v}")
        return v

    @field_validator("health_score")
    @classmethod
    def validate_health_score(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"health_score must be 0.0-1.0, got: {v}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {v}")
        return v

    @field_validator("production_line")
    @classmethod
    def validate_production_line(cls, v: str) -> str:
        if v not in {"LINE-A", "LINE-B", "LINE-C"}:
            raise ValueError(f"Invalid production_line: {v}")
        return v
