"""Brain Agent LangGraph state machine.

Defines the state graph with nodes:
1. assess_severity — analyze raw sensor values, detect compound anomalies
2. query_machine_history — read machine state from DynamoDB
3. determine_delegation — decide which managers to activate based on severity
4. invoke_managers — invoke the selected managers (parallel where possible)
5. synthesize_recommendation — combine results into unified recommendation

Compound anomaly rule: vibration >8.0 AND coolant <30.0 → escalate to CRITICAL

Delegation routing:
- CRITICAL → Predictive Maintenance + Digital Twin + human escalation flag
- HIGH → relevant domain manager + Digital Twin
- MEDIUM → relevant domain manager only
- LOW → log only, no delegation
"""

from typing import Any, TypedDict

from langgraph.graph import StateGraph, END

from agents.shared.constants import (
    COMPOUND_RULE_VIBRATION_THRESHOLD,
    COMPOUND_RULE_COOLANT_THRESHOLD,
    VIBRATION_ANOMALY_THRESHOLD,
    CURRENT_ANOMALY_THRESHOLD,
    COOLANT_ANOMALY_THRESHOLD,
    ACOUSTIC_ANOMALY_THRESHOLD,
)


class BrainState(TypedDict):
    """State passed through the Brain Agent LangGraph nodes."""

    brain_decision_id: str
    plant_id: str
    machine_id: str
    alert_type: str
    initial_severity: str
    timestamp: str
    raw_sensor_snapshot: dict[str, Any]
    production_line: str
    severity_assessed: str
    compound_anomaly_detected: bool
    machine_history: dict[str, Any]
    delegation_targets: list[str]
    escalate_to_human: bool
    manager_results: dict[str, Any]
    unified_recommendation: str
    agents_activated: list[str]


# --- Node implementations ---


def assess_severity(state: BrainState) -> BrainState:
    """Analyze raw sensor values and detect compound anomalies.

    Checks for compound rule: vibration >8.0 AND coolant <30.0 → CRITICAL.
    Also evaluates individual sensor thresholds to potentially escalate severity.
    """
    snapshot = state["raw_sensor_snapshot"]
    current_severity = state["initial_severity"]
    compound_detected = False

    # Sensor keys may arrive in either telemetry-canonical form (vibration_mms, current_amps,
    # coolant_lmin, acoustic_db) when escalated by Edge AI / IoT Ingestion, or in the
    # short-form aliases (vibration, current, coolant, acoustic) when the Brain Agent is
    # invoked directly. Resolve both so the compound rule fires regardless of source.
    vibration = snapshot.get("vibration_mms", snapshot.get("vibration", 0.0))
    coolant = snapshot.get(
        "coolant_lmin", snapshot.get("coolant_flow", snapshot.get("coolant", 0.0))
    )
    current = snapshot.get("current_amps", snapshot.get("current", 0.0))
    acoustic = snapshot.get("acoustic_db", snapshot.get("acoustic", 0.0))

    # Compound anomaly rule: vibration >8.0 AND coolant <30.0 → CRITICAL
    if vibration > COMPOUND_RULE_VIBRATION_THRESHOLD and coolant < COMPOUND_RULE_COOLANT_THRESHOLD:
        current_severity = "CRITICAL"
        compound_detected = True

    # Individual sensor threshold checks for severity escalation
    if current_severity != "CRITICAL":
        critical_count = 0
        if vibration > VIBRATION_ANOMALY_THRESHOLD:
            critical_count += 1
        if current > CURRENT_ANOMALY_THRESHOLD:
            critical_count += 1
        if coolant < COOLANT_ANOMALY_THRESHOLD and coolant > 0:
            critical_count += 1
        if acoustic > ACOUSTIC_ANOMALY_THRESHOLD:
            critical_count += 1

        # Multiple sensors breaching thresholds escalates severity
        if critical_count >= 2 and current_severity in ("MEDIUM", "LOW"):
            current_severity = "HIGH"

    state["severity_assessed"] = current_severity
    state["compound_anomaly_detected"] = compound_detected
    return state


def query_machine_history(state: BrainState) -> BrainState:
    """Read machine state from DynamoDB for context.

    Retrieves the current machine state to inform delegation decisions.
    Best-effort: if DynamoDB is unavailable, proceed with empty history.
    """
    try:
        from agents.shared.utils.aws_clients import get_dynamodb_resource

        dynamodb = get_dynamodb_resource()
        table = dynamodb.Table("FactoryMind_MachineState")
        response = table.get_item(Key={"machine_id": state["machine_id"]})
        state["machine_history"] = response.get("Item", {})
    except Exception:
        # Best-effort: proceed without history
        state["machine_history"] = {}

    return state


def determine_delegation(state: BrainState) -> BrainState:
    """Decide which managers to activate based on assessed severity.

    Routing rules:
    - CRITICAL → Predictive Maintenance + Digital Twin + human escalation
    - HIGH → relevant domain manager + Digital Twin
    - MEDIUM → relevant domain manager only
    - LOW → log only, no delegation
    """
    severity = state["severity_assessed"]
    alert_type = state["alert_type"]
    targets: list[str] = []
    escalate = False

    if severity == "CRITICAL":
        targets = ["predictive_maintenance", "digital_twin"]
        escalate = True
    elif severity == "HIGH":
        domain_manager = _resolve_domain_manager(alert_type)
        targets = [domain_manager, "digital_twin"]
    elif severity == "MEDIUM":
        domain_manager = _resolve_domain_manager(alert_type)
        targets = [domain_manager]
    else:
        # LOW — log only, no delegation
        targets = []

    state["delegation_targets"] = targets
    state["escalate_to_human"] = escalate
    state["agents_activated"] = targets.copy()
    return state


def invoke_managers(state: BrainState) -> BrainState:
    """Invoke the selected managers (parallel where possible).

    For each delegation target, invoke the corresponding Lambda function.
    Collects results from all managers. Best-effort: if a manager fails,
    record the error and continue with remaining managers.
    """
    targets = state["delegation_targets"]
    results: dict[str, Any] = {}

    if not targets:
        state["manager_results"] = results
        return state

    for target in targets:
        try:
            result = _invoke_manager(
                manager_name=target,
                machine_id=state["machine_id"],
                plant_id=state["plant_id"],
                alert_type=state["alert_type"],
                raw_sensor_snapshot=state["raw_sensor_snapshot"],
                timestamp=state["timestamp"],
                severity=state["severity_assessed"],
            )
            results[target] = result
        except Exception as e:
            results[target] = {"error": str(e), "status": "failed"}

    state["manager_results"] = results
    return state


def synthesize_recommendation(state: BrainState) -> BrainState:
    """Combine results from all managers into a unified recommendation.

    Builds a human-readable recommendation summarizing the assessed severity,
    activated agents, and any specific findings from manager results.
    """
    severity = state["severity_assessed"]
    machine_id = state["machine_id"]
    targets = state["delegation_targets"]
    results = state["manager_results"]
    compound = state["compound_anomaly_detected"]

    parts: list[str] = []

    # Severity header
    parts.append(f"[{severity}] Alert for {machine_id}")

    # Compound anomaly note
    if compound:
        parts.append(
            "COMPOUND ANOMALY: vibration and coolant thresholds breached simultaneously. "
            "Immediate spindle stop recommended."
        )

    # Manager results summary
    if not targets:
        parts.append("No delegation required. Event logged.")
    else:
        parts.append(f"Activated agents: {', '.join(targets)}")
        for target, result in results.items():
            if isinstance(result, dict) and result.get("status") == "failed":
                parts.append(f"  - {target}: FAILED ({result.get('error', 'unknown')})")
            elif isinstance(result, dict):
                # Summarize key findings from manager
                summary = _summarize_manager_result(target, result)
                if summary:
                    parts.append(f"  - {target}: {summary}")

    # Escalation note
    if state["escalate_to_human"]:
        parts.append("⚠️ HUMAN ESCALATION REQUIRED — notify plant operations manager.")

    state["unified_recommendation"] = " | ".join(parts)
    return state


# --- Helper functions ---


def _resolve_domain_manager(alert_type: str) -> str:
    """Map alert type to the relevant domain manager."""
    alert_to_manager = {
        "VIBRATION_ANOMALY": "predictive_maintenance",
        "CURRENT_SPIKE": "predictive_maintenance",
        "COOLANT_FAILURE": "predictive_maintenance",
        "ACOUSTIC_ANOMALY": "quality_vision",
        "COMPOUND_FAILURE": "predictive_maintenance",
        "QUALITY_DEFECT": "quality_vision",
        "ENERGY_SPIKE": "sustainability",
        "THERMAL_ANOMALY": "predictive_maintenance",
    }
    return alert_to_manager.get(alert_type, "predictive_maintenance")


def _invoke_manager(
    manager_name: str,
    machine_id: str,
    plant_id: str,
    alert_type: str,
    raw_sensor_snapshot: dict[str, Any],
    timestamp: str,
    severity: str,
) -> dict[str, Any]:
    """Invoke a manager agent Lambda function.

    In production, this invokes the Lambda function via boto3.
    Returns the manager's response payload.
    """
    import json

    from agents.shared.utils.aws_clients import get_lambda_client

    function_map = {
        "predictive_maintenance": "factorymind-predictive-maintenance-manager",
        "digital_twin": "factorymind-digital-twin-manager",
        "quality_vision": "factorymind-quality-vision-manager",
        "sustainability": "factorymind-sustainability-manager",
        "iot_ingestion": "factorymind-iot-ingestion-manager",
    }

    function_name = function_map.get(manager_name, f"factorymind-{manager_name}-manager")

    payload = {
        "machine_id": machine_id,
        "plant_id": plant_id,
        "alert_type": alert_type,
        "raw_sensor_snapshot": raw_sensor_snapshot,
        "timestamp": timestamp,
        "severity": severity,
    }

    # For digital twin, adapt payload to expected format
    if manager_name == "digital_twin":
        payload = {
            "plant_id": plant_id,
            "machine_id": machine_id,
            "state_update": raw_sensor_snapshot,
            "source": "brain_decision",
            "severity": severity,
        }

    client = get_lambda_client()
    response = client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload),
    )

    response_payload = json.loads(response["Payload"].read())
    return response_payload


def _summarize_manager_result(manager_name: str, result: dict[str, Any]) -> str:
    """Extract a brief summary from a manager's result."""
    if manager_name == "predictive_maintenance":
        severity = result.get("final_severity", "")
        consensus = result.get("consensus_reached", False)
        if severity:
            return f"severity={severity}, consensus={'yes' if consensus else 'no'}"
    elif manager_name == "digital_twin":
        synced = result.get("twinmaker_synced", False)
        return f"twin_synced={'yes' if synced else 'no'}"
    elif manager_name == "quality_vision":
        verdict = result.get("verdict", "")
        if verdict:
            return f"verdict={verdict}"
    elif manager_name == "sustainability":
        score = result.get("overall_score")
        if score is not None:
            return f"overall_score={score}"
    return ""


def build_brain_graph() -> Any:
    """Build and compile the Brain Agent LangGraph state machine.

    Graph flow:
    assess_severity → query_machine_history → determine_delegation
    → invoke_managers → synthesize_recommendation → END
    """
    graph = StateGraph(BrainState)

    # Add nodes
    graph.add_node("assess_severity", assess_severity)
    graph.add_node("query_machine_history", query_machine_history)
    graph.add_node("determine_delegation", determine_delegation)
    graph.add_node("invoke_managers", invoke_managers)
    graph.add_node("synthesize_recommendation", synthesize_recommendation)

    # Define edges (linear flow)
    graph.set_entry_point("assess_severity")
    graph.add_edge("assess_severity", "query_machine_history")
    graph.add_edge("query_machine_history", "determine_delegation")
    graph.add_edge("determine_delegation", "invoke_managers")
    graph.add_edge("invoke_managers", "synthesize_recommendation")
    graph.add_edge("synthesize_recommendation", END)

    return graph.compile()
