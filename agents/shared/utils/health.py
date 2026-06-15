"""Derive dashboard machine status + health from telemetry and anomaly severity."""
from typing import Any, Optional

# Normal-operation reference points for titanium milling (see constants.py).
_NOMINAL = {"vibration_mms": 3.5, "current_amps": 18.0, "coolant_lmin": 45.0, "acoustic_db": 78.0}
_ANOMALY = {"vibration_mms": 8.0, "current_amps": 35.0, "coolant_lmin": 30.0, "acoustic_db": 95.0}

_STATUS_BY_SEVERITY = {"CRITICAL": "FAULT", "HIGH": "MAINTENANCE", "MEDIUM": "MAINTENANCE"}


def derive_status_health(severity: Optional[str], telemetry: dict[str, Any]) -> tuple[str, float]:
    """Map (severity, telemetry) → (status, health_score 0..1)."""
    status = _STATUS_BY_SEVERITY.get(severity or "", "RUNNING")
    health = _telemetry_health(telemetry)
    # Floor health for explicit anomalies so the badge matches the status.
    if severity == "CRITICAL":
        health = min(health, 0.2)
    elif severity in ("HIGH", "MEDIUM"):
        health = min(health, 0.6)
    return status, round(max(0.0, min(1.0, health)), 3)


def _telemetry_health(telemetry: dict[str, Any]) -> float:
    """Worst-channel health: the sensor closest to failing drives the score.

    For each channel, ``frac`` is how far the value has moved from _NOMINAL
    toward _ANOMALY (0 = nominal, 1 = at the anomaly threshold). Coolant is
    inverted automatically because its anomaly point is *below* nominal, so the
    (anom - nom) denominator is negative and the sign flips. We take the worst
    channel and map the anomaly threshold to mid-health (0.5) so threshold-
    crossing telemetry reads as "degraded" rather than "dead" — confirmed
    anomalies are driven lower by the severity floor in derive_status_health.
    """
    worst = 0.0
    for ch, nom in _NOMINAL.items():
        val = telemetry.get(ch)
        if val is None:
            continue
        frac = (val - nom) / (_ANOMALY[ch] - nom)
        worst = max(worst, max(0.0, frac))
    return max(0.0, min(1.0, 1.0 - 0.5 * worst))
