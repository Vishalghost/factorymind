#!/usr/bin/env bash
# Build the new dashboard with live env vars (AppSync + AgentCore gateway),
# upload to the existing S3 bucket, and invalidate CloudFront.
#
# Reads:
#   - infrastructure/cdk outputs (AppSync URL, API key, dashboard bucket,
#     CloudFront distribution id) via CloudFormation describe-stacks
#   - agentcore-outputs.json (assistantGatewayUrl) if present
#
# Usage:
#   ./scripts/deploy_dashboard.sh
#   ./scripts/deploy_dashboard.sh --region us-east-1

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --region) REGION="$2"; shift 2 ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== FactoryMind Dashboard Deploy ==="
echo "  Region: $REGION"

# 1. Resolve outputs from existing stacks.
APPSYNC_URL="$(aws cloudformation describe-stacks \
  --stack-name FactoryMindML --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='AppSyncEndpoint'].OutputValue" \
  --output text)"
APPSYNC_KEY="$(aws cloudformation describe-stacks \
  --stack-name FactoryMindML --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='AppSyncApiKey'].OutputValue" \
  --output text)"
DASHBOARD_BUCKET="$(aws cloudformation describe-stacks \
  --stack-name FactoryMindFrontend --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='DashboardBucketName'].OutputValue" \
  --output text)"
DISTRIBUTION_ID="$(aws cloudformation describe-stacks \
  --stack-name FactoryMindFrontend --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDistributionId'].OutputValue" \
  --output text)"
DASHBOARD_URL="$(aws cloudformation describe-stacks \
  --stack-name FactoryMindFrontend --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='DashboardURL'].OutputValue" \
  --output text)"

ASSISTANT_GATEWAY_URL=""
if [[ -f agentcore-outputs.json ]]; then
  ASSISTANT_GATEWAY_URL="$(python -c "import json; print(json.load(open('agentcore-outputs.json')).get('assistantGatewayUrl',''))")"
fi

echo "  AppSync URL: $APPSYNC_URL"
echo "  Bucket:      $DASHBOARD_BUCKET"
echo "  Dist ID:     $DISTRIBUTION_ID"
echo "  Assistant:   ${ASSISTANT_GATEWAY_URL:-(none — preview mode)}"
echo

# 2. Build dashboard with VITE_* env injected.
cd dashboard
[[ -d node_modules ]] || npm install --no-audit --no-fund --loglevel=warn

VITE_APPSYNC_URL="$APPSYNC_URL" \
VITE_APPSYNC_API_KEY="$APPSYNC_KEY" \
VITE_AWS_REGION="$REGION" \
VITE_ASSISTANT_GATEWAY_URL="$ASSISTANT_GATEWAY_URL" \
  npx vite build

cd "$REPO_ROOT"

# 3. Upload + invalidate.
echo "[*] Sync dist/ -> s3://$DASHBOARD_BUCKET"
aws s3 sync dashboard/dist/ "s3://$DASHBOARD_BUCKET/" --region "$REGION" --delete

echo "[*] Invalidate CloudFront $DISTRIBUTION_ID"
INV_ID="$(aws cloudfront create-invalidation \
  --distribution-id "$DISTRIBUTION_ID" \
  --paths "/*" \
  --query "Invalidation.Id" \
  --output text)"
echo "    Invalidation: $INV_ID"

echo
echo "Done. Dashboard: $DASHBOARD_URL"
