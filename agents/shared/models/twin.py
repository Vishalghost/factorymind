"""Digital Twin data models."""

from typing import Any, Optional
from pydantic import BaseModel, field_validator


class MachineState(BaseModel):
    """Current state of a CNC machine in the digital twin."""

    machine_id: str
    machine_type: str  # CNC_MILL
    production_line: str
    status: str  # RUNNING | IDLE | MAINTENANCE | FAULT
    health_score: float  # 0.0 to 1.0
    last_sensor_reading: dict[str, Any]
    last_updated: str
    active_alerts: list[str]

    @field_validator("health_score")
    @classmethod
    def validate_health_score(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"health_score must be 0.0-1.0, got: {v}")
        return v


class TwinSyncInput(BaseModel):
    """Input to Digital Twin Manager."""

    plant_id: str
    machine_id: str
    state_update: dict[str, Any]
    source: str  # "iot_ingestion" | "brain_decision" | "maintenance"
    severity: Optional[str] = None


class TwinSyncOutput(BaseModel):
    """Output from Digital Twin Manager."""

    sync_id: str  # TWNR-<uuid>
    plant_id: str
    machine_id: str
    twinmaker_updated: bool
    redis_updated: bool
    appsync_published: bool
    snapshot_taken: bool  # True for CRITICAL events
    processing_time_ms: int

    @field_validator("sync_id")
    @classmethod
    def validate_sync_id(cls, v: str) -> str:
        if not v.startswith("TWNR-"):
            raise ValueError(f"sync_id must start with TWNR-, got: {v}")
        return v
