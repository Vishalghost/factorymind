"""E2E test: tool wear trending path.

Path under test:
    Steady current/vibration increase over time → IoT Ingestion Manager →
    eventually trips HIGH threshold → AnomalyDetected event → Brain Agent →
    Predictive Maintenance Manager → Work Order created.

The simulator's TOOL_WEAR mode is the production analogue. This test compresses
the simulation into a handful of synthesized batches.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from agents.iot_ingestion.manager.handler import handler as ingestion_handler


def _reading(vibration: float, current: float, coolant: float = 45.0, acoustic: float = 78.5) -> dict:
    return {
        "reading_id": f"ING-{uuid4().hex[:8]}",
        "machine_id": "CNC-AERO-12",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "telemetry": {
            "vibration_mms": vibration,
            "current_amps": current,
            "coolant_lmin": coolant,
            "acoustic_db": acoustic,
        },
        "metadata": {
            "part_id": "FUS-BRACKET-992",
            "material": "Ti-6Al-4V",
            "spindle_rpm": 3500,
        },
    }


class TestToolWearPath:
    def test_progression_from_normal_to_high_severity(self, aws_resources):
        """Stage 1 normal, Stage 2 warning zone, Stage 3 trips HIGH.

        Verifies that the same machine moves through clean → warning → anomalous
        as wear accumulates. Each stage is its own ingestion batch.
        """
        # Stage 1: normal — no anomaly
        normal = ingestion_handler(
            {"plant_id": "PLANT-001", "records": [_reading(3.5, 18.5)]},
            context=None,
        )
        assert normal["anomalies_detected"] == 0

        # Stage 2: warning zone — still no formal anomaly, but readings drift
        warning = ingestion_handler(
            {"plant_id": "PLANT-001", "records": [_reading(6.5, 28.0)]},
            context=None,
        )
        assert warning["anomalies_detected"] == 0

        # Stage 3: vibration crosses HIGH threshold
        anomalous = ingestion_handler(
            {"plant_id": "PLANT-001", "records": [_reading(9.0, 32.0)]},
            context=None,
        )
        assert anomalous["anomalies_detected"] == 1
        anomaly = anomalous["anomaly_events"][0]
        assert anomaly["severity"] == "HIGH"
        assert anomaly["alert_type"] == "VIBRATION_ANOMALY"

    def test_current_spike_alone_triggers_high(self, aws_resources):
        """Current >35.0 with healthy other sensors should trigger HIGH only."""
        result = ingestion_handler(
            {"plant_id": "PLANT-001", "records": [_reading(4.0, 38.0, coolant=45.0)]},
            context=None,
        )
        assert result["anomalies_detected"] == 1
        anomaly = result["anomaly_events"][0]
        # CURRENT_SPIKE is HIGH severity (per anomaly_detector). Coolant is fine,
        # so compound rule does not trigger.
        assert anomaly["alert_type"] == "CURRENT_SPIKE"
        assert anomaly["severity"] == "HIGH"
