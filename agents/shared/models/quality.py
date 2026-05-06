"""Quality vision inspection data models."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, field_validator


class DefectType(str, Enum):
    SCRATCH = "SCRATCH"
    DENT = "DENT"
    CRACK = "CRACK"
    DISCOLORATION = "DISCOLORATION"
    MISALIGNMENT = "MISALIGNMENT"
    NO_DEFECT = "NO_DEFECT"


class BoundingBox(BaseModel):
    """Bounding box for detected defect."""

    x: float
    y: float
    width: float
    height: float


class Detection(BaseModel):
    """Single defect detection result."""

    defect_type: DefectType
    confidence: float  # 0.0 to 1.0
    bounding_box: BoundingBox

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be 0.0-1.0, got: {v}")
        return v


class QualityResultRecord(BaseModel):
    """DynamoDB: FactoryMind_QualityResults (PK: inspection_report_id)."""

    inspection_report_id: str  # QCR-<uuid>
    plant_id: str
    machine_id: str
    production_line: str
    product_type: str
    batch_number: str
    image_s3_key: str
    verdict: str  # PASS | FAIL | REVIEW
    defects: list[dict]
    primary_model: str  # "yolov8" | "rekognition"
    confidence_score: float
    defect_rate: float
    threshold_exceeded: bool
    annotated_image_s3_key: Optional[str] = None
    inspected_at: str
    processing_time_ms: int
