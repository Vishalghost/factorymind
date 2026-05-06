"""Rekognition Worker — fallback detector when YOLOv8 confidence < 0.75."""

from typing import Any

import structlog

from agents.shared.utils.retry import with_retry

logger = structlog.get_logger()


@with_retry(max_retries=1, base_delay=0.5)
def detect_with_rekognition(
    image_s3_key: str,
    client: Any = None,
) -> tuple[list[dict[str, Any]], float]:
    """Invoke Amazon Rekognition as fallback detector.

    Args:
        image_s3_key: S3 key in factorymind-product-images bucket.
        client: Optional pre-configured Rekognition client.

    Returns:
        Tuple of (list of detection dicts, overall confidence score).
    """
    if client is None:
        import boto3
        client = boto3.client("rekognition")

    logger.info("invoking_rekognition_fallback", image_key=image_s3_key)

    try:
        response = client.detect_labels(
            Image={
                "S3Object": {
                    "Bucket": "factorymind-product-images",
                    "Name": image_s3_key,
                }
            },
            MaxLabels=20,
            MinConfidence=50.0,
        )

        detections = []
        max_confidence = 0.0

        for label in response.get("Labels", []):
            confidence = label["Confidence"] / 100.0
            max_confidence = max(max_confidence, confidence)

            for instance in label.get("Instances", []):
                bbox = instance.get("BoundingBox", {})
                detections.append({
                    "defect_type": _map_label_to_defect(label["Name"]),
                    "confidence": confidence,
                    "bounding_box": {
                        "x": bbox.get("Left", 0),
                        "y": bbox.get("Top", 0),
                        "width": bbox.get("Width", 0),
                        "height": bbox.get("Height", 0),
                    },
                })

        return detections, max_confidence
    except Exception as e:
        logger.error("rekognition_failed", error=str(e))
        return [], 0.0


def _map_label_to_defect(label_name: str) -> str:
    """Map Rekognition label to DefectType."""
    label_lower = label_name.lower()
    if "scratch" in label_lower:
        return "SCRATCH"
    elif "dent" in label_lower:
        return "DENT"
    elif "crack" in label_lower:
        return "CRACK"
    elif "discolor" in label_lower or "stain" in label_lower:
        return "DISCOLORATION"
    elif "misalign" in label_lower or "offset" in label_lower:
        return "MISALIGNMENT"
    return "NO_DEFECT"
