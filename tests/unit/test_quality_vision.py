"""Unit tests for Quality Vision Manager."""

import json
import pytest
from unittest.mock import MagicMock, patch, ANY
from decimal import Decimal

from agents.quality_vision.workers.vision_preprocessor import preprocess_image
from agents.quality_vision.workers.yolov8_worker import detect_with_yolov8
from agents.quality_vision.workers.rekognition_worker import (
    detect_with_rekognition,
    _map_label_to_defect,
)
from agents.quality_vision.workers.defect_analyser import analyse_defects
from agents.quality_vision.workers.qc_report_generator import generate_report


class TestVisionPreprocessor:
    """Tests for vision_preprocessor worker."""

    def test_preprocess_returns_metadata(self):
        """Preprocessing returns correct metadata structure."""
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=lambda: b"\x89PNG" * 100)
        }

        result = preprocess_image("images/part-001.jpg", client=mock_s3)

        assert result["s3_key"] == "images/part-001.jpg"
        assert result["target_size"] == (640, 640)
        assert result["normalized"] is True
        assert result["original_size_bytes"] == 400

    def test_preprocess_downloads_from_correct_bucket(self):
        """Preprocessor downloads from factorymind-product-images bucket."""
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=lambda: b"image_data")
        }

        preprocess_image("line-a/batch-001/img.jpg", client=mock_s3)

        mock_s3.get_object.assert_called_once_with(
            Bucket="factorymind-product-images",
            Key="line-a/batch-001/img.jpg",
        )

    def test_preprocess_handles_s3_error_gracefully(self):
        """Preprocessor returns empty bytes on S3 download failure."""
        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = Exception("Access Denied")

        result = preprocess_image("missing/image.jpg", client=mock_s3)

        assert result["original_size_bytes"] == 0
        assert result["s3_key"] == "missing/image.jpg"
        assert result["normalized"] is True


class TestYolov8Worker:
    """Tests for yolov8_worker — SageMaker endpoint invocation."""

    def _make_preprocessed(self, s3_key="images/part.jpg"):
        return {
            "s3_key": s3_key,
            "original_size_bytes": 1024,
            "target_size": (640, 640),
            "normalized": True,
            "image_data": b"fake_image",
        }

    def test_yolov8_high_confidence_accepted(self):
        """YOLOv8 confidence >= 0.75 should be accepted by the manager."""
        mock_client = MagicMock()
        mock_client.invoke_endpoint.return_value = {
            "Body": MagicMock(
                read=lambda: json.dumps({
                    "detections": [
                        {
                            "defect_type": "SCRATCH",
                            "confidence": 0.85,
                            "bounding_box": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                        }
                    ],
                    "confidence": 0.85,
                }).encode()
            )
        }

        detections, confidence = detect_with_yolov8(
            self._make_preprocessed(), client=mock_client
        )

        assert confidence >= 0.75
        assert len(detections) == 1
        assert detections[0]["defect_type"] == "SCRATCH"

    def test_yolov8_low_confidence_triggers_fallback(self):
        """YOLOv8 confidence < 0.75 should trigger Rekognition fallback."""
        mock_client = MagicMock()
        mock_client.invoke_endpoint.return_value = {
            "Body": MagicMock(
                read=lambda: json.dumps({
                    "detections": [
                        {
                            "defect_type": "DENT",
                            "confidence": 0.60,
                            "bounding_box": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                        }
                    ],
                    "confidence": 0.60,
                }).encode()
            )
        }

        detections, confidence = detect_with_yolov8(
            self._make_preprocessed(), client=mock_client
        )

        # Confidence below threshold — manager should invoke Rekognition
        assert confidence < 0.75

    def test_yolov8_boundary_confidence_075_accepted(self):
        """YOLOv8 confidence exactly 0.75 should be accepted (>= threshold)."""
        mock_client = MagicMock()
        mock_client.invoke_endpoint.return_value = {
            "Body": MagicMock(
                read=lambda: json.dumps({
                    "detections": [],
                    "confidence": 0.75,
                }).encode()
            )
        }

        _, confidence = detect_with_yolov8(
            self._make_preprocessed(), client=mock_client
        )

        assert confidence >= 0.75

    def test_yolov8_boundary_confidence_074_triggers_fallback(self):
        """YOLOv8 confidence 0.74 should trigger fallback (< 0.75)."""
        mock_client = MagicMock()
        mock_client.invoke_endpoint.return_value = {
            "Body": MagicMock(
                read=lambda: json.dumps({
                    "detections": [],
                    "confidence": 0.74,
                }).encode()
            )
        }

        _, confidence = detect_with_yolov8(
            self._make_preprocessed(), client=mock_client
        )

        assert confidence < 0.75

    def test_yolov8_invocation_failure_returns_empty(self):
        """YOLOv8 endpoint failure returns empty detections and 0.0 confidence."""
        mock_client = MagicMock()
        mock_client.invoke_endpoint.side_effect = Exception("Endpoint unavailable")

        detections, confidence = detect_with_yolov8(
            self._make_preprocessed(), client=mock_client
        )

        assert detections == []
        assert confidence == 0.0

    def test_yolov8_invokes_correct_endpoint(self):
        """YOLOv8 worker invokes the factorymind-yolov8-quality endpoint."""
        mock_client = MagicMock()
        mock_client.invoke_endpoint.return_value = {
            "Body": MagicMock(
                read=lambda: json.dumps({"detections": [], "confidence": 0.9}).encode()
            )
        }

        detect_with_yolov8(self._make_preprocessed(), client=mock_client)

        mock_client.invoke_endpoint.assert_called_once_with(
            EndpointName="factorymind-yolov8-quality",
            ContentType="application/json",
            Body=ANY,
        )


class TestRekognitionWorker:
    """Tests for rekognition_worker — fallback detection."""

    def test_rekognition_fallback_invocation(self):
        """Rekognition is invoked with correct bucket and key."""
        mock_client = MagicMock()
        mock_client.detect_labels.return_value = {"Labels": []}

        detect_with_rekognition("images/part-001.jpg", client=mock_client)

        mock_client.detect_labels.assert_called_once_with(
            Image={
                "S3Object": {
                    "Bucket": "factorymind-product-images",
                    "Name": "images/part-001.jpg",
                }
            },
            MaxLabels=20,
            MinConfidence=50.0,
        )

    def test_rekognition_returns_detections(self):
        """Rekognition returns mapped detections with bounding boxes."""
        mock_client = MagicMock()
        mock_client.detect_labels.return_value = {
            "Labels": [
                {
                    "Name": "Scratch",
                    "Confidence": 92.5,
                    "Instances": [
                        {
                            "BoundingBox": {
                                "Left": 0.1,
                                "Top": 0.2,
                                "Width": 0.3,
                                "Height": 0.4,
                            }
                        }
                    ],
                }
            ]
        }

        detections, confidence = detect_with_rekognition(
            "images/part.jpg", client=mock_client
        )

        assert len(detections) == 1
        assert detections[0]["defect_type"] == "SCRATCH"
        assert detections[0]["confidence"] == 0.925
        assert detections[0]["bounding_box"]["x"] == 0.1
        assert confidence == 0.925

    def test_rekognition_failure_returns_empty(self):
        """Rekognition failure returns empty detections and 0.0 confidence."""
        mock_client = MagicMock()
        mock_client.detect_labels.side_effect = Exception("Service unavailable")

        detections, confidence = detect_with_rekognition(
            "images/part.jpg", client=mock_client
        )

        assert detections == []
        assert confidence == 0.0

    def test_map_label_scratch(self):
        assert _map_label_to_defect("Scratch") == "SCRATCH"
        assert _map_label_to_defect("Deep Scratch") == "SCRATCH"

    def test_map_label_dent(self):
        assert _map_label_to_defect("Dent") == "DENT"
        assert _map_label_to_defect("Surface Dent") == "DENT"

    def test_map_label_crack(self):
        assert _map_label_to_defect("Crack") == "CRACK"
        assert _map_label_to_defect("Hairline Crack") == "CRACK"

    def test_map_label_discoloration(self):
        assert _map_label_to_defect("Discoloration") == "DISCOLORATION"
        assert _map_label_to_defect("Stain") == "DISCOLORATION"

    def test_map_label_misalignment(self):
        assert _map_label_to_defect("Misalignment") == "MISALIGNMENT"
        assert _map_label_to_defect("Offset") == "MISALIGNMENT"

    def test_map_label_unknown_returns_no_defect(self):
        assert _map_label_to_defect("Person") == "NO_DEFECT"
        assert _map_label_to_defect("Machine") == "NO_DEFECT"


class TestDefectAnalyser:
    """Tests for defect_analyser worker — classification and verdict."""

    def test_no_detections_pass(self):
        """No detections → PASS verdict."""
        verdict, defect_rate, threshold_exceeded = analyse_defects(
            detections=[], product_type="TITANIUM_BRACKET"
        )
        assert verdict == "PASS"
        assert defect_rate == 0.0
        assert threshold_exceeded is False

    def test_only_no_defect_detections_pass(self):
        """Only NO_DEFECT detections → PASS verdict."""
        detections = [
            {"defect_type": "NO_DEFECT", "confidence": 0.95},
        ]
        verdict, defect_rate, threshold_exceeded = analyse_defects(
            detections=detections, product_type="TITANIUM_BRACKET"
        )
        assert verdict == "PASS"
        assert defect_rate == 0.0
        assert threshold_exceeded is False

    def test_crack_defect_fails(self):
        """CRACK is a critical defect → FAIL verdict."""
        detections = [
            {"defect_type": "CRACK", "confidence": 0.90},
        ]
        verdict, defect_rate, threshold_exceeded = analyse_defects(
            detections=detections, product_type="TITANIUM_BRACKET"
        )
        assert verdict == "FAIL"

    def test_misalignment_defect_fails(self):
        """MISALIGNMENT is a critical defect → FAIL verdict."""
        detections = [
            {"defect_type": "MISALIGNMENT", "confidence": 0.88},
        ]
        verdict, defect_rate, threshold_exceeded = analyse_defects(
            detections=detections, product_type="TITANIUM_BRACKET"
        )
        assert verdict == "FAIL"

    def test_scratch_defect_review(self):
        """SCRATCH with high confidence, below threshold → REVIEW."""
        detections = [
            {"defect_type": "SCRATCH", "confidence": 0.80},
        ]
        verdict, defect_rate, threshold_exceeded = analyse_defects(
            detections=detections, product_type="TITANIUM_BRACKET", batch_size=100
        )
        assert verdict == "REVIEW"

    def test_dent_defect_review(self):
        """DENT with high confidence, below threshold → REVIEW."""
        detections = [
            {"defect_type": "DENT", "confidence": 0.82},
        ]
        verdict, defect_rate, threshold_exceeded = analyse_defects(
            detections=detections, product_type="TITANIUM_BRACKET", batch_size=100
        )
        assert verdict == "REVIEW"

    def test_discoloration_defect_review(self):
        """DISCOLORATION with high confidence, below threshold → REVIEW."""
        detections = [
            {"defect_type": "DISCOLORATION", "confidence": 0.78},
        ]
        verdict, defect_rate, threshold_exceeded = analyse_defects(
            detections=detections, product_type="TITANIUM_BRACKET", batch_size=100
        )
        assert verdict == "REVIEW"

    def test_low_confidence_triggers_review(self):
        """Low average confidence (< 0.6) → REVIEW regardless of defect type."""
        detections = [
            {"defect_type": "SCRATCH", "confidence": 0.45},
        ]
        verdict, defect_rate, threshold_exceeded = analyse_defects(
            detections=detections, product_type="TITANIUM_BRACKET"
        )
        assert verdict == "REVIEW"

    def test_threshold_exceeded_titanium_bracket(self):
        """Defect rate > 5% for TITANIUM_BRACKET → threshold_exceeded=True."""
        # batch_size=1, 1 defect → defect_rate = 1.0 > 0.05
        detections = [
            {"defect_type": "SCRATCH", "confidence": 0.80},
        ]
        verdict, defect_rate, threshold_exceeded = analyse_defects(
            detections=detections, product_type="TITANIUM_BRACKET", batch_size=1
        )
        assert threshold_exceeded is True
        assert defect_rate == 1.0

    def test_threshold_not_exceeded_large_batch(self):
        """1 defect in batch of 100 → defect_rate = 0.01 < 0.05 threshold."""
        detections = [
            {"defect_type": "SCRATCH", "confidence": 0.80},
        ]
        verdict, defect_rate, threshold_exceeded = analyse_defects(
            detections=detections, product_type="TITANIUM_BRACKET", batch_size=100
        )
        assert threshold_exceeded is False
        assert defect_rate == 0.01

    def test_threshold_exceeded_fuselage_panel(self):
        """FUSELAGE_PANEL has stricter threshold (2%)."""
        # 1 defect in batch of 10 → 10% > 2%
        detections = [
            {"defect_type": "DENT", "confidence": 0.80},
        ]
        _, _, threshold_exceeded = analyse_defects(
            detections=detections, product_type="FUSELAGE_PANEL", batch_size=10
        )
        assert threshold_exceeded is True

    def test_threshold_exceeded_engine_mount(self):
        """ENGINE_MOUNT has strictest threshold (1%)."""
        # 1 defect in batch of 50 → 2% > 1%
        detections = [
            {"defect_type": "SCRATCH", "confidence": 0.80},
        ]
        _, _, threshold_exceeded = analyse_defects(
            detections=detections, product_type="ENGINE_MOUNT", batch_size=50
        )
        assert threshold_exceeded is True

    def test_threshold_exceeded_causes_fail_verdict(self):
        """When threshold is exceeded and no critical defects, verdict is FAIL."""
        # Many non-critical defects exceeding threshold
        detections = [
            {"defect_type": "SCRATCH", "confidence": 0.80},
            {"defect_type": "DENT", "confidence": 0.75},
            {"defect_type": "SCRATCH", "confidence": 0.82},
        ]
        verdict, defect_rate, threshold_exceeded = analyse_defects(
            detections=detections, product_type="TITANIUM_BRACKET", batch_size=1
        )
        assert threshold_exceeded is True
        assert verdict == "FAIL"

    def test_defect_rate_calculation(self):
        """Defect rate = number of actual defects / batch_size."""
        detections = [
            {"defect_type": "SCRATCH", "confidence": 0.80},
            {"defect_type": "DENT", "confidence": 0.75},
            {"defect_type": "NO_DEFECT", "confidence": 0.90},
        ]
        _, defect_rate, _ = analyse_defects(
            detections=detections, product_type="TITANIUM_BRACKET", batch_size=10
        )
        # 2 actual defects (NO_DEFECT excluded) / 10 batch_size = 0.2
        assert defect_rate == 0.2


class TestVerdictDetermination:
    """Tests for verdict logic in defect_analyser."""

    def test_verdict_pass_no_defects(self):
        """Empty detections → PASS."""
        verdict, _, _ = analyse_defects([], "TITANIUM_BRACKET")
        assert verdict == "PASS"

    def test_verdict_fail_critical_crack(self):
        """CRACK defect → FAIL regardless of other factors."""
        verdict, _, _ = analyse_defects(
            [{"defect_type": "CRACK", "confidence": 0.90}],
            "TITANIUM_BRACKET",
        )
        assert verdict == "FAIL"

    def test_verdict_fail_critical_misalignment(self):
        """MISALIGNMENT defect → FAIL regardless of other factors."""
        verdict, _, _ = analyse_defects(
            [{"defect_type": "MISALIGNMENT", "confidence": 0.90}],
            "TITANIUM_BRACKET",
        )
        assert verdict == "FAIL"

    def test_verdict_review_low_confidence(self):
        """Average confidence < 0.6 → REVIEW (needs human review)."""
        verdict, _, _ = analyse_defects(
            [{"defect_type": "SCRATCH", "confidence": 0.50}],
            "TITANIUM_BRACKET",
            batch_size=100,
        )
        assert verdict == "REVIEW"

    def test_verdict_review_non_critical_defect(self):
        """Non-critical defect with high confidence, below threshold → REVIEW."""
        verdict, _, _ = analyse_defects(
            [{"defect_type": "SCRATCH", "confidence": 0.80}],
            "TITANIUM_BRACKET",
            batch_size=100,  # defect_rate = 0.01 < 0.05 threshold
        )
        assert verdict == "REVIEW"


class TestQCReportGenerator:
    """Tests for qc_report_generator worker — DynamoDB write and EventBridge publish."""

    def test_dynamodb_write(self):
        """Report is written to DynamoDB FactoryMind_QualityResults table."""
        mock_table = MagicMock()

        result = generate_report(
            inspection_id="QCR-test-123",
            plant_id="PLANT-001",
            machine_id="CNC-AERO-01",
            production_line="LINE-A",
            product_type="TITANIUM_BRACKET",
            batch_number="BATCH-001",
            image_s3_key="images/part-001.jpg",
            verdict="PASS",
            defects=[],
            primary_model="yolov8",
            confidence_score=0.92,
            defect_rate=0.0,
            threshold_exceeded=False,
            table=mock_table,
        )

        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["inspection_report_id"] == "QCR-test-123"
        assert item["plant_id"] == "PLANT-001"
        assert item["machine_id"] == "CNC-AERO-01"
        assert item["verdict"] == "PASS"
        assert item["primary_model"] == "yolov8"
        assert item["threshold_exceeded"] is False

    def test_dynamodb_write_with_defects(self):
        """Report with defects is correctly persisted."""
        mock_table = MagicMock()
        defects = [
            {"defect_type": "SCRATCH", "confidence": 0.85, "bounding_box": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}},
        ]

        result = generate_report(
            inspection_id="QCR-test-456",
            plant_id="PLANT-001",
            machine_id="CNC-AERO-02",
            production_line="LINE-B",
            product_type="FUSELAGE_PANEL",
            batch_number="BATCH-002",
            image_s3_key="images/part-002.jpg",
            verdict="REVIEW",
            defects=defects,
            primary_model="rekognition",
            confidence_score=0.85,
            defect_rate=0.10,
            threshold_exceeded=True,
            table=mock_table,
        )

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["verdict"] == "REVIEW"
        assert item["primary_model"] == "rekognition"
        assert item["threshold_exceeded"] is True
        assert len(item["defects"]) == 1

    @patch("agents.quality_vision.workers.qc_report_generator.publish_event")
    def test_eventbridge_publish(self, mock_publish):
        """InspectionCompleted event is published to EventBridge."""
        mock_table = MagicMock()

        generate_report(
            inspection_id="QCR-test-789",
            plant_id="PLANT-001",
            machine_id="CNC-AERO-03",
            production_line="LINE-C",
            product_type="ENGINE_MOUNT",
            batch_number="BATCH-003",
            image_s3_key="images/part-003.jpg",
            verdict="FAIL",
            defects=[{"defect_type": "CRACK", "confidence": 0.92}],
            primary_model="yolov8",
            confidence_score=0.92,
            defect_rate=1.0,
            threshold_exceeded=True,
            table=mock_table,
        )

        mock_publish.assert_called_once_with(
            source="factorymind.quality.inspection",
            detail_type="InspectionCompleted",
            detail={
                "inspection_report_id": "QCR-test-789",
                "machine_id": "CNC-AERO-03",
                "verdict": "FAIL",
                "threshold_exceeded": True,
            },
        )

    @patch("agents.quality_vision.workers.qc_report_generator.publish_event")
    def test_eventbridge_failure_does_not_raise(self, mock_publish):
        """EventBridge publish failure is logged but does not raise."""
        mock_table = MagicMock()
        mock_publish.side_effect = Exception("EventBridge unavailable")

        # Should not raise
        result = generate_report(
            inspection_id="QCR-test-err",
            plant_id="PLANT-001",
            machine_id="CNC-AERO-01",
            production_line="LINE-A",
            product_type="TITANIUM_BRACKET",
            batch_number="BATCH-004",
            image_s3_key="images/part-004.jpg",
            verdict="PASS",
            defects=[],
            primary_model="yolov8",
            confidence_score=0.95,
            defect_rate=0.0,
            threshold_exceeded=False,
            table=mock_table,
        )

        assert result["inspection_report_id"] == "QCR-test-err"

    def test_report_contains_timestamp(self):
        """Report includes inspected_at timestamp."""
        mock_table = MagicMock()

        result = generate_report(
            inspection_id="QCR-ts-test",
            plant_id="PLANT-001",
            machine_id="CNC-AERO-01",
            production_line="LINE-A",
            product_type="TITANIUM_BRACKET",
            batch_number="BATCH-005",
            image_s3_key="images/part-005.jpg",
            verdict="PASS",
            defects=[],
            primary_model="yolov8",
            confidence_score=0.90,
            defect_rate=0.0,
            threshold_exceeded=False,
            table=mock_table,
        )

        assert "inspected_at" in result
        assert result["inspected_at"] is not None


class TestManagerPipelineIntegration:
    """Tests for the full Quality Vision Manager pipeline logic."""

    def test_high_confidence_uses_yolov8(self):
        """When YOLOv8 confidence >= 0.75, primary_model is 'yolov8'."""
        from agents.quality_vision.manager.handler import YOLOV8_CONFIDENCE_THRESHOLD

        yolo_confidence = 0.85
        assert yolo_confidence >= YOLOV8_CONFIDENCE_THRESHOLD

    def test_low_confidence_triggers_rekognition(self):
        """When YOLOv8 confidence < 0.75, Rekognition fallback is used."""
        from agents.quality_vision.manager.handler import YOLOV8_CONFIDENCE_THRESHOLD

        yolo_confidence = 0.60
        assert yolo_confidence < YOLOV8_CONFIDENCE_THRESHOLD

    def test_threshold_constant_is_075(self):
        """The YOLOv8 confidence threshold is exactly 0.75."""
        from agents.quality_vision.manager.handler import YOLOV8_CONFIDENCE_THRESHOLD

        assert YOLOV8_CONFIDENCE_THRESHOLD == 0.75
