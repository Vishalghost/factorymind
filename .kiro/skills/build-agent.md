---
inclusion: manual
---

# Skill: Build a FactoryMind Agent

## When to Use
Use this skill when creating a new Manager Agent or Worker Agent for the FactoryMind platform.

## Agent Structure Template

Every agent follows this pattern:

### Manager Agent (`agents/{agent-name}/manager/handler.py`)

```python
"""
{Agent Name} Manager Agent
Manages {N} worker agents for {domain description}.
"""
import uuid
import json
import time
import structlog
import boto3
from pydantic import BaseModel
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger(service="{agent-name}-manager")
tracer = Tracer(service="{agent-name}-manager")
metrics = Metrics(namespace="FactoryMind", service="{agent-name}-manager")

# Initialize AWS clients
dynamodb = boto3.resource("dynamodb")
eventbridge = boto3.client("events")
lambda_client = boto3.client("lambda")


class ManagerInput(BaseModel):
    """Input schema — define fields from the agent spec."""
    request_id: str
    plant_id: str
    machine_id: str
    timestamp: str


class ManagerOutput(BaseModel):
    """Output schema — define fields from the agent spec."""
    report_id: str
    plant_id: str
    timestamp: str
    processing_time_ms: int


@tracer.capture_lambda_handler
@logger.inject_lambda_context
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context) -> dict:
    start_time = time.time()
    request = ManagerInput(**event)
    
    # 1. Delegate to workers
    # 2. Aggregate results
    # 3. Write to DynamoDB
    # 4. Publish to EventBridge if needed
    # 5. Emit metrics
    
    processing_time_ms = int((time.time() - start_time) * 1000)
    metrics.add_metric(name="ProcessingTime", unit=MetricUnit.Milliseconds, value=processing_time_ms)
    
    return ManagerOutput(
        report_id=f"PREFIX-{uuid.uuid4().hex[:8]}",
        plant_id=request.plant_id,
        timestamp=request.timestamp,
        processing_time_ms=processing_time_ms,
    ).model_dump()


def invoke_worker(function_name: str, payload: dict) -> dict:
    """Invoke a worker Lambda and return parsed response."""
    response = lambda_client.invoke(
        FunctionName=f"factorymind-{function_name}",
        InvocationType="RequestResponse",
        Payload=json.dumps(payload),
    )
    return json.loads(response["Payload"].read())
```

### Worker Agent (`agents/{agent-name}/workers/{worker_name}.py`)

```python
"""
{Worker Name} Worker
{One-line description of what this worker does.}
"""
import structlog
import boto3
from pydantic import BaseModel
from aws_lambda_powertools import Logger, Tracer

logger = Logger(service="{worker-name}")
tracer = Tracer(service="{worker-name}")


class WorkerInput(BaseModel):
    """Input from Manager."""
    pass


class WorkerOutput(BaseModel):
    """Output back to Manager."""
    status: str  # "SUCCESS" | "ERROR"
    summary: str


@tracer.capture_lambda_handler
@logger.inject_lambda_context
def handler(event: dict, context) -> dict:
    request = WorkerInput(**event)
    
    # Worker-specific logic here
    
    return WorkerOutput(
        status="SUCCESS",
        summary="Completed successfully",
    ).model_dump()
```

## Checklist for New Agents

1. [ ] Define Pydantic input/output models matching the agent spec
2. [ ] Implement handler with aws-lambda-powertools decorators
3. [ ] Add structured logging with structlog
4. [ ] Add CloudWatch metrics emission
5. [ ] Add X-Ray tracing spans for each AWS call
6. [ ] Implement retry logic (once, then escalate)
7. [ ] Write unit tests with mocked boto3 clients
8. [ ] Add SAM/CDK template for Lambda deployment
9. [ ] Register EventBridge rules if agent publishes/subscribes events
10. [ ] Update DynamoDB table definitions if new tables needed

## Error Handling Pattern

```python
from botocore.exceptions import ClientError

def safe_invoke(func, *args, max_retries=1, **kwargs):
    """Retry once, then raise for manager to handle."""
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            if attempt == max_retries:
                logger.error("Operation failed after retry", error=str(e))
                raise
            logger.warning("Retrying operation", attempt=attempt + 1)
            time.sleep(2 ** attempt)  # Exponential backoff
```

## EventBridge Event Pattern

```python
def publish_event(source: str, detail_type: str, detail: dict):
    """Publish event to EventBridge."""
    eventbridge.put_events(
        Entries=[{
            "Source": f"factorymind.{source}",
            "DetailType": detail_type,
            "Detail": json.dumps(detail),
            "EventBusName": "factorymind-bus",
        }]
    )
```
