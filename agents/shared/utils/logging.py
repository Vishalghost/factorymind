"""Structured logging configuration using structlog + aws-lambda-powertools."""

import structlog
from aws_lambda_powertools import Logger


def configure_logging(service_name: str) -> structlog.BoundLogger:
    """Configure structlog with JSON output for Lambda.

    Args:
        service_name: Name of the agent/service for log correlation.

    Returns:
        Configured structlog logger instance.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    return structlog.get_logger(service=service_name)


def get_powertools_logger(service_name: str) -> Logger:
    """Get aws-lambda-powertools Logger for Lambda observability."""
    return Logger(service=service_name)
