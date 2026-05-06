"""Lookout Worker — invoke Lookout for Equipment for anomaly detection."""

import json
from typing import Any

import structlog

from agents.shared.utils.retry import with_retry

logger = structlog.get_logger()

LOOKOUT_MODEL = "factorymind-machine-anomaly-model"


@with_retry(max_retries=1, base_delay=0.5)
def predict_with_lookout(
    machine_id: str,
    sensor_history: list[dict[str, Any]],
    current_snapshot: dict[str, Any],
    client: Any = None,
) -> dict[str, Any]:
    """Invoke Lookout for Equipment for anomaly prediction.

    Args:
        machine_id: CNC machine identifier.
        sensor_history: 72-hour sensor history from Timestream.
        current_snapshot: Current telemetry values.
        client: Optional pre-configured Lookout client.

    Returns:
        Prediction result dict with severity, failure_mode, probability.
    """
    if client is None:
        import boto3
        client = boto3.client("lookoutequipment")

    logger.info("invoking_lookout", machine_id=machine_id)

    try:
        response = client.list_inference_executions(
            InferenceSchedulerName=f"{LOOKOUT_MODEL}-{machine_id}",
            MaxResults=1,
        )

        executions = response.get("InferenceExecutionSummaries", [])
        if executions:
            latest = executions[0]
            status = latest.get("Status", "")
            if status == "SUCCESS":
                return _parse_lookout_result(latest)

        # Fallback: use current snapshot for rule-based assessment
        return _assess_from_snapshot(current_snapshot)
    except Exception as e:
        logger.error("lookout_prediction_failed", error=str(e))
        return _assess_from_snapshot(current_snapshot)


def _parse_lookout_result(execution: dict) -> dict[str, Any]:
    """Parse Lookout for Equipment execution result."""
    return {
        "model": "lookout",
        "severity": execution.get("severity", "LOW"),
        "failure_mode": execution.get("failure_mode", "UNKNOWN"),
        "probability": execution.get("anomaly_score", 0.0),
        "rul_hours": execution.get("rul_hours", 999),
    }


def _assess_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Rule-based assessment from current sensor snapshot."""
    from agents.shared.constants import (
        VIBRATION_ANOMALY_THRESHOLD,
        CURRENT_ANOMALY_THRESHOLD,
        COOLANT_ANOMALY_THRESHOLD,
    )

    vib = snapshot.get("vibration_mms", 0.0)
    cur = snapshot.get("current_amps", 0.0)
    cool = snapshot.get("coolant_lmin", 50.0)

    if vib > VIBRATION_ANOMALY_THRESHOLD and cool < COOLANT_ANOMALY_THRESHOLD:
        return {"model": "lookout", "severity": "CRITICAL", "failure_mode": "COMPOUND_FAILURE", "probability": 0.95}
    elif cool < COOLANT_ANOMALY_THRESHOLD:
        return {"model": "lookout", "severity": "CRITICAL", "failure_mode": "COOLANT_BLOCKAGE", "probability": 0.9}
    elif vib > VIBRATION_ANOMALY_THRESHOLD:
        return {"model": "lookout", "severity": "HIGH", "failure_mode": "TOOL_WEAR", "probability": 0.8}
    elif cur > CURRENT_ANOMALY_THRESHOLD:
        return {"model": "lookout", "severity": "HIGH", "failure_mode": "TOOL_WEAR", "probability": 0.75}
    return {"model": "lookout", "severity": "LOW", "failure_mode": "NONE", "probability": 0.1}
