---
inclusion: manual
---

# Skill: Brain Agent Orchestration with LangGraph

## When to Use
Use this skill when building or modifying the Brain Agent's LangGraph state machine, delegation logic, or decision synthesis.

## LangGraph State Machine

```python
"""
Brain Agent — LangGraph Orchestrator
Top-level decision maker for FactoryMind.
"""
import json
import uuid
import time
from typing import TypedDict, Annotated, Literal
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
import boto3
from pydantic import BaseModel

dynamodb = boto3.resource("dynamodb")
eventbridge = boto3.client("events")
lambda_client = boto3.client("lambda")


# --- State Definition ---

class BrainState(TypedDict):
    """State passed between graph nodes."""
    alert_input: dict
    machine_history: dict | None
    severity_assessed: str
    agents_to_activate: list[str]
    delegation_results: dict
    unified_recommendation: str
    escalate_to_human: bool
    brain_decision_id: str


# --- Graph Nodes ---

def assess_severity(state: BrainState) -> BrainState:
    """Read alert and determine severity level."""
    alert = state["alert_input"]["alert_summary"]
    severity = alert["severity"]
    
    # Override based on sensor values
    snapshot = alert.get("raw_sensor_snapshot", {})
    if snapshot.get("vibration_hz", 0) > 150 or snapshot.get("temperature_c", 0) > 90:
        severity = "CRITICAL"
    
    return {**state, "severity_assessed": severity}


def query_machine_history(state: BrainState) -> BrainState:
    """Query DynamoDB for machine's recent state."""
    table = dynamodb.Table("FactoryMind_MachineState")
    machine_id = state["alert_input"]["alert_summary"]["machine_id"]
    
    response = table.get_item(Key={"machine_id": machine_id})
    history = response.get("Item", {})
    
    return {**state, "machine_history": history}


def determine_delegation(state: BrainState) -> BrainState:
    """Decide which managers to activate based on severity."""
    severity = state["severity_assessed"]
    alert_type = state["alert_input"]["alert_summary"]["alert_type"]
    
    agents = []
    
    if severity == "CRITICAL":
        agents = ["maintenance_manager", "digitaltwin_manager"]
        escalate = True
    elif severity == "HIGH":
        # Route to domain-specific manager + digital twin
        if "VIBRATION" in alert_type or "TEMPERATURE" in alert_type:
            agents = ["maintenance_manager", "digitaltwin_manager"]
        elif "DEFECT" in alert_type:
            agents = ["quality_manager", "digitaltwin_manager"]
        elif "ENERGY" in alert_type:
            agents = ["sustainability_manager", "digitaltwin_manager"]
        escalate = False
    elif severity == "MEDIUM":
        if "VIBRATION" in alert_type or "TEMPERATURE" in alert_type:
            agents = ["maintenance_manager"]
        elif "DEFECT" in alert_type:
            agents = ["quality_manager"]
        elif "ENERGY" in alert_type:
            agents = ["sustainability_manager"]
        escalate = False
    else:  # LOW
        agents = []
        escalate = False
    
    return {
        **state,
        "agents_to_activate": agents,
        "escalate_to_human": escalate,
    }


def delegate_to_managers(state: BrainState) -> BrainState:
    """Invoke each selected manager agent."""
    results = {}
    
    manager_functions = {
        "maintenance_manager": "factorymind-maintenance-manager",
        "quality_manager": "factorymind-quality-manager",
        "sustainability_manager": "factorymind-sustainability-manager",
        "digitaltwin_manager": "factorymind-digitaltwin-manager",
        "iot_manager": "factorymind-iot-manager",
    }
    
    for agent_name in state["agents_to_activate"]:
        fn_name = manager_functions[agent_name]
        try:
            response = lambda_client.invoke(
                FunctionName=fn_name,
                InvocationType="RequestResponse",
                Payload=json.dumps(state["alert_input"]),
            )
            result = json.loads(response["Payload"].read())
            results[agent_name] = {"status": "COMPLETED", "summary": result}
        except Exception as e:
            # Retry once
            try:
                response = lambda_client.invoke(
                    FunctionName=fn_name,
                    InvocationType="RequestResponse",
                    Payload=json.dumps(state["alert_input"]),
                )
                result = json.loads(response["Payload"].read())
                results[agent_name] = {"status": "COMPLETED", "summary": result}
            except Exception as retry_err:
                results[agent_name] = {"status": "ERROR", "summary": str(retry_err)}
    
    return {**state, "delegation_results": results}


def synthesize_recommendation(state: BrainState) -> BrainState:
    """Combine all manager results into unified recommendation."""
    results = state["delegation_results"]
    severity = state["severity_assessed"]
    machine_id = state["alert_input"]["alert_summary"]["machine_id"]
    
    summaries = []
    for agent, result in results.items():
        if result["status"] == "COMPLETED":
            summaries.append(f"{agent}: {result['summary'].get('unified_recommendation', 'OK')}")
    
    recommendation = f"[{severity}] Machine {machine_id} — " + " | ".join(summaries)
    
    return {**state, "unified_recommendation": recommendation}


def publish_decision(state: BrainState) -> BrainState:
    """Publish final decision to EventBridge."""
    decision_id = f"BRN-{uuid.uuid4().hex[:8]}"
    
    eventbridge.put_events(Entries=[{
        "Source": "factorymind.brain",
        "DetailType": "BrainDecision",
        "Detail": json.dumps({
            "brain_decision_id": decision_id,
            "severity": state["severity_assessed"],
            "recommendation": state["unified_recommendation"],
            "escalate_to_human": state["escalate_to_human"],
            "agents_activated": state["agents_to_activate"],
        }),
        "EventBusName": "factorymind-bus",
    }])
    
    return {**state, "brain_decision_id": decision_id}


# --- Conditional Edges ---

def should_delegate(state: BrainState) -> Literal["delegate", "skip"]:
    """Only delegate if there are agents to activate."""
    if state["agents_to_activate"]:
        return "delegate"
    return "skip"


# --- Build Graph ---

def build_brain_graph() -> StateGraph:
    graph = StateGraph(BrainState)
    
    # Add nodes
    graph.add_node("assess_severity", assess_severity)
    graph.add_node("query_history", query_machine_history)
    graph.add_node("determine_delegation", determine_delegation)
    graph.add_node("delegate_to_managers", delegate_to_managers)
    graph.add_node("synthesize", synthesize_recommendation)
    graph.add_node("publish", publish_decision)
    
    # Add edges
    graph.set_entry_point("assess_severity")
    graph.add_edge("assess_severity", "query_history")
    graph.add_edge("query_history", "determine_delegation")
    graph.add_conditional_edges(
        "determine_delegation",
        should_delegate,
        {"delegate": "delegate_to_managers", "skip": "publish"},
    )
    graph.add_edge("delegate_to_managers", "synthesize")
    graph.add_edge("synthesize", "publish")
    graph.add_edge("publish", END)
    
    return graph.compile()


# --- Lambda Handler ---

brain_graph = build_brain_graph()


def handler(event: dict, context) -> dict:
    """Lambda entry point for Brain Agent."""
    start = time.time()
    
    initial_state: BrainState = {
        "alert_input": event,
        "machine_history": None,
        "severity_assessed": "",
        "agents_to_activate": [],
        "delegation_results": {},
        "unified_recommendation": "",
        "escalate_to_human": False,
        "brain_decision_id": "",
    }
    
    final_state = brain_graph.invoke(initial_state)
    
    return {
        "brain_decision_id": final_state["brain_decision_id"],
        "plant_id": event.get("plant_id", "PLANT-001"),
        "machine_id": event["alert_summary"]["machine_id"],
        "severity_assessed": final_state["severity_assessed"],
        "agents_activated": final_state["agents_to_activate"],
        "delegation_results": final_state["delegation_results"],
        "unified_recommendation": final_state["unified_recommendation"],
        "escalate_to_human": final_state["escalate_to_human"],
        "eventbridge_event_published": True,
        "processing_time_ms": int((time.time() - start) * 1000),
    }
```

## Severity Routing Rules

| Severity | Agents Activated | Human Escalation |
|----------|-----------------|------------------|
| CRITICAL | Domain Manager + Digital Twin | YES |
| HIGH | Domain Manager + Digital Twin | NO |
| MEDIUM | Domain Manager only | NO |
| LOW | None (log only) | NO |

## Testing the Brain Graph

```python
def test_critical_activates_maintenance_and_twin():
    state = brain_graph.invoke({
        "alert_input": {
            "plant_id": "PLANT-001",
            "alert_summary": {
                "machine_id": "MCH-042",
                "alert_type": "VIBRATION_ANOMALY",
                "severity": "CRITICAL",
                "raw_sensor_snapshot": {"vibration_hz": 155.0, "temperature_c": 92.0},
            }
        },
        # ... other initial state fields
    })
    assert "maintenance_manager" in state["agents_to_activate"]
    assert "digitaltwin_manager" in state["agents_to_activate"]
    assert state["escalate_to_human"] is True
```
