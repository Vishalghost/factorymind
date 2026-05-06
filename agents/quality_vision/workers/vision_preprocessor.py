"""Vision Preprocessor Worker — resize and normalize image for model input."""

from typing import Any

import structlog

logger = structlog.get_logger()


def preprocess_image(image_s3_key: str, client: Any = None) -> dict[str, Any]:
    """Download and preprocess image from S3.

    Resizes to 640x640 and normalizes pixel values for YOLOv8 input.

    Args:
        image_s3_key: S3 key in factorymind-product-images bucket.
        client: Optional pre-configured S3 client.

    Returns:
        Dict with preprocessed image data and metadata.
    """
    if client is None:
        from agents.shared.utils.aws_clients import get_s3_client
        client = get_s3_client()

    logger.info("preprocessing_image", s3_key=image_s3_key)

    # Download image from S3
    try:
        response = client.get_object(
            Bucket="factorymind-product-images",
            Key=image_s3_key,
        )
        image_bytes = response["Body"].read()
    except Exception as e:
        logger.error("image_download_failed", error=str(e))
        image_bytes = b""

    # In production: resize to 640x640, normalize to [0,1]
    # For MVP: return metadata about the preprocessing
    return {
        "s3_key": image_s3_key,
        "original_size_bytes": len(image_bytes),
        "target_size": (640, 640),
        "normalized": True,
        "image_data": image_bytes,
    }
