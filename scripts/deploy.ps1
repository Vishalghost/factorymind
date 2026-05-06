<#
.SYNOPSIS
    FactoryMind end-to-end deploy script (PowerShell / Windows).

.DESCRIPTION
    Mirrors scripts/deploy.sh for Windows users.
    Steps: tooling check -> tests -> build layers -> CDK bootstrap -> CDK deploy
    -> patch Redis endpoint -> seed data -> build dashboard + CloudFront upload.

.PARAMETER Region
    AWS region. Default: ap-south-1.

.EXAMPLE
    .\scripts\deploy.ps1
    .\scripts\deploy.ps1 -SkipTests -Region us-east-1
#>

param(
    [string]$Region = "ap-south-1",
    [switch]$SkipTests,
    [switch]$SkipDashboard,
    [switch]$SkipLayers,
    [switch]$SkipSeed
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

Write-Host "=== FactoryMind Deploy ===" -ForegroundColor Cyan
Write-Host "  Region: $Region"
Write-Host "  Repo:   $RepoRoot"
Write-Host ""

# Step 1 - tooling
Write-Host "[1/8] Checking tooling..."
foreach ($cmd in @("python", "node", "npm", "aws", "cdk")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Error "Missing required tool: $cmd"; exit 1
    }
}
$Account = (aws sts get-caller-identity --query Account --output text)
Write-Host "  AWS account: $Account"
Write-Host "  CDK version: $(cdk --version)"
Write-Host ""

# Step 2 - tests
if (-not $SkipTests) {
    Write-Host "[2/8] Running unit tests..."
    $env:PYTHONPATH = "."
    python -m pytest tests/unit/ -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host ""
} else { Write-Host "[2/8] Skipping tests (-SkipTests)" }

# Step 3 - Lambda layers
if (-not $SkipLayers) {
    Write-Host "[3/8] Building shared Lambda layer..."
    bash scripts/build_layers.sh
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host ""
} else { Write-Host "[3/8] Skipping layer build (-SkipLayers)" }

# Step 4 - CDK bootstrap
Write-Host "[4/8] CDK bootstrap..."
Push-Location infrastructure/cdk
cdk bootstrap "aws://$Account/$Region"
Pop-Location
Write-Host ""

# Step 5 - CDK deploy
Write-Host "[5/8] CDK deploy (Storage -> IoT -> Compute -> ML -> Monitoring -> Frontend)..."
Push-Location infrastructure/cdk
cdk deploy `
    FactoryMindStorage `
    FactoryMindIoT `
    FactoryMindCompute `
    FactoryMindML `
    FactoryMindMonitoring `
    FactoryMindFrontend `
    --require-approval never `
    --context region=$Region
if ($LASTEXITCODE -ne 0) { Pop-Location; exit $LASTEXITCODE }
Pop-Location
Write-Host ""

# Step 6 - patch Redis endpoint (ElastiCache Serverless)
Write-Host "[6/8] Patching Lambda env vars with ElastiCache Serverless endpoint..."
$RedisHost = aws elasticache describe-serverless-caches `
    --serverless-cache-name factorymind-redis --region $Region `
    --query 'ServerlessCaches[0].Endpoint.Address' --output text 2>$null
$RedisPort = aws elasticache describe-serverless-caches `
    --serverless-cache-name factorymind-redis --region $Region `
    --query 'ServerlessCaches[0].Endpoint.Port' --output text 2>$null

if ($RedisHost -and $RedisHost -ne "None") {
    foreach ($fn in @("factorymind-edge-ai-manager", "factorymind-digital-twin-manager")) {
        $envVars = "Variables={EVENT_BUS_NAME=factorymind-bus,PLANT_ID=PLANT-001,REDIS_HOST=$RedisHost,REDIS_PORT=$RedisPort,REDIS_TLS=true,POWERTOOLS_SERVICE_NAME=$fn,POWERTOOLS_METRICS_NAMESPACE=FactoryMind,LOG_LEVEL=INFO}"
        aws lambda update-function-configuration --function-name $fn --environment $envVars --region $Region | Out-Null
        Write-Host "  Patched $fn -> REDIS_HOST=$($RedisHost):$($RedisPort) (TLS=true)"
    }
} else {
    Write-Warning "  Could not resolve ElastiCache Serverless endpoint; Lambdas will use placeholder."
}
Write-Host ""

# Step 7 - seed
if (-not $SkipSeed) {
    Write-Host "[7/8] Seeding DynamoDB reference data..."
    $env:PYTHONPATH = "."
    python scripts/seed_dummy_data.py --region $Region
    Write-Host ""
} else { Write-Host "[7/8] Skipping seed (-SkipSeed)" }

# Step 8 - dashboard build + CloudFront upload + invalidate
if (-not $SkipDashboard) {
    Write-Host "[8/8] Building dashboard, uploading to S3, invalidating CloudFront..."
    if ((Test-Path "dashboard") -and (Test-Path "dashboard/package.json")) {
        $AppsyncUrl = aws cloudformation describe-stacks --stack-name FactoryMindML --region $Region `
            --query "Stacks[0].Outputs[?OutputKey=='AppSyncEndpoint'].OutputValue" --output text
        $AppsyncKey = aws cloudformation describe-stacks --stack-name FactoryMindML --region $Region `
            --query "Stacks[0].Outputs[?OutputKey=='AppSyncApiKey'].OutputValue" --output text
        $Bucket = aws cloudformation describe-stacks --stack-name FactoryMindFrontend --region $Region `
            --query "Stacks[0].Outputs[?OutputKey=='DashboardBucketName'].OutputValue" --output text
        $DistId = aws cloudformation describe-stacks --stack-name FactoryMindFrontend --region $Region `
            --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDistributionId'].OutputValue" --output text
        $DashboardUrl = aws cloudformation describe-stacks --stack-name FactoryMindFrontend --region $Region `
            --query "Stacks[0].Outputs[?OutputKey=='DashboardURL'].OutputValue" --output text

        Push-Location dashboard
        npm install
        $env:VITE_APPSYNC_URL = $AppsyncUrl
        $env:VITE_APPSYNC_API_KEY = $AppsyncKey
        $env:VITE_AWS_REGION = $Region
        npm run build
        Pop-Location

        aws s3 sync dashboard/dist "s3://$Bucket" --delete --region $Region
        aws cloudfront create-invalidation --distribution-id $DistId --paths '/*' | Out-Null
        Write-Host "  Dashboard URL: $DashboardUrl" -ForegroundColor Green
    } else { Write-Host "  Skipping - dashboard/ not found." }
} else { Write-Host "[8/8] Skipping dashboard (-SkipDashboard)" }

Write-Host ""
Write-Host "=== Deploy complete ===" -ForegroundColor Green
Write-Host "Tail Lambda logs:     aws logs tail /aws/lambda/factorymind-brain-agent --follow --region $Region"
Write-Host "CloudWatch dashboard: https://$Region.console.aws.amazon.com/cloudwatch/home?region=$Region#dashboards:name=FactoryMind-Operations"
