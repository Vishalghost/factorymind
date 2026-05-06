"""Bedrock AgentCore Runtime entrypoint for FactoryMind.

Hosts all three FactoryMind agents inside a single AgentCore Runtime:

  - "brain"          — LangGraph orchestrator (severity assess + delegation)
  - "sustainability" — Plant energy/KPI analysis with Claude recommendations
  - "assistant"      — Conversational GenAI Assistant for the dashboard

A single runtime dispatches by `agent_kind` in the request payload. This keeps
the deployment surface small (one image, one Runtime, one ECR repo) while
matching the multi-agent intent in `.kiro/steering/factorymind-architecture.md`.

Invocation contract (POST /invocations on the AgentCore-managed HTTP server):

    { "agent_kind": "brain" | "sustainability" | "assistant", ...kind-specific }

Stream processors (IoT Ingestion, Edge AI) and the synchronous workers
(Quality Vision, Predictive Maintenance, Digital Twin) intentionally remain
as Lambdas — their SLAs (<10ms, <500ms) and event-driven triggers make
AgentCore Runtime the wrong shape for them.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from aws_lambda_powertools import Logger

# ``bedrock_agentcore`` is the AWS-published SDK that exposes
# ``BedrockAgentCoreApp`` — it stands up an HTTP server with ``/invocations``
# and ``/ping`` endpoints, dispatching to ``@app.entrypoint`` callables.
from bedrock_agentcore.runtime import BedrockAgentCoreApp

logger = Logger(service="factorymind-agentcore")
app = BedrockAgentCoreApp()


# --- Brain Agent ---------------------------------------------------------


def _run_brain(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the Brain Agent's LangGraph state machine on ``payload``.

    Re-uses the existing graph definition unchanged — only the host changes.
    """
    from agents.brain.graph import build_brain_graph
    from agents.shared.constants import PLANT_ID
    from agents.shared.utils.id_generator import generate_brain_id

    start = time.time()
    decision_id = generate_brain_id()
    detail = payload.get("detail", payload)

    initial_state = {
        "brain_decision_id": decision_id,
        "plant_id": detail.get("plant_id", PLANT_ID),
        "machine_id": detail["machine_id"],
        "alert_type": detail.get("alert_type", "UNSPECIFIED"),
        "initial_severity": detail.get("severity", "MEDIUM"),
        "timestamp": detail.get("timestamp", ""),
        "raw_sensor_snapshot": detail.get("raw_sensor_snapshot", {}),
        "production_line": detail.get("production_line", "LINE-A"),
        "severity_assessed": detail.get("severity", "MEDIUM"),
        "compound_anomaly_detected": False,
        "machine_history": {},
        "delegation_targets": [],
        "escalate_to_human": False,
        "manager_results": {},
        "unified_recommendation": "",
        "agents_activated": [],
    }

    graph = build_brain_graph()
    final = graph.invoke(initial_state)

    return {
        "brain_decision_id": decision_id,
        "plant_id": final["plant_id"],
        "machine_id": final["machine_id"],
        "severity_assessed": final["severity_assessed"],
        "agents_activated": final["agents_activated"],
        "unified_recommendation": final["unified_recommendation"],
        "escalate_to_human": final["escalate_to_human"],
        "processing_time_ms": int((time.time() - start) * 1000),
    }


# --- Sustainability Agent ------------------------------------------------


def _run_sustainability(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the Sustainability Manager pipeline on ``payload``.

    Calls the existing worker chain (energy_monitor → waste_detector →
    carbon_calculator → kpi_calculator → genai_recommender). The recommender
    invokes Bedrock Claude, optionally augmenting with the Knowledge Base
    when ``KNOWLEDGE_BASE_ID`` is set.
    """
    from agents.shared.constants import PLANT_ID
    from agents.shared.utils.id_generator import generate_sustainability_id
    from agents.sustainability.workers.carbon_calculator import calculate_carbon
    from agents.sustainability.workers.energy_monitor import monitor_energy
    from agents.sustainability.workers.genai_recommender import generate_recommendations
    from agents.sustainability.workers.kpi_calculator import calculate_kpis
    from agents.sustainability.workers.waste_detector import detect_waste

    start = time.time()
    report_id = generate_sustainability_id()
    plant_id = payload.get("plant_id", PLANT_ID)
    machine_id = payload.get("machine_id")

    energy_metrics = monitor_energy(plant_id, machine_id)
    waste_data = detect_waste(energy_metrics)
    carbon_data = calculate_carbon(energy_metrics)
    kpis = calculate_kpis(energy_metrics, waste_data, carbon_data)
    recommendations = generate_recommendations(
        energy_metrics=energy_metrics,
        kpis=kpis,
        waste_data=waste_data,
    )

    return {
        "report_id": report_id,
        "plant_id": plant_id,
        "energy_metrics": energy_metrics,
        "kpis": kpis,
        "recommendations": recommendations,
        "carbon_saved_kg": carbon_data.get("potential_savings_kg", 0.0),
        "cost_saved_inr": carbon_data.get("potential_cost_savings_inr", 0.0),
        "processing_time_ms": int((time.time() - start) * 1000),
    }


# --- GenAI Assistant -----------------------------------------------------


_ASSISTANT_SYSTEM_PROMPT = """You are the FactoryMind GenAI Assistant — an
operational copilot for plant managers at PLANT-001 (Chennai Aerospace,
Ti-6Al-4V CNC titanium milling, 50 machines across 3 production lines).

You have read access to live telemetry (vibration, current, coolant flow,
acoustic) and machine state via the underlying multi-agent platform.

When the operator asks about plant health, faults, energy, or maintenance:
- Be concrete and quantitative — cite numbers, machine IDs, severities
- Prefer 2-4 sentence answers; bullet only when listing distinct items
- If the question requires deep analysis, briefly note which agent would
  handle it (Predictive Maintenance, Quality Vision, Sustainability, etc.)
- Never invent data you don't have; if state is unknown, say so

You are running inside Bedrock AgentCore Runtime."""


def _run_assistant(payload: dict[str, Any]) -> dict[str, Any]:
    """Conversational assistant for the dashboard.

    Calls Claude 3.5 (Bedrock) with a manufacturing system prompt + the
    user's message. Pulls a one-shot snapshot of the fleet state from
    DynamoDB so the model has factual context when the user asks about
    "the plant" generically.

    Optionally augments with the same Knowledge Base used by the
    Sustainability Manager (industry benchmarks etc.) when configured.
    """
    import boto3

    from agents.shared.utils.aws_clients import get_dynamodb_resource

    user_msg: str = payload.get("message") or ""
    session_id: str = payload.get("session_id") or str(uuid.uuid4())
    history: list[dict[str, Any]] = payload.get("history") or []

    if not user_msg.strip():
        return {
            "session_id": session_id,
            "answer": "Ask me about the plant — fleet health, faults, energy, or what to do next.",
            "context_used": False,
        }

    # Pull a small fleet snapshot so the model has live data to work with.
    fleet_summary = _fleet_snapshot()

    # Optional KB augmentation.
    kb_context = ""
    kb_id = os.environ.get("KNOWLEDGE_BASE_ID", "")
    if kb_id:
        try:
            kb_context = _retrieve_kb(kb_id, user_msg)
        except Exception as e:
            logger.warning("kb_retrieve_failed", error=str(e))

    bedrock = boto3.client(
        "bedrock-runtime",
        region_name=os.environ.get("BEDROCK_REGION", "us-east-1"),
    )
    # Use a cross-region inference profile (the "us." prefix). Claude 3.x is
    # now flagged Legacy and Haiku 4.5 needs an AWS Marketplace subscription
    # this account can't make; Sonnet 4.5 is the highest-quality model that
    # invokes successfully in the workshop us-east-1 environment.
    model_id = os.environ.get(
        "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )

    messages: list[dict[str, Any]] = []
    for turn in history[-6:]:  # cap context to last 6 turns
        role = turn.get("role")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    user_block_parts = [user_msg, "\n\n## Live fleet snapshot\n" + fleet_summary]
    if kb_context:
        user_block_parts.append("\n\n## Knowledge base context\n" + kb_context)
    messages.append({"role": "user", "content": "\n".join(user_block_parts)})

    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 800,
            "temperature": 0.4,
            "system": _ASSISTANT_SYSTEM_PROMPT,
            "messages": messages,
        }
    )

    response = bedrock.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=body,
    )
    response_body = json.loads(response["body"].read())
    blocks = response_body.get("content", [])
    answer = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()

    return {
        "session_id": session_id,
        "answer": answer or "(empty response from model)",
        "context_used": bool(kb_context),
        "model_id": model_id,
    }


def _fleet_snapshot() -> str:
    """Return a compact summary of the 50-machine fleet from DynamoDB."""
    import boto3 as _boto3

    region = os.environ.get("AWS_REGION", "us-east-1")
    try:
        # Don't share the cached resource (which honours different region env
        # vars in the container) — bind to the runtime's region explicitly.
        ddb = _boto3.resource("dynamodb", region_name=region)
        table = ddb.Table("FactoryMind_MachineState")
        resp = table.scan(
            ProjectionExpression="machine_id, #s, health_score, last_telemetry",
            ExpressionAttributeNames={"#s": "status"},
            Limit=60,
        )
        items = resp.get("Items", [])
        if not items:
            return "(no machine state available)"
        running = sum(1 for i in items if str(i.get("status")) == "RUNNING")
        fault = sum(1 for i in items if str(i.get("status")) == "FAULT")
        idle = sum(1 for i in items if str(i.get("status")) == "IDLE")
        worst = sorted(
            items,
            key=lambda i: float(i.get("health_score") or 1.0),
        )[:3]
        worst_lines = [
            f"  - {i.get('machine_id')}: status={i.get('status')} health={i.get('health_score')}"
            for i in worst
        ]
        return (
            f"Fleet: {len(items)} machines, running={running}, fault={fault}, idle={idle}\n"
            f"Lowest-health machines:\n" + "\n".join(worst_lines)
        )
    except Exception as e:
        # Log the real reason so we can see it in CloudWatch instead of just
        # bubbling a vague string back to the model.
        logger.exception("fleet_snapshot_failed", region=region, error=str(e))
        return f"(fleet snapshot unavailable: {type(e).__name__}: {e})"


def _retrieve_kb(kb_id: str, query: str) -> str:
    """Pull up to 4 grounded snippets from the Bedrock Knowledge Base."""
    import boto3

    client = boto3.client(
        "bedrock-agent-runtime",
        region_name=os.environ.get("BEDROCK_REGION", "us-east-1"),
    )
    resp = client.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 4}},
    )
    parts = []
    for r in resp.get("retrievalResults", []):
        text = r.get("content", {}).get("text", "")
        if text:
            parts.append(f"- {text.strip()}")
    return "\n".join(parts)


# --- Dispatcher ----------------------------------------------------------


_DISPATCH = {
    "brain": _run_brain,
    "sustainability": _run_sustainability,
    "assistant": _run_assistant,
}


@app.entrypoint
def invoke(payload: dict[str, Any]) -> dict[str, Any]:
    """Single AgentCore Runtime entrypoint, dispatching by ``agent_kind``."""
    kind = (payload or {}).get("agent_kind", "assistant")
    fn = _DISPATCH.get(kind)
    if fn is None:
        return {"error": f"unknown agent_kind: {kind}", "valid": list(_DISPATCH)}

    logger.info("agentcore_invocation", agent_kind=kind)
    try:
        return fn(payload)
    except Exception as e:
        logger.exception("agentcore_invocation_failed", agent_kind=kind, error=str(e))
        return {"error": str(e), "agent_kind": kind}


if __name__ == "__main__":
    # Local dev: ``python -m agents.runtime.app`` — AgentCore Runtime
    # ignores this in production and runs the SDK's HTTP server itself.
    app.run()
