"""LSTM Worker — invoke SageMaker endpoint for failure prediction.

Analyzes 72-hour sensor trends to predict tool wear and failure.
"""

import json
from typing import Any

import structlog

from agents.shared.utils.retry import with_retry

logger = structlog.get_logger()

SAGEMAKER_ENDPOINT = "factorymind-lstm-maintenance"


@with_retry(max_retries=1, base_delay=0.5)
def predict_with_lstm(
    machine_id: str,
    sensor_history: list[dict[str, Any]],
    current_snapshot: dict[str, Any],
    client: Any = None,
) -> dict[str, Any]:
    """Invoke LSTM SageMaker endpoint for maintenance prediction.

    Args:
        machine_id: CNC machine identifier.
        sensor_history: 72-hour sensor history from Timestream.
        current_snapshot: Current telemetry values.
        client: Optional pre-configured SageMaker Runtime client.

    Returns:
        Prediction result dict with severity, failure_mode, probability, rul_hours.
    """
    if client is None:
        from agents.shared.utils.aws_clients import get_sagemaker_runtime_client
        client = get_sagemaker_runtime_client()

    logger.info("invoking_lstm", machine_id=machine_id, history_size=len(sensor_history))

    try:
        payload = {
            "machine_id": machine_id,
            "sensor_history": sensor_history[-500:],  # Last 500 readings
            "current_snapshot": current_snapshot,
        }

        response = client.invoke_endpoint(
            EndpointName=SAGEMAKER_ENDPOINT,
            ContentType="application/json",
            Body=json.dumps(payload),
        )

        result = json.loads(response["Body"].read())
        return {
            "model": "lstm",
            "severity": result.get("severity", "LOW"),
            "failure_mode": result.get("failure_mode", "UNKNOWN"),
            "probability": result.get("probability", 0.0),
            "rul_hours": result.get("remaining_useful_life_hours", 999),
            "confidence_interval": result.get("confidence_interval", [0.0, 1.0]),
        }
    except Exception as e:
        logger.error("lstm_prediction_failed", error=str(e))
        return {
            "model": "lstm",
            "severity": "LOW",
            "failure_mode": "UNKNOWN",
            "probability": 0.0,
            "rul_hours": 999,
            "error": str(e),
        }
