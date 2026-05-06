"""Parallel invocation utility for multi-manager delegation.

Uses concurrent.futures ThreadPoolExecutor to invoke multiple
Manager Agent Lambda functions in parallel, ensuring the full
delegation chain completes within the 2000ms SLA.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import structlog

from agents.shared.constants import SLA_BRAIN_AGENT_MS
from agents.brain.tools.invoke_iot_ingestion import invoke_iot_ingestion
from agents.brain.tools.invoke_quality_vision import invoke_quality_vision
from agents.brain.tools.invoke_predictive_maintenance import invoke_predictive_maintenance
from agents.brain.tools.invoke_sustainability import invoke_sustainability
from agents.brain.tools.invoke_digital_twin import invoke_digital_twin

logger = structlog.get_logger()

# Map manager names to their invocation functions
MANAGER_INVOKE_MAP: dict[str, Any] = {
    "iot_ingestion": invoke_iot_ingestion,
    "quality_vision": invoke_quality_vision,
    "predictive_maintenance": invoke_predictive_maintenance,
    "sustainability": invoke_sustainability,
    "digital_twin": invoke_digital_twin,
}


def invoke_managers_parallel(
    targets: list[str],
    machine_id: str,
    plant_id: str,
    alert_type: str,
    raw_sensor_snapshot: dict[str, Any],
    timestamp: str,
    severity: str,
    timeout_ms: int = SLA_BRAIN_AGENT_MS,
) -> dict[str, Any]:
    """Invoke multiple Manager Agents in parallel.

    Uses ThreadPoolExecutor to invoke all delegation targets concurrently.
    Each manager invocation is best-effort: if one fails, the others
    continue and the error is recorded in the results.

    Args:
        targets: List of manager names to invoke (e.g., ["predictive_maintenance", "digital_twin"]).
        machine_id: Target machine identifier.
        plant_id: Plant identifier.
        alert_type: Type of alert triggering delegation.
        raw_sensor_snapshot: Current sensor values.
        timestamp: ISO 8601 timestamp of the event.
        severity: Assessed severity level.
        timeout_ms: Maximum time allowed for all invocations (default: 2000ms).

    Returns:
        Dictionary mapping manager names to their results or error details.
    """
    if not targets:
        return {}

    start_ms = time.time()
    results: dict[str, Any] = {}
    timeout_seconds = timeout_ms / 1000.0

    logger.info(
        "parallel_invocation_started",
        targets=targets,
        machine_id=machine_id,
        severity=severity,
    )

    with ThreadPoolExecutor(max_workers=len(targets)) as executor:
        future_to_manager = {}

        for target in targets:
            invoke_fn = MANAGER_INVOKE_MAP.get(target)
            if invoke_fn is None:
                results[target] = {
                    "error": f"Unknown manager: {target}",
                    "status": "failed",
                }
                continue

            # Digital Twin has a different signature
            if target == "digital_twin":
                future = executor.submit(
                    invoke_fn,
                    machine_id=machine_id,
                    plant_id=plant_id,
                    raw_sensor_snapshot=raw_sensor_snapshot,
                    severity=severity,
                )
            else:
                future = executor.submit(
                    invoke_fn,
                    machine_id=machine_id,
                    plant_id=plant_id,
                    alert_type=alert_type,
                    raw_sensor_snapshot=raw_sensor_snapshot,
                    timestamp=timestamp,
                    severity=severity,
                )

            future_to_manager[future] = target

        # Collect results with timeout
        for future in as_completed(future_to_manager, timeout=timeout_seconds):
            manager_name = future_to_manager[future]
            try:
                result = future.result()
                results[manager_name] = result
            except Exception as e:
                results[manager_name] = {
                    "error": str(e),
                    "status": "failed",
                }
                logger.warning(
                    "manager_invocation_failed",
                    manager=manager_name,
                    error=str(e),
                )

    # Record any managers that didn't complete in time
    for future, manager_name in future_to_manager.items():
        if manager_name not in results:
            results[manager_name] = {
                "error": "Invocation timed out",
                "status": "timeout",
            }
            logger.warning(
                "manager_invocation_timeout",
                manager=manager_name,
                timeout_ms=timeout_ms,
            )

    elapsed_ms = int((time.time() - start_ms) * 1000)

    logger.info(
        "parallel_invocation_complete",
        targets=targets,
        elapsed_ms=elapsed_ms,
        results_count=len(results),
        within_sla=elapsed_ms < timeout_ms,
    )

    return results
