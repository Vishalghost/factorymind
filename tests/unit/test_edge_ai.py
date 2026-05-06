"""Unit tests for Edge AI Manager."""

import json
import pytest
import numpy as np

from agents.edge_ai.workers.edge_cache import get_sliding_window, update_sliding_window
from agents.edge_ai.workers.edge_classifier import classify, ClassificationResult
from agents.edge_ai.workers.onnx_worker import _rule_based_inference
from agents.shared.models.edge import EdgeClassification


class FakeRedis:
    """Minimal fake Redis for testing."""

    def __init__(self):
        self._data: dict[str, list] = {}

    def lrange(self, key: str, start: int, end: int) -> list:
        data = self._data.get(key, [])
        return [json.dumps(item).encode() for item in data[start:end + 1]]

    def lpush(self, key: str, value: str) -> int:
        if key not in self._data:
            self._data[key] = []
        self._data[key].insert(0, json.loads(value))
        return len(self._data[key])

    def ltrim(self, key: str, start: int, end: int) -> None:
        if key in self._data:
            self._data[key] = self._data[key][start:end + 1]

    def llen(self, key: str) -> int:
        return len(self._data.get(key, []))


class TestEdgeCache:
    """Tests for Redis sliding window management."""

    def test_empty_window(self):
        redis = FakeRedis()
        window = get_sliding_window("CNC-AERO-01", redis)
        assert window == []

    def test_update_and_retrieve(self):
        redis = FakeRedis()
        values = {"vibration_mms": 3.4, "current_amps": 18.2}
        update_sliding_window("CNC-AERO-01", values, redis)
        window = get_sliding_window("CNC-AERO-01", redis)
        assert len(window) == 1
        assert window[0]["vibration_mms"] == 3.4

    def test_window_max_size_10(self):
        redis = FakeRedis()
        for i in range(15):
            values = {"vibration_mms": float(i), "current_amps": 18.0}
            update_sliding_window("CNC-AERO-01", values, redis)

        window = get_sliding_window("CNC-AERO-01", redis)
        assert len(window) == 10
        # Most recent should be first
        assert window[0]["vibration_mms"] == 14.0

    def test_separate_machines(self):
        redis = FakeRedis()
        update_sliding_window("CNC-AERO-01", {"vibration_mms": 3.0}, redis)
        update_sliding_window("CNC-AERO-02", {"vibration_mms": 5.0}, redis)

        w1 = get_sliding_window("CNC-AERO-01", redis)
        w2 = get_sliding_window("CNC-AERO-02", redis)
        assert w1[0]["vibration_mms"] == 3.0
        assert w2[0]["vibration_mms"] == 5.0


class TestEdgeClassifier:
    """Tests for edge classification logic."""

    def test_normal_classification(self):
        """All values in normal range → NORMAL."""
        model_output = np.array([[0.9, 0.08, 0.02]], dtype=np.float32)
        sensor_values = {
            "vibration_mms": 3.4,
            "current_amps": 18.2,
            "coolant_lmin": 45.1,
            "acoustic_db": 78.5,
        }
        result = classify(model_output, sensor_values)
        assert result.classification == EdgeClassification.NORMAL
        assert result.confidence >= 0.89  # float32 precision
        assert result.compound_rule_triggered is False

    def test_warning_classification(self):
        """Warning zone values → WARNING."""
        model_output = np.array([[0.1, 0.8, 0.1]], dtype=np.float32)
        sensor_values = {
            "vibration_mms": 6.5,
            "current_amps": 28.0,
            "coolant_lmin": 35.0,
            "acoustic_db": 88.0,
        }
        result = classify(model_output, sensor_values)
        assert result.classification == EdgeClassification.WARNING

    def test_anomaly_classification(self):
        """Anomaly zone values → ANOMALY."""
        model_output = np.array([[0.0, 0.1, 0.9]], dtype=np.float32)
        sensor_values = {
            "vibration_mms": 9.0,
            "current_amps": 18.2,
            "coolant_lmin": 45.1,
            "acoustic_db": 78.5,
        }
        result = classify(model_output, sensor_values)
        assert result.classification == EdgeClassification.ANOMALY
        assert result.compound_rule_triggered is False

    def test_compound_rule_overrides_model(self):
        """Compound rule: vibration >8.0 AND coolant <30.0 → ANOMALY regardless of model."""
        # Even if model says NORMAL, compound rule overrides
        model_output = np.array([[0.9, 0.05, 0.05]], dtype=np.float32)
        sensor_values = {
            "vibration_mms": 10.0,
            "current_amps": 18.2,
            "coolant_lmin": 25.0,  # Below 30.0
            "acoustic_db": 78.5,
        }
        result = classify(model_output, sensor_values)
        assert result.classification == EdgeClassification.ANOMALY
        assert result.confidence == 1.0
        assert result.compound_rule_triggered is True

    def test_compound_rule_not_triggered_vibration_only(self):
        """High vibration alone doesn't trigger compound rule."""
        model_output = np.array([[0.0, 0.1, 0.9]], dtype=np.float32)
        sensor_values = {
            "vibration_mms": 10.0,
            "current_amps": 18.2,
            "coolant_lmin": 45.0,  # Normal coolant
            "acoustic_db": 78.5,
        }
        result = classify(model_output, sensor_values)
        assert result.classification == EdgeClassification.ANOMALY
        assert result.compound_rule_triggered is False

    def test_compound_rule_not_triggered_coolant_only(self):
        """Low coolant alone doesn't trigger compound rule."""
        model_output = np.array([[0.0, 0.1, 0.9]], dtype=np.float32)
        sensor_values = {
            "vibration_mms": 4.0,  # Normal vibration
            "current_amps": 18.2,
            "coolant_lmin": 25.0,
            "acoustic_db": 78.5,
        }
        result = classify(model_output, sensor_values)
        assert result.classification == EdgeClassification.ANOMALY
        assert result.compound_rule_triggered is False


class TestRuleBasedInference:
    """Tests for rule-based fallback when ONNX not available."""

    def test_normal_values(self):
        result = _rule_based_inference({
            "vibration_mms": 3.4,
            "current_amps": 18.2,
            "coolant_lmin": 45.1,
            "acoustic_db": 78.5,
        })
        # Should return high normal probability
        assert result[0][0] > 0.5  # normal_prob

    def test_warning_vibration(self):
        result = _rule_based_inference({
            "vibration_mms": 6.5,  # Between 5.0 and 8.0
            "current_amps": 18.2,
            "coolant_lmin": 45.1,
            "acoustic_db": 78.5,
        })
        # Should return high warning probability
        assert result[0][1] > 0.5  # warning_prob

    def test_anomaly_vibration(self):
        result = _rule_based_inference({
            "vibration_mms": 9.0,  # Above 8.0
            "current_amps": 18.2,
            "coolant_lmin": 45.1,
            "acoustic_db": 78.5,
        })
        # Should return high anomaly probability
        assert result[0][2] > 0.5  # anomaly_prob

    def test_compound_rule(self):
        result = _rule_based_inference({
            "vibration_mms": 10.0,
            "current_amps": 18.2,
            "coolant_lmin": 25.0,  # Below 30.0
            "acoustic_db": 78.5,
        })
        # Should return maximum anomaly probability
        assert result[0][2] == 1.0  # anomaly_prob

    def test_coolant_anomaly(self):
        result = _rule_based_inference({
            "vibration_mms": 3.4,
            "current_amps": 18.2,
            "coolant_lmin": 25.0,  # Below 30.0
            "acoustic_db": 78.5,
        })
        assert result[0][2] > 0.5  # anomaly_prob
