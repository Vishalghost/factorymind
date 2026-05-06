# FactoryMind — Deployment Guide

End-to-end runbook for deploying the FactoryMind multi-agent platform to AWS.
Everything in this stack is AWS-native: Bedrock, Lambda, IoT Core, Kinesis,
Timestream, DynamoDB, S3, EventBridge, SQS, SNS, SageMaker, Lookout for
Equipment, Rekognition, IoT TwinMaker, AppSync, ElastiCache Redis, SES, KMS,
CloudWatch, X-Ray.

---

## 1. Prerequisites

| Tool                | Version  | Why                                                  |
| ------------------- | -------- | ---------------------------------------------------- |
| Python              | ≥ 3.11   | Lambda runtime + agent code                          |
| Node.js             | ≥ 20.x   | React dashboard (Vite)                               |
| AWS CLI v2          | latest   | `aws sts ...`, S3 sync, Lambda invoke                |
| AWS CDK v2          | ≥ 2.140  | Infrastructure as code                               |
| Docker              | latest   | Lambda layer build, agent images, local LocalStack   |
| jq                  | optional | Reading CloudFormation outputs in scripts            |

Configure AWS credentials:

```bash
aws configure
# or for SSO:
aws configure sso
aws sts get-caller-identity   # confirm
```

Default deploy region is **`ap-south-1`** (Mumbai) to match the Chennai plant
domain. Override with `--region us-east-1` if you prefer.

---

## 2. One-shot deploy

```bash
# From repo root
chmod +x scripts/deploy.sh scripts/build_layers.sh
./scripts/deploy.sh
```

Or on Windows:

```powershell
.\scripts\deploy.ps1
```

This runs eight steps:

1. Tooling check (python, node, npm, aws, cdk).
2. `pytest tests/unit/` — must pass before deploy.
3. `scripts/build_layers.sh` — packages Python deps + ONNX into Lambda layers.
4. `cdk bootstrap` (idempotent).
5. `cdk deploy FactoryMindStorage FactoryMindIoT FactoryMindCompute FactoryMindML FactoryMindMonitoring`.
6. Resolve the ElastiCache Redis endpoint and patch the env vars on
   `factorymind-edge-ai-manager` and `factorymind-digital-twin-manager`.
7. `scripts/seed_dummy_data.py` — 50 CNC-AERO machines, baselines, thresholds.
8. Build the React dashboard with the resolved AppSync URL/API key and
   sync to a public S3 website bucket.

Skip flags: `--skip-tests`, `--skip-layers`, `--skip-seed`, `--skip-dashboard`.

---

## 3. What gets provisioned

### Storage stack — `FactoryMindStorage`
- 12 DynamoDB tables (PAY_PER_REQUEST), 5 S3 buckets, Timestream database
  + 2 tables, ElastiCache Redis cluster, VPC for Redis access.

### IoT stack — `FactoryMindIoT`
- Kinesis stream `factorymind-sensor-stream` (2 shards),
  Kinesis Firehose → S3 archive,
  EventBridge bus `factorymind-bus` + 7-day archive,
  SQS queue `factorymind-workorder-queue` + DLQ,
  SNS topics for quality + maintenance alerts,
  IoT Core rules: telemetry → Kinesis, telemetry → Edge AI Lambda.

### Compute stack — `FactoryMindCompute`
- Shared Python deps Lambda layer + ONNX Runtime layer.
- 7 Lambda functions: `factorymind-iot-ingestion-manager`,
  `factorymind-edge-ai-manager`, `factorymind-quality-vision-manager`,
  `factorymind-predictive-maintenance-manager`,
  `factorymind-sustainability-manager`, `factorymind-digital-twin-manager`,
  `factorymind-brain-agent`.
- IAM roles with least-privilege per agent.
- Event source mappings: Kinesis → IoT Ingestion, S3 → Quality Vision,
  EventBridge rules: anomaly + escalation → Brain, BrainDecision → Digital Twin.
- Edge AI + Digital Twin Lambdas live in the StorageStack VPC for Redis access.

### ML stack — `FactoryMindML`
- SageMaker models + serverless endpoint configs + endpoints for YOLOv8 (quality)
  and LSTM (predictive maintenance). Model artifacts must be uploaded to
  `s3://factorymind-ml-models/{yolov8,lstm}/model.tar.gz` first.
- IAM role for Lookout for Equipment (model itself is created out-of-band —
  see §5 below).
- AppSync GraphQL API `factorymind-appsync-api` (API key auth) wired to
  `FactoryMind_TwinState` for real-time updates.
- IoT TwinMaker workspace + scenes bucket.
- Outputs: `AppSyncEndpoint`, `AppSyncApiKey`, `MLModelsBucket`.

### Monitoring stack — `FactoryMindMonitoring`
- SNS topic `factorymind-ops-alerts` (subscribe via context: `--context ops_email=you@co`).
- Per-agent error-rate + p99-duration alarms vs. each SLA target.
- CloudWatch dashboard `FactoryMind-Operations`.

---

## 4. ML model training and upload

The Edge AI and Predictive Maintenance agents both need real model artifacts.
**Train them locally** — synthetic data, 1-minute training, no SageMaker
training-job costs. SageMaker is only used for *inference* (already provisioned
by `FactoryMindML`).

### Install ML build dependencies (build machine only)

```bash
pip install -r requirements-ml.txt          # torch, onnx, onnxruntime, scikit-learn
```

### Edge AI — ONNX classifier (Lambda Layer)

```bash
PYTHONIOENCODING=utf-8 PYTHONPATH=. python models/edge/train_edge_classifier.py
# Trains a 6→32→16→3 MLP on synthetic CNC telemetry. Takes ~30s.
# Output: models/edge/edge_classifier_v2.onnx
#         models/edge/edge_classifier_v2.metrics.json

# Rebuild the Lambda layer so it picks up the new model
./scripts/build_layers.sh

# Re-deploy compute stack so the layer version pointer updates
cd infrastructure/cdk && cdk deploy FactoryMindCompute --context region=us-east-1
```

The agent loads the model from `/opt/models/edge_classifier_v2.onnx` (Lambda
Layer mount path). If the file is missing or onnxruntime fails, the agent
silently falls back to the rule-based path in `_rule_based_inference`.

### Predictive Maintenance — LSTM (SageMaker Serverless Endpoint)

```bash
# 1. Train the PyTorch LSTM (TorchScripted, 4 input features, 72-step sequences).
PYTHONIOENCODING=utf-8 PYTHONPATH=. python models/lstm/train_lstm_maintenance.py
# Output: models/lstm/model.pt              — TorchScript artifact
#         models/lstm/feature_config.json   — normalization stats + class labels
#         models/lstm/metrics.json          — accuracy + RUL MAE

# 2. Package model.pt + inference.py + requirements.txt into model.tar.gz
bash models/lstm/package_lstm.sh

# 3. Upload to S3 and reload the endpoint (one command)
bash models/lstm/package_lstm.sh --upload --region us-east-1

# Or do it manually:
aws s3 cp models/lstm/model.tar.gz s3://factorymind-ml-models/lstm/model.tar.gz --region us-east-1
aws sagemaker update-endpoint \
    --endpoint-name factorymind-lstm-maintenance \
    --endpoint-config-name factorymind-lstm-maintenance-config \
    --region us-east-1
```

The SageMaker container is `pytorch-inference:2.1-cpu-py310`. The bundled
`code/inference.py` defines `model_fn`/`input_fn`/`predict_fn`/`output_fn`
matching the request shape that `agents/predictive_maintenance/workers/lstm_worker.py`
sends. Feature normalization runs inside `input_fn` using the stats baked
into `feature_config.json`.

### Quality Vision — YOLOv8 (still placeholder)

`ml_stack.py` provisions the YOLOv8 endpoint config, but a YOLOv8 model trained
on aerospace defect imagery is out of scope here. Two options for hackathon:
1. Skip it — the agent falls back to Amazon Rekognition `DetectLabels` when
   YOLOv8 confidence < 0.75. Rekognition needs zero setup.
2. Stub it — upload a tiny PyTorch model (e.g. ResNet18 trained on placeholder
   classes) packaged the same way as the LSTM tarball, into
   `s3://factorymind-ml-models/yolov8/model.tar.gz`.

### Why local-train, not SageMaker-train?

- Synthetic data: nothing to upload. Training in cloud just rents you compute.
- Both models are small (MLP + 2-layer LSTM). CPU training takes <1 min each.
- SageMaker training jobs cost ~$0.10–0.50/run and need extra IAM permissions
  (`iam:PassRole`, `sagemaker:CreateTrainingJob`) which workshop roles like
  `WSParticipantRole` typically don't have.
- The output `.pt` / `.onnx` files are byte-identical regardless of where they
  were trained. SageMaker training adds value when (a) data is real and large,
  (b) you need GPUs, (c) you want hyperparameter tuning. None of these apply.

### Verifying the deployed endpoint

```bash
# Send a sample 72-step sequence to the live LSTM endpoint
aws sagemaker-runtime invoke-endpoint \
    --endpoint-name factorymind-lstm-maintenance \
    --content-type application/json \
    --body '{"machine_id":"CNC-AERO-08","sensor_history":[],"current_snapshot":{"vibration_mms":12.0,"current_amps":38.0,"coolant_lmin":10.0,"acoustic_db":98.0}}' \
    --region us-east-1 \
    response.json && cat response.json
# Expected: {"severity":"CRITICAL","failure_mode":"COOLANT_BLOCKAGE",...}
```

---

## 5. Lookout for Equipment — manual setup

Lookout for Equipment has no production-grade L2 CDK construct; the CDK stack
provisions only the IAM role. Create the model itself out-of-band:

```bash
# 1. Upload historical sensor data CSVs to S3
aws s3 cp historical/sensor_history.csv s3://factorymind-ml-models/lookout/

# 2. Create Lookout dataset + model via boto3
python - <<'PY'
import boto3
le = boto3.client("lookoutequipment", region_name="ap-south-1")

# Create dataset
le.create_dataset(
    DatasetName="factorymind-cnc-history",
    DatasetSchema={"InlineDataSchema": '{"Components":[{"ComponentName":"CNC","Columns":[{"Name":"Timestamp","Type":"DATETIME"},{"Name":"vibration_mms","Type":"DOUBLE"},{"Name":"current_amps","Type":"DOUBLE"},{"Name":"coolant_lmin","Type":"DOUBLE"},{"Name":"acoustic_db","Type":"DOUBLE"}]}]}',
    },
)
# ... ingest, train, deploy — see AWS docs for full sequence.
PY
```

The agent code already calls `lookoutequipment:DescribeInferenceScheduler` and
`ListInferenceExecutions`; the IAM policy is provisioned by ComputeStack.

---

## 6. Smoke-testing the deploy

```bash
# 1. Confirm Lambdas exist + are wired
aws lambda list-functions --region ap-south-1 \
    --query "Functions[?starts_with(FunctionName,'factorymind-')].FunctionName" \
    --output table

# 2. Generate a CRITICAL alert via the simulator
python scripts/simulate_aerospace_cnc.py \
    --machine-id CNC-AERO-01 \
    --mode catastrophic \
    --duration 30 \
    --publish \
    --endpoint $(aws iot describe-endpoint --endpoint-type iot:Data-ATS --query endpointAddress --output text)

# 3. Watch the Brain Agent log
aws logs tail /aws/lambda/factorymind-brain-agent --follow --region ap-south-1

# 4. Inspect EventBridge events
aws events list-rules --event-bus-name factorymind-bus --region ap-south-1

# 5. Check the CloudWatch dashboard
open "https://ap-south-1.console.aws.amazon.com/cloudwatch/home?region=ap-south-1#dashboards:name=FactoryMind-Operations"
```

When the simulator runs in `catastrophic` mode, Edge AI's compound rule should
trip in < 10ms, escalate to Brain via EventBridge, and Brain should activate
Predictive Maintenance + Digital Twin. The dashboard's Plant Overview will turn
the affected machine card red.

---

## 7. Local development with Docker

For testing without spending AWS dollars:

```bash
# Build the base image first
docker compose --profile build up base

# Bring up LocalStack + Redis + the agent containers
docker compose up --build localstack redis brain iot-ingestion edge-ai digital-twin

# Seed LocalStack DynamoDB
docker compose run --rm seed

# Drive simulated telemetry into LocalStack
docker compose run --rm simulator --mode tool_wear --duration 60
```

Each agent listens on a local port (9001–9007) speaking the AWS Lambda Runtime
Interface. Invoke directly:

```bash
curl -XPOST http://localhost:9001/2015-03-31/functions/function/invocations \
    -H 'Content-Type: application/json' \
    -d '{"detail":{"machine_id":"CNC-AERO-01","alert_type":"COMPOUND_FAILURE","severity":"CRITICAL","timestamp":"2026-05-06T14:30:00Z","raw_sensor_snapshot":{"vibration_mms":12.0,"current_amps":38.0,"coolant_lmin":10.0,"acoustic_db":98.0},"production_line":"LINE-A","plant_id":"PLANT-001"}}'
```

LocalStack covers ~95% of the surface area; SageMaker Serverless inference and
Lookout for Equipment do not run in LocalStack (community edition) — those
calls error out and the agents fall back to their rule-based paths.

---

## 8. Tear down

```bash
cd infrastructure/cdk
cdk destroy FactoryMindMonitoring FactoryMindML FactoryMindCompute FactoryMindIoT FactoryMindStorage
```

**Ordering matters** — the destroy order is the inverse of deploy. CDK does
this automatically because of the `add_dependency()` graph in `app.py`, but
you can pass them explicitly to be safe.

S3 buckets with `auto_delete_objects=True` clean up. ElastiCache, SageMaker
endpoints, and TwinMaker workspaces take 5-10 minutes each.

---

## 9. Operational runbook

| Issue                                           | First check                                                              |
| ----------------------------------------------- | ------------------------------------------------------------------------ |
| Edge AI p99 > 10ms                              | `EdgeInferenceTimeMs` in CloudWatch dashboard. Likely cold start — set provisioned concurrency. |
| Brain Lambda timing out                          | EventBridge rule `factorymind-anomaly-to-brain` retries; check DLQ.      |
| `ResourceNotFoundException` on Timestream       | StorageStack out of sync — re-run `cdk deploy FactoryMindStorage`.       |
| Redis connection refused from Lambda            | Lambda not in VPC, or `REDIS_HOST` env var not patched. Re-run step 6 of `deploy.sh`. |
| AppSync subscription fires but dashboard empty  | API key expired (default rotation 7 days). `cdk deploy FactoryMindML` to mint a new one. |
| Dashboard works locally, blank in S3            | `VITE_*` env vars weren't set during `npm run build`. Re-run dashboard build inside `deploy.sh`. |

---

## 10. Cost estimate (idle plant, ap-south-1)

Order of magnitude only — actual costs depend on telemetry volume.

| Resource                                            | Idle/day  |
| --------------------------------------------------- | --------- |
| 12 DynamoDB tables (PAY_PER_REQUEST, no traffic)    | ~$0       |
| 7 Lambda functions                                  | ~$0       |
| Kinesis 2 shards                                    | ~$1       |
| ElastiCache cache.t3.small                          | ~$0.85    |
| SageMaker Serverless (provisioned, idle)            | ~$0.50    |
| AppSync                                             | ~$0       |
| CloudWatch logs + dashboard                         | ~$0.10    |
| VPC NAT gateway (StorageStack — main offender)      | ~$1.40    |
| **Approx. idle baseline**                           | **~$4/day** |

A simulator running at 600 events/min × 24h adds ~$2-3/day in Kinesis +
Lambda + DynamoDB charges. Tear down or stop the cluster between hackathon
demos to keep the bill flat.
