"""HTTP gateway Lambda for the FactoryMind Assistant.

Exposed via a Lambda Function URL with CORS so the React dashboard can POST
chat messages directly. Forwards each request to the Bedrock AgentCore
Runtime (``factorymind_agentcore_runtime``) with ``agent_kind=assistant``.

We use a Function URL (not API Gateway) because:
  - The dashboard is a static SPA on CloudFront; CORS-enabled function URLs
    are the lowest-friction integration.
  - We don't need throttling/auth-N beyond Bedrock's per-runtime IAM.

Request body (JSON):

    {
      "message": "What machines need attention right now?",
      "session_id": "optional-stable-id-for-multi-turn",
      "history": [{"role": "user|assistant", "content": "..."}]   // optional
    }

Response body (JSON):

    { "session_id": "...", "answer": "...", "model_id": "...", "context_used": false }
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import boto3

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Accepts two event shapes:

    * Function URL / API Gateway HTTP API ``v2`` event (``event["body"]`` is a
      JSON string) — returns a Lambda-proxy response with statusCode + headers.
    * AppSync resolver event (``event["arguments"]["input"]`` already a dict)
      — returns the parsed response body directly.
    """
    is_appsync = isinstance(event.get("arguments"), dict)
    method = (event.get("requestContext") or {}).get("http", {}).get("method", "POST")
    if not is_appsync and method == "OPTIONS":
        return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}

    runtime_arn = os.environ.get("AGENT_RUNTIME_ARN")
    if not runtime_arn:
        if is_appsync:
            return {"error": "AGENT_RUNTIME_ARN env var is not configured."}
        return _response(500, {"error": "AGENT_RUNTIME_ARN env var is not configured."})

    if is_appsync:
        body = event["arguments"].get("input") or {}
    else:
        try:
            body = json.loads(event.get("body") or "{}")
        except json.JSONDecodeError as e:
            return _response(400, {"error": f"invalid JSON body: {e}"})

    message = (body.get("message") or "").strip()
    if not message:
        if is_appsync:
            return {"error": "message field is required"}
        return _response(400, {"error": "message field is required"})

    # Bedrock AgentCore requires runtimeSessionId to be at least 33 chars.
    # The dashboard's `crypto.randomUUID()` (36 chars) clears the bar but the
    # `sess-${Date.now()}` fallback (~17 chars) does not, and an inbound
    # caller (curl/Postman) can also send a short value. Pad up rather than
    # rejecting the request — there is no security implication, the session
    # id is opaque to AgentCore.
    session_id = (body.get("session_id") or str(uuid.uuid4())).strip() or str(uuid.uuid4())
    if len(session_id) < 33:
        session_id = (session_id + "-" + uuid.uuid4().hex)[:64]
    history = body.get("history") or []

    payload = {
        "agent_kind": "assistant",
        "message": message,
        "session_id": session_id,
        "history": history,
    }

    client = boto3.client(
        "bedrock-agentcore",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )

    try:
        result = client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            qualifier="DEFAULT",
            runtimeSessionId=session_id,
            payload=json.dumps(payload).encode("utf-8"),
            contentType="application/json",
        )
    except Exception as e:
        if is_appsync:
            return {"error": f"agentcore_invoke_failed: {e}", "session_id": session_id}
        return _response(502, {"error": f"agentcore_invoke_failed: {e}"})

    # Response body is a streaming object — read it fully.
    raw = result.get("response")
    if hasattr(raw, "read"):
        data = raw.read()
    else:
        data = raw or b""
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8", errors="replace")

    try:
        parsed = json.loads(data) if data else {}
    except json.JSONDecodeError:
        parsed = {"raw": data}

    parsed.setdefault("session_id", session_id)
    if is_appsync:
        # AppSync resolver: return the model directly (no HTTP envelope).
        return parsed
    return _response(200, parsed)
