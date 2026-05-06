"""End-to-end provisioning script for the FactoryMind AgentCore Runtime.

Replaces local-Docker + manual-IAM steps with a single boto3 driver. Idempotent:
re-running re-uses existing resources, only triggers a fresh CodeBuild + image
update on every run.

Steps:
  1. Ensure an ECR repository exists for the agent image.
  2. Ensure a CodeBuild service role with ECR/Logs permissions.
  3. Ensure a CodeBuild project that builds docker/agentcore.Dockerfile and
     pushes to that ECR repo (uploaded as a zipped source bundle to S3).
  4. Upload current repo source to the build bucket and start a build.
  5. Wait for the build to succeed; read the resulting image URI.
  6. Ensure an AgentCore execution role.
  7. Create or update a single AgentCore Runtime
     (``factorymind-agentcore-runtime``) pointing to that image.
  8. Print the runtime ARN — used by the AppSync gateway Lambda.

Run with:

    python scripts/deploy_agentcore.py --region us-east-1

The script intentionally writes minimal CDK output and does not touch the
existing CDK stacks.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError


REPO_NAME = "factorymind-agentcore"
RUNTIME_NAME = "factorymind_agentcore_runtime"
CODEBUILD_PROJECT = "factorymind-agentcore-build"
CODEBUILD_ROLE = "FactoryMindAgentCoreBuildRole"
RUNTIME_ROLE = "FactoryMindAgentCoreRuntimeRole"
GATEWAY_LAMBDA_NAME = "factorymind-assistant-gateway"
GATEWAY_LAMBDA_ROLE = "FactoryMindAssistantGatewayRole"
SOURCE_BUCKET_PREFIX = "factorymind-agentcore-source"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Re-use existing image; skip CodeBuild step.",
    )
    args = parser.parse_args()

    region = args.region
    sts = boto3.client("sts", region_name=region)
    account = sts.get_caller_identity()["Account"]
    print(f"[*] AWS account: {account}    region: {region}")

    ecr = boto3.client("ecr", region_name=region)
    iam = boto3.client("iam", region_name=region)
    s3 = boto3.client("s3", region_name=region)
    codebuild = boto3.client("codebuild", region_name=region)
    bedrock_agentcore = boto3.client("bedrock-agentcore-control", region_name=region)

    # 1. ECR
    print("[1/8] Ensure ECR repository...")
    ensure_ecr_repo(ecr, REPO_NAME)
    image_uri_base = f"{account}.dkr.ecr.{region}.amazonaws.com/{REPO_NAME}"
    print(f"     repo: {image_uri_base}")

    # 2. CodeBuild role
    print("[2/8] Ensure CodeBuild service role...")
    cb_role_arn = ensure_codebuild_role(iam, account, REPO_NAME)
    print(f"     role: {cb_role_arn}")

    # 3. CodeBuild project
    print("[3/8] Ensure CodeBuild project + source bucket...")
    bucket = f"{SOURCE_BUCKET_PREFIX}-{account}-{region}"
    ensure_bucket(s3, bucket, region)
    ensure_codebuild_project(codebuild, account, region, REPO_NAME, cb_role_arn, bucket)

    image_uri = f"{image_uri_base}:latest"

    if not args.skip_build:
        # 4. Upload source + start build
        print("[4/8] Upload source + start CodeBuild...")
        source_key = upload_source(s3, bucket)
        build_id = start_build(codebuild, source_key)
        print(f"     build id: {build_id}")

        # 5. Wait for build
        print("[5/8] Wait for CodeBuild to finish (this can take 5-8 min)...")
        wait_for_build(codebuild, build_id)
    else:
        print("[4-5/8] --skip-build set; using existing image at " + image_uri)

    # 6. AgentCore execution role
    print("[6/8] Ensure AgentCore execution role...")
    runtime_role_arn = ensure_agentcore_runtime_role(iam, account, region)
    print(f"     role: {runtime_role_arn}")

    # 7. Create/update AgentCore Runtime
    print("[7/8] Create or update AgentCore Runtime...")
    runtime = ensure_agent_runtime(
        bedrock_agentcore,
        name=RUNTIME_NAME,
        image_uri=image_uri,
        role_arn=runtime_role_arn,
    )
    runtime_arn = runtime["agentRuntimeArn"]
    print(f"     runtime ARN: {runtime_arn}")

    # 8. Assistant gateway Lambda + Function URL
    print("[8/9] Ensure assistant gateway Lambda + Function URL...")
    gateway_role_arn = ensure_gateway_lambda_role(iam, account, region)
    function_url = ensure_gateway_lambda(
        boto3.client("lambda", region_name=region),
        role_arn=gateway_role_arn,
        runtime_arn=runtime_arn,
        region=region,
    )
    print(f"     gateway URL: {function_url}")

    # 9. Persist outputs
    print("[9/9] Persist outputs to agentcore-outputs.json")
    outputs = {
        "agentRuntimeArn": runtime_arn,
        "agentRuntimeName": RUNTIME_NAME,
        "imageUri": image_uri,
        "assistantGatewayUrl": function_url,
        "region": region,
    }
    Path("agentcore-outputs.json").write_text(json.dumps(outputs, indent=2))
    print(json.dumps(outputs, indent=2))
    return 0


# --- ECR --------------------------------------------------------------------


def ensure_ecr_repo(ecr: Any, name: str) -> None:
    try:
        ecr.create_repository(
            repositoryName=name,
            imageTagMutability="MUTABLE",
            imageScanningConfiguration={"scanOnPush": False},
        )
    except ecr.exceptions.RepositoryAlreadyExistsException:
        pass


# --- IAM --------------------------------------------------------------------


def _ensure_role(iam: Any, role_name: str, trust_policy: dict[str, Any]) -> str:
    try:
        resp = iam.get_role(RoleName=role_name)
        return resp["Role"]["Arn"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
    resp = iam.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=json.dumps(trust_policy),
        Description="FactoryMind AgentCore Runtime helper role",
    )
    return resp["Role"]["Arn"]


def ensure_codebuild_role(iam: Any, account: str, repo_name: str) -> str:
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "codebuild.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    arn = _ensure_role(iam, CODEBUILD_ROLE, trust)
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:GetObjectVersion",
                    "s3:PutObject",
                    "s3:ListBucket",
                ],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:CompleteLayerUpload",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:InitiateLayerUpload",
                    "ecr:PutImage",
                    "ecr:UploadLayerPart",
                    "ecr:BatchGetImage",
                ],
                "Resource": "*",
            },
        ],
    }
    iam.put_role_policy(
        RoleName=CODEBUILD_ROLE,
        PolicyName="FactoryMindAgentCoreBuildPolicy",
        PolicyDocument=json.dumps(policy),
    )
    return arn


def ensure_agentcore_runtime_role(iam: Any, account: str, region: str) -> str:
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{region}:{account}:*"
                    },
                },
            }
        ],
    }
    arn = _ensure_role(iam, RUNTIME_ROLE, trust)
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate",
                ],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "lambda:InvokeFunction",
                ],
                "Resource": f"arn:aws:lambda:{region}:{account}:function:factorymind-*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                ],
                "Resource": f"arn:aws:dynamodb:{region}:{account}:table/FactoryMind_*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "events:PutEvents",
                ],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                    "logs:DescribeLogGroups",
                ],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchCheckLayerAvailability",
                ],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                ],
                "Resource": "*",
            },
        ],
    }
    iam.put_role_policy(
        RoleName=RUNTIME_ROLE,
        PolicyName="FactoryMindAgentCoreRuntimePolicy",
        PolicyDocument=json.dumps(policy),
    )
    # Give IAM a moment to propagate the policy globally before AgentCore
    # validates the role; otherwise CreateAgentRuntime may use a stale view.
    time.sleep(8)
    return arn


# --- S3 + source upload -----------------------------------------------------


def ensure_bucket(s3: Any, bucket: str, region: str) -> None:
    try:
        s3.head_bucket(Bucket=bucket)
        return
    except ClientError:
        pass
    if region == "us-east-1":
        s3.create_bucket(Bucket=bucket)
    else:
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": region},
        )


def upload_source(s3: Any, bucket: str) -> str:
    """Zip the repo source we need to build the image and upload to S3.

    Only ships agents/ + docker/ — everything else is excluded so the upload
    is small and the build is fast.
    """
    buf = io.BytesIO()
    repo_root = Path(__file__).resolve().parent.parent
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for sub in ("agents", "docker"):
            for path in (repo_root / sub).rglob("*"):
                if path.is_dir():
                    continue
                if "__pycache__" in path.parts or path.name.endswith(".pyc"):
                    continue
                rel = path.relative_to(repo_root).as_posix()
                zf.write(path, rel)
    key = f"src/{int(time.time())}.zip"
    buf.seek(0)
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    print(f"     uploaded source: s3://{bucket}/{key} ({buf.getbuffer().nbytes // 1024} KB)")
    # Also mirror to a stable key so codebuild project source can resolve it.
    s3.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": key}, Key="src/latest.zip")
    return key


# --- CodeBuild --------------------------------------------------------------


def ensure_codebuild_project(
    codebuild: Any,
    account: str,
    region: str,
    repo: str,
    role_arn: str,
    bucket: str,
) -> None:
    env_vars = [
        {"name": "AWS_ACCOUNT_ID", "value": account},
        {"name": "AWS_REGION", "value": region},
        {"name": "ECR_REPOSITORY", "value": repo},
    ]
    artifacts = {"type": "NO_ARTIFACTS"}
    source = {
        "type": "S3",
        "location": f"{bucket}/src/latest.zip",
        "buildspec": "docker/agentcore.buildspec.yml",
    }
    environment = {
        "type": "ARM_CONTAINER",
        "image": "aws/codebuild/amazonlinux2-aarch64-standard:3.0",
        "computeType": "BUILD_GENERAL1_SMALL",
        "privilegedMode": True,
        "environmentVariables": env_vars,
    }

    def _create_or_update() -> None:
        try:
            codebuild.create_project(
                name=CODEBUILD_PROJECT,
                description="FactoryMind AgentCore Runtime image build",
                source=source,
                artifacts=artifacts,
                environment=environment,
                serviceRole=role_arn,
                timeoutInMinutes=20,
            )
        except codebuild.exceptions.ResourceAlreadyExistsException:
            codebuild.update_project(
                name=CODEBUILD_PROJECT,
                description="FactoryMind AgentCore Runtime image build",
                source=source,
                artifacts=artifacts,
                environment=environment,
                serviceRole=role_arn,
                timeoutInMinutes=20,
            )

    # IAM trust-policy propagation can take a few seconds after role creation.
    # CodeBuild rejects the project create with "not authorized to assume role"
    # until the trust is fully replicated, so retry with backoff.
    last_err: Exception | None = None
    for attempt in range(8):
        try:
            _create_or_update()
            return
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            msg = e.response.get("Error", {}).get("Message", "")
            if code == "InvalidInputException" and "AssumeRole" in msg:
                last_err = e
                wait = 5 + attempt * 3
                print(f"     IAM not yet propagated, retry in {wait}s...")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"CodeBuild project create failed after retries: {last_err}")


def start_build(codebuild: Any, source_key: str) -> str:
    resp = codebuild.start_build(projectName=CODEBUILD_PROJECT)
    return resp["build"]["id"]


def wait_for_build(codebuild: Any, build_id: str) -> None:
    while True:
        resp = codebuild.batch_get_builds(ids=[build_id])
        b = resp["builds"][0]
        status = b["buildStatus"]
        phase = b.get("currentPhase", "?")
        print(f"     build {build_id}  status={status}  phase={phase}")
        if status in ("SUCCEEDED",):
            return
        if status in ("FAILED", "FAULT", "STOPPED", "TIMED_OUT"):
            raise RuntimeError(f"CodeBuild {status}: see CloudWatch logs for {build_id}")
        time.sleep(15)


# --- AgentCore Runtime ------------------------------------------------------


def ensure_agent_runtime(
    bedrock_agentcore: Any,
    name: str,
    image_uri: str,
    role_arn: str,
) -> dict[str, Any]:
    """Create the runtime if it doesn't exist, otherwise update its image.

    Retries on ValidationException("Role validation failed") because the IAM
    trust policy needs a few seconds to propagate before AgentCore can
    sts:AssumeRole the new role.
    """
    existing = None
    paginator = bedrock_agentcore.get_paginator("list_agent_runtimes")
    for page in paginator.paginate():
        for rt in page.get("agentRuntimes", []):
            if rt.get("agentRuntimeName") == name:
                existing = rt
                break
        if existing:
            break

    container_cfg = {
        "containerConfiguration": {"containerUri": image_uri},
    }

    common_kwargs = dict(
        description="FactoryMind multi-agent runtime (brain, sustainability, assistant).",
        agentRuntimeArtifact=container_cfg,
        roleArn=role_arn,
        networkConfiguration={"networkMode": "PUBLIC"},
        protocolConfiguration={"serverProtocol": "HTTP"},
    )

    def _do_call() -> dict[str, Any]:
        if existing is None:
            return bedrock_agentcore.create_agent_runtime(
                agentRuntimeName=name, **common_kwargs
            )
        return bedrock_agentcore.update_agent_runtime(
            agentRuntimeId=existing["agentRuntimeId"], **common_kwargs
        )

    last_err: Exception | None = None
    for attempt in range(10):
        try:
            return _do_call()
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            msg = e.response.get("Error", {}).get("Message", "")
            if code in ("ValidationException", "AccessDeniedException") and (
                "Role validation" in msg
                or "assume" in msg.lower()
                or "Access denied" in msg
                or "execution role requires permissions" in msg.lower()
            ):
                last_err = e
                wait = 8 + attempt * 4
                print(f"     IAM not yet propagated ({code}); retry in {wait}s...")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"AgentCore CreateAgentRuntime failed after retries: {last_err}")


# --- Assistant gateway Lambda + Function URL ------------------------------


def ensure_gateway_lambda_role(iam: Any, account: str, region: str) -> str:
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    arn = _ensure_role(iam, GATEWAY_LAMBDA_ROLE, trust)
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:InvokeAgentRuntime",
                ],
                "Resource": "*",
            },
        ],
    }
    iam.put_role_policy(
        RoleName=GATEWAY_LAMBDA_ROLE,
        PolicyName="FactoryMindAssistantGatewayPolicy",
        PolicyDocument=json.dumps(policy),
    )
    # Settle pause for IAM propagation before Lambda CreateFunction.
    time.sleep(8)
    return arn


def _gateway_zip() -> bytes:
    """Zip the gateway Lambda code (only the assistant_gateway/ subpackage)."""
    repo_root = Path(__file__).resolve().parent.parent
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Only need agents/__init__.py and agents/assistant_gateway/* for the
        # handler to import as `agents.assistant_gateway.handler.handler`.
        for sub_path in [
            repo_root / "agents" / "__init__.py",
        ]:
            zf.write(sub_path, sub_path.relative_to(repo_root).as_posix())
        for path in (repo_root / "agents" / "assistant_gateway").rglob("*"):
            if path.is_dir():
                continue
            if "__pycache__" in path.parts or path.name.endswith(".pyc"):
                continue
            zf.write(path, path.relative_to(repo_root).as_posix())
    return buf.getvalue()


def ensure_gateway_lambda(
    lam: Any,
    role_arn: str,
    runtime_arn: str,
    region: str,
) -> str:
    """Create or update the gateway Lambda and return its Function URL."""
    code_bytes = _gateway_zip()
    env_vars = {
        "AGENT_RUNTIME_ARN": runtime_arn,
        "AWS_REGION_OVERRIDE": region,
    }
    def _create_with_retry() -> None:
        last: Exception | None = None
        for attempt in range(8):
            try:
                lam.create_function(
                    FunctionName=GATEWAY_LAMBDA_NAME,
                    Runtime="python3.11",
                    Role=role_arn,
                    Handler="agents.assistant_gateway.handler.handler",
                    Code={"ZipFile": code_bytes},
                    Timeout=60,
                    MemorySize=512,
                    Environment={"Variables": env_vars},
                    Description="HTTP gateway for FactoryMind GenAI Assistant (AgentCore-backed).",
                )
                return
            except lam.exceptions.ResourceConflictException:
                raise
            except ClientError as e:
                msg = e.response.get("Error", {}).get("Message", "")
                if "cannot be assumed by Lambda" in msg or "InvalidParameterValueException" in str(e):
                    last = e
                    wait = 6 + attempt * 3
                    print(f"     Lambda role not yet assumable, retry in {wait}s...")
                    time.sleep(wait)
                    continue
                raise
        raise RuntimeError(f"Lambda create_function failed after retries: {last}")

    try:
        _create_with_retry()
        time.sleep(3)
    except lam.exceptions.ResourceConflictException:
        lam.update_function_code(
            FunctionName=GATEWAY_LAMBDA_NAME,
            ZipFile=code_bytes,
            Publish=False,
        )
        # Wait for code update to settle before configuration update.
        waiter = lam.get_waiter("function_updated_v2")
        waiter.wait(FunctionName=GATEWAY_LAMBDA_NAME)
        lam.update_function_configuration(
            FunctionName=GATEWAY_LAMBDA_NAME,
            Role=role_arn,
            Handler="agents.assistant_gateway.handler.handler",
            Timeout=60,
            MemorySize=512,
            Environment={"Variables": env_vars},
        )
        waiter.wait(FunctionName=GATEWAY_LAMBDA_NAME)

    # Function URL with permissive CORS (POST only).
    # Note: AllowMethods values are capped at 6 chars by the Function URL API
    # ("*", "GET", "PUT", "POST", "DELETE", "HEAD", "PATCH"). OPTIONS preflight
    # is handled implicitly by Lambda Function URLs — listing it explicitly
    # fails validation, so we just allow POST.
    url_cfg = {
        "AuthType": "NONE",
        "Cors": {
            "AllowOrigins": ["*"],
            "AllowMethods": ["POST"],
            "AllowHeaders": ["content-type", "authorization"],
            "MaxAge": 600,
        },
    }
    try:
        url_resp = lam.create_function_url_config(
            FunctionName=GATEWAY_LAMBDA_NAME, **url_cfg
        )
    except lam.exceptions.ResourceConflictException:
        url_resp = lam.update_function_url_config(
            FunctionName=GATEWAY_LAMBDA_NAME, **url_cfg
        )

    # Public invoke permission needed for AuthType=NONE Function URLs.
    try:
        lam.add_permission(
            FunctionName=GATEWAY_LAMBDA_NAME,
            StatementId="PublicFunctionUrlInvoke",
            Action="lambda:InvokeFunctionUrl",
            Principal="*",
            FunctionUrlAuthType="NONE",
        )
    except lam.exceptions.ResourceConflictException:
        pass

    return url_resp["FunctionUrl"]


if __name__ == "__main__":
    sys.exit(main())
