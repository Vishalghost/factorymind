"""Continuously publish telemetry for the full 50-machine CNC fleet.

Sends one MQTT reading per machine per cycle to factory/aerospace/cnc/telemetry,
which the IoT rule routes through Kinesis → IoT Ingestion Lambda → DynamoDB
FactoryMind_MachineState. The dashboard subscribes to AppSync mutations on
that table, so each cycle becomes a visible dashboard update.

Usage:
    python scripts/simulate_fleet.py                       # runs forever
    python scripts/simulate_fleet.py --duration 300        # 5 minutes
    python scripts/simulate_fleet.py --machines 10 --interval 3
"""

from __future__ import annotations

import argparse
import json
import random
import time
import uuid
from datetime import datetime, timezone

import boto3


def reading_for(machine_idx: int) -> dict:
    """Generate a plausible telemetry reading with mild jitter + occasional drift."""
    # Per-machine deterministic baseline so health varies across the fleet.
    rng = random.Random(machine_idx * 7919)
    base_vib = 3.0 + rng.random() * 1.5      # 3.0 - 4.5
    base_cur = 16.0 + rng.random() * 3.5     # 16 - 19.5
    base_cool = 42.0 + rng.random() * 5.0    # 42 - 47
    base_acoustic = 76 + rng.random() * 4.0  # 76 - 80

    j = lambda v, range_: v + (random.random() - 0.5) * range_
    return {
        "machine_id": f"CNC-AERO-{machine_idx:02d}",
        "plant_id": "PLANT-001",
        "reading_id": f"ING-{uuid.uuid4().hex[:12]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "telemetry": {
            "vibration_mms": round(j(base_vib, 0.6), 2),
            "current_amps": round(j(base_cur, 1.5), 2),
            "coolant_lmin": round(j(base_cool, 2.0), 2),
            "acoustic_db": round(j(base_acoustic, 2.0), 2),
        },
        "metadata": {
            "part_id": "FUS-BRACKET-992",
            "material": "Ti-6Al-4V",
            "spindle_rpm": 8400,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--machines", type=int, default=50)
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between cycles")
    parser.add_argument("--duration", type=int, default=0, help="0 = run forever")
    parser.add_argument("--topic", default="factory/aerospace/cnc/telemetry")
    args = parser.parse_args()

    client = boto3.client("iot-data", region_name=args.region)
    started = time.time()
    cycles = 0

    print(f"[*] Publishing {args.machines} machines every {args.interval}s to {args.topic}")
    try:
        while True:
            for i in range(1, args.machines + 1):
                payload = reading_for(i)
                client.publish(topic=args.topic, payload=json.dumps(payload))
            cycles += 1
            elapsed = time.time() - started
            print(f"  cycle {cycles}: {args.machines} msgs sent  (elapsed {elapsed:.1f}s)")
            if args.duration and elapsed >= args.duration:
                print("[*] Duration reached, stopping.")
                return
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[*] Stopped by user.")


if __name__ == "__main__":
    main()
