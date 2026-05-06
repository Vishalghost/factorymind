#!/usr/bin/env python3
"""Seed FactoryMind DynamoDB tables with aerospace CNC reference data.

Populates:
  - FactoryMind_MachineSpecs:        50 CNC machines (CNC-AERO-01..50), Ti-6Al-4V
  - FactoryMind_MachineState:        initial RUNNING state per machine, health=1.0
  - FactoryMind_EnergyBaselines:     baseline kWh per machine for sustainability KPIs
  - FactoryMind_QualityThresholds:   per-product defect rate thresholds
  - FactoryMind_EdgeThresholds:      per-machine NORMAL/WARNING/ANOMALY zones
  - FactoryMind_FloorLayout:         3 production lines (LINE-A/B/C) × 50 machines

Usage:
    # Seed live AWS account (requires AWS credentials + tables already provisioned)
    python scripts/seed_dummy_data.py

    # Seed against local DynamoDB (LocalStack or DynamoDB Local on :4566 / :8000)
    python scripts/seed_dummy_data.py --endpoint-url http://localhost:4566

    # Dry run — print payloads without writing
    python scripts/seed_dummy_data.py --dry-run
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

import boto3

from agents.shared.utils.aws_clients import to_dynamodb_item
from agents.shared.constants import (
    ACOUSTIC_ANOMALY_THRESHOLD,
    ACOUSTIC_NORMAL_MAX,
    ACOUSTIC_NORMAL_MIN,
    ACOUSTIC_WARNING_MAX,
    COOLANT_ANOMALY_THRESHOLD,
    COOLANT_NORMAL_MAX,
    COOLANT_NORMAL_MIN,
    COOLANT_WARNING_MIN,
    CURRENT_ANOMALY_THRESHOLD,
    CURRENT_NORMAL_MAX,
    CURRENT_NORMAL_MIN,
    CURRENT_WARNING_MAX,
    MACHINE_COUNT,
    MACHINE_PREFIX,
    MACHINE_TYPE,
    MATERIAL,
    PLANT_ID,
    PLANT_NAME,
    PRODUCTION_LINES,
    SIM_ACOUSTIC_BASELINE,
    SIM_COOLANT_BASELINE,
    SIM_CURRENT_BASELINE,
    SIM_SPINDLE_RPM,
    SIM_VIBRATION_BASELINE,
    VIBRATION_ANOMALY_THRESHOLD,
    VIBRATION_NORMAL_MAX,
    VIBRATION_NORMAL_MIN,
    VIBRATION_WARNING_MAX,
)


def machine_ids() -> list[str]:
    """Return MACHINE_PREFIX-NN for 1..MACHINE_COUNT."""
    return [f"{MACHINE_PREFIX}{i:02d}" for i in range(1, MACHINE_COUNT + 1)]


def line_for(machine_id: str) -> str:
    """Distribute machines round-robin across production lines."""
    idx = int(machine_id.split("-")[-1])
    return PRODUCTION_LINES[(idx - 1) % len(PRODUCTION_LINES)]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------
# Table seed payload builders
# ---------------------------------------------------------------


def build_machine_specs() -> list[dict[str, Any]]:
    """Static specs for each CNC machine: type, install date, max RPM, etc."""
    items = []
    for mid in machine_ids():
        items.append(
            {
                "machine_id": mid,
                "plant_id": PLANT_ID,
                "machine_type": MACHINE_TYPE,
                "production_line": line_for(mid),
                "manufacturer": "Mazak",
                "model": "VARIAXIS i-700",
                "max_spindle_rpm": 12000,
                "nominal_spindle_rpm": SIM_SPINDLE_RPM,
                "material_supported": [MATERIAL, "Inconel-718", "Aluminum-7075"],
                "install_date": "2023-04-15",
                "last_calibration": "2026-04-01",
                "tool_change_interval_hours": 80,
            }
        )
    return items


def build_machine_state() -> list[dict[str, Any]]:
    """Initial machine state: RUNNING, health=1.0, baseline telemetry snapshot."""
    items = []
    for mid in machine_ids():
        items.append(
            {
                "machine_id": mid,
                "plant_id": PLANT_ID,
                "production_line": line_for(mid),
                "machine_type": MACHINE_TYPE,
                "status": "RUNNING",
                "health_score": 1.0,
                "last_telemetry": {
                    "vibration_mms": SIM_VIBRATION_BASELINE,
                    "current_amps": SIM_CURRENT_BASELINE,
                    "coolant_lmin": SIM_COOLANT_BASELINE,
                    "acoustic_db": SIM_ACOUSTIC_BASELINE,
                },
                "active_alerts": [],
                "last_reading_timestamp": now_iso(),
                "total_runtime_hours": 1240.5,
                "updated_at": now_iso(),
            }
        )
    return items


def build_energy_baselines() -> list[dict[str, Any]]:
    """Baseline kWh per machine for sustainability deviation calculations."""
    items = []
    for mid in machine_ids():
        items.append(
            {
                "machine_id": mid,
                "plant_id": PLANT_ID,
                "baseline_kwh_per_hour": 22.5,
                "baseline_kwh_per_day": 540.0,
                "idle_kwh_per_hour": 4.0,
                "established_at": "2026-01-15",
                "sample_size": 5040,
            }
        )
    return items


def build_quality_thresholds() -> list[dict[str, Any]]:
    """Defect-rate thresholds per aerospace product type."""
    return [
        {
            "product_type": "TITANIUM_BRACKET",
            "defect_rate_threshold": 0.02,
            "critical_defects": ["CRACK", "MISALIGNMENT"],
            "review_defects": ["SCRATCH", "DISCOLORATION"],
        },
        {
            "product_type": "FUSELAGE_FRAME",
            "defect_rate_threshold": 0.01,
            "critical_defects": ["CRACK", "DENT", "MISALIGNMENT"],
            "review_defects": ["SCRATCH"],
        },
        {
            "product_type": "ENGINE_BLADE",
            "defect_rate_threshold": 0.005,
            "critical_defects": ["CRACK", "DENT", "DISCOLORATION", "MISALIGNMENT"],
            "review_defects": ["SCRATCH"],
        },
    ]


def build_edge_thresholds() -> list[dict[str, Any]]:
    """Per-machine NORMAL/WARNING/ANOMALY zones for Edge AI classification."""
    items = []
    for mid in machine_ids():
        items.append(
            {
                "machine_id": mid,
                "plant_id": PLANT_ID,
                "vibration_mms": {
                    "normal_min": VIBRATION_NORMAL_MIN,
                    "normal_max": VIBRATION_NORMAL_MAX,
                    "warning_max": VIBRATION_WARNING_MAX,
                    "anomaly_threshold": VIBRATION_ANOMALY_THRESHOLD,
                },
                "current_amps": {
                    "normal_min": CURRENT_NORMAL_MIN,
                    "normal_max": CURRENT_NORMAL_MAX,
                    "warning_max": CURRENT_WARNING_MAX,
                    "anomaly_threshold": CURRENT_ANOMALY_THRESHOLD,
                },
                "coolant_lmin": {
                    "normal_min": COOLANT_NORMAL_MIN,
                    "normal_max": COOLANT_NORMAL_MAX,
                    "warning_min": COOLANT_WARNING_MIN,
                    "anomaly_threshold": COOLANT_ANOMALY_THRESHOLD,
                },
                "acoustic_db": {
                    "normal_min": ACOUSTIC_NORMAL_MIN,
                    "normal_max": ACOUSTIC_NORMAL_MAX,
                    "warning_max": ACOUSTIC_WARNING_MAX,
                    "anomaly_threshold": ACOUSTIC_ANOMALY_THRESHOLD,
                },
                "compound_rule": {
                    "vibration_threshold": VIBRATION_ANOMALY_THRESHOLD,
                    "coolant_threshold": COOLANT_ANOMALY_THRESHOLD,
                    "action": "IMMEDIATE_SPINDLE_STOP",
                },
            }
        )
    return items


def build_floor_layout() -> list[dict[str, Any]]:
    """Single floor layout record for the plant."""
    layout: dict[str, list[dict[str, Any]]] = {line: [] for line in PRODUCTION_LINES}
    for mid in machine_ids():
        layout[line_for(mid)].append({"machine_id": mid, "machine_type": MACHINE_TYPE})

    return [
        {
            "plant_id": PLANT_ID,
            "plant_name": PLANT_NAME,
            "floor_area_sqm": 12000,
            "production_lines": [
                {
                    "line_id": line,
                    "machines": layout[line],
                    "machine_count": len(layout[line]),
                }
                for line in PRODUCTION_LINES
            ],
            "total_machines": MACHINE_COUNT,
            "updated_at": now_iso(),
        }
    ]


SEED_TABLES: dict[str, callable] = {
    "FactoryMind_MachineSpecs": build_machine_specs,
    "FactoryMind_MachineState": build_machine_state,
    "FactoryMind_EnergyBaselines": build_energy_baselines,
    "FactoryMind_QualityThresholds": build_quality_thresholds,
    "FactoryMind_EdgeThresholds": build_edge_thresholds,
    "FactoryMind_FloorLayout": build_floor_layout,
}


def seed(endpoint_url: str | None, dry_run: bool, region: str) -> None:
    """Write seed data to all configured tables."""
    if dry_run:
        print("DRY RUN — no writes will occur.\n")
        for table_name, builder in SEED_TABLES.items():
            items = builder()
            print(f"=== {table_name} ({len(items)} items) ===")
            print(json.dumps(items[:2], indent=2, default=str))
            if len(items) > 2:
                print(f"... + {len(items) - 2} more")
            print()
        return

    kwargs = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url

    ddb = boto3.resource("dynamodb", **kwargs)

    for table_name, builder in SEED_TABLES.items():
        items = builder()
        table = ddb.Table(table_name)
        print(f"Seeding {table_name}: {len(items)} items...", end="", flush=True)
        with table.batch_writer() as batch:
            for item in items:
                batch.put_item(Item=to_dynamodb_item(item))
        print(" done.")

    print("\nSeed complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed FactoryMind DynamoDB tables.")
    parser.add_argument(
        "--endpoint-url",
        default=None,
        help="DynamoDB endpoint URL (e.g., http://localhost:4566 for LocalStack)",
    )
    parser.add_argument(
        "--region",
        default="ap-south-1",
        help="AWS region (default: ap-south-1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payloads without writing to DynamoDB",
    )
    args = parser.parse_args()
    seed(endpoint_url=args.endpoint_url, dry_run=args.dry_run, region=args.region)


if __name__ == "__main__":
    main()
