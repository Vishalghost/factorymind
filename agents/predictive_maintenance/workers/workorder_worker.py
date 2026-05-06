"""Work Order Worker — generate and queue maintenance work orders."""

import json
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

from agents.shared.utils.id_generator import generate_work_order_id
from agents.shared.utils.retry import with_retry

logger = structlog.get_logger()

# Global counter for sequential work order IDs (in production, use DynamoDB atomic counter)
_work_order_counter = 2290


def create_work_order(
    machine_id: str,
    plant_id: str,
    priority: str,
    failure_mode: str,
    predicted_by: str,
    probability: float,
    prediction_report_id: str,
    sqs_client: Any = None,
    dynamodb_table: Any = None,
) -> dict[str, Any]:
    """Generate a work order and queue to SQS.

    Args:
        machine_id: CNC machine identifier.
        plant_id: Plant identifier.
        priority: CRITICAL or HIGH.
        failure_mode: Predicted failure mode.
        predicted_by: "consensus", "lstm", or "lookout".
        probability: Failure probability.
        prediction_report_id: PRD- reference ID.
        sqs_client: Optional pre-configured SQS client.
        dynamodb_table: Optional pre-configured DynamoDB Table.

    Returns:
        Complete work order dict.
    """
    global _work_order_counter
    _work_order_counter += 1
    work_order_id = generate_work_order_id(_work_order_counter)

    now = datetime.now(timezone.utc)
    # Schedule based on priority
    if priority == "CRITICAL":
        scheduled = now + timedelta(hours=1)  # ASAP
        action = f"IMMEDIATE: Replace tool on {machine_id}. Compound failure risk."
    else:
        scheduled = now + timedelta(hours=8)  # End of shift
        action = f"Replace end-mill on {machine_id} before next shift."

    work_order = {
        "work_order_id": work_order_id,
        "machine_id": machine_id,
        "plant_id": plant_id,
        "priority": priority,
        "status": "OPEN",
        "failure_mode": failure_mode,
        "predicted_by": predicted_by,
        "probability": probability,
        "recommended_action": action,
        "estimated_downtime_hours": 4.0 if priority == "CRITICAL" else 2.0,
        "parts_required": _get_parts_for_failure(failure_mode),
        "scheduled_date": scheduled.isoformat(),
        "created_at": now.isoformat(),
        "prediction_report_id": prediction_report_id,
    }

    # Write to DynamoDB
    _persist_work_order(work_order, dynamodb_table)

    # Queue to SQS
    _queue_work_order(work_order, sqs_client)

    logger.info(
        "work_order_created",
        work_order_id=work_order_id,
        priority=priority,
        machine_id=machine_id,
    )
    return work_order


@with_retry(max_retries=1, base_delay=0.5)
def _persist_work_order(work_order: dict, table: Any = None) -> None:
    """Write work order to DynamoDB. Floats converted to Decimal."""
    from agents.shared.utils.aws_clients import to_dynamodb_item

    if table is None:
        from agents.shared.utils.aws_clients import get_dynamodb_resource
        dynamodb = get_dynamodb_resource()
        table = dynamodb.Table("FactoryMind_WorkOrders")

    table.put_item(Item=to_dynamodb_item(work_order))


@with_retry(max_retries=1, base_delay=0.5)
def _queue_work_order(work_order: dict, client: Any = None) -> None:
    """Queue work order to SQS for downstream processing."""
    if client is None:
        from agents.shared.utils.aws_clients import get_sqs_client
        client = get_sqs_client()

    try:
        client.send_message(
            QueueUrl="https://sqs.ap-south-1.amazonaws.com/123456789012/factorymind-workorder-queue",
            MessageBody=json.dumps(work_order),
            MessageAttributes={
                "priority": {
                    "DataType": "String",
                    "StringValue": work_order["priority"],
                },
                "machine_id": {
                    "DataType": "String",
                    "StringValue": work_order["machine_id"],
                },
            },
        )
    except Exception as e:
        logger.error("sqs_queue_failed", error=str(e))


def _get_parts_for_failure(failure_mode: str) -> list[str]:
    """Get required parts list based on failure mode."""
    parts_map = {
        "TOOL_WEAR": ["Carbide end-mill 12mm", "Tool holder collet"],
        "COOLANT_BLOCKAGE": ["Coolant filter", "Coolant pump seal", "Nozzle assembly"],
        "BEARING_FAILURE": ["Spindle bearing assembly", "Bearing grease"],
        "COMPOUND_FAILURE": ["Carbide end-mill 12mm", "Coolant filter", "Spindle bearing assembly"],
    }
    return parts_map.get(failure_mode, ["General maintenance kit"])
