#!/usr/bin/env python3
"""FactoryMind CDK Application entry point.

Deploys the full FactoryMind multi-agent manufacturing intelligence platform
infrastructure to AWS (ap-south-1, Chennai plant).

Stack dependency order:
  1. Storage (DynamoDB, S3, Timestream, ElastiCache Redis)
  2. IoT (IoT Core rules, Kinesis streams, Firehose, EventBridge)
  3. Compute (Lambda functions for all agents, ONNX layer)
  4. ML (SageMaker endpoints, Lookout, AppSync, TwinMaker)
  5. Monitoring (CloudWatch dashboards, alarms, X-Ray)
"""

import os

import aws_cdk as cdk

from stacks.compute_stack import ComputeStack
from stacks.frontend_stack import FrontendStack
from stacks.iot_stack import IoTStack
from stacks.ml_stack import MLStack
from stacks.monitoring_stack import MonitoringStack
from stacks.storage_stack import StorageStack

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account") or os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=app.node.try_get_context("region") or os.environ.get("CDK_DEFAULT_REGION") or "ap-south-1",
)

# Stack 1: Storage — all data stores must exist before other stacks
storage = StorageStack(app, "FactoryMindStorage", env=env)

# Stack 2: IoT — ingestion pipeline depends on storage targets
iot = IoTStack(app, "FactoryMindIoT", env=env)
iot.add_dependency(storage)

# Stack 3: Compute — Lambda functions need storage and IoT event sources
compute = ComputeStack(app, "FactoryMindCompute", env=env, vpc=storage.vpc)
compute.add_dependency(storage)
compute.add_dependency(iot)

# Stack 4: ML — SageMaker, AppSync, TwinMaker depend on storage and compute
ml = MLStack(app, "FactoryMindML", env=env)
ml.add_dependency(storage)
ml.add_dependency(compute)

# Stack 5: Monitoring — observability layer over all other stacks
monitoring = MonitoringStack(app, "FactoryMindMonitoring", env=env)
monitoring.add_dependency(compute)
monitoring.add_dependency(ml)

# Stack 6: Frontend — S3 + CloudFront for the React dashboard.
# Independent of every other stack: the dashboard reads from AppSync (provisioned
# in MLStack) at runtime via env vars baked into the build, but CDK doesn't need
# a hard dependency for that.
frontend = FrontendStack(app, "FactoryMindFrontend", env=env)
frontend.add_dependency(ml)

app.synth()
