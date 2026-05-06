"""EventBridge event models for inter-agent communication."""

from typing import Any, Optional
from pydantic import BaseModel, field_validator


class AlertSummary(BaseModel):
    """Incoming alert from IoT Ingestion or Edge AI."""

    machine_id: str  # CNC-AERO-XX
    alert_type: str  # VIBRATION_ANOMALY, CURRENT_SPIKE, COOLANT_FAILURE, ACOUSTIC_ANOMALY, COMPOUND_FAILURE
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    timestamp: str  # ISO 8601
    raw_sensor_snapshot: dict[str, Any]  # Current telemetry values
    production_line: str  # LINE-A, LINE-B, LINE-C

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        if v not in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}:
            raise ValueError(f"Invalid severity: {v}")
        return v


class AnomalyEvent(BaseModel):
    """Published to EventBridge when anomaly detected."""

    ingestion_id: str  # ING-<uuid>
    machine_id: str
    alert_type: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    anomaly_score: float  # 0.0 to 1.0
    raw_sensor_snapshot: dict[str, Any]
    timestamp: str
    compound_rule_triggered: bool = False  # True if vibration >8.0 AND coolant <30.0

    @field_validator("anomaly_score")
    @classmethod
    def validate_anomaly_score(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"anomaly_score must be 0.0-1.0, got: {v}")
        return v


class EventBridgeEnvelope(BaseModel):
    """Standard EventBridge event envelope for FactoryMind events."""

    source: str  # e.g., factorymind.brain.decision
    detail_type: str  # e.g., AnomalyDetected, BrainDecision
    detail: dict[str, Any]
    event_bus_name: str = "factorymind-bus"
    resources: list[str] = []

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        if not v.startswith("factorymind."):
            raise ValueError(f"source must start with 'factorymind.', got: {v}")
        return v


class BrainDecisionEvent(BaseModel):
    """Brain Agent decision published to EventBridge."""

    brain_decision_id: str  # BRN-<uuid>
    plant_id: str
    machine_id: str
    severity_assessed: str
    agents_activated: list[str]
    unified_recommendation: str
    escalate_to_human: bool
    timestamp: str
