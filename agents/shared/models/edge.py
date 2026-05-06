"""Edge AI inference data models for real-time CNC protection."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, field_validator


class EdgeClassification(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    ANOMALY = "ANOMALY"


class EdgeResultRecord(BaseModel):
    """DynamoDB: FactoryMind_EdgeResults (PK: edge_result_id)."""

    edge_result_id: str  # EDGR-<uuid>
    machine_id: str
    plant_id: str
    classification: str  # NORMAL | WARNING | ANOMALY
    confidence: float
    inference_time_ms: float  # Must be < 10ms
    sensor_values: dict  # Raw telemetry snapshot
    sliding_window_size: int  # Should be 10
    escalated: bool
    escalation_event_id: Optional[str] = None
    compound_rule_triggered: bool = False  # vibration >8.0 AND coolant <30.0
    timestamp: str

    @field_validator("edge_result_id")
    @classmethod
    def validate_edge_result_id(cls, v: str) -> str:
        if not v.startswith("EDGR-"):
            raise ValueError(f"edge_result_id must start with EDGR-, got: {v}")
        return v

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be 0.0-1.0, got: {v}")
        return v

    @field_validator("classification")
    @classmethod
    def validate_classification(cls, v: str) -> str:
        valid = {e.value for e in EdgeClassification}
        if v not in valid:
            raise ValueError(f"Invalid classification: {v}")
        return v
