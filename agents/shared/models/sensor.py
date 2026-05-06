"""Aerospace CNC Titanium Milling sensor data models."""

from datetime import datetime, timezone
from pydantic import BaseModel, field_validator


class TelemetryData(BaseModel):
    """Real-time telemetry from CNC spindle sensors."""

    vibration_mms: float  # Spindle vibration in mm/s
    current_amps: float  # Spindle motor current in Amps
    coolant_lmin: float  # Coolant flow rate in L/min
    acoustic_db: float  # Acoustic emission in dB

    @field_validator("vibration_mms")
    @classmethod
    def validate_vibration(cls, v: float) -> float:
        if not 0.0 <= v <= 20.0:
            raise ValueError(f"vibration_mms {v} outside physical range 0-20 mm/s")
        return v

    @field_validator("current_amps")
    @classmethod
    def validate_current(cls, v: float) -> float:
        if not 0.0 <= v <= 50.0:
            raise ValueError(f"current_amps {v} outside physical range 0-50 A")
        return v

    @field_validator("coolant_lmin")
    @classmethod
    def validate_coolant(cls, v: float) -> float:
        if not 0.0 <= v <= 80.0:
            raise ValueError(f"coolant_lmin {v} outside physical range 0-80 L/min")
        return v

    @field_validator("acoustic_db")
    @classmethod
    def validate_acoustic(cls, v: float) -> float:
        if not 0.0 <= v <= 120.0:
            raise ValueError(f"acoustic_db {v} outside physical range 0-120 dB")
        return v


class SensorMetadata(BaseModel):
    """Metadata about the machining operation."""

    part_id: str  # e.g., FUS-BRACKET-992
    material: str  # e.g., Ti-6Al-4V
    spindle_rpm: int  # e.g., 3500


class SensorReading(BaseModel):
    """Complete sensor reading from aerospace CNC machine.

    Published to MQTT topic: factory/aerospace/cnc/telemetry
    """

    reading_id: str  # ING-<uuid>
    machine_id: str  # CNC-AERO-01 through CNC-AERO-50
    timestamp: str  # ISO 8601
    telemetry: TelemetryData
    metadata: SensorMetadata

    @field_validator("reading_id")
    @classmethod
    def validate_reading_id(cls, v: str) -> str:
        if not v.startswith("ING-"):
            raise ValueError(f"reading_id must start with ING- prefix, got: {v}")
        return v

    @field_validator("machine_id")
    @classmethod
    def validate_machine_id(cls, v: str) -> str:
        if not v.startswith("CNC-AERO-"):
            raise ValueError(f"machine_id must match CNC-AERO-XX pattern, got: {v}")
        return v

    @field_validator("timestamp")
    @classmethod
    def validate_not_stale(cls, v: str) -> str:
        ts = datetime.fromisoformat(v.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age_seconds = (now - ts).total_seconds()
        if age_seconds > 60:
            raise ValueError(f"Stale reading: {age_seconds:.1f}s old (max 60s)")
        return v


class TimestreamSensorReading(BaseModel):
    """Timestream record format for FactoryMindSensors.SensorReadings."""

    machine_id: str
    plant_id: str
    sensor_type: str  # vibration | current | coolant | acoustic
    value: float
    unit: str  # mms | amps | lmin | db
    timestamp: str
