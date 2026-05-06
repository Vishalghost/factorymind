---
inclusion: manual
---

# Skill: Deploy a FactoryMind Agent

## When to Use
Use this skill when deploying a FactoryMind agent to AWS (Lambda, SAM, or CDK).

## Deployment Options

### Option 1: AWS SAM (Single Agent)

```yaml
# template.yaml for individual agent deployment
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: FactoryMind {Agent Name} Agent

Globals:
  Function:
    Runtime: python3.11
    Timeout: 30
    MemorySize: 512
    Tracing: Active
    Environment:
      Variables:
        POWERTOOLS_SERVICE_NAME: !Sub "${AgentName}"
        POWERTOOLS_METRICS_NAMESPACE: FactoryMind
        LOG_LEVEL: INFO

Parameters:
  AgentName:
    Type: String
    Default: edge-ai-manager
  Environment:
    Type: String
    AllowedValues: [dev, staging, prod]
    Default: dev

Resources:
  ManagerFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: !Sub "factorymind-${AgentName}"
      Handler: handler.handler
      CodeUri: manager/
      Policies:
        - DynamoDBCrudPolicy:
            TableName: !Ref StateTable
        - EventBridgePutEventsPolicy:
            EventBusName: factorymind-bus
      Events:
        EventBridgeTrigger:
          Type: EventBridgeRule
          Properties:
            EventBusName: factorymind-bus
            Pattern:
              source:
                - factorymind.brain
              detail-type:
                - !Sub "${AgentName}-request"

  WorkerFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: !Sub "factorymind-${AgentName}-worker"
      Handler: handler.handler
      CodeUri: workers/
      Policies:
        - DynamoDBCrudPolicy:
            TableName: !Ref StateTable
```

### Option 2: CDK (Full Stack)

```bash
# Deploy all stacks
cd infrastructure/cdk
cdk synth
cdk deploy --all --require-approval never

# Deploy single stack
cdk deploy FactoryMindComputeStack
```

### Option 3: Docker + ECR (for larger agents)

```dockerfile
FROM public.ecr.aws/lambda/python:3.11

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY agents/{agent-name}/ ${LAMBDA_TASK_ROOT}/

CMD ["manager.handler.handler"]
```

## Deployment Checklist

### Pre-Deployment
1. [ ] All unit tests pass: `pytest tests/unit/ -v`
2. [ ] Pydantic models validate against agent spec I/O format
3. [ ] Environment variables documented in template
4. [ ] IAM permissions follow least-privilege
5. [ ] CloudWatch log group configured with retention

### Deployment Steps
```bash
# 1. Run tests
pytest tests/unit/ -v --tb=short

# 2. Build
sam build --template agents/{agent-name}/template.yaml

# 3. Deploy to dev
sam deploy \
  --stack-name factorymind-{agent-name}-dev \
  --parameter-overrides Environment=dev \
  --capabilities CAPABILITY_IAM \
  --no-confirm-changeset

# 4. Smoke test
aws lambda invoke \
  --function-name factorymind-{agent-name} \
  --payload file://tests/fixtures/sample_event.json \
  output.json

cat output.json | python -m json.tool
```

### Post-Deployment
1. [ ] Verify CloudWatch logs show successful cold start
2. [ ] Verify X-Ray traces appear in console
3. [ ] Verify EventBridge rule is active
4. [ ] Run integration test against deployed function
5. [ ] Check CloudWatch metrics dashboard

## Environment Configuration

```bash
# Dev environment
export ENVIRONMENT=dev
export EVENT_BUS_NAME=factorymind-bus-dev
export TABLE_PREFIX=FactoryMind_Dev_

# Staging
export ENVIRONMENT=staging
export EVENT_BUS_NAME=factorymind-bus-staging
export TABLE_PREFIX=FactoryMind_Staging_

# Production
export ENVIRONMENT=prod
export EVENT_BUS_NAME=factorymind-bus
export TABLE_PREFIX=FactoryMind_
```

## Rollback Procedure

```bash
# SAM rollback
aws cloudformation rollback-stack --stack-name factorymind-{agent-name}-prod

# Lambda version rollback (if using aliases)
aws lambda update-alias \
  --function-name factorymind-{agent-name} \
  --name prod \
  --function-version {previous-version}
```

## Monitoring After Deploy

```bash
# Tail logs
aws logs tail /aws/lambda/factorymind-{agent-name} --follow

# Check error rate
aws cloudwatch get-metric-statistics \
  --namespace FactoryMind \
  --metric-name Errors \
  --dimensions Name=service,Value={agent-name} \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Sum
```
