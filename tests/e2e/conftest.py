"""Shared fixtures for E2E tests.

Reuses the integration conftest setup but adds whole-system orchestration:
e.g., chaining IoT ingestion → Brain delegation, Edge AI escalation → Brain.
"""

# E2E fixtures inherit from tests/integration/conftest.py via path-based collection
# (pytest auto-discovers conftest.py at every level). To keep things simple, we
# re-import the same fixtures here.

from tests.integration.conftest import (  # noqa: F401
    aws_credentials,
    mocked_aws,
    fake_redis,
    aws_resources,
    fresh_now,
    critical_telemetry,
    healthy_telemetry,
    reset_onnx_cache,
    reset_boto_cache,
)
