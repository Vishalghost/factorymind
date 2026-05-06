"""Exponential backoff retry decorator for AWS service calls."""

import time
import functools
from typing import Any, Callable, TypeVar

import structlog

logger = structlog.get_logger()

F = TypeVar("F", bound=Callable[..., Any])


def with_retry(
    max_retries: int = 1,
    base_delay: float = 0.5,
    exceptions: tuple = (Exception,),
) -> Callable[[F], F]:
    """Decorator for exponential backoff retry.

    All agents retry once except Edge AI (which never retries).

    Args:
        max_retries: Maximum number of retry attempts (default 1).
        base_delay: Base delay in seconds before first retry.
        exceptions: Tuple of exception types to catch and retry.

    Returns:
        Decorated function with retry logic.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = base_delay * (2**attempt)
                        logger.warning(
                            "retry_attempt",
                            function=func.__name__,
                            attempt=attempt + 1,
                            max_retries=max_retries,
                            delay_seconds=delay,
                            error=str(e),
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "retry_exhausted",
                            function=func.__name__,
                            attempts=max_retries + 1,
                            error=str(e),
                        )
            raise last_exception  # type: ignore

        return wrapper  # type: ignore

    return decorator
