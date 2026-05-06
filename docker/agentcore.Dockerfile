# FactoryMind AgentCore Runtime image.
#
# AgentCore Runtime requires linux/arm64 images that listen on port 8080
# and serve POST /invocations + GET /ping. The bedrock_agentcore SDK's
# BedrockAgentCoreApp does this automatically when its `app.run()` is invoked
# (or, in production, AgentCore Runtime starts the server via the entrypoint).
#
# Build context = repo root. Build via CodeBuild with arm64 build environment.

FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AWS_REGION=us-east-1

WORKDIR /app

# System deps (curl for healthcheck, build-essential for any wheel that
# needs compilation on arm64 — most pure-python deps do not).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps in two layers so requirement edits don't bust the
# (slow) ML/AWS SDK cache.
COPY docker/agentcore.requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Application code — agents/ tree only. No dashboard/, no infra/, no tests.
COPY agents /app/agents

# AgentCore Runtime expects HTTP on 8080.
EXPOSE 8080

# BedrockAgentCoreApp.run() binds to 0.0.0.0:8080 and exposes the required
# /invocations and /ping endpoints, dispatching to @app.entrypoint.
CMD ["python", "-m", "agents.runtime.app"]
