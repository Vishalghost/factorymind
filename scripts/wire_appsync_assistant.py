"""Add a chatWithAssistant mutation to the existing AppSync API.

The CDK stack `FactoryMindML` already provisions the AppSync API for
machine state. This script extends the schema with a new mutation that
calls the assistant gateway Lambda (which in turn invokes Bedrock
AgentCore Runtime). It runs out-of-band — no CDK redeploy needed.

Steps:
  1. Resolve API id from CloudFormation outputs of FactoryMindML
  2. Read current schema; append types/mutation if missing
  3. start_schema_creation + poll
  4. Ensure a Lambda data source pointing to the gateway
  5. Ensure a unit resolver for Mutation.chatWithAssistant
  6. Update IAM: grant AppSync the right to invoke the gateway

Run:
    python scripts/wire_appsync_assistant.py --region us-east-1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError


GATEWAY_LAMBDA_NAME = "factorymind-assistant-gateway"
DATA_SOURCE_NAME = "AssistantGatewayLambda"
APPSYNC_ROLE_NAME = "FactoryMindAppSyncAssistantRole"

ASSISTANT_SCHEMA_FRAGMENT = """
input AssistantChatInput {
  message: String!
  session_id: String
  history: [AssistantTurnInput!]
}

input AssistantTurnInput {
  role: String!
  content: String!
}

type AssistantChatResponse {
  session_id: String!
  answer: String
  context_used: Boolean
  model_id: String
  error: String
}
"""

REQUEST_TEMPLATE = """{
  "version": "2017-02-28",
  "operation": "Invoke",
  "payload": {
    "arguments": $util.toJson($context.arguments),
    "_appsync": true
  }
}"""

RESPONSE_TEMPLATE = """#if($context.result.error)
  $util.error($context.result.error)
#end
$util.toJson($context.result)"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    args = parser.parse_args()
    region = args.region

    sts = boto3.client("sts", region_name=region)
    account = sts.get_caller_identity()["Account"]
    print(f"[*] account={account} region={region}")

    cf = boto3.client("cloudformation", region_name=region)
    appsync = boto3.client("appsync", region_name=region)
    iam = boto3.client("iam", region_name=region)
    lam = boto3.client("lambda", region_name=region)

    # 1. Resolve API id
    api_id = _resolve_appsync_api_id(cf, region)
    print(f"[*] AppSync API id: {api_id}")

    # 2. Update schema (idempotent)
    print("[1/4] Update schema...")
    new_schema = _update_schema(appsync, api_id)
    print(f"     schema length: {len(new_schema)} chars")

    # 3. Ensure AppSync service role for Lambda data source
    print("[2/4] Ensure AppSync service role...")
    role_arn = _ensure_appsync_role(iam, account, region)
    print(f"     role: {role_arn}")

    # Wait briefly for IAM trust to propagate.
    time.sleep(6)

    # 4. Ensure Lambda data source
    print("[3/4] Ensure Lambda data source...")
    lambda_arn = lam.get_function(FunctionName=GATEWAY_LAMBDA_NAME)["Configuration"]["FunctionArn"]
    _ensure_data_source(appsync, api_id, role_arn, lambda_arn)

    # 5. Ensure resolver
    print("[4/4] Ensure Mutation.chatWithAssistant resolver...")
    _ensure_resolver(appsync, api_id)

    # Persist outputs append
    out_path = Path("agentcore-outputs.json")
    outputs = json.loads(out_path.read_text()) if out_path.exists() else {}
    outputs["appsyncApiId"] = api_id
    outputs["appsyncMutation"] = "chatWithAssistant"
    out_path.write_text(json.dumps(outputs, indent=2))
    print(json.dumps(outputs, indent=2))
    return 0


def _resolve_appsync_api_id(cf: Any, region: str) -> str:
    """Look up the AppSync API ID. Prefer a CFN output; fall back to listing."""
    try:
        resp = cf.describe_stacks(StackName="FactoryMindML")
        outputs = resp["Stacks"][0].get("Outputs", [])
        endpoint = next(
            (o["OutputValue"] for o in outputs if o["OutputKey"] == "AppSyncEndpoint"),
            None,
        )
    except ClientError:
        endpoint = None

    appsync = boto3.client("appsync", region_name=region)
    paginator = appsync.get_paginator("list_graphql_apis")
    for page in paginator.paginate():
        for api in page.get("graphqlApis", []):
            if endpoint and api.get("uris", {}).get("GRAPHQL") == endpoint:
                return api["apiId"]
            if api.get("name", "").startswith("FactoryMind"):
                return api["apiId"]
    raise RuntimeError("Could not locate FactoryMind AppSync API")


def _update_schema(appsync: Any, api_id: str) -> str:
    """Fetch current schema and append assistant types/mutation if absent."""
    current = appsync.get_introspection_schema(apiId=api_id, format="SDL")["schema"]
    if isinstance(current, (bytes, bytearray)):
        current = current.decode("utf-8")

    if "chatWithAssistant" in current:
        # Already wired. Re-write file from local source-of-truth though.
        new_schema = _compose_schema()
    else:
        new_schema = _compose_schema()

    appsync.start_schema_creation(apiId=api_id, definition=new_schema.encode("utf-8"))
    while True:
        resp = appsync.get_schema_creation_status(apiId=api_id)
        status = resp.get("status")
        details = resp.get("details", "")
        print(f"     schema status: {status} — {details[:120]}")
        if status in ("SUCCESS",):
            break
        if status in ("FAILED", "DELETING"):
            raise RuntimeError(f"schema_creation status={status}: {details}")
        time.sleep(2)
    return new_schema


def _compose_schema() -> str:
    """Build the full schema by inlining the assistant field into Mutation.

    AppSync's schema validator doesn't merge ``extend type`` declarations from
    SDL passed to ``start_schema_creation`` — every field must appear on the
    original ``type Mutation``. So we patch the existing block in place.
    """
    base_path = Path("infrastructure/cdk/schema/factorymind.graphql")
    base = base_path.read_text()

    chat_field = "  chatWithAssistant(input: AssistantChatInput!): AssistantChatResponse\n"

    if "chatWithAssistant" in base:
        patched = base
    else:
        marker = "type Mutation {"
        idx = base.index(marker) + len(marker) + 1  # past "{\n"
        # Insert immediately after the opening brace of `type Mutation {`.
        patched = base[:idx] + chat_field + base[idx:]
    return patched + "\n" + ASSISTANT_SCHEMA_FRAGMENT


def _ensure_appsync_role(iam: Any, account: str, region: str) -> str:
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "appsync.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    try:
        resp = iam.get_role(RoleName=APPSYNC_ROLE_NAME)
        arn = resp["Role"]["Arn"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        resp = iam.create_role(
            RoleName=APPSYNC_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="AppSync Lambda data source role for FactoryMind assistant",
        )
        arn = resp["Role"]["Arn"]
    iam.put_role_policy(
        RoleName=APPSYNC_ROLE_NAME,
        PolicyName="InvokeAssistantGateway",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["lambda:InvokeFunction"],
                        "Resource": (
                            f"arn:aws:lambda:{region}:{account}:function:{GATEWAY_LAMBDA_NAME}"
                        ),
                    }
                ],
            }
        ),
    )
    return arn


def _ensure_data_source(appsync: Any, api_id: str, role_arn: str, lambda_arn: str) -> None:
    cfg = {
        "apiId": api_id,
        "name": DATA_SOURCE_NAME,
        "type": "AWS_LAMBDA",
        "serviceRoleArn": role_arn,
        "lambdaConfig": {"lambdaFunctionArn": lambda_arn},
    }
    try:
        appsync.create_data_source(description="Gateway to AgentCore assistant", **cfg)
    except appsync.exceptions.BadRequestException as e:
        if "already exists" not in str(e):
            raise
        appsync.update_data_source(
            description="Gateway to AgentCore assistant",
            **cfg,
        )


def _ensure_resolver(appsync: Any, api_id: str) -> None:
    cfg = {
        "apiId": api_id,
        "typeName": "Mutation",
        "fieldName": "chatWithAssistant",
        "dataSourceName": DATA_SOURCE_NAME,
        "requestMappingTemplate": REQUEST_TEMPLATE,
        "responseMappingTemplate": RESPONSE_TEMPLATE,
        "kind": "UNIT",
    }
    try:
        appsync.create_resolver(**cfg)
    except appsync.exceptions.BadRequestException as e:
        msg = str(e)
        if "already exists" not in msg and "Only one resolver" not in msg:
            raise
        appsync.update_resolver(**cfg)


if __name__ == "__main__":
    sys.exit(main())
