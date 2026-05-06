"""Defect Analyser Worker — classify defects and determine verdict."""

from typing import Any

import structlog

logger = structlog.get_logger()

# Default defect rate thresholds by product type
DEFAULT_THRESHOLDS = {
    "TITANIUM_BRACKET": 0.05,  # 5% defect rate threshold
    "FUSELAGE_PANEL": 0.02,  # 2% for critical structural parts
    "ENGINE_MOUNT": 0.01,  # 1% for engine components
}
DEFAULT_THRESHOLD = 0.05


def analyse_defects(
    detections: list[dict[str, Any]],
    product_type: str,
    batch_size: int = 1,
) -> tuple[str, float, bool]:
    """Analyse detected defects and determine verdict.

    Args:
        detections: List of detection dicts from YOLOv8 or Rekognition.
        product_type: Product type for threshold lookup.
        batch_size: Number of items in current batch.

    Returns:
        Tuple of (verdict, defect_rate, threshold_exceeded).
        verdict: PASS | FAIL | REVIEW
    """
    if not detections:
        return "PASS", 0.0, False

    # Filter out NO_DEFECT detections
    actual_defects = [
        d for d in detections
        if d.get("defect_type", "NO_DEFECT") != "NO_DEFECT"
    ]

    if not actual_defects:
        return "PASS", 0.0, False

    # Calculate defect rate
    defect_count = len(actual_defects)
    defect_rate = defect_count / max(batch_size, 1)

    # Check threshold
    threshold = DEFAULT_THRESHOLDS.get(product_type, DEFAULT_THRESHOLD)
    threshold_exceeded = defect_rate > threshold

    # Determine verdict based on severity
    has_critical = any(
        d.get("defect_type") in ("CRACK", "MISALIGNMENT")
        for d in actual_defects
    )
    avg_confidence = sum(
        d.get("confidence", 0.0) for d in actual_defects
    ) / len(actual_defects)

    if has_critical:
        verdict = "FAIL"
    elif avg_confidence < 0.6:
        verdict = "REVIEW"  # Low confidence, needs human review
    elif threshold_exceeded:
        verdict = "FAIL"
    else:
        verdict = "REVIEW" if defect_count > 0 else "PASS"

    logger.info(
        "defect_analysis_complete",
        defect_count=defect_count,
        defect_rate=defect_rate,
        verdict=verdict,
        threshold_exceeded=threshold_exceeded,
    )

    return verdict, defect_rate, threshold_exceeded
