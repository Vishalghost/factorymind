"""ONNX Worker — sub-10ms inference using ONNX Runtime.

Loads the edge classifier model from Lambda Layer and runs inference
on the sliding window of CNC sensor readings.
"""

import time
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# Model is loaded once at cold start from Lambda Layer
_model_session = None


def _load_model() -> Any:
    """Load ONNX model from Lambda Layer path.

    Returns the cached session if already loaded. On any failure (missing
    onnxruntime, missing model file, corrupt model), returns None and the
    caller falls back to the rule-based path. Edge AI is fire-and-forget,
    so we never raise from this function.

    Returns:
        ONNX Runtime InferenceSession, or None if unavailable.
    """
    global _model_session
    if _model_session is not None:
        return _model_session

    try:
        import onnxruntime as ort
        import os

        model_path = os.environ.get(
            "ONNX_MODEL_PATH", "/opt/models/edge_classifier_v2.onnx"
        )
        if not os.path.isfile(model_path):
            logger.warning("onnx_model_missing", path=model_path)
            return None

        _model_session = ort.InferenceSession(model_path)
        logger.info("onnx_model_loaded", path=model_path)
    except Exception as e:
        # Catches ImportError (no onnxruntime), NoSuchFile, Fail (corrupt model).
        # Caller falls back to _rule_based_inference.
        _model_session = None
        logger.warning("onnx_load_failed", error=str(e))

    return _model_session


def run_inference(
    sensor_values: dict[str, float],
    sliding_window: list[dict[str, Any]],
) -> tuple[np.ndarray, float]:
    """Run ONNX inference on current reading + sliding window.

    Must complete in < 10ms.

    Args:
        sensor_values: Current telemetry dict with vibration_mms, current_amps, etc.
        sliding_window: List of recent readings for context.

    Returns:
        Tuple of (model output array, inference_time_ms).
    """
    start = time.perf_counter()

    # Prepare input features: current reading + window statistics
    features = _prepare_features(sensor_values, sliding_window)

    session = _load_model()
    if session is not None:
        input_name = session.get_inputs()[0].name
        output = session.run(None, {input_name: features})
        result = output[0]
    else:
        # Rule-based fallback when ONNX not available
        result = _rule_based_inference(sensor_values)

    inference_time_ms = (time.perf_counter() - start) * 1000
    return result, inference_time_ms


def _prepare_features(
    sensor_values: dict[str, float],
    sliding_window: list[dict[str, Any]],
) -> np.ndarray:
    """Prepare feature vector for ONNX model.

    Features: [vibration, current, coolant, acoustic, window_mean_vib, window_std_vib]
    """
    vib = sensor_values.get("vibration_mms", 0.0)
    cur = sensor_values.get("current_amps", 0.0)
    cool = sensor_values.get("coolant_lmin", 0.0)
    aco = sensor_values.get("acoustic_db", 0.0)

    # Window statistics for trend detection
    if sliding_window:
        window_vibs = [r.get("vibration_mms", 0.0) for r in sliding_window]
        window_mean_vib = float(np.mean(window_vibs))
        window_std_vib = float(np.std(window_vibs))
    else:
        window_mean_vib = vib
        window_std_vib = 0.0

    features = np.array(
        [[vib, cur, cool, aco, window_mean_vib, window_std_vib]],
        dtype=np.float32,
    )
    return features


def _rule_based_inference(sensor_values: dict[str, float]) -> np.ndarray:
    """Rule-based fallback when ONNX Runtime is not available.

    Returns array with [normal_prob, warning_prob, anomaly_prob].
    """
    from agents.shared.constants import (
        VIBRATION_NORMAL_MAX,
        VIBRATION_ANOMALY_THRESHOLD,
        CURRENT_NORMAL_MAX,
        CURRENT_ANOMALY_THRESHOLD,
        COOLANT_NORMAL_MIN,
        COOLANT_ANOMALY_THRESHOLD,
        ACOUSTIC_NORMAL_MAX,
        ACOUSTIC_ANOMALY_THRESHOLD,
        COMPOUND_RULE_VIBRATION_THRESHOLD,
        COMPOUND_RULE_COOLANT_THRESHOLD,
    )

    vib = sensor_values.get("vibration_mms", 0.0)
    cur = sensor_values.get("current_amps", 0.0)
    cool = sensor_values.get("coolant_lmin", 50.0)
    aco = sensor_values.get("acoustic_db", 0.0)

    # Compound rule: immediate anomaly
    if vib > COMPOUND_RULE_VIBRATION_THRESHOLD and cool < COMPOUND_RULE_COOLANT_THRESHOLD:
        return np.array([[0.0, 0.0, 1.0]], dtype=np.float32)

    # Individual anomaly checks
    if (
        vib > VIBRATION_ANOMALY_THRESHOLD
        or cur > CURRENT_ANOMALY_THRESHOLD
        or cool < COOLANT_ANOMALY_THRESHOLD
        or aco > ACOUSTIC_ANOMALY_THRESHOLD
    ):
        return np.array([[0.0, 0.1, 0.9]], dtype=np.float32)

    # Warning zone checks
    if (
        vib > VIBRATION_NORMAL_MAX
        or cur > CURRENT_NORMAL_MAX
        or cool < COOLANT_NORMAL_MIN
        or aco > ACOUSTIC_NORMAL_MAX
    ):
        return np.array([[0.1, 0.8, 0.1]], dtype=np.float32)

    # Normal
    return np.array([[0.9, 0.1, 0.0]], dtype=np.float32)
