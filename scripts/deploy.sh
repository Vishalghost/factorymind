#!/usr/bin/env bash
# FactoryMind end-to-end deploy script.
#
# Steps:
#   1. Sanity-check tooling (python, node, npm, aws, cdk, docker)
#   2. Run unit tests
#   3. Build the shared Lambda layer (pip install into infrastructure/layers/)
#   4. Bootstrap CDK in target region (idempotent)
#   5. Deploy CDK stacks in order: Storage → IoT → Compute → ML → Monitoring
#   6. Patch Lambda env vars with the resolved Redis endpoint
#   7. Seed DynamoDB tables with reference data
#   8. Build and upload the React dashboard to S3 (optional)
#
# Usage:
#   ./scripts/deploy.sh                      # full deploy
#   ./scripts/deploy.sh --skip-tests         # skip pytest
#   ./scripts/deploy.sh --skip-dashboard     # skip dashboard build
#   ./scripts/deploy.sh --region us-east-1   # override region (default ap-south-1)

set -euo pipefail

# --- Defaults ---
REGION="${AWS_REGION:-ap-south-1}"
SKIP_TESTS=0
SKIP_DASHBOARD=0
SKIP_LAYERS=0
SKIP_SEED=0

# --- Arg parsing ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --region)         REGION="$2"; shift 2 ;;
    --skip-tests)     SKIP_TESTS=1; shift ;;
    --skip-dashboard) SKIP_DASHBOARD=1; shift ;;
    --skip-layers)    SKIP_LAYERS=1; shift ;;
    --skip-seed)      SKIP_SEED=1; shift ;;
    -h|--help)
      grep -E '^# ' "$0" | sed 's/^# //'; exit 0 ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== FactoryMind Deploy ==="
echo "  Region: $REGION"
echo "  Repo:   $REPO_ROOT"
echo

# --- Step 1: Tooling check ---
echo "[1/8] Checking tooling..."
for cmd in python3 node npm aws cdk; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "  ✗ Missing: $cmd" >&2
    exit 1
  fi
done
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
echo "  AWS account: $ACCOUNT"
echo "  CDK version: $(cdk --version)"
echo

# --- Step 2: Unit tests ---
if [[ $SKIP_TESTS -eq 0 ]]; then
  echo "[2/8] Running unit tests..."
  PYTHONPATH=. python3 -m pytest tests/unit/ -q
  echo
else
  echo "[2/8] Skipping tests (--skip-tests)"
fi

# --- Step 3: Build shared Lambda layer ---
if [[ $SKIP_LAYERS -eq 0 ]]; then
  echo "[3/8] Building shared Lambda layer..."
  bash scripts/build_layers.sh
  echo
else
  echo "[3/8] Skipping layer build (--skip-layers)"
fi

# --- Step 4: CDK bootstrap (idempotent) ---
echo "[4/8] CDK bootstrap..."
cd infrastructure/cdk
cdk bootstrap "aws://${ACCOUNT}/${REGION}" || true
echo

# --- Step 5: CDK deploy ---
echo "[5/8] CDK deploy (Storage → IoT → Compute → ML → Monitoring)..."
cdk deploy \
    FactoryMindStorage \
    FactoryMindIoT \
    FactoryMindCompute \
    FactoryMindML \
    FactoryMindMonitoring \
    --require-approval never \
    --context region="$REGION"
echo

# --- Step 6: Patch Redis endpoint ---
echo "[6/8] Patching Lambda env vars with Redis endpoint..."
cd "$REPO_ROOT"
REDIS_HOST="$(aws elasticache describe-cache-clusters \
    --cache-cluster-id factorymind-redis \
    --show-cache-node-info \
    --region "$REGION" \
    --query 'CacheClusters[0].CacheNodes[0].Endpoint.Address' \
    --output text 2>/dev/null || echo '')"

if [[ -n "$REDIS_HOST" && "$REDIS_HOST" != "None" ]]; then
  for fn in factorymind-edge-ai-manager factorymind-digital-twin-manager; do
    aws lambda update-function-configuration \
        --function-name "$fn" \
        --environment "Variables={EVENT_BUS_NAME=factorymind-bus,PLANT_ID=PLANT-001,REDIS_HOST=$REDIS_HOST,REDIS_PORT=6379,POWERTOOLS_SERVICE_NAME=$fn,POWERTOOLS_METRICS_NAMESPACE=FactoryMind,LOG_LEVEL=INFO}" \
        --region "$REGION" >/dev/null
    echo "  Patched $fn → REDIS_HOST=$REDIS_HOST"
  done
else
  echo "  WARN: could not resolve Redis endpoint; Lambdas will use placeholder."
fi
echo

# --- Step 7: Seed reference data ---
if [[ $SKIP_SEED -eq 0 ]]; then
  echo "[7/8] Seeding DynamoDB reference data..."
  PYTHONPATH=. python3 scripts/seed_dummy_data.py --region "$REGION"
  echo
else
  echo "[7/8] Skipping seed (--skip-seed)"
fi

# --- Step 8: Dashboard build + upload ---
if [[ $SKIP_DASHBOARD -eq 0 ]]; then
  echo "[8/8] Building and uploading React dashboard..."
  if [[ -d "dashboard" && -f "dashboard/package.json" ]]; then
    APPSYNC_URL="$(aws cloudformation describe-stacks \
        --stack-name FactoryMindML \
        --region "$REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='AppSyncEndpoint'].OutputValue" \
        --output text 2>/dev/null || echo '')"
    APPSYNC_KEY="$(aws cloudformation describe-stacks \
        --stack-name FactoryMindML \
        --region "$REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='AppSyncApiKey'].OutputValue" \
        --output text 2>/dev/null || echo '')"

    pushd dashboard >/dev/null
    npm install
    VITE_APPSYNC_URL="$APPSYNC_URL" \
    VITE_APPSYNC_API_KEY="$APPSYNC_KEY" \
    VITE_AWS_REGION="$REGION" \
        npm run build
    popd >/dev/null

    DASHBOARD_BUCKET="factorymind-dashboard-${ACCOUNT}-${REGION}"
    aws s3api head-bucket --bucket "$DASHBOARD_BUCKET" --region "$REGION" 2>/dev/null \
        || aws s3 mb "s3://$DASHBOARD_BUCKET" --region "$REGION"
    aws s3 sync dashboard/dist "s3://$DASHBOARD_BUCKET" --delete --region "$REGION"

    echo "  Dashboard URL: http://$DASHBOARD_BUCKET.s3-website-$REGION.amazonaws.com"
  else
    echo "  Skipping — dashboard/ not found."
  fi
else
  echo "[8/8] Skipping dashboard (--skip-dashboard)"
fi

echo
echo "=== Deploy complete ==="
echo "Tail Lambda logs:        aws logs tail /aws/lambda/factorymind-brain-agent --follow --region $REGION"
echo "Run simulator:           PYTHONPATH=. python3 scripts/simulate_aerospace_cnc.py --mode catastrophic --duration 60 --publish --endpoint <iot-endpoint>"
echo "CloudWatch dashboard:    https://$REGION.console.aws.amazon.com/cloudwatch/home?region=$REGION#dashboards:name=FactoryMind-Operations"
