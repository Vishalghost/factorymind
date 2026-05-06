---
inclusion: manual
---

# Skill: Build a FactoryMind CDK Stack

## When to Use
Use this skill when creating or modifying AWS infrastructure for FactoryMind using CDK (Python).

## CDK Stack Template

```python
"""
{Stack Name} Stack
Provisions {description of resources} for FactoryMind.
"""
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_lambda as _lambda,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_logs as logs,
)
from constructs import Construct


class FactoryMindExampleStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # DynamoDB Table
        table = dynamodb.Table(
            self, "ExampleTable",
            table_name="FactoryMind_Example",
            partition_key=dynamodb.Attribute(
                name="id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
            point_in_time_recovery=True,
        )

        # Lambda Function (Agent)
        agent_fn = _lambda.Function(
            self, "AgentFunction",
            function_name="factorymind-example-agent",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=_lambda.Code.from_asset("agents/example/manager"),
            memory_size=512,
            timeout=Duration.seconds(30),
            tracing=_lambda.Tracing.ACTIVE,
            log_retention=logs.RetentionDays.TWO_WEEKS,
            environment={
                "TABLE_NAME": table.table_name,
                "POWERTOOLS_SERVICE_NAME": "example-manager",
                "POWERTOOLS_METRICS_NAMESPACE": "FactoryMind",
            },
        )

        # Grant permissions
        table.grant_read_write_data(agent_fn)

        # EventBridge Rule
        rule = events.Rule(
            self, "ExampleRule",
            event_bus=events.EventBus.from_event_bus_name(
                self, "Bus", "factorymind-bus"
            ),
            event_pattern=events.EventPattern(
                source=["factorymind.brain"],
                detail_type=["ExampleRequest"],
            ),
        )
        rule.add_target(targets.LambdaFunction(agent_fn))
```

## Common Patterns

### Lambda with Layers (Edge AI)
```python
onnx_layer = _lambda.LayerVersion(
    self, "OnnxLayer",
    code=_lambda.Code.from_asset("layers/onnx-runtime"),
    compatible_runtimes=[_lambda.Runtime.PYTHON_3_11],
    description="ONNX Runtime for edge inference",
)

edge_fn = _lambda.Function(
    self, "EdgeAI",
    function_name="factorymind-edge-ai-manager",
    memory_size=1024,
    timeout=Duration.seconds(3),
    layers=[onnx_layer],
    # ...
)
```

### Kinesis Stream + Lambda Trigger
```python
from aws_cdk import aws_kinesis as kinesis, aws_lambda_event_sources as sources

stream = kinesis.Stream(
    self, "SensorStream",
    stream_name="factorymind-sensor-stream",
    shard_count=2,
)

iot_fn.add_event_source(sources.KinesisEventSource(
    stream,
    starting_position=_lambda.StartingPosition.LATEST,
    batch_size=100,
    max_batching_window=Duration.seconds(5),
))
```

### SageMaker Endpoint Invocation Permission
```python
agent_fn.add_to_role_policy(iam.PolicyStatement(
    actions=["sagemaker:InvokeEndpoint"],
    resources=[f"arn:aws:sagemaker:{self.region}:{self.account}:endpoint/factorymind-*"],
))
```

## Stack Organization

| Stack | Resources |
|-------|-----------|
| iot_stack.py | IoT Core rules, Kinesis streams, Firehose |
| compute_stack.py | All Lambda functions, layers, event sources |
| storage_stack.py | DynamoDB tables, S3 buckets, ElastiCache |
| ml_stack.py | SageMaker endpoints, Lookout models |
| monitoring_stack.py | CloudWatch dashboards, alarms, X-Ray groups |

## Checklist

1. [ ] Use `factorymind-` prefix for all resource names
2. [ ] Enable X-Ray tracing on all Lambda functions
3. [ ] Set log retention to 2 weeks (cost control)
4. [ ] Use PAY_PER_REQUEST billing for DynamoDB
5. [ ] Enable point-in-time recovery on all tables
6. [ ] Grant least-privilege IAM permissions
7. [ ] Add CloudWatch alarms for error rates > 1%
8. [ ] Tag all resources with `project: factorymind`
