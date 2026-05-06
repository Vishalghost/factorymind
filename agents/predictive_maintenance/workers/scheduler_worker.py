"""Scheduler Worker — apply consensus rule for severity classification.

Consensus Rule:
- BOTH LSTM and Lookout must agree for CRITICAL classification
- Single model CRITICAL → downgrade to HIGH
- Both HIGH → HIGH
- Mixed HIGH/MEDIUM → HIGH
- Both MEDIUM or lower → MEDIUM
"""

import structlog

logger = structlog.get_logger()

SEVERITY_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}


def apply_consensus(
    lstm_severity: str,
    lookout_severity: str,
) -> tuple[bool, str]:
    """Apply consensus rule to determine final severity.

    Args:
        lstm_severity: Severity from LSTM model.
        lookout_severity: Severity from Lookout for Equipment.

    Returns:
        Tuple of (consensus_reached, final_severity).
        consensus_reached is True only when both agree on CRITICAL.
    """
    logger.info(
        "applying_consensus",
        lstm=lstm_severity,
        lookout=lookout_severity,
    )

    # Both CRITICAL → consensus reached, final = CRITICAL
    if lstm_severity == "CRITICAL" and lookout_severity == "CRITICAL":
        return True, "CRITICAL"

    # One CRITICAL, other not → no consensus, downgrade to HIGH
    if lstm_severity == "CRITICAL" or lookout_severity == "CRITICAL":
        return False, "HIGH"

    # Both HIGH → HIGH (no consensus needed for non-CRITICAL)
    if lstm_severity == "HIGH" and lookout_severity == "HIGH":
        return False, "HIGH"

    # One HIGH → HIGH
    if lstm_severity == "HIGH" or lookout_severity == "HIGH":
        return False, "HIGH"

    # Both MEDIUM → MEDIUM
    if lstm_severity == "MEDIUM" or lookout_severity == "MEDIUM":
        return False, "MEDIUM"

    # Both LOW → LOW
    return False, "LOW"
