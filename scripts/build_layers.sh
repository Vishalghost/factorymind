#!/usr/bin/env bash
# Build shared Lambda layers for FactoryMind agents.
#
# Outputs:
#   infrastructure/layers/python_deps/python/  — pip-installed dependencies
#   infrastructure/layers/onnx_runtime/python/ — ONNX Runtime + edge model
#
# Strategy: pip with --platform manylinux2014_x86_64 --only-binary=:all: to
# fetch Linux wheels directly. Avoids Docker volume-mount path issues on
# Windows + Git Bash and produces identical results across host OSes.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAYERS_DIR="$REPO_ROOT/infrastructure/layers"
DEPS_DIR="$LAYERS_DIR/python_deps/python"
ONNX_DIR="$LAYERS_DIR/onnx_runtime/python"

PIP_LINUX_FLAGS=(
    --platform manylinux2014_x86_64
    --python-version 3.11
    --only-binary=:all:
    --implementation cp
)

# --- Build python_deps layer ---
echo "Building python_deps layer..."
rm -rf "$LAYERS_DIR/python_deps"
mkdir -p "$DEPS_DIR"

DEPS=(
    "pydantic>=2.5.0"
    "structlog>=24.1.0"
    "aws-lambda-powertools>=2.34.0"
    "langgraph>=0.0.40"
    "redis>=5.0.0"
    "numpy>=1.26.0,<2.0"
)

pip install --no-cache-dir --target "$DEPS_DIR" "${PIP_LINUX_FLAGS[@]}" "${DEPS[@]}"

# Strip caches to keep layer under 250 MB unzipped
find "$DEPS_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$DEPS_DIR" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true

echo "  python_deps layer built: $DEPS_DIR"

# --- Build onnx_runtime layer ---
echo "Building onnx_runtime layer..."
rm -rf "$LAYERS_DIR/onnx_runtime"
mkdir -p "$ONNX_DIR"

pip install --no-cache-dir --target "$ONNX_DIR" "${PIP_LINUX_FLAGS[@]}" \
    "onnxruntime>=1.16.0,<1.17.0" "numpy>=1.26.0,<2.0"

find "$ONNX_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$ONNX_DIR" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true

# Bundle the edge model if it exists
if [[ -f "$REPO_ROOT/models/edge/edge_classifier_v2.onnx" ]]; then
    cp "$REPO_ROOT/models/edge/edge_classifier_v2.onnx" "$ONNX_DIR/"
    echo "  Bundled edge_classifier_v2.onnx into ONNX layer"
fi

echo "  onnx_runtime layer built: $ONNX_DIR"
echo
echo "Both layers built."
