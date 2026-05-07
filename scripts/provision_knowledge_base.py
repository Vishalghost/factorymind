"""Provision a Bedrock Knowledge Base for the FactoryMind sustainability docs.

Creates (idempotently):
  1. S3 bucket + uploads docs/knowledge_base/*.md
  2. OpenSearch Serverless collection + index for vector search
  3. IAM execution role for the KB
  4. Bedrock Knowledge Base + S3 data source
  5. Triggers an ingestion job

Then patches the AgentCore Runtime + Sustainability Manager Lambda env so
both pick up KNOWLEDGE_BASE_ID.

Run:
    python scripts/provision_knowledge_base.py --region us-east-1

Re-running is safe — every step is create-or-noop.

NOTE — SCP gating: this account's SCP may block aoss:* or
bedrock:CreateKnowledgeBase. Run with --print-policy to dump the IAM policy
that would be required, so the platform team can pre-approve.
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


KB_NAME = "factorymind-sustainability-kb"
DATA_SOURCE_NAME = "factorymind-kb-docs"
KB_ROLE_NAME = "FactoryMindKnowledgeBaseRole"
AOSS_COLLECTION_NAME = "factorymind-kb"
AOSS_INDEX_NAME = "factorymind-kb-index"
DOC_BUCKET_PREFIX = "factorymind-kb-docs"

# 1024-dim embeddings — Titan Embed Text v2 default.
EMBEDDING_MODEL_ARN = "arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0"
EMBEDDING_DIM = 1024
DOCS_DIR = Path("docs/knowledge_base")

# Lambdas/Runtimes that need KNOWLEDGE_BASE_ID patched in once the KB is up.
SUSTAINABILITY_LAMBDA = "factorymind-sustainability-manager"
GATEWAY_LAMBDA = "factorymind-assistant-gateway"
AGENTCORE_RUNTIME_NAME = "factorymind_agentcore_runtime"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument(
        "--print-policy",
        action="store_true",
        help="Print the required IAM policy and exit (no AWS calls).",
    )
    args = parser.parse_args()

    if args.print_policy:
        print(json.dumps(_required_policy(), indent=2))
        return 0

    region = args.region
    sts = boto3.client("sts", region_name=region)
    account = sts.get_caller_identity()["Account"]
    print(f"[*] account={account} region={region}")

    s3 = boto3.client("s3", region_name=region)
    iam = boto3.client("iam", region_name=region)
    aoss = boto3.client("opensearchserverless", region_name=region)
    bedrock_agent = boto3.client("bedrock-agent", region_name=region)
    lam = boto3.client("lambda", region_name=region)

    bucket = f"{DOC_BUCKET_PREFIX}-{account}-{region}"

    # 1. S3 bucket + upload
    print("[1/6] Ensure docs S3 bucket + upload...")
    _ensure_bucket(s3, bucket, region)
    keys = _upload_docs(s3, bucket)
    print(f"     uploaded {len(keys)} files to s3://{bucket}/")

    # 2. AOSS collection (network/security policies + collection itself)
    print("[2/6] Ensure OpenSearch Serverless collection...")
    collection_arn, collection_endpoint, collection_id = _ensure_aoss_collection(
        aoss, AOSS_COLLECTION_NAME, account, region
    )
    print(f"     collection: {collection_arn}")
    print(f"     endpoint: {collection_endpoint}")

    # 3. KB execution role (must exist before AOSS data-access policy can reference it)
    print("[3/6] Ensure KB execution role...")
    role_arn = _ensure_kb_role(iam, account, region, bucket)
    print(f"     role: {role_arn}")

    # 4. AOSS data-access policy + vector index
    print("[4/6] Configure AOSS access + index...")
    _ensure_aoss_data_access(aoss, account, role_arn)
    # Wait briefly for AOSS to apply the data-access policy.
    time.sleep(8)
    _ensure_aoss_index(collection_endpoint, region)

    # 5. Bedrock Knowledge Base + S3 data source
    print("[5/6] Ensure Bedrock Knowledge Base...")
    kb_id = _ensure_knowledge_base(
        bedrock_agent,
        role_arn=role_arn,
        collection_arn=collection_arn,
        region=region,
    )
    ds_id = _ensure_data_source(bedrock_agent, kb_id, bucket)
    print(f"     knowledgeBaseId: {kb_id}")
    print(f"     dataSourceId:    {ds_id}")

    # Trigger ingestion (best-effort).
    try:
        ingest = bedrock_agent.start_ingestion_job(
            knowledgeBaseId=kb_id, dataSourceId=ds_id
        )
        print(f"     ingestion job: {ingest['ingestionJob']['ingestionJobId']}")
    except ClientError as e:
        print(f"     ingestion start skipped: {e}")

    # 6. Patch downstream Lambdas/runtime so they actually USE the KB.
    print("[6/6] Patch downstream functions with KNOWLEDGE_BASE_ID...")
    _patch_lambda_env(lam, SUSTAINABILITY_LAMBDA, {"KNOWLEDGE_BASE_ID": kb_id})
    _patch_lambda_env(lam, GATEWAY_LAMBDA, {"KNOWLEDGE_BASE_ID": kb_id})

    out_path = Path("agentcore-outputs.json")
    outputs = json.loads(out_path.read_text()) if out_path.exists() else {}
    outputs["knowledgeBaseId"] = kb_id
    outputs["knowledgeBaseDataSourceId"] = ds_id
    outputs["knowledgeBaseBucket"] = bucket
    outputs["knowledgeBaseCollectionArn"] = collection_arn
    out_path.write_text(json.dumps(outputs, indent=2))
    print(json.dumps(outputs, indent=2))
    print()
    print("Next:")
    print(f"  1. Re-deploy AgentCore so the runtime picks up KNOWLEDGE_BASE_ID:")
    print(f"     python scripts/deploy_agentcore.py --region {region}")
    print(f"  2. Tail ingestion: aws bedrock-agent list-ingestion-jobs --knowledge-base-id {kb_id} --data-source-id {ds_id}")
    return 0


# --- S3 ---------------------------------------------------------------------


def _ensure_bucket(s3: Any, bucket: str, region: str) -> None:
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
    # Block public access by default.
    s3.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )


def _upload_docs(s3: Any, bucket: str) -> list[str]:
    if not DOCS_DIR.exists():
        raise FileNotFoundError(f"docs dir not found: {DOCS_DIR}")
    keys: list[str] = []
    for p in sorted(DOCS_DIR.rglob("*.md")):
        key = p.relative_to(DOCS_DIR).as_posix()
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=p.read_bytes(),
            ContentType="text/markdown",
        )
        keys.append(key)
    return keys


# --- IAM --------------------------------------------------------------------


def _ensure_kb_role(iam: Any, account: str, region: str, bucket: str) -> str:
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account},
                },
            }
        ],
    }
    try:
        resp = iam.get_role(RoleName=KB_ROLE_NAME)
        arn = resp["Role"]["Arn"]
        # Refresh trust in case it drifted.
        iam.update_assume_role_policy(
            RoleName=KB_ROLE_NAME, PolicyDocument=json.dumps(trust)
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        resp = iam.create_role(
            RoleName=KB_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="FactoryMind Bedrock Knowledge Base execution role",
        )
        arn = resp["Role"]["Arn"]

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadDocs",
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:ListBucket"],
                "Resource": [
                    f"arn:aws:s3:::{bucket}",
                    f"arn:aws:s3:::{bucket}/*",
                ],
            },
            {
                "Sid": "InvokeEmbeddings",
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel"],
                "Resource": EMBEDDING_MODEL_ARN.format(region=region),
            },
            {
                "Sid": "AossDataAccess",
                "Effect": "Allow",
                "Action": ["aoss:APIAccessAll"],
                "Resource": f"arn:aws:aoss:{region}:{account}:collection/*",
            },
        ],
    }
    iam.put_role_policy(
        RoleName=KB_ROLE_NAME,
        PolicyName="FactoryMindKnowledgeBasePolicy",
        PolicyDocument=json.dumps(policy),
    )
    time.sleep(5)
    return arn


# --- OpenSearch Serverless --------------------------------------------------


def _ensure_aoss_collection(
    aoss: Any, name: str, account: str, region: str
) -> tuple[str, str, str]:
    """Returns (collectionArn, collectionEndpoint, collectionId)."""
    # Encryption policy (KMS — AWS-owned).
    enc_policy = {
        "Rules": [{"ResourceType": "collection", "Resource": [f"collection/{name}"]}],
        "AWSOwnedKey": True,
    }
    _put_aoss_policy(
        aoss,
        name=f"{name}-enc",
        type_="encryption",
        policy=json.dumps(enc_policy),
    )

    # Network policy — public access (workshop). For prod, swap to VPC.
    net_policy = [
        {
            "Rules": [
                {"ResourceType": "collection", "Resource": [f"collection/{name}"]},
                {"ResourceType": "dashboard", "Resource": [f"collection/{name}"]},
            ],
            "AllowFromPublic": True,
        }
    ]
    _put_aoss_policy(
        aoss,
        name=f"{name}-net",
        type_="network",
        policy=json.dumps(net_policy),
    )

    # Create collection.
    try:
        aoss.create_collection(
            name=name,
            type="VECTORSEARCH",
            description="FactoryMind Bedrock KB vector store",
        )
    except aoss.exceptions.ConflictException:
        pass

    # Wait for ACTIVE.
    while True:
        resp = aoss.batch_get_collection(names=[name])
        rows = resp.get("collectionDetails", [])
        if rows:
            row = rows[0]
            status = row["status"]
            print(f"     AOSS collection status={status}")
            if status == "ACTIVE":
                return row["arn"], row["collectionEndpoint"], row["id"]
            if status == "FAILED":
                raise RuntimeError(f"AOSS collection {name} failed to create")
        time.sleep(8)


def _put_aoss_policy(aoss: Any, name: str, type_: str, policy: str) -> None:
    try:
        aoss.create_security_policy(name=name, type=type_, policy=policy)
    except aoss.exceptions.ConflictException:
        # Update with version handling.
        try:
            current = aoss.get_security_policy(name=name, type=type_)
            aoss.update_security_policy(
                name=name,
                type=type_,
                policyVersion=current["securityPolicyDetail"]["policyVersion"],
                policy=policy,
            )
        except Exception:
            pass


def _ensure_aoss_data_access(aoss: Any, account: str, role_arn: str) -> None:
    """Allow the KB execution role + the caller principal to read/write the index."""
    caller_arn = boto3.client("sts").get_caller_identity()["Arn"]
    name = f"{AOSS_COLLECTION_NAME}-data"
    policy = [
        {
            "Rules": [
                {
                    "ResourceType": "index",
                    "Resource": [f"index/{AOSS_COLLECTION_NAME}/*"],
                    "Permission": [
                        "aoss:CreateIndex",
                        "aoss:DeleteIndex",
                        "aoss:UpdateIndex",
                        "aoss:DescribeIndex",
                        "aoss:ReadDocument",
                        "aoss:WriteDocument",
                    ],
                },
                {
                    "ResourceType": "collection",
                    "Resource": [f"collection/{AOSS_COLLECTION_NAME}"],
                    "Permission": [
                        "aoss:CreateCollectionItems",
                        "aoss:DescribeCollectionItems",
                        "aoss:UpdateCollectionItems",
                    ],
                },
            ],
            "Principal": [role_arn, caller_arn],
            "Description": "FactoryMind KB data access",
        }
    ]
    body = json.dumps(policy)
    try:
        aoss.create_access_policy(name=name, type="data", policy=body)
    except aoss.exceptions.ConflictException:
        current = aoss.get_access_policy(name=name, type="data")
        aoss.update_access_policy(
            name=name,
            type="data",
            policyVersion=current["accessPolicyDetail"]["policyVersion"],
            policy=body,
        )


def _ensure_aoss_index(endpoint: str, region: str) -> None:
    """Create the vector index in the collection if it doesn't exist.

    AOSS doesn't accept the bulk python OpenSearch client without SigV4 signing.
    We use opensearch-py with AWSV4SignerAuth.
    """
    try:
        from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth
    except ImportError:
        print("     ! opensearch-py not installed; install with: pip install opensearch-py")
        print("     ! skipping index creation — Bedrock will fail until the index exists")
        return

    credentials = boto3.Session().get_credentials()
    auth = AWSV4SignerAuth(credentials, region, "aoss")
    host = endpoint.replace("https://", "").replace("http://", "")
    client = OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30,
    )

    if client.indices.exists(index=AOSS_INDEX_NAME):
        print(f"     index {AOSS_INDEX_NAME} already exists")
        return

    body = {
        "settings": {"index": {"knn": True, "knn.algo_param.ef_search": 512}},
        "mappings": {
            "properties": {
                "vector_field": {
                    "type": "knn_vector",
                    "dimension": EMBEDDING_DIM,
                    "method": {
                        "name": "hnsw",
                        "engine": "faiss",
                        "parameters": {"ef_construction": 512, "m": 16},
                        "space_type": "l2",
                    },
                },
                "text_field": {"type": "text"},
                "metadata_field": {"type": "text"},
            }
        },
    }
    client.indices.create(index=AOSS_INDEX_NAME, body=body)
    print(f"     created index {AOSS_INDEX_NAME}")


# --- Bedrock Knowledge Base -------------------------------------------------


def _ensure_knowledge_base(
    bedrock_agent: Any, role_arn: str, collection_arn: str, region: str
) -> str:
    # Look up existing KB by name.
    paginator = bedrock_agent.get_paginator("list_knowledge_bases")
    for page in paginator.paginate():
        for kb in page.get("knowledgeBaseSummaries", []):
            if kb.get("name") == KB_NAME:
                return kb["knowledgeBaseId"]

    # Create new.
    embedding_arn = EMBEDDING_MODEL_ARN.format(region=region)
    last_err: Exception | None = None
    for attempt in range(8):
        try:
            resp = bedrock_agent.create_knowledge_base(
                name=KB_NAME,
                description="FactoryMind sustainability + maintenance playbooks",
                roleArn=role_arn,
                knowledgeBaseConfiguration={
                    "type": "VECTOR",
                    "vectorKnowledgeBaseConfiguration": {
                        "embeddingModelArn": embedding_arn,
                    },
                },
                storageConfiguration={
                    "type": "OPENSEARCH_SERVERLESS",
                    "opensearchServerlessConfiguration": {
                        "collectionArn": collection_arn,
                        "vectorIndexName": AOSS_INDEX_NAME,
                        "fieldMapping": {
                            "vectorField": "vector_field",
                            "textField": "text_field",
                            "metadataField": "metadata_field",
                        },
                    },
                },
            )
            return resp["knowledgeBase"]["knowledgeBaseId"]
        except ClientError as e:
            msg = e.response.get("Error", {}).get("Message", "")
            if "no identity-based policy" in msg or "is not authorized" in msg or "could not assume" in msg.lower():
                last_err = e
                wait = 8 + attempt * 4
                print(f"     IAM not yet propagated; retry in {wait}s ({msg[:80]})")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"Bedrock CreateKnowledgeBase failed after retries: {last_err}")


def _ensure_data_source(bedrock_agent: Any, kb_id: str, bucket: str) -> str:
    paginator = bedrock_agent.get_paginator("list_data_sources")
    for page in paginator.paginate(knowledgeBaseId=kb_id):
        for ds in page.get("dataSourceSummaries", []):
            if ds.get("name") == DATA_SOURCE_NAME:
                return ds["dataSourceId"]

    resp = bedrock_agent.create_data_source(
        knowledgeBaseId=kb_id,
        name=DATA_SOURCE_NAME,
        description="FactoryMind playbook docs (S3)",
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {"bucketArn": f"arn:aws:s3:::{bucket}"},
        },
    )
    return resp["dataSource"]["dataSourceId"]


# --- Lambda env patching ----------------------------------------------------


def _patch_lambda_env(lam: Any, fn_name: str, extra: dict[str, str]) -> None:
    try:
        cfg = lam.get_function_configuration(FunctionName=fn_name)
    except lam.exceptions.ResourceNotFoundException:
        print(f"     {fn_name}: not found, skipping")
        return
    env = (cfg.get("Environment") or {}).get("Variables", {})
    if all(env.get(k) == v for k, v in extra.items()):
        print(f"     {fn_name}: env already up to date")
        return
    env.update(extra)
    waiter = lam.get_waiter("function_updated_v2")
    waiter.wait(FunctionName=fn_name)
    lam.update_function_configuration(
        FunctionName=fn_name, Environment={"Variables": env}
    )
    print(f"     {fn_name}: env patched ({list(extra.keys())})")


# --- Misc -------------------------------------------------------------------


def _required_policy() -> dict[str, Any]:
    """The minimal IAM policy needed by the caller running this script."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "BedrockKB",
                "Effect": "Allow",
                "Action": [
                    "bedrock:CreateKnowledgeBase",
                    "bedrock:UpdateKnowledgeBase",
                    "bedrock:GetKnowledgeBase",
                    "bedrock:ListKnowledgeBases",
                    "bedrock:CreateDataSource",
                    "bedrock:GetDataSource",
                    "bedrock:ListDataSources",
                    "bedrock:StartIngestionJob",
                    "bedrock:GetIngestionJob",
                    "bedrock:ListIngestionJobs",
                ],
                "Resource": "*",
            },
            {
                "Sid": "OpenSearchServerless",
                "Effect": "Allow",
                "Action": ["aoss:*"],
                "Resource": "*",
            },
            {
                "Sid": "S3Docs",
                "Effect": "Allow",
                "Action": ["s3:CreateBucket", "s3:PutBucketPublicAccessBlock", "s3:PutObject", "s3:HeadBucket"],
                "Resource": "*",
            },
            {
                "Sid": "IAMRoles",
                "Effect": "Allow",
                "Action": [
                    "iam:CreateRole",
                    "iam:GetRole",
                    "iam:PutRolePolicy",
                    "iam:UpdateAssumeRolePolicy",
                    "iam:PassRole",
                ],
                "Resource": "arn:aws:iam::*:role/FactoryMind*",
            },
            {
                "Sid": "LambdaPatch",
                "Effect": "Allow",
                "Action": [
                    "lambda:GetFunctionConfiguration",
                    "lambda:UpdateFunctionConfiguration",
                ],
                "Resource": "arn:aws:lambda:*:*:function:factorymind-*",
            },
        ],
    }


if __name__ == "__main__":
    sys.exit(main())
