"""Boto3 client factory for FactoryMind AWS services."""

import os
from decimal import Decimal
from functools import lru_cache
from typing import Any

import boto3
import redis

from agents.shared.constants import REDIS_TWIN_TTL_SECONDS


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
def get_redis_client() -> redis.Redis:
    """Get cached Redis client for ElastiCache.

    Connects to the Redis endpoint specified by REDIS_HOST and REDIS_PORT
    environment variables. Defaults to localhost:6379 for local development.

    Returns:
        Configured redis.Redis client instance.
    """
    host = os.environ.get("REDIS_HOST", "localhost")
    port = int(os.environ.get("REDIS_PORT", "6379"))
    db = int(os.environ.get("REDIS_DB", "0"))
    return redis.Redis(
        host=host,
        port=port,
        db=db,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
