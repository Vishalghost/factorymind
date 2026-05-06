---
inclusion: manual
---

# Skill: Simulate Sensor Data for FactoryMind

## When to Use
Use this skill when generating test/dummy sensor data, seeding DynamoDB, or simulating the IoT pipeline for local development.

## Machine Normal Ranges

| Machine | Temp (°C) | Vibration (Hz) | Pressure (bar) | Power (kW) | RPM |
|---------|-----------|----------------|----------------|------------|-----|
| MCH-042 (CNC_LATHE) | 60–80 | 100–130 | 5.0–7.0 | 30–40 | 2600–2900 |
| Default (all others) | 55–75 | 90–125 | 4.5–6.5 | 25–38 | 2400–2800 |

## Anomaly Thresholds

| Metric | WARNING | ANOMALY/CRITICAL |
|--------|---------|-----------------|
| temperature_c | > 80°C | > 85°C |
| vibration_hz | > 130 Hz | > 140 Hz |
| pressure_bar | > 7.0 or < 4.5 | > 8.0 or < 4.0 |
| power_kw | > 40 kW | > 45 kW |
| rpm | > 2900 or < 2500 | > 3000 or < 2400 |

## Sensor Simulator Script

```python
"""
Sensor data simulator for FactoryMind local development.
Generates realistic sensor readings with configurable anomaly injection.
"""
import json
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import boto3


NORMAL_RANGES = {
    "temperature_c": (60.0, 80.0),
    "vibration_hz": (100.0, 130.0),
    "pressure_bar": (5.0, 7.0),
    "power_kw": (30.0, 40.0),
    "rpm": (2600, 2900),
    "oil_level_pct": (65.0, 95.0),
}

ANOMALY_VALUES = {
    "temperature_c": (85.0, 95.0),
    "vibration_hz": (140.0, 165.0),
    "pressure_bar": (8.0, 10.0),
    "power_kw": (45.0, 55.0),
    "rpm": (3000, 3200),
}


def generate_reading(
    machine_id: str = "MCH-042",
    plant_id: str = "PLANT-001",
    line_id: str = "LINE-A",
    inject_anomaly: Optional[str] = None,
) -> dict:
    """Generate a single sensor reading."""
    readings = {}
    for metric, (low, high) in NORMAL_RANGES.items():
        if inject_anomaly and metric == inject_anomaly:
            anom_low, anom_high = ANOMALY_VALUES[metric]
            readings[metric] = round(random.uniform(anom_low, anom_high), 1)
        else:
            readings[metric] = round(random.uniform(low, high), 1)

    return {
        "device_id": f"{machine_id}-SENSOR-01",
        "plant_id": plant_id,
        "line_id": line_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "readings": readings,
        "firmware_version": "v2.4.1",
        "battery_pct": random.randint(80, 100),
    }


def generate_degradation_series(
    machine_id: str = "MCH-042",
    hours: int = 72,
    interval_minutes: int = 5,
) -> list[dict]:
    """
    Generate a time series showing gradual degradation.
    Useful for testing predictive maintenance LSTM model.
    """
    readings = []
    total_points = (hours * 60) // interval_minutes
    
    for i in range(total_points):
        progress = i / total_points  # 0.0 to 1.0
        
        # Gradually increase vibration and temperature
        vibration = 110.0 + (progress * 40.0) + random.uniform(-2, 2)
        temperature = 65.0 + (progress * 25.0) + random.uniform(-1, 1)
        
        reading = generate_reading(machine_id=machine_id)
        reading["readings"]["vibration_hz"] = round(vibration, 1)
        reading["readings"]["temperature_c"] = round(temperature, 1)
        readings.append(reading)
    
    return readings


def simulate_batch(
    num_machines: int = 50,
    anomaly_probability: float = 0.05,
) -> list[dict]:
    """Generate a batch of readings from multiple machines."""
    batch = []
    for i in range(1, num_machines + 1):
        machine_id = f"MCH-{i:03d}"
        inject = None
        if random.random() < anomaly_probability:
            inject = random.choice(list(ANOMALY_VALUES.keys()))
        batch.append(generate_reading(machine_id=machine_id, inject_anomaly=inject))
    return batch
```

## Seeding DynamoDB (Machine State)

```python
def seed_machine_state(table_name: str = "FactoryMind_MachineState"):
    """Seed initial machine state for all 50 machines."""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)
    
    machine_types = ["CNC_LATHE", "HYDRAULIC_PRESS", "CONVEYOR", "ROBOT_ARM", "WELDING_UNIT"]
    lines = ["LINE-A", "LINE-B", "LINE-C"]
    
    with table.batch_writer() as batch:
        for i in range(1, 51):
            batch.put_item(Item={
                "machine_id": f"MCH-{i:03d}",
                "plant_id": "PLANT-001",
                "line_id": lines[i % 3],
                "machine_type": machine_types[i % 5],
                "operational_status": "RUNNING",
                "last_maintenance_date": "2026-04-15",
                "readings": generate_reading(f"MCH-{i:03d}")["readings"],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
```

## ONNX Edge Model Simulation

```python
def simulate_onnx_inference(readings: dict) -> dict:
    """Simulate ONNX model output for edge AI testing."""
    # Normalise features
    features = [
        readings["temperature_c"] / 100.0,
        readings["vibration_hz"] / 200.0,
        readings["pressure_bar"] / 10.0,
        readings["power_kw"] / 50.0,
        readings["rpm"] / 3000.0,
    ]
    
    # Simple threshold-based classification (simulates model)
    if readings["vibration_hz"] > 140 or readings["temperature_c"] > 85:
        classification = "ANOMALY"
        confidence = 0.85 + random.uniform(0, 0.14)
    elif readings["vibration_hz"] > 130 or readings["temperature_c"] > 80:
        classification = "WARNING"
        confidence = 0.70 + random.uniform(0, 0.15)
    else:
        classification = "NORMAL"
        confidence = 0.90 + random.uniform(0, 0.09)
    
    return {
        "class": classification,
        "confidence": round(confidence, 3),
        "inference_time_ms": round(random.uniform(2.4, 8.9), 1),
        "features_used": [round(f, 3) for f in features],
    }
```

## SageMaker LSTM Simulation

```python
def simulate_lstm_prediction(time_series: list[dict]) -> dict:
    """Simulate LSTM failure prediction for testing."""
    # Check if trend is increasing
    if len(time_series) < 4:
        return {"failure_probability": 0.1, "predicted_failure_type": "NONE", "confidence": 0.5}
    
    recent_vibration = [r["readings"]["vibration_hz"] for r in time_series[-10:]]
    trend = recent_vibration[-1] - recent_vibration[0]
    
    if trend > 20:
        return {
            "failure_probability": 0.87,
            "predicted_failure_type": "BEARING_FAILURE",
            "estimated_time_to_failure_hours": 18.5,
            "confidence": 0.91,
        }
    elif trend > 10:
        return {
            "failure_probability": 0.55,
            "predicted_failure_type": "LUBRICATION_ISSUE",
            "estimated_time_to_failure_hours": 48.0,
            "confidence": 0.72,
        }
    else:
        return {
            "failure_probability": 0.12,
            "predicted_failure_type": "NONE",
            "estimated_time_to_failure_hours": None,
            "confidence": 0.88,
        }
```
