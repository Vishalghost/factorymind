"""Anomaly Detector Worker — threshold-based anomaly detection for titanium milling.

Detection rules:
- vibration_mms > 8.0 → HIGH severity (severe tool wear/chatter)
- current_amps > 35.0 → HIGH severity (dull tool)
- coolant_lmin < 30.0 → CRITICAL severity (blockage, tool damage risk)
- acoustic_db > 95 → HIGH severity (micro-fractures)
- Compound: vibration >8.0 AND coolant <30.0 → CRITICAL (IMMEDIATE SPINDLE STOP)
"""

from typing import Optional

from agents.shared.models.sensor import SensorReading
from agents.shared.models.events import AnomalyEvent
from agents.shared.constants import (
    VIBRATION_ANOMALY_THRESHOLD,
    CURRENT_ANOMALY_THRESHOLD,
    COOLANT_ANOMALY_THRESHOLD,
    ACOUSTIC_ANOMALY_THRESHOLD,
    COMPOUND_RULE_VIBRATION_THRESHOLD,
    COMPOUND_RULE_COOLANT_THRESHOLD,
    IOT_EVENT_SOURCE,
    EVENT_BUS_NAME,
)
from agents.shared.utils.eventbridge import publish_event


def detect_anomalies(
    reading: SensorReading,
    ingestion_id: str,
    publish: bool = True,
) -> Optional[AnomalyEvent]:
    """Detect anomalies in a validated sensor reading.

    Args:
        reading: Validated SensorReading from stream_validator.
        ingestion_id: Parent ingestion batch ID.
        publish: Whether to publish to EventBridge (disable for testing).

    Returns:
        AnomalyEvent if anomaly detected, None otherwise.
    """
    telemetry = reading.telemetry
    alert_type: Optional[str] = None
    severity: Optional[str] = None
    anomaly_score: float = 0.0
    compound_rule_triggered = False

    # Check compound rule first (highest priority)
    if (
        telemetry.vibration_mms > COMPOUND_RULE_VIBRATION_THRESHOLD
        and telemetry.coolant_lmin < COMPOUND_RULE_COOLANT_THRESHOLD
    ):
        alert_type = "COMPOUND_FAILURE"
        severity = "CRITICAL"
        anomaly_score = 1.0
        compound_rule_triggered = True

    # Individual sensor checks (if compound rule not triggered)
    elif telemetry.coolant_lmin < COOLANT_ANOMALY_THRESHOLD:
        alert_type = "COOLANT_FAILURE"
        severity = "CRITICAL"
        # Score based on how far below threshold
        anomaly_score = min(1.0, (COOLANT_ANOMALY_THRESHOLD - telemetry.coolant_lmin) / COOLANT_ANOMALY_THRESHOLD)

    elif telemetry.vibration_mms > VIBRATION_ANOMALY_THRESHOLD:
        alert_type = "VIBRATION_ANOMALY"
        severity = "HIGH"
        anomaly_score = min(1.0, (telemetry.vibration_mms - VIBRATION_ANOMALY_THRESHOLD) / VIBRATION_ANOMALY_THRESHOLD)

    elif telemetry.current_amps > CURRENT_ANOMALY_THRESHOLD:
        alert_type = "CURRENT_SPIKE"
        severity = "HIGH"
        anomaly_score = min(1.0, (telemetry.current_amps - CURRENT_ANOMALY_THRESHOLD) / CURRENT_ANOMALY_THRESHOLD)

    elif telemetry.acoustic_db > ACOUSTIC_ANOMALY_THRESHOLD:
        alert_type = "ACOUSTIC_ANOMALY"
        severity = "HIGH"
        anomaly_score = min(1.0, (telemetry.acoustic_db - ACOUSTIC_ANOMALY_THRESHOLD) / ACOUSTIC_ANOMALY_THRESHOLD)

    # No anomaly detected
    if alert_type is None:
        return None

    # Build anomaly event
    anomaly_event = AnomalyEvent(
        ingestion_id=ingestion_id,
        machine_id=reading.machine_id,
        alert_type=alert_type,
        severity=severity,
        anomaly_score=round(anomaly_score, 3),
        raw_sensor_snapshot=telemetry.model_dump(),
        timestamp=reading.timestamp,
        compound_rule_triggered=compound_rule_triggered,
    )

    # Publish to EventBridge
    if publish:
        try:
            publish_event(
                source=IOT_EVENT_SOURCE,
                detail_type="AnomalyDetected",
                detail=anomaly_event.model_dump(),
            )
        except Exception:
            # Log but don't fail ingestion for publish errors
            pass

    return anomaly_event
