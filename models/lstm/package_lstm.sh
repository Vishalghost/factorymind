#!/usr/bin/env bash
# Package the trained LSTM model + inference.py + requirements.txt into a
# SageMaker-compatible model.tar.gz, then optionally upload to S3.
#
# Layout SageMaker expects inside the tarball:
#     model.pt                  ← TorchScript artifact (top-level)
#     feature_config.json       ← used by inference.py at load time
#     code/inference.py         ← entry point (model_fn, predict_fn, etc.)
#     code/requirements.txt     ← extra runtime deps
#
# Usage:
#   bash models/lstm/package_lstm.sh                    # just build the tarball
#   bash models/lstm/package_lstm.sh --upload           # build + S3 upload
#   bash models/lstm/package_lstm.sh --upload --region us-east-1

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LSTM_DIR="$REPO_ROOT/models/lstm"
S3_BUCKET="factorymind-ml-models"
REGION="${AWS_REGION:-us-east-1}"
DO_UPLOAD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --upload)  DO_UPLOAD=1; shift ;;
    --region)  REGION="$2"; shift 2 ;;
    --bucket)  S3_BUCKET="$2"; shift 2 ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
done

# Sanity checks
for f in model.pt feature_config.json inference.py requirements.txt; do
  if [[ ! -f "$LSTM_DIR/$f" ]]; then
    echo "ERROR: missing $LSTM_DIR/$f"
    echo "       Run 'python models/lstm/train_lstm_maintenance.py' first."
    exit 1
  fi
done

# Stage files in a temp dir so the tarball has the exact layout SageMaker wants.
STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGE_DIR"' EXIT

cp "$LSTM_DIR/model.pt" "$STAGE_DIR/"
cp "$LSTM_DIR/feature_config.json" "$STAGE_DIR/"
mkdir -p "$STAGE_DIR/code"
cp "$LSTM_DIR/inference.py" "$STAGE_DIR/code/"
cp "$LSTM_DIR/requirements.txt" "$STAGE_DIR/code/"

# Build the tarball (use deterministic ordering for reproducibility).
TAR_PATH="$LSTM_DIR/model.tar.gz"
tar -czf "$TAR_PATH" -C "$STAGE_DIR" model.pt feature_config.json code

echo "Built $TAR_PATH"
echo "Contents:"
tar -tzf "$TAR_PATH" | sed 's/^/  /'

if [[ $DO_UPLOAD -eq 1 ]]; then
  S3_KEY="lstm/model.tar.gz"
  echo
  echo "Uploading to s3://$S3_BUCKET/$S3_KEY (region=$REGION)..."
  aws s3 cp "$TAR_PATH" "s3://$S3_BUCKET/$S3_KEY" --region "$REGION"

  echo
  echo "Triggering SageMaker endpoint reload (so it picks up the new artifact)..."
  if aws sagemaker describe-endpoint --endpoint-name factorymind-lstm-maintenance \
        --region "$REGION" >/dev/null 2>&1; then
    aws sagemaker update-endpoint \
        --endpoint-name factorymind-lstm-maintenance \
        --endpoint-config-name factorymind-lstm-maintenance-config \
        --region "$REGION" >/dev/null
    echo "  Endpoint update initiated. Watch: aws sagemaker describe-endpoint --endpoint-name factorymind-lstm-maintenance --region $REGION"
  else
    echo "  Endpoint not yet created — deploy MLStack first:"
    echo "    cd infrastructure/cdk && cdk deploy FactoryMindML --context region=$REGION"
  fi
fi
