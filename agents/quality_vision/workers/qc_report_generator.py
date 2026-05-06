"""QC Report Generator Worker — generate inspection report and persist."""

from datetime import datetime, timezone
from typing import Any

import structlog

from agents.shared.utils.retry import with_retry
from agents.shared.utils.eventbridge import publish_event
from agents.shared.constants import EVENT_BUS_NAME

logger = structlog.get_logger()


@with_retry(max_retries=1, base_delay=0.5)
def generate_report(
    inspection_id: str,
    plant_id: str,
    machine_id: str,
    production_line: str,
    product_type: str,
    batch_number: str,
    image_s3_key: str,
    verdict: str,
    defects: list[dict[str, Any]],
    primary_model: str,
    confidence_score: float,
    defect_rate: float,
    threshold_exceeded: bool,
    table: Any = None,
) -> dict[str, Any]:
    """Generate QC report, write to DynamoDB, publish event.

    Args:
        All inspection result fields.
        table: Optional pre-configured DynamoDB Table resource.

    Returns:
        Complete report record dict.
    """
    now = datetime.now(timezone.utc).isoformat()

    report = {
        "inspection_report_id": inspection_id,
        "plant_id": plant_id,
        "machine_id": machine_id,
        "production_line": production_line,
        "product_type": product_type,
        "batch_number": batch_number,
        "image_s3_key": image_s3_key,
        "verdict": verdict,
        "defects": defects,
        "primary_model": primary_model,
        "confidence_score": str(confidence_score),
        "defect_rate": str(defect_rate),
        "threshold_exceeded": threshold_exceeded,
        "inspected_at": now,
    }

    # Write to DynamoDB
    if table is None:
        from agents.shared.utils.aws_clients import get_dynamodb_resource
        dynamodb = get_dynamodb_resource()
        table = dynamodb.Table("FactoryMind_QualityResults")

    table.put_item(Item=report)

    # Publish event to EventBridge
    try:
        publish_event(
            source="factorymind.quality.inspection",
            detail_type="InspectionCompleted",
            detail={
                "inspection_report_id": inspection_id,
                "machine_id": machine_id,
                "verdict": verdict,
                "threshold_exceeded": threshold_exceeded,
            },
        )
    except Exception as e:
        logger.warning("event_publish_failed", error=str(e))

    logger.info("report_generated", inspection_id=inspection_id, verdict=verdict)
    return report
