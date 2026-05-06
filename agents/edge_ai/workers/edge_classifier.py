"""Edge Classifier Worker — classifies CNC readings as NORMAL/WARNING/ANOMALY.

Classification zones for titanium milling:
- NORMAL: vibration 2.0-5.0, current 15.0-25.0, coolant 40.0-50.0, acoustic 75-85
- WARNING: vibration 5.0-8.0, current 25.0-35.0, coolant 30.0-40.0, acoustic 85-95
- ANOMALY: vibration >8.0, current >35.0, coolant <30.0, acoustic >95
- ANOMALY (compound): vibration >8.0 AND coolant <30.0 → IMMEDIATE SPINDLE STOP
"""

import numpy as np
import structlog

from agents.shared.models.edge import EdgeClassification
from agents.shared.constants import (
    COMPOUND_RULE_VIBRATION_THRESHOLD,
    COMPOUND_RULE_COOLANT_THRESHOLD,
)

logger = structlog.get_logger()


class ClassificationResult:
    """Result of edge classification."""

    def __init__(
        self,
        classification: EdgeClassification,
        confidence: float,
        compound_rule_triggered: bool = False,
    ):
        self.classification = classification
        self.confidence = confidence
        self.compound_rule_triggered = compound_rule_triggered


def classify(
    model_output: np.ndarray,
    sensor_values: dict[str, float],
) -> ClassificationResult:
    """Classify sensor reading based on model output.

    Args:
        model_output: ONNX model output array [normal_prob, warning_prob, anomaly_prob].
        sensor_values: Current telemetry values for compound rule check.

    Returns:
        ClassificationResult with classification, confidence, and compound flag.
    """
    probabilities = model_output[0]  # Shape: [3]
    normal_prob = float(probabilities[0])
    warning_prob = float(probabilities[1])
    anomaly_prob = float(probabilities[2])

    # Check compound rule explicitly (overrides model)
    vib = sensor_values.get("vibration_mms", 0.0)
    cool = sensor_values.get("coolant_lmin", 50.0)
    compound_triggered = (
        vib > COMPOUND_RULE_VIBRATION_THRESHOLD
        and cool < COMPOUND_RULE_COOLANT_THRESHOLD
    )

    if compound_triggered:
        logger.critical(
            "compound_rule_triggered",
            vibration=vib,
            coolant=cool,
            action="IMMEDIATE_SPINDLE_STOP",
        )
        return ClassificationResult(
            classification=EdgeClassification.ANOMALY,
            confidence=1.0,
            compound_rule_triggered=True,
        )

    # Standard classification from model probabilities
    max_idx = int(np.argmax(probabilities))
    confidence = float(probabilities[max_idx])

    if max_idx == 0:
        classification = EdgeClassification.NORMAL
    elif max_idx == 1:
        classification = EdgeClassification.WARNING
    else:
        classification = EdgeClassification.ANOMALY

    return ClassificationResult(
        classification=classification,
        confidence=confidence,
        compound_rule_triggered=False,
    )
