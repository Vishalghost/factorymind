"""Work order data models for predictive maintenance."""

from typing import Optional
from pydantic import BaseModel, field_validator, model_validator


VALID_WO_STATUSES = {"OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
VALID_WO_TRANSITIONS = {
    "OPEN": {"IN_PROGRESS", "CANCELLED"},
    "IN_PROGRESS": {"COMPLETED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}
VALID_PRIORITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


class WorkOrderRecord(BaseModel):
    """DynamoDB: FactoryMind_WorkOrders (PK: work_order_id)."""

    work_order_id: str  # WO-<sequential>
    machine_id: str
    plant_id: str
    priority: str  # CRITICAL | HIGH | MEDIUM | LOW
    status: str  # OPEN | IN_PROGRESS | COMPLETED | CANCELLED
    failure_mode: str  # TOOL_WEAR, COOLANT_BLOCKAGE, BEARING_FAILURE, etc.
    predicted_by: str  # "lstm" | "lookout" | "consensus"
    probability: float
    recommended_action: str
    estimated_downtime_hours: float
    parts_required: list[str]
    scheduled_date: str
    assigned_to: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
    prediction_report_id: str  # PRD-<uuid> reference

    @field_validator("work_order_id")
    @classmethod
    def validate_work_order_id(cls, v: str) -> str:
        if not v.startswith("WO-"):
            raise ValueError(f"work_order_id must start with WO-, got: {v}")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        if v not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority: {v}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_WO_STATUSES:
            raise ValueError(f"Invalid status: {v}")
        return v

    @field_validator("estimated_downtime_hours")
    @classmethod
    def validate_downtime(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"estimated_downtime_hours must be positive, got: {v}")
        return v

    @model_validator(mode="after")
    def validate_consensus_rule(self) -> "WorkOrderRecord":
        """CRITICAL priority requires predicted_by='consensus'."""
        if self.priority == "CRITICAL" and self.predicted_by != "consensus":
            raise ValueError(
                "CRITICAL priority requires predicted_by='consensus'"
            )
        return self
