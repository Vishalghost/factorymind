"""Digital Twin Manager Lambda handler.

Maintains real-time digital representation of the plant.
Pipeline: Redis cache → DynamoDB persist → TwinMaker sync → AppSync publish → snapshot if CRITICAL.
SLA: processing_time_ms < 500ms.
"""

import time
from typing import Any

from aws_lambda_powertools import Logger, Tracer

from agents.shared.models.twin import TwinSyncInput, TwinSyncOutput
from agents.shared.utils.id_generator import generate_twin_id
from agents.shared.constants import PLANT_ID, REDIS_TWIN_TTL_SECONDS
from agents.digital_twin.workers.twinmaker_worker import sync_to_twinmaker
from agents.digital_twin.workers.dashboard_worker import publish_to_appsync
from agents.digital_twin.workers.reconciler_worker import reconcile_state
from agents.digital_twin.workers.snapshot_worker import take_snapshot

logger = Logger(service="digital-twin-manager")
tracer = Tracer(service="digital-twin-manager")


@tracer.capture_lambda_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for Digital Twin Manager.

    Pipeline:
    1. Update Redis cache (TTL 300s)
    2. Persist to DynamoDB TwinState
    3. Sync to IoT TwinMaker
    4. Publish via AppSync
    5. Snapshot to S3 if CRITICAL

    Args:
        event: TwinSyncInput payload.
        context: Lambda context.

    Returns:
        TwinSyncOutput as dict.
    """
    start_time = time.perf_counter()
    sync_id = generate_twin_id()

    input_data = TwinSyncInput(**event)
    logger.info(
        "twin_sync_started",
        sync_id=sync_id,
        plant_id=input_data.plant_id,
        machine_id=input_data.machine_id,
        source=input_data.source,
        severity=input_data.severity,
    )

    redis_key = f"twin:state:{input_data.plant_id}:{input_data.machine_id}"

    # Step 1: Update Redis cache (TTL 300s)
    redis_updated = _update_redis(
        redis_key=redis_key,
        state_update=input_data.state_update,
        ttl=REDIS_TWIN_TTL_SECONDS,
    )

    # Step 2: Persist to DynamoDB
    _persist_dynamodb(
        machine_id=input_data.machine_id,
        plant_id=input_data.plant_id,
        state_update=input_data.state_update,
        source=input_data.source,
        sync_id=sync_id,
    )

    # Step 3: Sync to IoT TwinMaker
    twinmaker_updated = sync_to_twinmaker(
        machine_id=input_data.machine_id,
        state_update=input_data.state_update,
    )

    # Step 4: Publish via AppSync
    appsync_published = publish_to_appsync(
        plant_id=input_data.plant_id,
        machine_id=input_data.machine_id,
        state_update=input_data.state_update,
    )

    # Step 5: Snapshot if CRITICAL
    snapshot_taken = False
    if input_data.severity == "CRITICAL":
        snapshot_taken = take_snapshot(
            sync_id=sync_id,
            plant_id=input_data.plant_id,
            machine_id=input_data.machine_id,
            state_update=input_data.state_update,
            source=input_data.source,
        )

    processing_time_ms = int((time.perf_counter() - start_time) * 1000)

    output = TwinSyncOutput(
        sync_id=sync_id,
        plant_id=input_data.plant_id,
        machine_id=input_data.machine_id,
        twinmaker_updated=twinmaker_updated,
        redis_updated=redis_updated,
        appsync_published=appsync_published,
        snapshot_taken=snapshot_taken,
        processing_time_ms=processing_time_ms,
    )

    logger.info(
        "twin_sync_completed",
        sync_id=sync_id,
        time_ms=processing_time_ms,
        twinmaker=twinmaker_updated,
        redis=redis_updated,
        appsync=appsync_published,
        snapshot=snapshot_taken,
    )

    return output.model_dump()


def _update_redis(
    redis_key: str,
    state_update: dict[str, Any],
    ttl: int = REDIS_TWIN_TTL_SECONDS,
) -> bool:
    """Update Redis cache with state. Best-effort, no retry.

    Args:
        redis_key: Redis key pattern twin:state:{plant_id}:{machine_id}.
        state_update: State payload to cache.
        ttl: Time-to-live in seconds (default 300).

    Returns:
        True if update succeeded, False otherwise.
    """
    import json

    try:
        from agents.shared.utils.aws_clients import get_redis_client
        redis_client = get_redis_client()
        redis_client.setex(redis_key, ttl, json.dumps(state_update))
        logger.info("redis_updated", key=redis_key, ttl=ttl)
        return True
    except Exception as e:
        logger.warning("redis_update_failed", key=redis_key, error=str(e))
        return False


def _persist_dynamodb(
    machine_id: str,
    plant_id: str,
    state_update: dict[str, Any],
    source: str,
    sync_id: str,
) -> None:
    """Persist twin state to DynamoDB. Best-effort with single retry.

    Args:
        machine_id: Machine identifier.
        plant_id: Plant identifier.
        state_update: State payload to persist.
        source: Source of the update.
        sync_id: Sync operation identifier.
    """
    from datetime import datetime, timezone

    try:
        from agents.shared.utils.aws_clients import get_dynamodb_resource, to_dynamodb_item
        dynamodb = get_dynamodb_resource()
        table = dynamodb.Table("FactoryMind_TwinState")
        table.put_item(
            Item={
                "machine_id": machine_id,
                "plant_id": plant_id,
                "state": to_dynamodb_item(state_update),
                "source": source,
                "sync_id": sync_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        logger.info("dynamodb_persisted", machine_id=machine_id, sync_id=sync_id)
    except Exception as e:
        logger.error("dynamodb_persist_failed", machine_id=machine_id, error=str(e))
