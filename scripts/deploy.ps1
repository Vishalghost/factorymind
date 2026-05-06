<#
.SYNOPSIS
    FactoryMind end-to-end deploy script (PowerShell / Windows).

.DESCRIPTION
    Mirrors scripts/deploy.sh for Windows users.
    Steps: tooling check → tests → build layers → CDK bootstrap → CDK deploy
    → patch Redis endpoint → seed data → build & upload dashboard.

.PARAMETER Region
    AWS region. Default: ap-south-1.

.PARAMETER SkipTests
    Skip pytest run.

.PARAMETER SkipDashboard
    Skip React dashboard build & upload.

.PARAMETER SkipLayers
    Skip Lambda layer rebuild.

.PARAMETER SkipSeed
    Skip DynamoDB seed.

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

# Step 1 — tooling
Write-Host "[1/8] Checking tooling..."
$tools = @("python", "node", "npm", "aws", "cdk")
foreach ($cmd in $tools) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Error "Missing required tool: $cmd"
        exit 1
    }
}
$Account = (aws sts get-caller-identity --query Account --output text)
Write-Host "  AWS account: $Account"
Write-Host "  CDK version: $(cdk --version)"
Write-Host ""

# Step 2 — tests
if (-not $SkipTests) {
    Write-Host "[2/8] Running unit tests..."
    $env:PYTHONPATH = "."
    python -m pytest tests/unit/ -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host ""
} else {
    Write-Host "[2/8] Skipping tests (-SkipTests)"
}

# Step 3 — Lambda layers
if (-not $SkipLayers) {
    Write-Host "[3/8] Building shared Lambda layer..."
    bash scripts/build_layers.sh
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host ""
} else {
    Write-Host "[3/8] Skipping layer build (-SkipLayers)"
}

# Step 4 — CDK bootstrap
Write-Host "[4/8] CDK bootstrap..."
Push-Location infrastructure/cdk
cdk bootstrap "aws://$Account/$Region"
Pop-Location
Write-Host ""

# Step 5 — CDK deploy
Write-Host "[5/8] CDK deploy..."
Push-Location infrastructure/cdk
cdk deploy `
    FactoryMindStorage `
    FactoryMindIoT `
    FactoryMindCompute `
    FactoryMindML `
    FactoryMindMonitoring `
    --require-approval never `
    --context region=$Region
if ($LASTEXITCODE -ne 0) { Pop-Location; exit $LASTEXITCODE }
Pop-Location
Write-Host ""

# Step 6 — patch Redis endpoint
Write-Host "[6/8] Patching Lambda env vars with Redis endpoint..."
$RedisHost = aws elasticache describe-cache-clusters `
    --cache-cluster-id factorymind-redis `
    --show-cache-node-info `
    --region $Region `
    --query 'CacheClusters[0].CacheNodes[0].Endpoint.Address' `
    --output text 2>$null

if ($RedisHost -and $RedisHost -ne "None") {
    foreach ($fn in @("factorymind-edge-ai-manager", "factorymind-digital-twin-manager")) {
        $envVars = "Variables={EVENT_BUS_NAME=factorymind-bus,PLANT_ID=PLANT-001,REDIS_HOST=$RedisHost,REDIS_PORT=6379,POWERTOOLS_SERVICE_NAME=$fn,POWERTOOLS_METRICS_NAMESPACE=FactoryMind,LOG_LEVEL=INFO}"
        aws lambda update-function-configuration `
            --function-name $fn `
            --environment $envVars `
            --region $Region | Out-Null
        Write-Host "  Patched $fn -> REDIS_HOST=$RedisHost"
    }
} else {
    Write-Warning "  Could not resolve Redis endpoint; Lambdas will use placeholder."
}
Write-Host ""

# Step 7 — seed
if (-not $SkipSeed) {
    Write-Host "[7/8] Seeding DynamoDB reference data..."
    $env:PYTHONPATH = "."
    python scripts/seed_dummy_data.py --region $Region
    Write-Host ""
} else {
    Write-Host "[7/8] Skipping seed (-SkipSeed)"
}

# Step 8 — dashboard
if (-not $SkipDashboard) {
    Write-Host "[8/8] Building and uploading React dashboard..."
    if ((Test-Path "dashboard") -and (Test-Path "dashboard/package.json")) {
        $AppsyncUrl = aws cloudformation describe-stacks `
            --stack-name FactoryMindML `
            --region $Region `
            --query "Stacks[0].Outputs[?OutputKey=='AppSyncEndpoint'].OutputValue" `
            --output text
        $AppsyncKey = aws cloudformation describe-stacks `
            --stack-name FactoryMindML `
            --region $Region `
            --query "Stacks[0].Outputs[?OutputKey=='AppSyncApiKey'].OutputValue" `
            --output text

        Push-Location dashboard
        npm install
        $env:VITE_APPSYNC_URL = $AppsyncUrl
        $env:VITE_APPSYNC_API_KEY = $AppsyncKey
        $env:VITE_AWS_REGION = $Region
        npm run build
        Pop-Location

        $DashboardBucket = "factorymind-dashboard-$Account-$Region"
        aws s3api head-bucket --bucket $DashboardBucket --region $Region 2>$null
        if ($LASTEXITCODE -ne 0) {
            aws s3 mb "s3://$DashboardBucket" --region $Region
        }
        aws s3 sync dashboard/dist "s3://$DashboardBucket" --delete --region $Region

        Write-Host "  Dashboard URL: http://$DashboardBucket.s3-website-$Region.amazonaws.com"
    } else {
        Write-Host "  Skipping - dashboard/ not found."
    }
} else {
    Write-Host "[8/8] Skipping dashboard (-SkipDashboard)"
}

Write-Host ""
Write-Host "=== Deploy complete ===" -ForegroundColor Green
Write-Host "Tail Lambda logs:     aws logs tail /aws/lambda/factorymind-brain-agent --follow --region $Region"
Write-Host "CloudWatch dashboard: https://$Region.console.aws.amazon.com/cloudwatch/home?region=$Region#dashboards:name=FactoryMind-Operations"
