"""YOLOv8 Worker — invoke SageMaker endpoint for defect detection."""

import json
from typing import Any

import structlog

from agents.shared.utils.retry import with_retry

logger = structlog.get_logger()

SAGEMAKER_ENDPOINT = "factorymind-yolov8-quality"


@with_retry(max_retries=1, base_delay=0.5)
def detect_with_yolov8(
    preprocessed_image: dict[str, Any],
    client: Any = None,
) -> tuple[list[dict[str, Any]], float]:
    """Invoke YOLOv8 SageMaker endpoint for defect detection.

    Args:
        preprocessed_image: Preprocessed image data from vision_preprocessor.
        client: Optional pre-configured SageMaker Runtime client.

    Returns:
        Tuple of (list of detection dicts, overall confidence score).
    """
    if client is None:
        from agents.shared.utils.aws_clients import get_sagemaker_runtime_client
        client = get_sagemaker_runtime_client()

    logger.info("invoking_yolov8", endpoint=SAGEMAKER_ENDPOINT)

    try:
        response = client.invoke_endpoint(
            EndpointName=SAGEMAKER_ENDPOINT,
            ContentType="application/json",
            Body=json.dumps({
                "image_key": preprocessed_image["s3_key"],
                "target_size": preprocessed_image["target_size"],
            }),
        )
        result = json.loads(response["Body"].read())
        detections = result.get("detections", [])
        confidence = result.get("confidence", 0.0)
        return detections, confidence
    except Exception as e:
        logger.error("yolov8_invocation_failed", error=str(e))
        return [], 0.0
