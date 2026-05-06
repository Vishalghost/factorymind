"""Cloud Escalator Worker — fire-and-forget EventBridge publish for ANOMALY.

Rules:
- Never retry failed escalation attempts
- Never wait for cloud response
- Publish EDGR- alert to EventBridge asynchronously
"""

from typing import Any

import structlog

from agents.shared.constants import EDGE_EVENT_SOURCE, EVENT_BUS_NAME
from agents.shared.utils.id_generator import generate_edge_id

logger = structlog.get_logger()


def escalate_to_cloud(
    machine_id: str,
    sensor_values: dict[str, Any],
    confidence: float,
    compound_rule_triggered: bool,
    timestamp: str,
    client: Any = None,
) -> str | None:
    """Fire-and-forget escalation to EventBridge.

    NO retry. NO wait. If it fails, log and move on.

    Args:
        machine_id: CNC machine identifier.
        sensor_values: Current telemetry snapshot.
        confidence: Classification confidence score.
        compound_rule_triggered: Whether compound rule was triggered.
        timestamp: Reading timestamp.
        client: Optional pre-configured EventBridge client.

    Returns:
        Escalation event ID if published, None if failed.
    """
    import json

    if client is None:
        import boto3
        client = boto3.client("events")

    escalation_id = generate_edge_id()

    # Detail must satisfy the Brain Agent's BrainInput schema since the
    # EventBridge rule routes this directly to the Brain Lambda. Required
    # fields: machine_id, alert_type, severity, timestamp, raw_sensor_snapshot.
    severity = "CRITICAL" if compound_rule_triggered else "HIGH"
    alert_type = "COMPOUND_FAILURE" if compound_rule_triggered else "EDGE_ANOMALY"

    detail = {
        "edge_result_id": escalation_id,
        "machine_id": machine_id,
        "alert_type": alert_type,
        "severity": severity,
        "timestamp": timestamp,
        "raw_sensor_snapshot": sensor_values,
        "classification": "ANOMALY",
        "confidence": confidence,
        "compound_rule_triggered": compound_rule_triggered,
        "action": "IMMEDIATE_SPINDLE_STOP" if compound_rule_triggered else "ESCALATE",
    }

    try:
        client.put_events(
            Entries=[{
                "Source": EDGE_EVENT_SOURCE,
                "DetailType": "EdgeEscalation",
                "Detail": json.dumps(detail),
                "EventBusName": EVENT_BUS_NAME,
            }]
        )
        logger.info(
            "escalation_published",
            escalation_id=escalation_id,
            machine_id=machine_id,
            compound=compound_rule_triggered,
        )
        return escalation_id
    except Exception as e:
        # Fire-and-forget: log error but DO NOT retry
        logger.error(
            "escalation_failed",
            escalation_id=escalation_id,
            error=str(e),
        )
        return None
