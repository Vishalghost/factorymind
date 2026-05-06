# FactoryMind — Simple Step-by-Step Deploy

Per-service plain-English guide. Run top to bottom. Each step has: **what**, **why**, **command**, **verify**.

> **Region**: this guide uses `us-east-1` (matches your AWS account). Change `--region` everywhere if you deploy elsewhere.

---

## Part A — Prerequisites (one-time, on your laptop)

### A1. Install tools
```bash
python --version          # must be 3.11+
node --version            # must be 20+
aws --version             # AWS CLI v2
cdk --version             # CDK 2.140+; install with: npm install -g aws-cdk
docker --version          # for Lambda layer build
```

### A2. Configure AWS credentials
```bash
aws configure
aws sts get-caller-identity   # confirm — should print your Account + Role
```

### A3. Install Python deps
```bash
pip install -r requirements-dev.txt    # runtime + test
pip install -r requirements-ml.txt     # ML training only
```

### A4. Train the ML models locally (~2 minutes total)
```bash
PYTHONIOENCODING=utf-8 PYTHONPATH=. python models/edge/train_edge_classifier.py
PYTHONIOENCODING=utf-8 PYTHONPATH=. python models/lstm/train_lstm_maintenance.py
bash models/lstm/package_lstm.sh
```

**Verify**: `models/edge/edge_classifier_v2.onnx` exists, `models/lstm/model.tar.gz` exists.

---

## Part B — Deploy the AWS infrastructure

The `deploy.sh` (Linux/macOS) or `deploy.ps1` (Windows) script does everything below in one shot. The per-service walkthrough that follows is for understanding what each step does — you don't need to run them individually.

### One-shot deploy
```bash
./scripts/deploy.sh --region us-east-1                # Linux/macOS
.\scripts\deploy.ps1 -Region us-east-1                # Windows
```

That's it. Everything below is the same flow broken out service by service if you want to run pieces manually.

---

## Part C — Per-service walkthrough (what each piece does)

### C1. CDK bootstrap (one-time per account+region)
**What**: creates a small CDK staging bucket so the framework can upload assets.
**Why**: required once per account+region before any `cdk deploy`.
```bash
cd infrastructure/cdk
cdk bootstrap aws://YOUR_ACCOUNT/us-east-1
```
**Verify**: bucket `cdk-hnb659fds-assets-YOUR_ACCOUNT-us-east-1` shows in S3 console.

### C2. Build Lambda layers (Python deps + ONNX runtime)
**What**: pip-installs deps inside the Amazon Linux Lambda container so wheels match.
**Why**: every Lambda imports pydantic, structlog, redis, langgraph from this layer.
```bash
bash scripts/build_layers.sh
```
**Verify**: `infrastructure/layers/python_deps/python/` has `pydantic/`, `structlog/`, etc.

### C3. Storage stack — DynamoDB, S3, Timestream, ElastiCache Serverless, VPC
**What**: 12 DynamoDB tables, 5 S3 buckets, Timestream DB + 2 tables, ElastiCache Serverless Redis, VPC with NAT + Gateway Endpoints for S3/DynamoDB.
**Why**: every other stack depends on these data stores existing.
```bash
cd infrastructure/cdk
cdk deploy FactoryMindStorage --context region=us-east-1 --require-approval never
```
**Time**: ~8 minutes (ElastiCache Serverless is the slow part).
**Verify**:
```bash
aws dynamodb list-tables --region us-east-1                  # 12 FactoryMind_* tables
aws s3 ls | grep factorymind                                 # 5 buckets
aws elasticache describe-serverless-caches --region us-east-1 --query 'ServerlessCaches[].ServerlessCacheName'
aws timestream-write describe-database --database-name FactoryMindSensors --region us-east-1
```

### C4. IoT stack — IoT Core, Kinesis (On-Demand), Firehose, EventBridge, SQS, SNS
**What**: MQTT topic rules, Kinesis On-Demand stream, Firehose to S3, EventBridge bus + 7-day archive, SQS work-order queue + DLQ, SNS alert topics.
**Why**: ingestion pipeline + inter-agent eventing.
```bash
cdk deploy FactoryMindIoT --context region=us-east-1 --require-approval never
```
**Time**: ~3 minutes.
**Verify**:
```bash
aws iot describe-endpoint --endpoint-type iot:Data-ATS --region us-east-1
aws kinesis describe-stream --stream-name factorymind-sensor-stream --region us-east-1 \
    --query 'StreamDescription.StreamModeDetails'
aws events list-event-buses --region us-east-1 --query "EventBuses[?Name=='factorymind-bus']"
aws sqs list-queues --region us-east-1 --queue-name-prefix factorymind
```

### C5. Compute stack — 7 Lambda functions + IAM + event source mappings
**What**: Brain Agent + 6 Manager Agents as Lambda functions, IAM roles per agent, Kinesis→IoT-Ingestion mapping, S3→Quality-Vision trigger, EventBridge rules.
**Why**: this is the actual application code running.
```bash
cdk deploy FactoryMindCompute --context region=us-east-1 --require-approval never
```
**Time**: ~5 minutes.
**Verify**:
```bash
aws lambda list-functions --region us-east-1 \
    --query "Functions[?starts_with(FunctionName,'factorymind-')].FunctionName"
# Expect 7 functions
```

### C6. ML stack — SageMaker endpoints, AppSync, IoT TwinMaker
**What**: SageMaker models + serverless endpoint configs for YOLOv8 + LSTM, IAM role for Lookout, AppSync GraphQL API + DynamoDB resolvers, IoT TwinMaker workspace.
**Why**: ML inference + real-time dashboard API.
```bash
cdk deploy FactoryMindML --context region=us-east-1 --require-approval never
```
**Time**: ~10 minutes (SageMaker endpoints are the slow part).
**Verify**:
```bash
aws cloudformation describe-stacks --stack-name FactoryMindML --region us-east-1 \
    --query "Stacks[0].Outputs[?OutputKey=='AppSyncEndpoint'].OutputValue"
aws sagemaker list-endpoints --region us-east-1 \
    --query "Endpoints[?starts_with(EndpointName,'factorymind-')].EndpointName"
```

### C7. Monitoring stack — CloudWatch dashboard + alarms + SNS
**What**: per-agent SLA breach alarms (p99 duration), error-rate alarms, SNS ops topic, CloudWatch dashboard `FactoryMind-Operations`.
**Why**: observability + alerting.
```bash
cdk deploy FactoryMindMonitoring --context region=us-east-1 --require-approval never
```
**Time**: ~2 minutes.
**Verify**:
```bash
aws cloudwatch list-dashboards --region us-east-1 \
    --query "DashboardEntries[?DashboardName=='FactoryMind-Operations']"
```

### C8. Frontend stack — S3 bucket + CloudFront distribution
**What**: private S3 bucket (Origin Access Control) + CloudFront distribution with SPA error handling.
**Why**: HTTPS hosting + global CDN for the React dashboard.
```bash
cdk deploy FactoryMindFrontend --context region=us-east-1 --require-approval never
```
**Time**: ~5 minutes (CloudFront propagation).
**Verify**:
```bash
aws cloudformation describe-stacks --stack-name FactoryMindFrontend --region us-east-1 \
    --query "Stacks[0].Outputs"
# Should show DashboardURL, DashboardBucketName, CloudFrontDistributionId
```

### C9. Patch Lambda env vars with Redis endpoint
**What**: read the ElastiCache Serverless endpoint, set `REDIS_HOST` / `REDIS_PORT` / `REDIS_TLS=true` on the Edge AI + Digital Twin Lambdas.
**Why**: the Lambdas were deployed with placeholder values; patch them with the real endpoint now that storage is up.
```bash
REDIS_HOST=$(aws elasticache describe-serverless-caches --serverless-cache-name factorymind-redis \
    --region us-east-1 --query 'ServerlessCaches[0].Endpoint.Address' --output text)
REDIS_PORT=$(aws elasticache describe-serverless-caches --serverless-cache-name factorymind-redis \
    --region us-east-1 --query 'ServerlessCaches[0].Endpoint.Port' --output text)

for fn in factorymind-edge-ai-manager factorymind-digital-twin-manager; do
  aws lambda update-function-configuration --function-name "$fn" --region us-east-1 \
      --environment "Variables={EVENT_BUS_NAME=factorymind-bus,PLANT_ID=PLANT-001,REDIS_HOST=$REDIS_HOST,REDIS_PORT=$REDIS_PORT,REDIS_TLS=true,POWERTOOLS_SERVICE_NAME=$fn,POWERTOOLS_METRICS_NAMESPACE=FactoryMind,LOG_LEVEL=INFO}" >/dev/null
done
```
**Verify**:
```bash
aws lambda get-function-configuration --function-name factorymind-edge-ai-manager \
    --region us-east-1 --query 'Environment.Variables.REDIS_HOST'
```

### C10. Upload SageMaker LSTM model
**What**: push the trained model.tar.gz to S3 and reload the endpoint.
**Why**: the SageMaker endpoint was created with no artifact; upload + reload makes it live.
```bash
bash models/lstm/package_lstm.sh --upload --region us-east-1
```
**Verify**: `aws sagemaker describe-endpoint --endpoint-name factorymind-lstm-maintenance --region us-east-1 --query 'EndpointStatus'` returns `InService` (5-10 min after upload).

### C11. Seed reference data into DynamoDB
**What**: populate 50 CNC machines + baselines + thresholds + floor layout.
**Why**: the agents need this reference data to make decisions.
```bash
PYTHONPATH=. python scripts/seed_dummy_data.py --region us-east-1
```
**Verify**:
```bash
aws dynamodb scan --table-name FactoryMind_MachineSpecs --region us-east-1 \
    --select COUNT --query 'Count'
# Expect 50
```

### C12. Build and deploy the React dashboard
**What**: read AppSync URL/key + bucket name + distribution ID from CFN outputs, build with Vite, sync to S3, invalidate CloudFront.
**Why**: deploys the live dashboard at the CloudFront URL.
```bash
APPSYNC_URL=$(aws cloudformation describe-stacks --stack-name FactoryMindML --region us-east-1 \
    --query "Stacks[0].Outputs[?OutputKey=='AppSyncEndpoint'].OutputValue" --output text)
APPSYNC_KEY=$(aws cloudformation describe-stacks --stack-name FactoryMindML --region us-east-1 \
    --query "Stacks[0].Outputs[?OutputKey=='AppSyncApiKey'].OutputValue" --output text)
BUCKET=$(aws cloudformation describe-stacks --stack-name FactoryMindFrontend --region us-east-1 \
    --query "Stacks[0].Outputs[?OutputKey=='DashboardBucketName'].OutputValue" --output text)
DIST_ID=$(aws cloudformation describe-stacks --stack-name FactoryMindFrontend --region us-east-1 \
    --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDistributionId'].OutputValue" --output text)

cd dashboard
npm install
VITE_APPSYNC_URL=$APPSYNC_URL VITE_APPSYNC_API_KEY=$APPSYNC_KEY VITE_AWS_REGION=us-east-1 npm run build
aws s3 sync dist s3://$BUCKET --delete --region us-east-1
aws cloudfront create-invalidation --distribution-id $DIST_ID --paths '/*'
cd ..
```
**Verify**:
```bash
aws cloudformation describe-stacks --stack-name FactoryMindFrontend --region us-east-1 \
    --query "Stacks[0].Outputs[?OutputKey=='DashboardURL'].OutputValue" --output text
# Open the printed https://xxxxx.cloudfront.net URL in a browser
```

---

## Part D — Smoke test the live system

### D1. Send a CRITICAL alert through real AWS
```bash
ENDPOINT=$(aws iot describe-endpoint --endpoint-type iot:Data-ATS --region us-east-1 \
    --query endpointAddress --output text)
PYTHONPATH=. python scripts/simulate_aerospace_cnc.py \
    --machine-id CNC-AERO-01 --mode catastrophic --duration 30 \
    --publish --endpoint $ENDPOINT
```

### D2. Watch the Brain Agent process it
```bash
aws logs tail /aws/lambda/factorymind-brain-agent --follow --region us-east-1
```

### D3. Open the dashboard
The CloudFront URL from step C12. Machine `CNC-AERO-01` should turn red within 5 seconds (compound rule trips → Brain delegates → Digital Twin pushes via AppSync subscription → dashboard re-renders).

---

## Part E — Tear down

```bash
cd infrastructure/cdk
cdk destroy FactoryMindFrontend FactoryMindMonitoring FactoryMindML \
            FactoryMindCompute FactoryMindIoT FactoryMindStorage \
            --context region=us-east-1
```

CDK destroys in the right order automatically. ElastiCache Serverless takes 5-10 minutes; CloudFront takes 15+ minutes (it's globally distributed).

---

## Cost summary (idle, us-east-1)

| Service | Idle/day |
|---|---|
| 7 Lambda functions, no invocations | ~$0 |
| 12 DynamoDB tables (on-demand) | ~$0 |
| Kinesis On-Demand (idle) | ~$0.40 |
| ElastiCache Serverless (min 1 GB) | ~$2.40 |
| NAT gateway (1) | ~$1.40 |
| CloudFront (low traffic) | ~$0 |
| SageMaker Serverless (idle) | ~$0.50 |
| AppSync, EventBridge, S3, CloudWatch | ~$0.20 |
| **Total idle** | **~$5/day** |

The biggest knob is the NAT gateway. To get to ~$3/day idle, replace the remaining outbound calls with VPC interface endpoints (Bedrock, EventBridge, SageMaker) — adds ~$21/month per endpoint × 3 = $2.10/day, but lets you set `nat_gateways=0` (saves $1.40/day). Net wash; do it for the cleaner cloud-native posture, not for cost savings.

Tear down between demos. Each restart costs ~5 minutes for ElastiCache + CloudFront propagation.
