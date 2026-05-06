"""Boto3 client factory for FactoryMind AWS services."""

import os
from decimal import Decimal
from functools import lru_cache
from typing import Any

import boto3

from agents.shared.constants import REDIS_TWIN_TTL_SECONDS

# ``redis`` is only required by Edge AI / Digital Twin / IoT Ingestion Lambdas
# that actually use ElastiCache. The AgentCore Runtime image ships without it
# to keep the image small, so we import lazily inside ``get_redis_client``.


def to_dynamodb_item(value: Any) -> Any:
    """Recursively convert Python floats to Decimal for DynamoDB put_item.

    The boto3 DynamoDB resource API rejects Python floats outright (DynamoDB
    only stores numbers as decimal). Every agent that writes telemetry, scores,
    or processing-time values must run its payload through this first.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [to_dynamodb_item(v) for v in value]
    if isinstance(value, tuple):
        return [to_dynamodb_item(v) for v in value]
    if isinstance(value, dict):
        return {k: to_dynamodb_item(v) for k, v in value.items()}
    return value


@lru_cache(maxsize=16)
def get_dynamodb_client() -> Any:
    """Get cached DynamoDB client."""
    return boto3.client("dynamodb")


@lru_cache(maxsize=16)
def get_dynamodb_resource() -> Any:
    """Get cached DynamoDB resource."""
    return boto3.resource("dynamodb")


@lru_cache(maxsize=16)
def get_timestream_write_client() -> Any:
    """Get cached Timestream Write client."""
    return boto3.client("timestream-write")


@lru_cache(maxsize=16)
def get_timestream_query_client() -> Any:
    """Get cached Timestream Query client."""
    return boto3.client("timestream-query")


@lru_cache(maxsize=16)
def get_s3_client() -> Any:
    """Get cached S3 client."""
    return boto3.client("s3")


@lru_cache(maxsize=16)
def get_eventbridge_client() -> Any:
    """Get cached EventBridge client."""
    return boto3.client("events")


@lru_cache(maxsize=16)
def get_sqs_client() -> Any:
    """Get cached SQS client."""
    return boto3.client("sqs")


@lru_cache(maxsize=16)
def get_lambda_client() -> Any:
    """Get cached Lambda client."""
    return boto3.client("lambda")


@lru_cache(maxsize=16)
def get_sagemaker_runtime_client() -> Any:
    """Get cached SageMaker Runtime client."""
    return boto3.client("sagemaker-runtime")


@lru_cache(maxsize=1)
def get_redis_client() -> Any:
    """Get cached Redis client for ElastiCache (Serverless or cluster).

    Reads connection params from env vars:
      REDIS_HOST  — endpoint hostname (default: localhost)
      REDIS_PORT  — endpoint port (default: 6379)
      REDIS_DB    — logical database number (default: 0)
      REDIS_TLS   — "true" to enable TLS (required for ElastiCache Serverless)

    ElastiCache Serverless ALWAYS requires TLS; deploy.sh sets REDIS_TLS=true
    on the Edge AI and Digital Twin Lambdas after stack deploy.
    """
    import redis  # imported lazily — see module docstring

    host = os.environ.get("REDIS_HOST", "localhost")
    port = int(os.environ.get("REDIS_PORT", "6379"))
    db = int(os.environ.get("REDIS_DB", "0"))
    use_tls = os.environ.get("REDIS_TLS", "false").lower() == "true"

    return redis.Redis(
        host=host,
        port=port,
        db=db,
        ssl=use_tls,
        ssl_cert_reqs=None if use_tls else "required",
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
