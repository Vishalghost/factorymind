#!/usr/bin/env python3
"""Train the LSTM tool-wear predictor for aerospace CNC titanium milling.

Inputs:  72-hour sensor history → [seq_len, 4] tensor (vib, cur, cool, aco).
Outputs: severity ∈ {LOW, MEDIUM, HIGH, CRITICAL},
         failure_mode ∈ {TOOL_WEAR, BEARING_WEAR, COOLANT_BLOCKAGE, NORMAL},
         probability ∈ [0, 1],
         remaining_useful_life_hours ∈ [0, 168].

Synthetic data generator simulates three regimes:
  - HEALTHY:        steady noise around baselines, no degradation
  - GRADUAL_WEAR:   current and vibration drift up over the window
  - ABRUPT_FAILURE: sudden coolant drop with vibration spike (compound rule)

The trained model is saved as TorchScript so the SageMaker PyTorch container
can load it without our Python source code at inference time.

Usage:
    pip install -r requirements-ml.txt
    python models/lstm/train_lstm_maintenance.py

Outputs:
    models/lstm/model.pt              — TorchScript model
    models/lstm/metrics.json          — final accuracy + RUL MAE
    models/lstm/feature_config.json   — input contract for inference.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from agents.shared.constants import (  # noqa: E402
    ACOUSTIC_NORMAL_MAX,
    ACOUSTIC_NORMAL_MIN,
    COOLANT_NORMAL_MAX,
    COOLANT_NORMAL_MIN,
    CURRENT_NORMAL_MAX,
    CURRENT_NORMAL_MIN,
    SIM_ACOUSTIC_BASELINE,
    SIM_COOLANT_BASELINE,
    SIM_CURRENT_BASELINE,
    SIM_VIBRATION_BASELINE,
    VIBRATION_NORMAL_MAX,
    VIBRATION_NORMAL_MIN,
)


SEQ_LEN = 72                      # 72 hourly samples (1 reading/hour aggregated)
N_FEATURES = 4                    # vib, cur, cool, aco
SEED = 42

# Severity classes
SEVERITY_CLASSES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
LOW, MEDIUM, HIGH, CRITICAL = 0, 1, 2, 3

# Failure modes
FAILURE_MODES = ["NORMAL", "TOOL_WEAR", "BEARING_WEAR", "COOLANT_BLOCKAGE"]
NORMAL, TOOL_WEAR, BEARING_WEAR, COOLANT_BLOCKAGE = 0, 1, 2, 3


class LSTMMaintenance(nn.Module):
    """LSTM with three heads: severity classifier, failure-mode classifier, RUL regressor."""

    def __init__(self, hidden_size: int = 64, num_layers: int = 2) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=N_FEATURES,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=0.1 if num_layers > 1 else 0.0,
        )
        self.severity_head = nn.Linear(hidden_size, len(SEVERITY_CLASSES))
        self.failure_head = nn.Linear(hidden_size, len(FAILURE_MODES))
        # RUL bounded to [0, 168] hours via sigmoid * 168.
        self.rul_head = nn.Sequential(nn.Linear(hidden_size, 1), nn.Sigmoid())

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        out, _ = self.lstm(x)
        last = out[:, -1, :]  # take final timestep
        return {
            "severity_logits": self.severity_head(last),
            "failure_logits": self.failure_head(last),
            "rul_normalized": self.rul_head(last).squeeze(-1),
        }


# ---------------------------------------------------------------
# Synthetic dataset
# ---------------------------------------------------------------


def _healthy_sequence(rng: np.random.Generator) -> np.ndarray:
    seq = np.column_stack([
        rng.normal(SIM_VIBRATION_BASELINE, 0.4, SEQ_LEN),
        rng.normal(SIM_CURRENT_BASELINE, 0.8, SEQ_LEN),
        rng.normal(SIM_COOLANT_BASELINE, 1.0, SEQ_LEN),
        rng.normal(SIM_ACOUSTIC_BASELINE, 1.5, SEQ_LEN),
    ])
    return _clip(seq)


def _gradual_wear_sequence(rng: np.random.Generator) -> tuple[np.ndarray, int, int, float]:
    """Tool wear: current and vibration drift upward through the window."""
    t = np.arange(SEQ_LEN, dtype=np.float32)
    drift_severity = rng.uniform(0.4, 1.0)  # how aggressive the drift is

    vib = SIM_VIBRATION_BASELINE + drift_severity * 0.05 * t + rng.normal(0, 0.3, SEQ_LEN)
    cur = SIM_CURRENT_BASELINE + drift_severity * 0.15 * t + rng.normal(0, 0.6, SEQ_LEN)
    cool = rng.normal(SIM_COOLANT_BASELINE, 1.0, SEQ_LEN)
    aco = SIM_ACOUSTIC_BASELINE + drift_severity * 0.1 * t + rng.normal(0, 1.2, SEQ_LEN)

    seq = _clip(np.column_stack([vib, cur, cool, aco]))

    # Severity label depends on whether the final reading crosses thresholds.
    final_vib, final_cur = seq[-1, 0], seq[-1, 1]
    if final_vib > 9.0 or final_cur > 38.0:
        severity = HIGH
    elif final_vib > VIBRATION_NORMAL_MAX or final_cur > CURRENT_NORMAL_MAX:
        severity = MEDIUM
    else:
        severity = LOW

    failure_mode = TOOL_WEAR
    # RUL: how many hours until tool replacement; faster drift → less time left.
    rul_hours = float(np.clip(168 * (1 - drift_severity), 4, 168))
    return seq, severity, failure_mode, rul_hours


def _bearing_wear_sequence(rng: np.random.Generator) -> tuple[np.ndarray, int, int, float]:
    """Bearing wear: oscillating vibration with rising amplitude."""
    t = np.arange(SEQ_LEN, dtype=np.float32)
    amplitude = rng.uniform(0.5, 2.5)
    osc = amplitude * np.sin(t * 0.5) * (t / SEQ_LEN)

    vib = SIM_VIBRATION_BASELINE + osc + rng.normal(0, 0.4, SEQ_LEN)
    cur = rng.normal(SIM_CURRENT_BASELINE, 1.0, SEQ_LEN)
    cool = rng.normal(SIM_COOLANT_BASELINE, 1.0, SEQ_LEN)
    aco = SIM_ACOUSTIC_BASELINE + osc * 1.5 + rng.normal(0, 1.2, SEQ_LEN)

    seq = _clip(np.column_stack([vib, cur, cool, aco]))
    severity = HIGH if amplitude > 1.8 else MEDIUM
    rul_hours = float(np.clip(168 * (1 - amplitude / 3.0), 8, 168))
    return seq, severity, BEARING_WEAR, rul_hours


def _coolant_blockage_sequence(rng: np.random.Generator) -> tuple[np.ndarray, int, int, float]:
    """Coolant blockage: sudden coolant drop in last 5-15 timesteps."""
    drop_start = rng.integers(SEQ_LEN - 15, SEQ_LEN - 5)

    vib = rng.normal(SIM_VIBRATION_BASELINE, 0.4, SEQ_LEN)
    cur = rng.normal(SIM_CURRENT_BASELINE, 0.8, SEQ_LEN)
    cool = rng.normal(SIM_COOLANT_BASELINE, 1.0, SEQ_LEN)
    aco = rng.normal(SIM_ACOUSTIC_BASELINE, 1.5, SEQ_LEN)

    cool[drop_start:] = rng.uniform(5.0, 25.0, SEQ_LEN - drop_start)
    vib[drop_start:] += rng.uniform(4.0, 8.0, SEQ_LEN - drop_start)
    aco[drop_start:] += rng.uniform(15.0, 25.0, SEQ_LEN - drop_start)

    seq = _clip(np.column_stack([vib, cur, cool, aco]))
    # Compound rule territory → CRITICAL.
    severity = CRITICAL
    rul_hours = float(rng.uniform(0.5, 4.0))  # hours until forced shutdown
    return seq, severity, COOLANT_BLOCKAGE, rul_hours


def _clip(seq: np.ndarray) -> np.ndarray:
    """Clamp to physical sensor ranges to avoid impossible training samples."""
    seq[:, 0] = np.clip(seq[:, 0], 0.5, 18.0)
    seq[:, 1] = np.clip(seq[:, 1], 5.0, 48.0)
    seq[:, 2] = np.clip(seq[:, 2], 2.0, 65.0)
    seq[:, 3] = np.clip(seq[:, 3], 60.0, 115.0)
    return seq.astype(np.float32)


def generate_dataset(samples_per_regime: int, seed: int = SEED) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    X, sev, fm, rul = [], [], [], []

    for _ in range(samples_per_regime):
        seq = _healthy_sequence(rng)
        X.append(seq); sev.append(LOW); fm.append(NORMAL); rul.append(168.0)

    for _ in range(samples_per_regime):
        seq, s, f, r = _gradual_wear_sequence(rng)
        X.append(seq); sev.append(s); fm.append(f); rul.append(r)

    for _ in range(samples_per_regime):
        seq, s, f, r = _bearing_wear_sequence(rng)
        X.append(seq); sev.append(s); fm.append(f); rul.append(r)

    for _ in range(samples_per_regime):
        seq, s, f, r = _coolant_blockage_sequence(rng)
        X.append(seq); sev.append(s); fm.append(f); rul.append(r)

    X = np.stack(X)
    sev = np.array(sev, dtype=np.int64)
    fm = np.array(fm, dtype=np.int64)
    rul = np.array(rul, dtype=np.float32)

    perm = rng.permutation(len(X))
    return X[perm], sev[perm], fm[perm], rul[perm]


def normalize(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Z-score normalize per-feature. Returns (X_norm, mean, std)."""
    mean = X.reshape(-1, N_FEATURES).mean(axis=0)
    std = X.reshape(-1, N_FEATURES).std(axis=0) + 1e-6
    return (X - mean) / std, mean.astype(np.float32), std.astype(np.float32)


# ---------------------------------------------------------------
# Training
# ---------------------------------------------------------------


def train(samples_per_regime: int = 600, epochs: int = 12, batch_size: int = 32) -> dict:
    torch.manual_seed(SEED)
    np.random.seed(SEED)

    X, y_sev, y_fm, y_rul = generate_dataset(samples_per_regime)
    X_norm, mean, std = normalize(X)

    n_train = int(0.85 * len(X_norm))
    X_train = torch.from_numpy(X_norm[:n_train])
    X_val = torch.from_numpy(X_norm[n_train:])
    sev_train = torch.from_numpy(y_sev[:n_train])
    sev_val = torch.from_numpy(y_sev[n_train:])
    fm_train = torch.from_numpy(y_fm[:n_train])
    fm_val = torch.from_numpy(y_fm[n_train:])
    rul_train = torch.from_numpy(y_rul[:n_train] / 168.0)  # normalize to [0,1]
    rul_val = torch.from_numpy(y_rul[n_train:] / 168.0)

    train_ds = TensorDataset(X_train, sev_train, fm_train, rul_train)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)

    model = LSTMMaintenance()
    optim = torch.optim.Adam(model.parameters(), lr=1e-3)
    ce = nn.CrossEntropyLoss()
    mse = nn.MSELoss()

    for epoch in range(epochs):
        model.train()
        total_loss = 0.0
        for xb, sb, fb, rb in train_loader:
            optim.zero_grad()
            out = model(xb)
            loss = (
                ce(out["severity_logits"], sb)
                + ce(out["failure_logits"], fb)
                + 2.0 * mse(out["rul_normalized"], rb)
            )
            loss.backward()
            optim.step()
            total_loss += loss.item() * xb.size(0)
        total_loss /= len(train_ds)

        model.eval()
        with torch.no_grad():
            val_out = model(X_val)
            sev_acc = (val_out["severity_logits"].argmax(-1) == sev_val).float().mean().item()
            fm_acc = (val_out["failure_logits"].argmax(-1) == fm_val).float().mean().item()
            rul_mae_h = (val_out["rul_normalized"] * 168 - rul_val * 168).abs().mean().item()
        print(f"  epoch {epoch + 1:2d}/{epochs}  loss={total_loss:.4f}  "
              f"sev_acc={sev_acc:.3f}  fm_acc={fm_acc:.3f}  rul_MAE={rul_mae_h:.1f}h")

    return {
        "model": model,
        "feature_mean": mean.tolist(),
        "feature_std": std.tolist(),
        "severity_accuracy": sev_acc,
        "failure_mode_accuracy": fm_acc,
        "rul_mae_hours": rul_mae_h,
        "samples_per_regime": samples_per_regime,
        "epochs": epochs,
    }


def export_torchscript(model: nn.Module, path: Path) -> None:
    """Save as TorchScript so SageMaker can load without our source code.

    Uses torch.jit.script (not trace) because forward() returns a dict; the
    tracer rejects dict outputs since it can't guarantee the container shape
    is constant.
    """
    model.eval()
    scripted = torch.jit.script(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    scripted.save(str(path))
    print(f"  TorchScript written: {path}")


def smoke_test(model_path: Path, mean: list, std: list) -> None:
    """Round-trip a known coolant-blockage sequence through the saved model."""
    model = torch.jit.load(str(model_path))
    model.eval()
    rng = np.random.default_rng(SEED + 1)
    seq, _, _, _ = _coolant_blockage_sequence(rng)
    norm = (seq - np.array(mean)) / np.array(std)
    with torch.no_grad():
        out = model(torch.from_numpy(norm).unsqueeze(0).float())
    severity_idx = int(out["severity_logits"].argmax(-1).item())
    failure_idx = int(out["failure_logits"].argmax(-1).item())
    rul_h = float(out["rul_normalized"].item()) * 168
    print(f"  smoke test: severity={SEVERITY_CLASSES[severity_idx]} "
          f"failure={FAILURE_MODES[failure_idx]} rul={rul_h:.1f}h")


def main() -> None:
    out_dir = Path(__file__).parent
    model_path = out_dir / "model.pt"
    metrics_path = out_dir / "metrics.json"
    feature_path = out_dir / "feature_config.json"

    print("Training LSTM tool-wear predictor...")
    result = train()

    print("\nExporting TorchScript...")
    export_torchscript(result["model"], model_path)

    feature_config = {
        "seq_len": SEQ_LEN,
        "n_features": N_FEATURES,
        "feature_order": ["vibration_mms", "current_amps", "coolant_lmin", "acoustic_db"],
        "feature_mean": result["feature_mean"],
        "feature_std": result["feature_std"],
        "severity_classes": SEVERITY_CLASSES,
        "failure_modes": FAILURE_MODES,
        "rul_max_hours": 168,
    }
    feature_path.write_text(json.dumps(feature_config, indent=2))
    print(f"  Feature config: {feature_path}")

    print("\nSmoke-testing exported model...")
    smoke_test(model_path, result["feature_mean"], result["feature_std"])

    metrics_path.write_text(
        json.dumps(
            {
                "severity_accuracy": result["severity_accuracy"],
                "failure_mode_accuracy": result["failure_mode_accuracy"],
                "rul_mae_hours": result["rul_mae_hours"],
                "samples_per_regime": result["samples_per_regime"],
                "epochs": result["epochs"],
            },
            indent=2,
        )
    )
    print(f"  Metrics: {metrics_path}")

    print("\nNext step: package for SageMaker:")
    print("  bash models/lstm/package_lstm.sh")
    print("  aws s3 cp models/lstm/model.tar.gz s3://factorymind-ml-models/lstm/")


if __name__ == "__main__":
    main()
