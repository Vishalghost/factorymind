"""Brain Agent Lambda handler.

Top-level LangGraph orchestrator that assesses alert severity,
queries machine history, delegates to Manager Agents, and synthesizes
unified recommendations. Publishes BrainDecision events to EventBridge.

SLA: processing_time_ms < 2000ms
ID Prefix: BRN-
"""

import time
from typing import Any

from aws_lambda_powertools import Logger, Tracer
from pydantic import BaseModel, field_validator

from agents.shared.constants import (
    PLANT_ID,
    BRAIN_EVENT_SOURCE,
)
from agents.shared.utils.id_generator import generate_brain_id
from agents.shared.utils.eventbridge import publish_event
from agents.brain.graph import build_brain_graph, BrainState

logger = Logger(service="brain-agent")
tracer = Tracer(service="brain-agent")


class BrainInput(BaseModel):
    """Input from EventBridge alert (AlertSummary from IoT Ingestion or Edge AI)."""

    machine_id: str
    alert_type: str
    severity: str
    timestamp: str
    raw_sensor_snapshot: dict[str, Any]
    production_line: str = "LINE-A"
    plant_id: str = PLANT_ID

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        if v not in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}:
            raise ValueError(f"Invalid severity: {v}")
        return v


class BrainOutput(BaseModel):
    """Output from Brain Agent decision."""

    brain_decision_id: str
    plant_id: str
    machine_id: str
    severity_assessed: str
    agents_activated: list[str]
    unified_recommendation: str
    escalate_to_human: bool
    processing_time_ms: int


@tracer.capture_lambda_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for Brain Agent.

    Accepts EventBridge events containing AlertSummary payloads.
    Runs the LangGraph state machine: assess_severity → query_machine_history
    → determine_delegation → invoke_managers → synthesize_recommendation.
    """
    start_time = time.time()
    brain_decision_id = generate_brain_id()

    # Extract detail from EventBridge envelope if present
    detail = event.get("detail", event)
    input_data = BrainInput(**detail)

    logger.info(
        "brain_processing_started",
        brain_decision_id=brain_decision_id,
        machine=input_data.machine_id,
        alert_type=input_data.alert_type,
        initial_severity=input_data.severity,
    )

    # Build and run the LangGraph state machine
    graph = build_brain_graph()

    initial_state: BrainState = {
        "brain_decision_id": brain_decision_id,
        "plant_id": input_data.plant_id,
        "machine_id": input_data.machine_id,
        "alert_type": input_data.alert_type,
        "initial_severity": input_data.severity,
        "timestamp": input_data.timestamp,
        "raw_sensor_snapshot": input_data.raw_sensor_snapshot,
        "production_line": input_data.production_line,
        "severity_assessed": input_data.severity,
        "compound_anomaly_detected": False,
        "machine_history": {},
        "delegation_targets": [],
        "escalate_to_human": False,
        "manager_results": {},
        "unified_recommendation": "",
        "agents_activated": [],
    }

    # Execute the graph
    final_state = graph.invoke(initial_state)

    processing_time_ms = int((time.time() - start_time) * 1000)

    output = BrainOutput(
        brain_decision_id=brain_decision_id,
        plant_id=input_data.plant_id,
        machine_id=input_data.machine_id,
        severity_assessed=final_state["severity_assessed"],
        agents_activated=final_state["agents_activated"],
        unified_recommendation=final_state["unified_recommendation"],
        escalate_to_human=final_state["escalate_to_human"],
        processing_time_ms=processing_time_ms,
    )

    # Publish BrainDecision event to EventBridge
    _publish_brain_decision(output, input_data.timestamp)

    logger.info(
        "brain_processing_completed",
        brain_decision_id=brain_decision_id,
        severity=output.severity_assessed,
        agents_activated=output.agents_activated,
        escalate=output.escalate_to_human,
        time_ms=processing_time_ms,
    )

    return output.model_dump()


def _publish_brain_decision(output: BrainOutput, timestamp: str) -> None:
    """Publish BrainDecision event to EventBridge (best-effort)."""
    try:
        detail = {
            "brain_decision_id": output.brain_decision_id,
            "plant_id": output.plant_id,
            "machine_id": output.machine_id,
            "severity_assessed": output.severity_assessed,
            "agents_activated": output.agents_activated,
            "unified_recommendation": output.unified_recommendation,
            "escalate_to_human": output.escalate_to_human,
            "timestamp": timestamp,
        }
        publish_event(
            source=BRAIN_EVENT_SOURCE,
            detail_type="BrainDecision",
            detail=detail,
        )
    except Exception as e:
        logger.warning("eventbridge_publish_failed", error=str(e))
