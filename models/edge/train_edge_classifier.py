#!/usr/bin/env python3
"""Train the Edge AI ONNX classifier for aerospace CNC titanium milling.

Architecture: 3-layer MLP (6 → 32 → 16 → 3-class softmax)
  Input features (matching agents/edge_ai/workers/onnx_worker.py:_prepare_features):
    [vibration_mms, current_amps, coolant_lmin, acoustic_db,
     window_mean_vib, window_std_vib]
  Output classes: [NORMAL, WARNING, ANOMALY]

Training data is synthetic — generated from the spec's known-good ranges so the
classifier learns the same boundaries as the rule-based fallback. This isn't a
substitute for a model trained on real plant data, but it produces a working
ONNX artifact for hackathon demos and CI.

Usage:
    pip install -r requirements-ml.txt
    python models/edge/train_edge_classifier.py

Outputs:
    models/edge/edge_classifier_v2.onnx        — Lambda Layer artifact
    models/edge/edge_classifier_v2.metrics.json — accuracy, class breakdown
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from agents.shared.constants import (  # noqa: E402
    ACOUSTIC_ANOMALY_THRESHOLD,
    ACOUSTIC_NORMAL_MAX,
    ACOUSTIC_NORMAL_MIN,
    COOLANT_ANOMALY_THRESHOLD,
    COOLANT_NORMAL_MAX,
    COOLANT_NORMAL_MIN,
    CURRENT_ANOMALY_THRESHOLD,
    CURRENT_NORMAL_MAX,
    CURRENT_NORMAL_MIN,
    VIBRATION_ANOMALY_THRESHOLD,
    VIBRATION_NORMAL_MAX,
    VIBRATION_NORMAL_MIN,
)


# Class labels mirror agents/shared/models/edge.py EdgeClassification
NORMAL, WARNING, ANOMALY = 0, 1, 2
N_FEATURES = 6
N_CLASSES = 3
SEED = 42


class EdgeClassifier(nn.Module):
    """Small MLP — keeps ONNX inference comfortably under 10ms on Lambda."""

    def __init__(self) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(N_FEATURES, 32),
            nn.ReLU(),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, N_CLASSES),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Returns softmax probabilities so the agent classifier can do argmax.
        return torch.softmax(self.net(x), dim=-1)


def _sample_telemetry(label: int, rng: np.random.Generator) -> tuple[float, float, float, float]:
    """Sample (vibration, current, coolant, acoustic) for a given label.

    NORMAL  — all four sensors comfortably within normal ranges.
    WARNING — one sensor drifted into the warning zone, others normal.
    ANOMALY — one sensor breaches its anomaly threshold, often paired with
              degraded coolant to mimic real tool-wear progressions.
    """
    if label == NORMAL:
        return (
            rng.uniform(VIBRATION_NORMAL_MIN, VIBRATION_NORMAL_MAX),
            rng.uniform(CURRENT_NORMAL_MIN, CURRENT_NORMAL_MAX),
            rng.uniform(COOLANT_NORMAL_MIN, COOLANT_NORMAL_MAX),
            rng.uniform(ACOUSTIC_NORMAL_MIN, ACOUSTIC_NORMAL_MAX),
        )

    if label == WARNING:
        # Pick one sensor to push into the warning band.
        which = rng.integers(0, 4)
        vib = rng.uniform(VIBRATION_NORMAL_MIN, VIBRATION_NORMAL_MAX)
        cur = rng.uniform(CURRENT_NORMAL_MIN, CURRENT_NORMAL_MAX)
        cool = rng.uniform(COOLANT_NORMAL_MIN, COOLANT_NORMAL_MAX)
        aco = rng.uniform(ACOUSTIC_NORMAL_MIN, ACOUSTIC_NORMAL_MAX)
        if which == 0:
            vib = rng.uniform(VIBRATION_NORMAL_MAX, VIBRATION_ANOMALY_THRESHOLD)
        elif which == 1:
            cur = rng.uniform(CURRENT_NORMAL_MAX, CURRENT_ANOMALY_THRESHOLD)
        elif which == 2:
            cool = rng.uniform(COOLANT_ANOMALY_THRESHOLD, COOLANT_NORMAL_MIN)
        else:
            aco = rng.uniform(ACOUSTIC_NORMAL_MAX, ACOUSTIC_ANOMALY_THRESHOLD)
        return vib, cur, cool, aco

    # ANOMALY: at least one sensor breaches its anomaly threshold.
    which = rng.integers(0, 4)
    vib = rng.uniform(VIBRATION_NORMAL_MIN, VIBRATION_NORMAL_MAX)
    cur = rng.uniform(CURRENT_NORMAL_MIN, CURRENT_NORMAL_MAX)
    cool = rng.uniform(COOLANT_NORMAL_MIN, COOLANT_NORMAL_MAX)
    aco = rng.uniform(ACOUSTIC_NORMAL_MIN, ACOUSTIC_NORMAL_MAX)
    if which == 0:
        vib = rng.uniform(VIBRATION_ANOMALY_THRESHOLD, 18.0)
    elif which == 1:
        cur = rng.uniform(CURRENT_ANOMALY_THRESHOLD, 48.0)
    elif which == 2:
        cool = rng.uniform(2.0, COOLANT_ANOMALY_THRESHOLD)
    else:
        aco = rng.uniform(ACOUSTIC_ANOMALY_THRESHOLD, 115.0)

    # Compound failures: vibration breach often coincides with coolant blockage.
    if which == 0 and rng.random() < 0.4:
        cool = rng.uniform(2.0, COOLANT_ANOMALY_THRESHOLD)
    return vib, cur, cool, aco


def _build_features(vib: float, cur: float, cool: float, aco: float, rng: np.random.Generator) -> np.ndarray:
    """Mirror agents/edge_ai/workers/onnx_worker.py:_prepare_features.

    Window stats are synthesised so the model sees realistic correlation between
    the current reading and the trailing window summary.
    """
    window_mean = vib + rng.normal(0.0, 0.3)
    window_std = abs(rng.normal(0.5, 0.2))
    return np.array([vib, cur, cool, aco, window_mean, window_std], dtype=np.float32)


def generate_dataset(samples_per_class: int, seed: int = SEED) -> tuple[np.ndarray, np.ndarray]:
    """Balanced dataset across the three classes."""
    rng = np.random.default_rng(seed)
    X, y = [], []
    for label in (NORMAL, WARNING, ANOMALY):
        for _ in range(samples_per_class):
            vib, cur, cool, aco = _sample_telemetry(label, rng)
            X.append(_build_features(vib, cur, cool, aco, rng))
            y.append(label)
    X = np.stack(X)
    y = np.array(y, dtype=np.int64)
    perm = rng.permutation(len(X))
    return X[perm], y[perm]


def train(samples_per_class: int = 4000, epochs: int = 20, batch_size: int = 128) -> dict:
    """Train the MLP and return final metrics + the trained model."""
    torch.manual_seed(SEED)
    np.random.seed(SEED)

    X, y = generate_dataset(samples_per_class)
    n_train = int(0.85 * len(X))
    X_train, y_train = X[:n_train], y[:n_train]
    X_val, y_val = X[n_train:], y[n_train:]

    train_ds = TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train))
    val_ds = TensorDataset(torch.from_numpy(X_val), torch.from_numpy(y_val))

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size)

    model = EdgeClassifier()
    optim = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.NLLLoss()

    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for xb, yb in train_loader:
            optim.zero_grad()
            probs = model(xb)
            # NLLLoss expects log-probabilities; clamp to avoid log(0).
            log_probs = torch.log(probs.clamp(min=1e-9))
            loss = loss_fn(log_probs, yb)
            loss.backward()
            optim.step()
            train_loss += loss.item() * xb.size(0)
        train_loss /= len(train_ds)

        model.eval()
        correct = 0
        with torch.no_grad():
            for xb, yb in val_loader:
                preds = model(xb).argmax(dim=-1)
                correct += (preds == yb).sum().item()
        val_acc = correct / len(val_ds)
        print(f"  epoch {epoch + 1:2d}/{epochs}  train_loss={train_loss:.4f}  val_acc={val_acc:.4f}")

    # Per-class accuracy on the held-out set.
    model.eval()
    with torch.no_grad():
        preds = model(torch.from_numpy(X_val)).argmax(dim=-1).numpy()
    per_class_acc = {
        "NORMAL": float((preds[y_val == NORMAL] == NORMAL).mean()),
        "WARNING": float((preds[y_val == WARNING] == WARNING).mean()),
        "ANOMALY": float((preds[y_val == ANOMALY] == ANOMALY).mean()),
    }

    return {
        "model": model,
        "val_accuracy": val_acc,
        "per_class_accuracy": per_class_acc,
        "samples_per_class": samples_per_class,
        "epochs": epochs,
    }


def export_onnx(model: nn.Module, output_path: Path) -> None:
    """Export the trained model to ONNX with a static input signature.

    Lambda Layer expects the file at /opt/models/edge_classifier_v2.onnx.
    """
    model.eval()
    dummy = torch.zeros(1, N_FEATURES, dtype=torch.float32)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        dummy,
        str(output_path),
        input_names=["features"],
        output_names=["probabilities"],
        dynamic_axes={
            "features": {0: "batch"},
            "probabilities": {0: "batch"},
        },
        opset_version=17,
    )
    print(f"  ONNX written: {output_path}")


def smoke_test_onnx(onnx_path: Path) -> None:
    """Round-trip a known-anomalous sample through the exported ONNX file."""
    import onnxruntime as ort

    session = ort.InferenceSession(str(onnx_path))
    # Compound failure: vib=12, cool=10
    sample = np.array([[12.0, 38.0, 10.0, 98.0, 11.5, 0.6]], dtype=np.float32)
    out = session.run(None, {"features": sample})[0][0]
    pred_idx = int(np.argmax(out))
    label = ["NORMAL", "WARNING", "ANOMALY"][pred_idx]
    print(f"  smoke test: {label} (probs={out.round(3).tolist()})")
    assert pred_idx == ANOMALY, f"expected ANOMALY for compound failure, got {label}"


def main() -> None:
    out_dir = Path(__file__).parent
    onnx_path = out_dir / "edge_classifier_v2.onnx"
    metrics_path = out_dir / "edge_classifier_v2.metrics.json"

    print("Training Edge AI ONNX classifier...")
    result = train()
    print(f"  final val_accuracy: {result['val_accuracy']:.4f}")
    print(f"  per-class accuracy: {result['per_class_accuracy']}")

    print("\nExporting to ONNX...")
    export_onnx(result["model"], onnx_path)

    print("\nSmoke-testing exported model...")
    smoke_test_onnx(onnx_path)

    metrics_path.write_text(
        json.dumps(
            {
                "val_accuracy": result["val_accuracy"],
                "per_class_accuracy": result["per_class_accuracy"],
                "samples_per_class": result["samples_per_class"],
                "epochs": result["epochs"],
                "n_features": N_FEATURES,
                "n_classes": N_CLASSES,
                "input_name": "features",
                "output_name": "probabilities",
            },
            indent=2,
        )
    )
    print(f"\nMetrics: {metrics_path}")
    print(f"\nNext step: rebuild the Lambda layer so it picks up the new model:")
    print("  ./scripts/build_layers.sh")


if __name__ == "__main__":
    main()
