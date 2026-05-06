# FactoryMind shared base image — used by every agent image.
#
# Provides:
#   - Python 3.11 (matches Lambda runtime)
#   - Shared dependencies (pydantic, boto3, structlog, aws-lambda-powertools, redis, langgraph, numpy)
#   - The `agents/` package mounted at /var/task/agents
#   - aws-lambda-runtime-interface-emulator for local invocation
#
# Build from repo root:
#   docker build -t factorymind/base:latest -f docker/base.Dockerfile .

FROM public.ecr.aws/lambda/python:3.11

# Match Lambda's working directory layout
WORKDIR /var/task

# System packages used by some workers (image processing for quality vision, etc.)
RUN dnf install -y --allowerasing \
        gcc \
        gcc-c++ \
        make \
        libjpeg-turbo \
        libjpeg-turbo-devel \
        zlib-devel \
    && dnf clean all

# Shared Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Application code
COPY agents/ /var/task/agents/

# Default to Lambda runtime emulator; child images override CMD with handler path.
# Operators set HANDLER env var (e.g., HANDLER=brain.handler.handler) when running
# locally with `docker run -e HANDLER=...`.
ENV PYTHONPATH=/var/task
ENV AWS_LAMBDA_FUNCTION_TIMEOUT=30
