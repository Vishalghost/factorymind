"""Edge AI Manager Lambda handler.

Provides sub-10ms inference for real-time CNC protection.
Triggered by IoT Core rule on factory/aerospace/cnc/telemetry.
Fire-and-forget: never retries, never waits for cloud response.
"""

import time
from typing import Any

from aws_lambda_powertools import Logger
from pydantic import BaseModel

from agents.shared.models.edge import EdgeClassification
from agents.shared.utils.id_generator import generate_edge_id
from agents.shared.constants import PLANT_ID
from agents.edge_ai.workers.edge_cache import get_sliding_window, update_sliding_window
from agents.edge_ai.workers.onnx_worker import run_inference
from agents.edge_ai.workers.edge_classifier import classify
from agents.edge_ai.workers.cloud_escalator import escalate_to_cloud

logger = Logger(service="edge-ai-manager")


class EdgeInferenceInput(BaseModel):
    """Input from IoT Core rule."""

    machine_id: str
    timestamp: str
    sensor_values: dict[str, float]
    plant_id: str = PLANT_ID


class EdgeInferenceOutput(BaseModel):
    """Output from Edge AI Manager."""

    edge_result_id: str
    machine_id: str
    classification: str
    confidence: float
    inference_time_ms: float
    escalated: bool
    compound_rule_triggered: bool
    processing_time_ms: int


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for Edge AI Manager.

    Triggered by IoT Core rule. Must complete inference in <10ms.
    No retry logic. Fire-and-forget escalation.
    """
    start_time = time.perf_counter()
    edge_result_id = generate_edge_id()

    # Parse input
    machine_id = event.get("machine_id", "")
    timestamp = event.get("timestamp", "")
    sensor_values = event.get("telemetry", event.get("sensor_values", {}))
    plant_id = event.get("plant_id", PLANT_ID)

    # Get Redis client (injected or created via env-configured factory)
    redis_client = event.get("_redis_client")
    if redis_client is None:
        from agents.shared.utils.aws_clients import get_redis_client
        redis_client = get_redis_client()

    # Step 1: Get sliding window from Redis
    sliding_window = get_sliding_window(machine_id, redis_client)

    # Step 2: Run ONNX inference (<10ms)
    model_output, inference_time_ms = run_inference(sensor_values, sliding_window)

    # Step 3: Classify
    result = classify(model_output, sensor_values)

    # Step 4: Update sliding window
    update_sliding_window(machine_id, sensor_values, redis_client)

    # Step 5: Escalate if ANOMALY (fire-and-forget)
    escalated = False
    escalation_event_id = None
    if result.classification == EdgeClassification.ANOMALY:
        escalation_event_id = escalate_to_cloud(
            machine_id=machine_id,
            sensor_values=sensor_values,
            confidence=result.confidence,
            compound_rule_triggered=result.compound_rule_triggered,
            timestamp=timestamp,
        )
        escalated = escalation_event_id is not None

    # Step 6: Write result to DynamoDB (best-effort, no retry)
    _write_result_to_dynamodb(
        edge_result_id=edge_result_id,
        machine_id=machine_id,
        plant_id=plant_id,
        classification=result.classification.value,
        confidence=result.confidence,
        inference_time_ms=inference_time_ms,
        sensor_values=sensor_values,
        sliding_window_size=len(sliding_window) + 1,
        escalated=escalated,
        escalation_event_id=escalation_event_id,
        compound_rule_triggered=result.compound_rule_triggered,
        timestamp=timestamp,
    )

    processing_time_ms = int((time.perf_counter() - start_time) * 1000)

    output = EdgeInferenceOutput(
        edge_result_id=edge_result_id,
        machine_id=machine_id,
        classification=result.classification.value,
        confidence=result.confidence,
        inference_time_ms=inference_time_ms,
        escalated=escalated,
        compound_rule_triggered=result.compound_rule_triggered,
        processing_time_ms=processing_time_ms,
    )

    return output.model_dump()


def _write_result_to_dynamodb(**kwargs: Any) -> None:
    """Write edge result to DynamoDB. Best-effort, no retry.

    Floats are converted to Decimal because DynamoDB rejects Python floats.
    """
    try:
        from agents.shared.utils.aws_clients import get_dynamodb_resource, to_dynamodb_item
        dynamodb = get_dynamodb_resource()
        table = dynamodb.Table("FactoryMind_EdgeResults")
        table.put_item(Item=to_dynamodb_item(kwargs))
    except Exception as e:
        logger.warning("dynamodb_write_failed", error=str(e))
