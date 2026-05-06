#!/usr/bin/env python3
"""Aerospace CNC Titanium Milling Simulator.

Generates realistic sensor telemetry for Ti-6Al-4V machining operations
and publishes to AWS IoT Core MQTT topic: factory/aerospace/cnc/telemetry

Simulation Modes:
- OPTIMAL: Normal Gaussian noise around baseline values
- TOOL_WEAR: Gradual current/vibration increase over 5 minutes
- CATASTROPHIC_FAILURE: Instant coolant drop + vibration spike

Usage:
    python scripts/simulate_aerospace_cnc.py --machine-id CNC-AERO-01 --mode optimal
    python scripts/simulate_aerospace_cnc.py --machine-id CNC-AERO-01 --mode tool_wear --duration 300
    python scripts/simulate_aerospace_cnc.py --machine-id CNC-AERO-01 --mode catastrophic
"""

import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from enum import Enum

import numpy as np


class SimulationMode(str, Enum):
    OPTIMAL = "optimal"
    TOOL_WEAR = "tool_wear"
    CATASTROPHIC = "catastrophic"


# Baseline values for Ti-6Al-4V milling (normal operation)
BASELINES = {
    "vibration_mms": 3.4,   # mm/s
    "current_amps": 18.2,   # Amps
    "coolant_lmin": 45.1,   # L/min
    "acoustic_db": 78.5,    # dB
}

# Standard deviations for Gaussian noise (normal operation)
NOISE_STD = {
    "vibration_mms": 0.5,
    "current_amps": 1.0,
    "coolant_lmin": 1.5,
    "acoustic_db": 2.0,
}

# Tool wear rates (per hour)
WEAR_RATES = {
    "current_amps": 0.5,    # +0.5 A/hour
    "vibration_mms": 0.3,   # +0.3 mm/s/hour
}


def generate_reading(
    machine_id: str,
    mode: SimulationMode,
    elapsed_seconds: float,
    part_id: str = "FUS-BRACKET-992",
) -> dict:
    """Generate a single sensor reading based on simulation mode.

    Args:
        machine_id: CNC machine identifier.
        mode: Current simulation mode.
        elapsed_seconds: Time elapsed since simulation start.
        part_id: Current part being machined.

    Returns:
        Complete sensor reading payload dict.
    """
    if mode == SimulationMode.OPTIMAL:
        telemetry = _generate_optimal()
    elif mode == SimulationMode.TOOL_WEAR:
        telemetry = _generate_tool_wear(elapsed_seconds)
    elif mode == SimulationMode.CATASTROPHIC:
        telemetry = _generate_catastrophic()
    else:
        telemetry = _generate_optimal()

    reading = {
        "reading_id": f"ING-{uuid.uuid4().hex[:8]}",
        "machine_id": machine_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "telemetry": telemetry,
        "metadata": {
            "part_id": part_id,
            "material": "Ti-6Al-4V",
            "spindle_rpm": 3500,
        },
    }
    return reading


def _generate_optimal() -> dict:
    """MODE_OPTIMAL: Normal Gaussian noise around baselines."""
    return {
        "vibration_mms": round(
            max(0.1, np.random.normal(BASELINES["vibration_mms"], NOISE_STD["vibration_mms"])), 2
        ),
        "current_amps": round(
            max(0.1, np.random.normal(BASELINES["current_amps"], NOISE_STD["current_amps"])), 2
        ),
        "coolant_lmin": round(
            max(0.1, np.random.normal(BASELINES["coolant_lmin"], NOISE_STD["coolant_lmin"])), 2
        ),
        "acoustic_db": round(
            max(0.1, np.random.normal(BASELINES["acoustic_db"], NOISE_STD["acoustic_db"])), 2
        ),
    }


def _generate_tool_wear(elapsed_seconds: float) -> dict:
    """MODE_TOOL_WEAR: Gradual increase in current and vibration over time.

    Simulates a dull tool that's progressively struggling to cut titanium.
    Over 5 minutes (300s), current increases by ~2.5A and vibration by ~1.5 mm/s.
    """
    elapsed_hours = elapsed_seconds / 3600.0

    # Gradual increase with noise
    current_offset = WEAR_RATES["current_amps"] * elapsed_hours * 12  # Accelerated for demo
    vibration_offset = WEAR_RATES["vibration_mms"] * elapsed_hours * 12

    return {
        "vibration_mms": round(
            max(0.1, np.random.normal(
                BASELINES["vibration_mms"] + vibration_offset,
                NOISE_STD["vibration_mms"] * 0.5,
            )), 2
        ),
        "current_amps": round(
            max(0.1, np.random.normal(
                BASELINES["current_amps"] + current_offset,
                NOISE_STD["current_amps"] * 0.5,
            )), 2
        ),
        "coolant_lmin": round(
            max(0.1, np.random.normal(BASELINES["coolant_lmin"], NOISE_STD["coolant_lmin"])), 2
        ),
        "acoustic_db": round(
            max(0.1, np.random.normal(
                BASELINES["acoustic_db"] + vibration_offset * 2,
                NOISE_STD["acoustic_db"],
            )), 2
        ),
    }


def _generate_catastrophic() -> dict:
    """MODE_CATASTROPHIC_FAILURE: Instant coolant drop + vibration spike.

    Simulates coolant line blockage with immediate tool overload.
    This should trigger the Edge AI compound rule:
    vibration >8.0 AND coolant <30.0 → IMMEDIATE SPINDLE STOP
    """
    return {
        "vibration_mms": round(np.random.normal(12.0, 1.0), 2),  # Severe spike
        "current_amps": round(np.random.normal(38.0, 2.0), 2),   # Overloaded
        "coolant_lmin": round(max(0.1, np.random.normal(10.0, 3.0)), 2),  # Blocked
        "acoustic_db": round(np.random.normal(98.0, 3.0), 2),    # Screeching
    }


def run_simulation(
    machine_id: str,
    mode: SimulationMode,
    duration_seconds: int,
    publish_to_iot: bool = False,
    iot_endpoint: str | None = None,
) -> list[dict]:
    """Run the CNC sensor simulation loop.

    Args:
        machine_id: Target CNC machine ID.
        mode: Simulation mode (optimal, tool_wear, catastrophic).
        duration_seconds: How long to run the simulation.
        publish_to_iot: Whether to publish to AWS IoT Core.
        iot_endpoint: AWS IoT Core endpoint (required if publish_to_iot=True).

    Returns:
        List of all generated readings.
    """
    mqtt_client = None
    if publish_to_iot and iot_endpoint:
        mqtt_client = _setup_mqtt_client(iot_endpoint, machine_id)

    readings = []
    start_time = time.time()
    reading_count = 0

    print(f"Starting simulation: machine={machine_id}, mode={mode.value}, duration={duration_seconds}s")
    print(f"Publishing at 1 Hz to topic: factory/aerospace/cnc/telemetry")
    print("-" * 60)

    try:
        while (time.time() - start_time) < duration_seconds:
            elapsed = time.time() - start_time
            reading = generate_reading(machine_id, mode, elapsed)
            readings.append(reading)
            reading_count += 1

            # Print to console
            t = reading["telemetry"]
            print(
                f"[{reading_count:04d}] "
                f"vib={t['vibration_mms']:5.2f} mm/s | "
                f"cur={t['current_amps']:5.2f} A | "
                f"cool={t['coolant_lmin']:5.2f} L/min | "
                f"aco={t['acoustic_db']:5.2f} dB"
            )

            # Publish to MQTT if configured
            if mqtt_client:
                topic = "factory/aerospace/cnc/telemetry"
                mqtt_client.publish(topic, json.dumps(reading), qos=1)

            # 1 Hz sampling rate
            time.sleep(1.0)

    except KeyboardInterrupt:
        print("\nSimulation interrupted by user.")

    print(f"\nSimulation complete: {reading_count} readings generated in {mode.value} mode.")
    return readings


def _setup_mqtt_client(endpoint: str, client_id: str):
    """Set up AWS IoT Core MQTT client.

    Requires certificates in ./certs/ directory.
    """
    try:
        from awsiot import mqtt_connection_builder
        from awscrt import mqtt

        connection = mqtt_connection_builder.mtls_from_path(
            endpoint=endpoint,
            cert_filepath="./certs/device.pem.crt",
            pri_key_filepath="./certs/private.pem.key",
            ca_filepath="./certs/AmazonRootCA1.pem",
            client_id=client_id,
            clean_session=False,
            keep_alive_secs=30,
        )
        connect_future = connection.connect()
        connect_future.result()
        print(f"Connected to IoT Core: {endpoint}")
        return connection
    except ImportError:
        print("WARNING: AWSIoTPythonSDK not installed. Running in local-only mode.")
        return None
    except Exception as e:
        print(f"WARNING: Could not connect to IoT Core: {e}. Running in local-only mode.")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Aerospace CNC Titanium Milling Sensor Simulator"
    )
    parser.add_argument(
        "--machine-id",
        default="CNC-AERO-01",
        help="CNC machine identifier (default: CNC-AERO-01)",
    )
    parser.add_argument(
        "--mode",
        choices=["optimal", "tool_wear", "catastrophic"],
        default="optimal",
        help="Simulation mode (default: optimal)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Duration in seconds (default: 60)",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish to AWS IoT Core MQTT",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="AWS IoT Core endpoint URL",
    )

    args = parser.parse_args()

    mode = SimulationMode(args.mode)
    run_simulation(
        machine_id=args.machine_id,
        mode=mode,
        duration_seconds=args.duration,
        publish_to_iot=args.publish,
        iot_endpoint=args.endpoint,
    )


if __name__ == "__main__":
    main()
