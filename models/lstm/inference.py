"""SageMaker PyTorch container entry point for the LSTM maintenance model.

Lifecycle hooks (called by the SageMaker container automatically):
  - model_fn(model_dir):    load TorchScript model + feature config
  - input_fn(body, type):   parse JSON request from the Lambda agent
  - predict_fn(input, model): run inference
  - output_fn(pred, accept):  serialize JSON response

Request shape from agents/predictive_maintenance/workers/lstm_worker.py:
  {
    "machine_id": "CNC-AERO-08",
    "sensor_history": [
      {"timestamp": "...", "vibration_mms": 3.4, "current_amps": 18.2, ...},
      ...                      # up to 500 readings (last 72h aggregated)
    ],
    "current_snapshot": {"vibration_mms": 12.0, ...}
  }

Response shape (matches agents' lstm_worker.py expectations):
  {
    "severity": "CRITICAL",
    "failure_mode": "COOLANT_BLOCKAGE",
    "probability": 0.94,
    "remaining_useful_life_hours": 2.5,
    "confidence_interval": [0.91, 0.97]
  }
"""

from __future__ import annotations

import json
import logging
import os

import numpy as np
import torch

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


SEVERITY_CLASSES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
FAILURE_MODES = ["NORMAL", "TOOL_WEAR", "BEARING_WEAR", "COOLANT_BLOCKAGE"]
SEQ_LEN = 72
N_FEATURES = 4
RUL_MAX_HOURS = 168


def model_fn(model_dir: str) -> dict:
    """SageMaker calls this once at endpoint cold start."""
    model_path = os.path.join(model_dir, "model.pt")
    config_path = os.path.join(model_dir, "feature_config.json")

    model = torch.jit.load(model_path, map_location="cpu")
    model.eval()

    if os.path.isfile(config_path):
        with open(config_path) as f:
            feature_config = json.load(f)
    else:
        # Fallback: zero-mean unit-std (model still works, just less precise).
        feature_config = {
            "feature_mean": [0.0] * N_FEATURES,
            "feature_std": [1.0] * N_FEATURES,
            "severity_classes": SEVERITY_CLASSES,
            "failure_modes": FAILURE_MODES,
            "rul_max_hours": RUL_MAX_HOURS,
        }

    logger.info("LSTM maintenance model loaded from %s", model_dir)
    return {"model": model, "config": feature_config}


def input_fn(request_body: str, content_type: str) -> dict:
    """Parse the incoming request from the Predictive Maintenance Lambda."""
    if content_type != "application/json":
        raise ValueError(f"Unsupported content type: {content_type}")
    return json.loads(request_body)


def _build_sequence(payload: dict, mean: list, std: list) -> torch.Tensor:
    """Convert sensor_history list into a normalized [1, SEQ_LEN, 4] tensor.

    If history is shorter than SEQ_LEN, pad at the front with the oldest
    reading (right-aligned so the most recent reading is at index -1).
    If longer, take the last SEQ_LEN entries.
    """
    history = payload.get("sensor_history") or []
    if not history and payload.get("current_snapshot"):
        # Fall back to the snapshot replicated SEQ_LEN times.
        history = [payload["current_snapshot"]] * SEQ_LEN

    rows = []
    for entry in history:
        rows.append([
            float(entry.get("vibration_mms", 0.0)),
            float(entry.get("current_amps", 0.0)),
            float(entry.get("coolant_lmin", 0.0)),
            float(entry.get("acoustic_db", 0.0)),
        ])

    arr = np.array(rows, dtype=np.float32)

    if len(arr) >= SEQ_LEN:
        arr = arr[-SEQ_LEN:]
    else:
        # Front-pad with the first reading (or zeros if empty).
        pad = arr[0] if len(arr) else np.zeros(N_FEATURES, dtype=np.float32)
        padded = np.tile(pad, (SEQ_LEN - len(arr), 1))
        arr = np.concatenate([padded, arr]) if len(arr) else padded

    mean_arr = np.array(mean, dtype=np.float32)
    std_arr = np.array(std, dtype=np.float32) + 1e-6
    arr = (arr - mean_arr) / std_arr

    return torch.from_numpy(arr).unsqueeze(0)  # [1, SEQ_LEN, 4]


def predict_fn(input_data: dict, loaded: dict) -> dict:
    """Run inference and assemble the response payload."""
    model = loaded["model"]
    config = loaded["config"]

    x = _build_sequence(input_data, config["feature_mean"], config["feature_std"])

    with torch.no_grad():
        out = model(x)

    severity_logits = out["severity_logits"][0]
    failure_logits = out["failure_logits"][0]
    rul_norm = float(out["rul_normalized"][0].item())

    severity_probs = torch.softmax(severity_logits, dim=-1).numpy()
    failure_probs = torch.softmax(failure_logits, dim=-1).numpy()

    severity_idx = int(np.argmax(severity_probs))
    failure_idx = int(np.argmax(failure_probs))
    severity_prob = float(severity_probs[severity_idx])
    rul_hours = rul_norm * config.get("rul_max_hours", RUL_MAX_HOURS)

    # 95% confidence interval — rough heuristic from softmax sharpness.
    half_width = max(0.02, (1.0 - severity_prob) / 2)
    ci = [
        max(0.0, severity_prob - half_width),
        min(1.0, severity_prob + half_width),
    ]

    severity_classes = config.get("severity_classes", SEVERITY_CLASSES)
    failure_modes = config.get("failure_modes", FAILURE_MODES)

    return {
        "severity": severity_classes[severity_idx],
        "failure_mode": failure_modes[failure_idx],
        "probability": severity_prob,
        "remaining_useful_life_hours": rul_hours,
        "confidence_interval": ci,
        "all_severity_probabilities": dict(zip(severity_classes, severity_probs.tolist())),
        "all_failure_probabilities": dict(zip(failure_modes, failure_probs.tolist())),
    }


def output_fn(prediction: dict, accept: str) -> tuple[str, str]:
    """Serialize the response. SageMaker passes content-type negotiation here."""
    if accept != "application/json":
        raise ValueError(f"Unsupported accept type: {accept}")
    return json.dumps(prediction), "application/json"
