"""Quality Vision Manager Lambda handler.

Orchestrates the visual inspection pipeline for aerospace CNC parts.
Triggered by S3 event notification when product image is uploaded.
"""

import time
from typing import Any

from aws_lambda_powertools import Logger, Tracer
from pydantic import BaseModel

from agents.shared.utils.id_generator import generate_quality_id
from agents.shared.constants import PLANT_ID
from agents.quality_vision.workers.vision_preprocessor import preprocess_image
from agents.quality_vision.workers.yolov8_worker import detect_with_yolov8
from agents.quality_vision.workers.rekognition_worker import detect_with_rekognition
from agents.quality_vision.workers.defect_analyser import analyse_defects
from agents.quality_vision.workers.qc_report_generator import generate_report

logger = Logger(service="quality-vision-manager")
tracer = Tracer(service="quality-vision-manager")

YOLOV8_CONFIDENCE_THRESHOLD = 0.75


class QualityInspectionInput(BaseModel):
    """Input to Quality Vision Manager."""

    plant_id: str = PLANT_ID
    machine_id: str
    production_line: str
    image_s3_key: str
    product_type: str
    batch_number: str


class QualityInspectionOutput(BaseModel):
    """Output from Quality Vision Manager."""

    inspection_report_id: str
    plant_id: str
    machine_id: str
    verdict: str  # PASS | FAIL | REVIEW
    defects_found: list[dict[str, Any]]
    primary_model: str  # "yolov8" | "rekognition"
    confidence_score: float
    defect_rate: float
    threshold_exceeded: bool
    processing_time_ms: int


@tracer.capture_lambda_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for Quality Vision Manager.

    Pipeline: preprocess → YOLOv8 → (fallback Rekognition) → analyse → report
    """
    start_time = time.time()
    inspection_id = generate_quality_id()

    # Parse S3 event or direct invocation
    if "Records" in event:
        # S3 event notification
        s3_record = event["Records"][0]["s3"]
        image_s3_key = s3_record["object"]["key"]
        input_data = QualityInspectionInput(
            machine_id=event.get("machine_id", "CNC-AERO-01"),
            production_line=event.get("production_line", "LINE-A"),
            image_s3_key=image_s3_key,
            product_type=event.get("product_type", "TITANIUM_BRACKET"),
            batch_number=event.get("batch_number", "BATCH-001"),
        )
    else:
        input_data = QualityInspectionInput(**event)

    logger.info("inspection_started", inspection_id=inspection_id, image=input_data.image_s3_key)

    # Step 1: Preprocess image
    preprocessed = preprocess_image(input_data.image_s3_key)

    # Step 2: YOLOv8 primary detection
    yolo_detections, yolo_confidence = detect_with_yolov8(preprocessed)

    # Step 3: Fallback to Rekognition if confidence < 0.75
    primary_model = "yolov8"
    if yolo_confidence < YOLOV8_CONFIDENCE_THRESHOLD:
        logger.info("yolov8_low_confidence", confidence=yolo_confidence, threshold=YOLOV8_CONFIDENCE_THRESHOLD)
        rek_detections, rek_confidence = detect_with_rekognition(input_data.image_s3_key)
        detections = rek_detections
        confidence_score = rek_confidence
        primary_model = "rekognition"
    else:
        detections = yolo_detections
        confidence_score = yolo_confidence

    # Step 4: Analyse defects
    verdict, defect_rate, threshold_exceeded = analyse_defects(
        detections=detections,
        product_type=input_data.product_type,
    )

    # Step 5: Generate report
    generate_report(
        inspection_id=inspection_id,
        plant_id=input_data.plant_id,
        machine_id=input_data.machine_id,
        production_line=input_data.production_line,
        product_type=input_data.product_type,
        batch_number=input_data.batch_number,
        image_s3_key=input_data.image_s3_key,
        verdict=verdict,
        defects=detections,
        primary_model=primary_model,
        confidence_score=confidence_score,
        defect_rate=defect_rate,
        threshold_exceeded=threshold_exceeded,
    )

    processing_time_ms = int((time.time() - start_time) * 1000)

    output = QualityInspectionOutput(
        inspection_report_id=inspection_id,
        plant_id=input_data.plant_id,
        machine_id=input_data.machine_id,
        verdict=verdict,
        defects_found=[d if isinstance(d, dict) else d.model_dump() for d in detections],
        primary_model=primary_model,
        confidence_score=confidence_score,
        defect_rate=defect_rate,
        threshold_exceeded=threshold_exceeded,
        processing_time_ms=processing_time_ms,
    )

    logger.info("inspection_completed", inspection_id=inspection_id, verdict=verdict, time_ms=processing_time_ms)
    return output.model_dump()
