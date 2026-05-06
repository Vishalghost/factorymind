"""Quality Vision Manager Lambda handler.

Orchestrates the visual inspection pipeline for aerospace CNC parts using
Amazon Rekognition for defect detection. Triggered by S3 event notification
when a product image is uploaded to factorymind-product-images.

Pipeline:
  1. preprocess (resize/normalize) → 2. Rekognition DetectLabels →
  3. defect analysis (PASS/FAIL/REVIEW) → 4. report to DynamoDB + EventBridge.

Why Rekognition only (not YOLOv8): zero training data required, no SageMaker
endpoint to keep warm, and the agents fall back to PASS automatically when
Rekognition can't find any matching labels. For higher accuracy on real defect
imagery, swap detect_with_rekognition() for a Rekognition Custom Labels call —
same response shape, just a trained project under the hood.
"""

import time
from typing import Any

from aws_lambda_powertools import Logger, Tracer
from pydantic import BaseModel

from agents.shared.utils.id_generator import generate_quality_id
from agents.shared.constants import PLANT_ID
from agents.quality_vision.workers.vision_preprocessor import preprocess_image
from agents.quality_vision.workers.rekognition_worker import detect_with_rekognition
from agents.quality_vision.workers.defect_analyser import analyse_defects
from agents.quality_vision.workers.qc_report_generator import generate_report

logger = Logger(service="quality-vision-manager")
tracer = Tracer(service="quality-vision-manager")

# Minimum Rekognition label confidence (0.0–1.0) to trust a defect detection.
# Below this, the verdict is REVIEW rather than PASS/FAIL — defect_analyser
# applies the same rule, so this is informational only.
REKOGNITION_MIN_CONFIDENCE = 0.5


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
    primary_model: str  # always "rekognition"
    confidence_score: float
    defect_rate: float
    threshold_exceeded: bool
    processing_time_ms: int


@tracer.capture_lambda_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for Quality Vision Manager.

    Pipeline: preprocess → Rekognition → analyse → report.
    """
    start_time = time.time()
    inspection_id = generate_quality_id()

    # Parse S3 event or direct invocation
    if "Records" in event:
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

    # Step 1: Preprocess image (download from S3, capture metadata)
    preprocessed = preprocess_image(input_data.image_s3_key)

    # Step 2: Rekognition DetectLabels — finds objects + patterns + confidence scores
    detections, confidence_score = detect_with_rekognition(input_data.image_s3_key)

    if confidence_score < REKOGNITION_MIN_CONFIDENCE:
        logger.info(
            "rekognition_low_confidence",
            confidence=confidence_score,
            threshold=REKOGNITION_MIN_CONFIDENCE,
        )

    # Step 3: Analyse defects → verdict + defect rate
    verdict, defect_rate, threshold_exceeded = analyse_defects(
        detections=detections,
        product_type=input_data.product_type,
    )

    # Step 4: Persist report + publish event
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
        primary_model="rekognition",
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
        primary_model="rekognition",
        confidence_score=confidence_score,
        defect_rate=defect_rate,
        threshold_exceeded=threshold_exceeded,
        processing_time_ms=processing_time_ms,
    )

    logger.info(
        "inspection_completed",
        inspection_id=inspection_id,
        verdict=verdict,
        time_ms=processing_time_ms,
    )
    return output.model_dump()
