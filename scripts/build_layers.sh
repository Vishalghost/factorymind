#!/usr/bin/env bash
# Build shared Lambda layers for FactoryMind agents.
#
# Outputs:
#   infrastructure/layers/python_deps/python/  — pip-installed dependencies
#   infrastructure/layers/onnx_runtime/python/ — ONNX Runtime + edge model
#
# Lambda layers must place Python packages under a top-level "python/" directory.
# This script uses Docker (lambci/lambda:build-python3.11 image) to ensure
# the wheels match the Lambda runtime environment.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAYERS_DIR="$REPO_ROOT/infrastructure/layers"
DEPS_DIR="$LAYERS_DIR/python_deps/python"
ONNX_DIR="$LAYERS_DIR/onnx_runtime/python"

# --- Build python_deps layer ---
echo "Building python_deps layer..."
mkdir -p "$DEPS_DIR"
rm -rf "$DEPS_DIR"/*

DEPS=(
    "pydantic>=2.5.0"
    "structlog>=24.1.0"
    "aws-lambda-powertools>=2.34.0"
    "langgraph>=0.0.40"
    "redis>=5.0.0"
    "numpy>=1.26.0"
)

if command -v docker >/dev/null 2>&1; then
    docker run --rm \
        -v "$DEPS_DIR":/var/task \
        --entrypoint pip \
        public.ecr.aws/sam/build-python3.11:latest \
        install --no-cache-dir --target /var/task "${DEPS[@]}"
else
    echo "  WARN: docker not found — falling back to local pip (may produce wrong-arch wheels)."
    pip install --no-cache-dir --target "$DEPS_DIR" "${DEPS[@]}"
fi

# Strip caches to keep layer under 250 MB unzipped
find "$DEPS_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$DEPS_DIR" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true

echo "  python_deps layer built: $DEPS_DIR"

# --- Build onnx_runtime layer ---
echo "Building onnx_runtime layer..."
mkdir -p "$ONNX_DIR"
rm -rf "$ONNX_DIR"/*

if command -v docker >/dev/null 2>&1; then
    docker run --rm \
        -v "$ONNX_DIR":/var/task \
        --entrypoint pip \
        public.ecr.aws/sam/build-python3.11:latest \
        install --no-cache-dir --target /var/task "onnxruntime>=1.17.0" "numpy>=1.26.0"
else
    pip install --no-cache-dir --target "$ONNX_DIR" "onnxruntime>=1.17.0" "numpy>=1.26.0"
fi

find "$ONNX_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$ONNX_DIR" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true

# Bundle the edge model if it exists
if [[ -f "$REPO_ROOT/models/edge/edge_classifier_v2.onnx" ]]; then
    cp "$REPO_ROOT/models/edge/edge_classifier_v2.onnx" "$ONNX_DIR/"
    echo "  Bundled edge_classifier_v2.onnx into ONNX layer"
fi

echo "  onnx_runtime layer built: $ONNX_DIR"
echo
echo "Both layers built. Run './scripts/deploy.sh' to deploy."
