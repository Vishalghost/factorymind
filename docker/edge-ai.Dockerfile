# Edge AI Manager — ONNX inference (<10ms SLA, fire-and-forget).
FROM factorymind/base:latest

# ONNX Runtime is heavier than the rest; install only here to keep
# other agent images small.
RUN pip install --no-cache-dir "onnxruntime>=1.17.0"

# Bundle the edge model (if present in repo)
COPY models/edge/ /var/task/models/edge/

CMD ["edge_ai.manager.handler.handler"]
