"""Reconciler Worker — detect and resolve Redis/DynamoDB state divergence.

Detects when the Redis cache and DynamoDB twin state diverge,
and reconciles by treating DynamoDB as the source of truth.
"""

import json
from typing import Any

import structlog

from agents.shared.constants import REDIS_TWIN_TTL_SECONDS

logger = structlog.get_logger()


def reconcile_state(
    plant_id: str,
    machine_id: str,
    redis_client: Any = None,
    dynamodb_resource: Any = None,
) -> dict[str, Any]:
    """Detect Redis/DynamoDB divergence and reconcile.

    DynamoDB is the source of truth. If Redis state differs from
    DynamoDB, Redis is overwritten with the DynamoDB value.

    Args:
        plant_id: Plant identifier.
        machine_id: Machine identifier.
        redis_client: Optional pre-configured Redis client.
        dynamodb_resource: Optional pre-configured DynamoDB resource.

    Returns:
        Reconciliation result with divergence details.
    """
    if redis_client is None:
        from agents.shared.utils.aws_clients import get_redis_client
        redis_client = get_redis_client()

    if dynamodb_resource is None:
        from agents.shared.utils.aws_clients import get_dynamodb_resource
        dynamodb_resource = get_dynamodb_resource()

    redis_key = f"twin:state:{plant_id}:{machine_id}"

    # Read from both sources
    redis_state = _get_redis_state(redis_client, redis_key)
    dynamo_state = _get_dynamodb_state(dynamodb_resource, machine_id)

    # Compare states
    diverged = _states_diverged(redis_state, dynamo_state)

    result = {
        "machine_id": machine_id,
        "plant_id": plant_id,
        "diverged": diverged,
        "reconciled": False,
        "source_of_truth": "dynamodb",
    }

    if diverged and dynamo_state is not None:
        # Reconcile: overwrite Redis with DynamoDB state
        _reconcile_redis(redis_client, redis_key, dynamo_state)
        result["reconciled"] = True
        logger.info(
            "state_reconciled",
            machine_id=machine_id,
            plant_id=plant_id,
        )
    elif diverged and dynamo_state is None:
        logger.warning(
            "reconciliation_skipped_no_dynamo",
            machine_id=machine_id,
        )
    else:
        logger.debug(
            "states_consistent",
            machine_id=machine_id,
        )

    return result


def _get_redis_state(redis_client: Any, redis_key: str) -> dict[str, Any] | None:
    """Read state from Redis cache.

    Args:
        redis_client: Redis client instance.
        redis_key: Cache key.

    Returns:
        Parsed state dict or None if not found.
    """
    try:
        raw = redis_client.get(redis_key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning("redis_read_failed", key=redis_key, error=str(e))
        return None


def _get_dynamodb_state(
    dynamodb_resource: Any,
    machine_id: str,
) -> dict[str, Any] | None:
    """Read state from DynamoDB TwinState table.

    Args:
        dynamodb_resource: DynamoDB resource instance.
        machine_id: Machine identifier (primary key).

    Returns:
        State dict from DynamoDB or None if not found.
    """
    try:
        table = dynamodb_resource.Table("FactoryMind_TwinState")
        response = table.get_item(Key={"machine_id": machine_id})
        item = response.get("Item")
        if item is None:
            return None
        return item.get("state")
    except Exception as e:
        logger.warning("dynamodb_read_failed", machine_id=machine_id, error=str(e))
        return None


def _states_diverged(
    redis_state: dict[str, Any] | None,
    dynamo_state: dict[str, Any] | None,
) -> bool:
    """Compare Redis and DynamoDB states for divergence.

    Args:
        redis_state: State from Redis (may be None).
        dynamo_state: State from DynamoDB (may be None).

    Returns:
        True if states differ, False if consistent.
    """
    if redis_state is None and dynamo_state is None:
        return False
    if redis_state is None or dynamo_state is None:
        return True
    return redis_state != dynamo_state


def _reconcile_redis(
    redis_client: Any,
    redis_key: str,
    dynamo_state: dict[str, Any],
) -> None:
    """Overwrite Redis with DynamoDB state (source of truth).

    Args:
        redis_client: Redis client instance.
        redis_key: Cache key to overwrite.
        dynamo_state: Authoritative state from DynamoDB.
    """
    try:
        redis_client.setex(redis_key, REDIS_TWIN_TTL_SECONDS, json.dumps(dynamo_state))
        logger.info("redis_reconciled", key=redis_key)
    except Exception as e:
        logger.error("redis_reconcile_failed", key=redis_key, error=str(e))
