"""Unit tests for Quality Vision Manager (Rekognition-only pipeline)."""

import pytest
from unittest.mock import MagicMock, patch

from agents.quality_vision.workers.vision_preprocessor import preprocess_image
from agents.quality_vision.workers.rekognition_worker import (
    detect_with_rekognition,
    _map_label_to_defect,
)
from agents.quality_vision.workers.defect_analyser import analyse_defects
from agents.quality_vision.workers.qc_report_generator import generate_report


class TestVisionPreprocessor:
    """Tests for vision_preprocessor worker."""

    def test_preprocess_returns_metadata(self):
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
        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = Exception("Access Denied")

        result = preprocess_image("missing/image.jpg", client=mock_s3)

        assert result["original_size_bytes"] == 0
        assert result["s3_key"] == "missing/image.jpg"
        assert result["normalized"] is True


class TestRekognitionWorker:
    """Tests for rekognition_worker — primary defect detector."""

    def test_rekognition_invoked_with_correct_bucket_and_key(self):
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

    def test_rekognition_returns_mapped_detections(self):
        """Rekognition labels with bounding boxes are converted to defect dicts."""
        mock_client = MagicMock()
        mock_client.detect_labels.return_value = {
            "Labels": [
                {
                    "Name": "Scratch",
                    "Confidence": 92.5,
                    "Instances": [
                        {
                            "BoundingBox": {
                                "Left": 0.1, "Top": 0.2, "Width": 0.3, "Height": 0.4,
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
        """Rekognition error returns empty detections + 0.0 confidence."""
        mock_client = MagicMock()
        mock_client.detect_labels.side_effect = Exception("Service unavailable")

        detections, confidence = detect_with_rekognition(
            "images/part.jpg", client=mock_client
        )

        assert detections == []
        assert confidence == 0.0

    def test_label_without_instances_does_not_produce_detection(self):
        """Labels without bounding box instances should not create detections."""
        mock_client = MagicMock()
        mock_client.detect_labels.return_value = {
            "Labels": [
                {"Name": "Scratch", "Confidence": 90.0, "Instances": []}
            ]
        }

        detections, confidence = detect_with_rekognition(
            "images/part.jpg", client=mock_client
        )

        # No bounding-box instances → no detection rows, but confidence still tracked.
        assert detections == []
        assert confidence == 0.9

    # --- Label → defect-type mapping ---

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
        verdict, defect_rate, threshold_exceeded = analyse_defects(
            detections=[], product_type="TITANIUM_BRACKET"
        )
        assert verdict == "PASS"
        assert defect_rate == 0.0
        assert threshold_exceeded is False

    def test_only_no_defect_detections_pass(self):
        detections = [{"defect_type": "NO_DEFECT", "confidence": 0.95}]
        verdict, defect_rate, threshold_exceeded = analyse_defects(
            detections=detections, product_type="TITANIUM_BRACKET"
        )
        assert verdict == "PASS"
        assert defect_rate == 0.0
        assert threshold_exceeded is False

    def test_crack_defect_fails(self):
        verdict, _, _ = analyse_defects(
            [{"defect_type": "CRACK", "confidence": 0.90}],
            "TITANIUM_BRACKET",
        )
        assert verdict == "FAIL"

    def test_misalignment_defect_fails(self):
        verdict, _, _ = analyse_defects(
            [{"defect_type": "MISALIGNMENT", "confidence": 0.88}],
            "TITANIUM_BRACKET",
        )
        assert verdict == "FAIL"

    def test_scratch_defect_review(self):
        verdict, _, _ = analyse_defects(
            [{"defect_type": "SCRATCH", "confidence": 0.80}],
            "TITANIUM_BRACKET",
            batch_size=100,
        )
        assert verdict == "REVIEW"

    def test_dent_defect_review(self):
        verdict, _, _ = analyse_defects(
            [{"defect_type": "DENT", "confidence": 0.82}],
            "TITANIUM_BRACKET",
            batch_size=100,
        )
        assert verdict == "REVIEW"

    def test_discoloration_defect_review(self):
        verdict, _, _ = analyse_defects(
            [{"defect_type": "DISCOLORATION", "confidence": 0.78}],
            "TITANIUM_BRACKET",
            batch_size=100,
        )
        assert verdict == "REVIEW"

    def test_low_confidence_triggers_review(self):
        """Low average confidence (< 0.6) → REVIEW regardless of defect type."""
        verdict, _, _ = analyse_defects(
            [{"defect_type": "SCRATCH", "confidence": 0.45}],
            "TITANIUM_BRACKET",
        )
        assert verdict == "REVIEW"

    def test_threshold_exceeded_titanium_bracket(self):
        """Defect rate > 5% for TITANIUM_BRACKET → threshold_exceeded=True."""
        verdict, defect_rate, threshold_exceeded = analyse_defects(
            [{"defect_type": "SCRATCH", "confidence": 0.80}],
            "TITANIUM_BRACKET",
            batch_size=1,
        )
        assert threshold_exceeded is True
        assert defect_rate == 1.0

    def test_threshold_not_exceeded_large_batch(self):
        """1 defect in batch of 100 → defect_rate = 0.01 < 0.05 threshold."""
        _, defect_rate, threshold_exceeded = analyse_defects(
            [{"defect_type": "SCRATCH", "confidence": 0.80}],
            "TITANIUM_BRACKET",
            batch_size=100,
        )
        assert threshold_exceeded is False
        assert defect_rate == 0.01

    def test_threshold_exceeded_fuselage_panel(self):
        """FUSELAGE_PANEL has stricter threshold (2%)."""
        _, _, threshold_exceeded = analyse_defects(
            [{"defect_type": "DENT", "confidence": 0.80}],
            "FUSELAGE_PANEL",
            batch_size=10,
        )
        assert threshold_exceeded is True

    def test_threshold_exceeded_engine_mount(self):
        """ENGINE_MOUNT has strictest threshold (1%)."""
        _, _, threshold_exceeded = analyse_defects(
            [{"defect_type": "SCRATCH", "confidence": 0.80}],
            "ENGINE_MOUNT",
            batch_size=50,
        )
        assert threshold_exceeded is True

    def test_threshold_exceeded_causes_fail_verdict(self):
        """When threshold is exceeded and no critical defects, verdict is FAIL."""
        detections = [
            {"defect_type": "SCRATCH", "confidence": 0.80},
            {"defect_type": "DENT", "confidence": 0.75},
            {"defect_type": "SCRATCH", "confidence": 0.82},
        ]
        verdict, _, threshold_exceeded = analyse_defects(
            detections, "TITANIUM_BRACKET", batch_size=1
        )
        assert threshold_exceeded is True
        assert verdict == "FAIL"

    def test_defect_rate_excludes_no_defect(self):
        """Defect rate = actual defects (NO_DEFECT excluded) / batch_size."""
        detections = [
            {"defect_type": "SCRATCH", "confidence": 0.80},
            {"defect_type": "DENT", "confidence": 0.75},
            {"defect_type": "NO_DEFECT", "confidence": 0.90},
        ]
        _, defect_rate, _ = analyse_defects(
            detections, "TITANIUM_BRACKET", batch_size=10
        )
        assert defect_rate == 0.2


class TestQCReportGenerator:
    """Tests for qc_report_generator worker."""

    def test_dynamodb_write(self):
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
            primary_model="rekognition",
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
        assert item["primary_model"] == "rekognition"
        assert item["threshold_exceeded"] is False
        assert result["inspection_report_id"] == "QCR-test-123"

    def test_dynamodb_write_with_defects(self):
        mock_table = MagicMock()
        defects = [
            {
                "defect_type": "SCRATCH",
                "confidence": 0.85,
                "bounding_box": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
            },
        ]

        generate_report(
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
            primary_model="rekognition",
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
            primary_model="rekognition",
            confidence_score=0.95,
            defect_rate=0.0,
            threshold_exceeded=False,
            table=mock_table,
        )

        assert result["inspection_report_id"] == "QCR-test-err"

    def test_report_contains_timestamp(self):
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
            primary_model="rekognition",
            confidence_score=0.90,
            defect_rate=0.0,
            threshold_exceeded=False,
            table=mock_table,
        )

        assert "inspected_at" in result
        assert result["inspected_at"] is not None


class TestManagerPipeline:
    """Tests for the Quality Vision Manager handler — Rekognition-only path."""

    def test_handler_uses_rekognition_as_primary_model(self):
        """The handler always reports primary_model='rekognition'."""
        from agents.quality_vision.manager.handler import handler

        with patch("agents.quality_vision.manager.handler.preprocess_image") as mock_pre, \
             patch("agents.quality_vision.manager.handler.detect_with_rekognition") as mock_rek, \
             patch("agents.quality_vision.manager.handler.generate_report") as mock_report:

            mock_pre.return_value = {
                "s3_key": "images/part.jpg",
                "target_size": (640, 640),
                "normalized": True,
                "original_size_bytes": 1024,
            }
            mock_rek.return_value = ([], 0.0)
            mock_report.return_value = {"inspection_report_id": "QCR-test"}

            event = {
                "machine_id": "CNC-AERO-01",
                "production_line": "LINE-A",
                "image_s3_key": "images/part.jpg",
                "product_type": "TITANIUM_BRACKET",
                "batch_number": "BATCH-001",
            }
            result = handler(event, context=None)

            assert result["primary_model"] == "rekognition"
            mock_rek.assert_called_once_with("images/part.jpg")

    def test_handler_returns_pass_on_empty_detections(self):
        from agents.quality_vision.manager.handler import handler

        with patch("agents.quality_vision.manager.handler.preprocess_image") as mock_pre, \
             patch("agents.quality_vision.manager.handler.detect_with_rekognition") as mock_rek, \
             patch("agents.quality_vision.manager.handler.generate_report") as mock_report:

            mock_pre.return_value = {"s3_key": "images/part.jpg", "target_size": (640, 640),
                                      "normalized": True, "original_size_bytes": 100}
            mock_rek.return_value = ([], 0.0)
            mock_report.return_value = {"inspection_report_id": "QCR-pass"}

            result = handler({
                "machine_id": "CNC-AERO-01",
                "production_line": "LINE-A",
                "image_s3_key": "images/clean.jpg",
                "product_type": "TITANIUM_BRACKET",
                "batch_number": "BATCH-002",
            }, context=None)

            assert result["verdict"] == "PASS"
            assert result["defects_found"] == []

    def test_handler_processing_time_within_sla(self):
        """processing_time_ms must be tracked and under the 3000ms SLA."""
        from agents.quality_vision.manager.handler import handler

        with patch("agents.quality_vision.manager.handler.preprocess_image") as mock_pre, \
             patch("agents.quality_vision.manager.handler.detect_with_rekognition") as mock_rek, \
             patch("agents.quality_vision.manager.handler.generate_report") as mock_report:

            mock_pre.return_value = {"s3_key": "x", "target_size": (640, 640),
                                      "normalized": True, "original_size_bytes": 0}
            mock_rek.return_value = ([], 0.0)
            mock_report.return_value = {"inspection_report_id": "QCR-x"}

            result = handler({
                "machine_id": "CNC-AERO-01",
                "production_line": "LINE-A",
                "image_s3_key": "x",
                "product_type": "TITANIUM_BRACKET",
                "batch_number": "BATCH-007",
            }, context=None)

            assert "processing_time_ms" in result
            assert result["processing_time_ms"] < 3000
