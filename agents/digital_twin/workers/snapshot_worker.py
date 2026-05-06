"""Snapshot Worker — take historical snapshots on CRITICAL events.

Stores a point-in-time snapshot of machine state to S3 when a CRITICAL
severity event occurs, enabling historical analysis and audit trails.
"""

import json
import datetime
from datetime import timezone
from typing import Any

import structlog

logger = structlog.get_logger()

SNAPSHOT_BUCKET = "factorymind-twin-snapshots"


def take_snapshot(
    sync_id: str,
    plant_id: str,
    machine_id: str,
    state_update: dict[str, Any],
    source: str,
    s3_client: Any = None,
) -> bool:
    """Take historical snapshot to S3 on CRITICAL events.

    Stores a JSON snapshot with full state context, timestamp, and
    metadata for post-incident analysis.

    Args:
        sync_id: Twin sync operation identifier.
        plant_id: Plant identifier.
        machine_id: Machine identifier.
        state_update: Current state at time of CRITICAL event.
        source: Source of the state update.
        s3_client: Optional pre-configured S3 client.

    Returns:
        True if snapshot stored successfully, False otherwise.
    """
    if s3_client is None:
        from agents.shared.utils.aws_clients import get_s3_client
        s3_client = get_s3_client()

    timestamp = datetime.datetime.now(timezone.utc)
    snapshot_key = _build_snapshot_key(plant_id, machine_id, timestamp)

    snapshot = {
        "sync_id": sync_id,
        "plant_id": plant_id,
        "machine_id": machine_id,
        "state": state_update,
        "source": source,
        "severity": "CRITICAL",
        "snapshot_timestamp": timestamp.isoformat(),
        "metadata": {
            "version": "1.0",
            "type": "critical_state_snapshot",
        },
    }

    try:
        s3_client.put_object(
            Bucket=SNAPSHOT_BUCKET,
            Key=snapshot_key,
            Body=json.dumps(snapshot, default=str),
            ContentType="application/json",
            Metadata={
                "sync_id": sync_id,
                "machine_id": machine_id,
                "severity": "CRITICAL",
            },
        )
        logger.info(
            "snapshot_taken",
            bucket=SNAPSHOT_BUCKET,
            key=snapshot_key,
            sync_id=sync_id,
            machine_id=machine_id,
        )
        return True
    except Exception as e:
        logger.error(
            "snapshot_failed",
            bucket=SNAPSHOT_BUCKET,
            key=snapshot_key,
            error=str(e),
        )
        return False


def _build_snapshot_key(
    plant_id: str,
    machine_id: str,
    timestamp: datetime.datetime,
) -> str:
    """Build S3 key for snapshot with date-partitioned path.

    Format: snapshots/{plant_id}/{machine_id}/{YYYY}/{MM}/{DD}/{timestamp}_{machine_id}.json

    Args:
        plant_id: Plant identifier.
        machine_id: Machine identifier.
        timestamp: Snapshot timestamp.

    Returns:
        S3 object key string.
    """
    date_path = timestamp.strftime("%Y/%m/%d")
    ts_str = timestamp.strftime("%Y%m%dT%H%M%S")
    return f"snapshots/{plant_id}/{machine_id}/{date_path}/{ts_str}_{machine_id}.json"
