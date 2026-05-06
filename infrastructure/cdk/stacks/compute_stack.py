"""Compute Stack — Lambda functions and layers for all FactoryMind agents.

Provisions:
  - Shared Python dependency layer (pydantic, structlog, aws-lambda-powertools, redis, langgraph)
  - ONNX Runtime layer for Edge AI inference
  - Lambda functions for each Manager + Brain Agent (7 functions total)
  - IAM roles with least-privilege permissions per agent
  - Event source mappings: Kinesis → IoT Ingestion, EventBridge rules → Brain
  - Lambda invoke permission for IoT Core → Edge AI

Stack consumers:
  - Reads existing DynamoDB tables, S3 buckets, Kinesis stream, EventBridge bus,
    SQS queue, and SNS topics by name (provisioned in StorageStack + IoTStack).
"""

from pathlib import Path

from aws_cdk import (
    Duration,
    Stack,
    aws_dynamodb as dynamodb,
    aws_ec2 as ec2,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_kinesis as kinesis,
    aws_lambda as _lambda,
    aws_lambda_event_sources as lambda_events,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_sns as sns,
    aws_sqs as sqs,
)
from constructs import Construct


# Repo root relative to this file: infrastructure/cdk/stacks/ → ../../..
REPO_ROOT = Path(__file__).resolve().parents[3]
AGENTS_DIR = REPO_ROOT / "agents"
LAYERS_DIR = REPO_ROOT / "infrastructure" / "layers"


class ComputeStack(Stack):
    """Lambda functions, layers, IAM roles, and event source mappings."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ---------------------------------------------------------------
        # Shared Lambda layer — Python dependencies (pydantic, structlog, etc.)
        # ---------------------------------------------------------------
        # Layer source must be packaged at infrastructure/layers/python_deps/
        # with python/ subdirectory containing pip-installed packages.
        # See scripts/build_layers.sh.

        deps_layer_path = LAYERS_DIR / "python_deps"
        if deps_layer_path.exists():
            self.deps_layer = _lambda.LayerVersion(
                self,
                "PythonDepsLayer",
                code=_lambda.Code.from_asset(str(deps_layer_path)),
                compatible_runtimes=[_lambda.Runtime.PYTHON_3_11],
                description="Shared Python dependencies for FactoryMind agents",
                layer_version_name="factorymind-python-deps",
            )
            common_layers = [self.deps_layer]
        else:
            # Layer not yet built — Lambdas will need bundling instead.
            # Operators must run scripts/build_layers.sh before cdk deploy.
            self.deps_layer = None
            common_layers = []

        # ONNX Runtime layer for Edge AI
        onnx_layer_path = LAYERS_DIR / "onnx_runtime"
        if onnx_layer_path.exists():
            self.onnx_layer = _lambda.LayerVersion(
                self,
                "OnnxRuntimeLayer",
                code=_lambda.Code.from_asset(str(onnx_layer_path)),
                compatible_runtimes=[_lambda.Runtime.PYTHON_3_11],
                description="ONNX Runtime for Edge AI sub-10ms inference",
                layer_version_name="factorymind-onnx-runtime",
            )
        else:
            self.onnx_layer = None

        # ---------------------------------------------------------------
        # VPC + security group for ElastiCache access
        # ---------------------------------------------------------------
        # ElastiCache lives in the StorageStack VPC. Lambdas that touch Redis
        # (Edge AI, Digital Twin) must be attached to the same VPC private subnets.
        # The VPC is passed in as a cross-stack reference from app.py to avoid
        # synth-time lookups (which would require StorageStack to be already
        # deployed before this stack can synth).
        if vpc is None:
            raise ValueError("ComputeStack requires `vpc` (pass storage.vpc from app.py)")

        lambda_sg = ec2.SecurityGroup(
            self,
            "LambdaSG",
            vpc=vpc,
            description="Security group for FactoryMind Lambda functions in VPC",
            allow_all_outbound=True,
        )

        # ---------------------------------------------------------------
        # Resource references (read by name — deployed in other stacks)
        # ---------------------------------------------------------------

        sensor_stream = kinesis.Stream.from_stream_attributes(
            self,
            "SensorStreamRef",
            stream_arn=f"arn:aws:kinesis:{self.region}:{self.account}:stream/factorymind-sensor-stream",
        )

        event_bus = events.EventBus.from_event_bus_name(
            self,
            "FactoryMindBusRef",
            event_bus_name="factorymind-bus",
        )

        product_images_bucket = s3.Bucket.from_bucket_name(
            self,
            "ProductImagesBucketRef",
            bucket_name="factorymind-product-images",
        )

        workorder_queue = sqs.Queue.from_queue_arn(
            self,
            "WorkOrderQueueRef",
            queue_arn=f"arn:aws:sqs:{self.region}:{self.account}:factorymind-workorder-queue",
        )

        maintenance_alerts_topic = sns.Topic.from_topic_arn(
            self,
            "MaintenanceAlertsTopicRef",
            topic_arn=f"arn:aws:sns:{self.region}:{self.account}:factorymind-maintenance-alerts",
        )

        quality_alerts_topic = sns.Topic.from_topic_arn(
            self,
            "QualityAlertsTopicRef",
            topic_arn=f"arn:aws:sns:{self.region}:{self.account}:factorymind-quality-alerts",
        )

        # DynamoDB table references
        ddb_tables = {
            name: dynamodb.Table.from_table_name(self, f"{name}Ref", table_name=name)
            for name in (
                "FactoryMind_MachineState",
                "FactoryMind_MachineSpecs",
                "FactoryMind_QualityResults",
                "FactoryMind_QualityThresholds",
                "FactoryMind_Predictions",
                "FactoryMind_WorkOrders",
                "FactoryMind_EnergyBaselines",
                "FactoryMind_SustainabilityKPIs",
                "FactoryMind_TwinState",
                "FactoryMind_FloorLayout",
                "FactoryMind_EdgeThresholds",
                "FactoryMind_EdgeResults",
            )
        }

        # ---------------------------------------------------------------
        # Helper: build a Lambda function with common settings
        # ---------------------------------------------------------------

        def make_lambda(
            id_: str,
            function_name: str,
            handler_path: str,
            *,
            timeout_seconds: int = 30,
            memory_mb: int = 512,
            in_vpc: bool = False,
            extra_layers: list[_lambda.LayerVersion] | None = None,
            env: dict[str, str] | None = None,
        ) -> _lambda.Function:
            base_env = {
                "EVENT_BUS_NAME": "factorymind-bus",
                "PLANT_ID": "PLANT-001",
                "POWERTOOLS_SERVICE_NAME": function_name,
                "POWERTOOLS_METRICS_NAMESPACE": "FactoryMind",
                "LOG_LEVEL": "INFO",
            }
            if env:
                base_env.update(env)

            layers = list(common_layers)
            if extra_layers:
                layers.extend(extra_layers)

            return _lambda.Function(
                self,
                id_,
                function_name=function_name,
                runtime=_lambda.Runtime.PYTHON_3_11,
                handler=f"agents.{handler_path}",
                code=_lambda.Code.from_asset(
                    str(REPO_ROOT),
                    exclude=[
                        "/.git",
                        "/.venv",
                        "/venv",
                        "/node_modules",
                        "/dashboard",
                        "/infrastructure",
                        "/tests",
                        "/models",
                        "/docs",
                        "/scripts",
                        "/notebooks",
                        "/cdk-deploy.log",
                        "/deploy.log",
                        "/cdk-outputs.json",
                        "*.md",
                        "*.log",
                        "**/__pycache__",
                        "**/*.pyc",
                    ],
                ),
                timeout=Duration.seconds(timeout_seconds),
                memory_size=memory_mb,
                tracing=_lambda.Tracing.ACTIVE,
                environment=base_env,
                layers=layers,
                vpc=vpc if in_vpc else None,
                vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS) if in_vpc else None,
                security_groups=[lambda_sg] if in_vpc else None,
            )

        # ---------------------------------------------------------------
        # Lambda functions — one per Manager Agent + Brain Agent
        # ---------------------------------------------------------------

        # 1. IoT Ingestion Manager — Kinesis-triggered, batches up to 100
        self.iot_ingestion_fn = make_lambda(
            id_="IoTIngestionManager",
            function_name="factorymind-iot-ingestion-manager",
            handler_path="iot_ingestion.manager.handler.handler",
            timeout_seconds=30,
            memory_mb=512,
        )
        sensor_stream.grant_read(self.iot_ingestion_fn)
        event_bus.grant_put_events_to(self.iot_ingestion_fn)
        for tbl in (
            ddb_tables["FactoryMind_MachineState"],
            ddb_tables["FactoryMind_MachineSpecs"],
        ):
            tbl.grant_read_write_data(self.iot_ingestion_fn)
        # Timestream removed (workshop SCP block).
        # Kinesis event source mapping
        self.iot_ingestion_fn.add_event_source(
            lambda_events.KinesisEventSource(
                sensor_stream,
                batch_size=100,
                starting_position=_lambda.StartingPosition.LATEST,
                max_batching_window=Duration.seconds(2),
            )
        )

        # 2. Edge AI Manager — IoT Core rule triggered, fire-and-forget, in VPC for Redis
        edge_layers = [self.onnx_layer] if self.onnx_layer else []
        self.edge_ai_fn = make_lambda(
            id_="EdgeAIManager",
            function_name="factorymind-edge-ai-manager",
            handler_path="edge_ai.manager.handler.handler",
            timeout_seconds=3,
            memory_mb=1024,
            in_vpc=True,
            extra_layers=edge_layers,
            env={
                "REDIS_HOST": "factorymind-redis.cache.amazonaws.com",  # placeholder — overwritten by post-deploy
                "REDIS_PORT": "6379",
            },
        )
        event_bus.grant_put_events_to(self.edge_ai_fn)
        ddb_tables["FactoryMind_EdgeResults"].grant_write_data(self.edge_ai_fn)
        ddb_tables["FactoryMind_EdgeThresholds"].grant_read_data(self.edge_ai_fn)

        # IoT Core invoke permission — referenced by IoTStack rule
        self.edge_ai_fn.add_permission(
            "AllowIoTCoreInvoke",
            principal=iam.ServicePrincipal("iot.amazonaws.com"),
            action="lambda:InvokeFunction",
            source_arn=f"arn:aws:iot:{self.region}:{self.account}:rule/factorymind_telemetry_to_edge_ai",
        )

        # 3. Quality Vision Manager — S3 trigger
        self.quality_vision_fn = make_lambda(
            id_="QualityVisionManager",
            function_name="factorymind-quality-vision-manager",
            handler_path="quality_vision.manager.handler.handler",
            timeout_seconds=60,
            memory_mb=1024,
        )
        product_images_bucket.grant_read(self.quality_vision_fn)
        event_bus.grant_put_events_to(self.quality_vision_fn)
        quality_alerts_topic.grant_publish(self.quality_vision_fn)
        for tbl in (
            ddb_tables["FactoryMind_QualityResults"],
            ddb_tables["FactoryMind_QualityThresholds"],
        ):
            tbl.grant_read_write_data(self.quality_vision_fn)
        self.quality_vision_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    # DetectLabels for object/concept detection on product images.
                    # DetectCustomLabels is the upgrade path once a Custom Labels
                    # project is trained on real defect imagery.
                    "rekognition:DetectLabels",
                    "rekognition:DetectAnomalies",
                    "rekognition:DetectCustomLabels",
                ],
                resources=["*"],
            )
        )
        # S3 → Quality Vision trigger
        product_images_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.quality_vision_fn),
        )

        # 4. Predictive Maintenance Manager
        self.predictive_maintenance_fn = make_lambda(
            id_="PredictiveMaintenanceManager",
            function_name="factorymind-predictive-maintenance-manager",
            handler_path="predictive_maintenance.manager.handler.handler",
            timeout_seconds=60,
            memory_mb=1024,
        )
        event_bus.grant_put_events_to(self.predictive_maintenance_fn)
        workorder_queue.grant_send_messages(self.predictive_maintenance_fn)
        maintenance_alerts_topic.grant_publish(self.predictive_maintenance_fn)
        for tbl in (
            ddb_tables["FactoryMind_Predictions"],
            ddb_tables["FactoryMind_WorkOrders"],
            ddb_tables["FactoryMind_MachineSpecs"],
            ddb_tables["FactoryMind_MachineState"],
        ):
            tbl.grant_read_write_data(self.predictive_maintenance_fn)
        self.predictive_maintenance_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "sagemaker:InvokeEndpoint",
                    "lookoutequipment:DescribeModel",
                    "lookoutequipment:DescribeInferenceScheduler",
                    "lookoutequipment:ListInferenceExecutions",
                ],
                resources=["*"],
            )
        )

        # 5. Sustainability Manager
        self.sustainability_fn = make_lambda(
            id_="SustainabilityManager",
            function_name="factorymind-sustainability-manager",
            handler_path="sustainability.manager.handler.handler",
            timeout_seconds=60,
            memory_mb=1024,
        )
        event_bus.grant_put_events_to(self.sustainability_fn)
        for tbl in (
            ddb_tables["FactoryMind_EnergyBaselines"],
            ddb_tables["FactoryMind_SustainabilityKPIs"],
            ddb_tables["FactoryMind_MachineState"],
        ):
            tbl.grant_read_write_data(self.sustainability_fn)
        self.sustainability_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate",
                    "ses:SendEmail",
                    "ses:SendRawEmail",
                ],
                resources=["*"],
            )
        )

        # 6. Digital Twin Manager — in VPC for Redis
        self.digital_twin_fn = make_lambda(
            id_="DigitalTwinManager",
            function_name="factorymind-digital-twin-manager",
            handler_path="digital_twin.manager.handler.handler",
            timeout_seconds=10,
            memory_mb=1024,
            in_vpc=True,
            env={
                "REDIS_HOST": "factorymind-redis.cache.amazonaws.com",  # overwritten post-deploy
                "REDIS_PORT": "6379",
            },
        )
        event_bus.grant_put_events_to(self.digital_twin_fn)
        for tbl in (
            ddb_tables["FactoryMind_TwinState"],
            ddb_tables["FactoryMind_FloorLayout"],
            ddb_tables["FactoryMind_MachineState"],
        ):
            tbl.grant_read_write_data(self.digital_twin_fn)
        self.digital_twin_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "iottwinmaker:GetEntity",
                    "iottwinmaker:UpdateEntity",
                    "iottwinmaker:GetPropertyValue",
                    "appsync:GraphQL",
                    "s3:PutObject",
                ],
                resources=["*"],
            )
        )

        # 7. Brain Agent — invokes other managers
        self.brain_fn = make_lambda(
            id_="BrainAgent",
            function_name="factorymind-brain-agent",
            handler_path="brain.handler.handler",
            timeout_seconds=30,
            memory_mb=1024,
        )
        event_bus.grant_put_events_to(self.brain_fn)
        ddb_tables["FactoryMind_MachineState"].grant_read_data(self.brain_fn)
        # Brain needs to invoke all other manager lambdas
        for mgr_fn in (
            self.iot_ingestion_fn,
            self.quality_vision_fn,
            self.predictive_maintenance_fn,
            self.sustainability_fn,
            self.digital_twin_fn,
        ):
            mgr_fn.grant_invoke(self.brain_fn)

        # ---------------------------------------------------------------
        # EventBridge → Brain Agent rule
        # ---------------------------------------------------------------
        # Route all anomaly + escalation events to the Brain Agent.

        events.Rule(
            self,
            "AnomalyToBrainRule",
            event_bus=event_bus,
            rule_name="factorymind-anomaly-to-brain",
            description="Route IoT anomalies and Edge AI escalations to Brain Agent",
            event_pattern=events.EventPattern(
                source=["factorymind.iot.anomaly", "factorymind.edge.escalation"],
            ),
            targets=[targets.LambdaFunction(self.brain_fn)],
        )

        # ---------------------------------------------------------------
        # EventBridge → Digital Twin Manager rule (BrainDecision events)
        # ---------------------------------------------------------------

        events.Rule(
            self,
            "BrainDecisionToTwinRule",
            event_bus=event_bus,
            rule_name="factorymind-brain-to-twin",
            description="Route BrainDecision events to Digital Twin Manager",
            event_pattern=events.EventPattern(
                source=["factorymind.brain.decision"],
            ),
            targets=[targets.LambdaFunction(self.digital_twin_fn)],
        )
