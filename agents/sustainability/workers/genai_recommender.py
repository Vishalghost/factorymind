"""GenAI Recommender Worker — invoke Bedrock Claude 3.5 for optimization recommendations."""

import json
import os
from typing import Any

import boto3
import structlog

from agents.shared.constants import CARBON_KG_PER_KWH, ENERGY_COST_INR_PER_KWH
from agents.shared.utils.retry import with_retry

logger = structlog.get_logger()

# Bedrock model configuration
BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"
)
KNOWLEDGE_BASE_ID = os.environ.get("KNOWLEDGE_BASE_ID", "")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1")


def _get_bedrock_runtime_client() -> Any:
    """Get Bedrock Runtime client."""
    return boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)


def _get_bedrock_agent_runtime_client() -> Any:
    """Get Bedrock Agent Runtime client for Knowledge Bases."""
    return boto3.client("bedrock-agent-runtime", region_name=BEDROCK_REGION)


def _query_knowledge_base(
    energy_metrics: list[dict[str, Any]],
    kpis: dict[str, Any],
) -> str:
    """Query Bedrock Knowledge Base for industry benchmarks and best practices.

    Args:
        energy_metrics: Energy consumption metrics per machine.
        kpis: Calculated sustainability KPIs.

    Returns:
        Context string from Knowledge Base, or empty string on failure.
    """
    if not KNOWLEDGE_BASE_ID:
        logger.info("knowledge_base_skipped", reason="no_knowledge_base_id_configured")
        return ""

    try:
        client = _get_bedrock_agent_runtime_client()
        query_text = (
            f"Manufacturing energy optimization benchmarks for CNC milling. "
            f"Current energy efficiency: {kpis.get('energy_efficiency', 0):.1%}. "
            f"Carbon footprint: {kpis.get('carbon_footprint_kg', 0):.1f} kg CO2. "
            f"Waste index: {kpis.get('waste_index', 0):.1%}."
        )

        response = client.retrieve(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            retrievalQuery={"text": query_text},
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": 5}
            },
        )

        # Extract text from retrieval results
        results = response.get("retrievalResults", [])
        context_parts = []
        for result in results:
            content = result.get("content", {}).get("text", "")
            if content:
                context_parts.append(content)

        context = "\n".join(context_parts)
        logger.info("knowledge_base_queried", results_count=len(results))
        return context

    except Exception as e:
        logger.warning("knowledge_base_query_failed", error=str(e))
        return ""


def _build_prompt(
    energy_metrics: list[dict[str, Any]],
    kpis: dict[str, Any],
    waste_data: dict[str, Any],
    kb_context: str,
) -> str:
    """Build the prompt for Claude 3.5 with energy data and context.

    Args:
        energy_metrics: Energy consumption metrics per machine.
        kpis: Calculated sustainability KPIs.
        waste_data: Waste detection results.
        kb_context: Context from Knowledge Base query.

    Returns:
        Formatted prompt string.
    """
    total_kwh = sum(m.get("current_kwh", 0.0) for m in energy_metrics)
    total_baseline = sum(m.get("baseline_kwh", 0.0) for m in energy_metrics)
    excess_kwh = max(0.0, total_kwh - total_baseline)
    carbon_excess_kg = excess_kwh * CARBON_KG_PER_KWH
    cost_excess_inr = excess_kwh * ENERGY_COST_INR_PER_KWH

    waste_machines = waste_data.get("waste_machines", [])
    waste_machine_ids = [m.get("machine_id", "") for m in waste_machines]

    prompt = f"""You are an energy optimization expert for aerospace CNC titanium milling operations.

Analyze the following plant sustainability data and provide 3-5 specific, actionable recommendations to reduce energy consumption, carbon footprint, and costs.

## Current Plant Metrics
- Total energy consumption: {total_kwh:.1f} kWh
- Baseline energy: {total_baseline:.1f} kWh
- Excess energy: {excess_kwh:.1f} kWh
- Carbon footprint: {kpis.get('carbon_footprint_kg', 0):.1f} kg CO2 (conversion: {CARBON_KG_PER_KWH} kg/kWh)
- Energy cost rate: Rs {ENERGY_COST_INR_PER_KWH}/kWh
- Potential cost savings: Rs {cost_excess_inr:.2f}
- Potential carbon savings: {carbon_excess_kg:.2f} kg CO2

## KPIs
- Energy efficiency: {kpis.get('energy_efficiency', 0):.1%}
- Waste index: {kpis.get('waste_index', 0):.1%}
- Overall sustainability score: {kpis.get('overall_score', 0):.1f}/100

## Waste Detection
- Machines with idle waste: {len(waste_machines)}
- Waste machine IDs: {', '.join(waste_machine_ids) if waste_machine_ids else 'None'}
- Total waste energy: {waste_data.get('total_waste_kwh', 0):.1f} kWh
"""

    if kb_context:
        prompt += f"""
## Industry Benchmarks (from Knowledge Base)
{kb_context}
"""

    prompt += """
## Instructions
Provide 3-5 specific recommendations. Each recommendation should be a single concise sentence.
Focus on:
1. Immediate actions to reduce waste (idle machines)
2. Scheduling optimizations for CNC operations
3. Maintenance actions that improve energy efficiency
4. Carbon reduction strategies

Return ONLY a JSON array of recommendation strings. Example:
["Recommendation 1", "Recommendation 2", "Recommendation 3"]
"""
    return prompt


@with_retry(max_retries=1, base_delay=0.5)
def _invoke_bedrock(prompt: str) -> list[str]:
    """Invoke Bedrock Claude 3.5 to generate recommendations.

    Args:
        prompt: The formatted prompt with plant data.

    Returns:
        List of recommendation strings.

    Raises:
        Exception: If Bedrock invocation fails after retry.
    """
    client = _get_bedrock_runtime_client()

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "temperature": 0.3,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    })

    response = client.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body,
    )

    response_body = json.loads(response["body"].read())
    content = response_body.get("content", [])

    # Extract text from response
    text = ""
    for block in content:
        if block.get("type") == "text":
            text += block.get("text", "")

    # Parse JSON array from response
    recommendations = json.loads(text.strip())
    if isinstance(recommendations, list):
        return [str(r) for r in recommendations]

    logger.warning("unexpected_response_format", response_text=text[:200])
    return []


def generate_recommendations(
    energy_metrics: list[dict[str, Any]],
    kpis: dict[str, Any],
    waste_data: dict[str, Any],
) -> list[str]:
    """Generate AI-powered optimization recommendations using Bedrock Claude 3.5.

    Queries Bedrock Knowledge Bases for industry benchmarks, then invokes
    Claude 3.5 to generate specific recommendations based on current plant
    energy metrics, KPIs, and waste data.

    Args:
        energy_metrics: Energy consumption metrics per machine.
        kpis: Calculated sustainability KPIs.
        waste_data: Waste detection results.

    Returns:
        List of recommendation strings. Returns fallback recommendations on failure.
    """
    try:
        # Query Knowledge Base for industry context
        kb_context = _query_knowledge_base(energy_metrics, kpis)

        # Build prompt with all data
        prompt = _build_prompt(energy_metrics, kpis, waste_data, kb_context)

        # Invoke Bedrock Claude 3.5
        recommendations = _invoke_bedrock(prompt)

        logger.info(
            "recommendations_generated",
            count=len(recommendations),
            used_knowledge_base=bool(kb_context),
        )
        return recommendations

    except Exception as e:
        logger.error("recommendation_generation_failed", error=str(e))
        # Return generic fallback recommendations on failure
        return _fallback_recommendations(energy_metrics, waste_data)


def _fallback_recommendations(
    energy_metrics: list[dict[str, Any]],
    waste_data: dict[str, Any],
) -> list[str]:
    """Generate basic rule-based recommendations when Bedrock is unavailable.

    Args:
        energy_metrics: Energy consumption metrics per machine.
        waste_data: Waste detection results.

    Returns:
        List of fallback recommendation strings.
    """
    recommendations = []

    waste_machines = waste_data.get("waste_machines", [])
    if waste_machines:
        machine_ids = [m.get("machine_id", "") for m in waste_machines[:3]]
        recommendations.append(
            f"Shut down idle machines consuming excess power: {', '.join(machine_ids)}"
        )

    # Check for high deviation machines
    high_deviation = [
        m for m in energy_metrics if m.get("deviation_pct", 0) > 15.0
    ]
    if high_deviation:
        recommendations.append(
            "Schedule maintenance for machines with >15% energy deviation from baseline"
        )

    total_excess = sum(
        max(0, m.get("current_kwh", 0) - m.get("baseline_kwh", 0))
        for m in energy_metrics
    )
    if total_excess > 0:
        savings_inr = total_excess * ENERGY_COST_INR_PER_KWH
        recommendations.append(
            f"Optimize scheduling to reduce excess consumption — potential savings: Rs {savings_inr:.0f}"
        )

    if not recommendations:
        recommendations.append(
            "Continue monitoring energy baselines and adjust thresholds seasonally"
        )

    return recommendations
