"""ML Stack — SageMaker, Lookout for Equipment, AppSync, IoT TwinMaker.

Provisions:
  - SageMaker Serverless inference endpoints (configs only — model artifacts must
    be uploaded separately to S3 and referenced by the model name).
  - Lookout for Equipment dataset + model placeholder (the model itself must be
    trained from real or synthetic data; this stack creates the IAM role and
    dataset shape).
  - AppSync GraphQL API for real-time machine state subscriptions.
  - IoT TwinMaker workspace + scene bucket.

Notes:
  - SageMaker model artifacts (yolov8.tar.gz, lstm.tar.gz) must exist in
    s3://factorymind-ml-models/ before deploy. Run scripts/upload_models.sh first.
  - Lookout for Equipment has no L2 CDK constructs; we create the IAM role here
    and document the manual model creation steps in DEPLOYMENT.md.
  - AppSync schema lives at infrastructure/cdk/schema/factorymind.graphql.
"""

from pathlib import Path

from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
    aws_appsync as appsync,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_iottwinmaker as twinmaker,
    aws_s3 as s3,
    aws_sagemaker as sagemaker,
)
from constructs import Construct


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = REPO_ROOT / "infrastructure" / "cdk" / "schema"


class MLStack(Stack):
    """ML and real-time API infrastructure."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ---------------------------------------------------------------
        # S3 bucket for SageMaker model artifacts + TwinMaker scenes
        # ---------------------------------------------------------------

        self.ml_models_bucket = s3.Bucket(
            self,
            "MLModelsBucket",
            bucket_name="factorymind-ml-models",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        self.twinmaker_scenes_bucket = s3.Bucket(
            self,
            "TwinMakerScenesBucket",
            bucket_name="factorymind-twinmaker-scenes",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # ---------------------------------------------------------------
        # SageMaker IAM execution role
        # ---------------------------------------------------------------

        sagemaker_role = iam.Role(
            self,
            "SageMakerExecutionRole",
            role_name="factorymind-sagemaker-execution-role",
            assumed_by=iam.ServicePrincipal("sagemaker.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSageMakerFullAccess"),
            ],
        )
        self.ml_models_bucket.grant_read(sagemaker_role)

        # ---------------------------------------------------------------
        # SageMaker Models — placeholder definitions (YOLOv8 + LSTM)
        # ---------------------------------------------------------------
        # The actual model artifacts (model.tar.gz) must be uploaded to S3
        # before the SageMaker endpoints can serve traffic.

        self.yolov8_model = sagemaker.CfnModel(
            self,
            "YOLOv8Model",
            model_name="factorymind-yolov8-quality",
            execution_role_arn=sagemaker_role.role_arn,
            primary_container=sagemaker.CfnModel.ContainerDefinitionProperty(
                image=f"763104351884.dkr.ecr.{self.region}.amazonaws.com/pytorch-inference:2.1-cpu-py310",
                model_data_url=f"s3://{self.ml_models_bucket.bucket_name}/yolov8/model.tar.gz",
                environment={
                    "SAGEMAKER_PROGRAM": "inference.py",
                    "SAGEMAKER_REGION": self.region,
                },
            ),
        )

        self.lstm_model = sagemaker.CfnModel(
            self,
            "LSTMModel",
            model_name="factorymind-lstm-maintenance",
            execution_role_arn=sagemaker_role.role_arn,
            primary_container=sagemaker.CfnModel.ContainerDefinitionProperty(
                image=f"763104351884.dkr.ecr.{self.region}.amazonaws.com/pytorch-inference:2.1-cpu-py310",
                model_data_url=f"s3://{self.ml_models_bucket.bucket_name}/lstm/model.tar.gz",
                environment={
                    "SAGEMAKER_PROGRAM": "inference.py",
                    "SAGEMAKER_REGION": self.region,
                },
            ),
        )

        # ---------------------------------------------------------------
        # SageMaker Serverless Endpoint Configurations
        # ---------------------------------------------------------------

        self.yolov8_endpoint_config = sagemaker.CfnEndpointConfig(
            self,
            "YOLOv8EndpointConfig",
            endpoint_config_name="factorymind-yolov8-quality-config",
            production_variants=[
                sagemaker.CfnEndpointConfig.ProductionVariantProperty(
                    model_name=self.yolov8_model.model_name,
                    variant_name="primary",
                    serverless_config=sagemaker.CfnEndpointConfig.ServerlessConfigProperty(
                        memory_size_in_mb=4096,
                        max_concurrency=10,
                    ),
                ),
            ],
        )
        self.yolov8_endpoint_config.add_dependency(self.yolov8_model)

        self.lstm_endpoint_config = sagemaker.CfnEndpointConfig(
            self,
            "LSTMEndpointConfig",
            endpoint_config_name="factorymind-lstm-maintenance-config",
            production_variants=[
                sagemaker.CfnEndpointConfig.ProductionVariantProperty(
                    model_name=self.lstm_model.model_name,
                    variant_name="primary",
                    serverless_config=sagemaker.CfnEndpointConfig.ServerlessConfigProperty(
                        memory_size_in_mb=2048,
                        max_concurrency=20,
                    ),
                ),
            ],
        )
        self.lstm_endpoint_config.add_dependency(self.lstm_model)

        # ---------------------------------------------------------------
        # SageMaker Endpoints
        # ---------------------------------------------------------------

        self.yolov8_endpoint = sagemaker.CfnEndpoint(
            self,
            "YOLOv8Endpoint",
            endpoint_name="factorymind-yolov8-quality",
            endpoint_config_name=self.yolov8_endpoint_config.endpoint_config_name,
        )
        self.yolov8_endpoint.add_dependency(self.yolov8_endpoint_config)

        self.lstm_endpoint = sagemaker.CfnEndpoint(
            self,
            "LSTMEndpoint",
            endpoint_name="factorymind-lstm-maintenance",
            endpoint_config_name=self.lstm_endpoint_config.endpoint_config_name,
        )
        self.lstm_endpoint.add_dependency(self.lstm_endpoint_config)

        # ---------------------------------------------------------------
        # Lookout for Equipment — IAM role only
        # ---------------------------------------------------------------
        # The Lookout model itself is created out-of-band via the AWS Console
        # or boto3 (see scripts/setup_lookout.py) because it requires training
        # data uploaded to S3 first. Provisioning a placeholder model here
        # would fail at deploy time.

        self.lookout_role = iam.Role(
            self,
            "LookoutEquipmentRole",
            role_name="factorymind-lookout-equipment-role",
            assumed_by=iam.ServicePrincipal("lookoutequipment.amazonaws.com"),
        )
        self.ml_models_bucket.grant_read(self.lookout_role)

        # ---------------------------------------------------------------
        # AppSync GraphQL API for real-time dashboard
        # ---------------------------------------------------------------

        schema_path = SCHEMA_DIR / "factorymind.graphql"
        # Use schema file if present, else inline minimal schema.
        if schema_path.exists():
            schema = appsync.SchemaFile.from_asset(str(schema_path))
        else:
            schema = appsync.SchemaFile.from_asset(
                str(self._write_default_schema(SCHEMA_DIR))
            )

        self.appsync_api = appsync.GraphqlApi(
            self,
            "FactoryMindAppSync",
            name="factorymind-appsync-api",
            definition=appsync.Definition.from_schema(schema),
            authorization_config=appsync.AuthorizationConfig(
                default_authorization=appsync.AuthorizationMode(
                    authorization_type=appsync.AuthorizationType.API_KEY,
                ),
            ),
            xray_enabled=True,
        )

        # Wire the TwinState DynamoDB table as the AppSync data source for
        # updateMachineState mutations and getMachineState queries.
        twin_state_table = dynamodb.Table.from_table_name(
            self,
            "TwinStateRefForAppSync",
            table_name="FactoryMind_TwinState",
        )
        twin_state_ds = self.appsync_api.add_dynamo_db_data_source(
            "TwinStateDataSource",
            twin_state_table,
        )

        twin_state_ds.create_resolver(
            "GetMachineStateResolver",
            type_name="Query",
            field_name="getMachineState",
            request_mapping_template=appsync.MappingTemplate.dynamo_db_get_item(
                "machine_id", "machine_id"
            ),
            response_mapping_template=appsync.MappingTemplate.dynamo_db_result_item(),
        )

        twin_state_ds.create_resolver(
            "UpdateMachineStateResolver",
            type_name="Mutation",
            field_name="updateMachineState",
            request_mapping_template=appsync.MappingTemplate.dynamo_db_put_item(
                appsync.PrimaryKey.partition("machine_id").is_("input.machine_id"),
                appsync.Values.projecting("input"),
            ),
            response_mapping_template=appsync.MappingTemplate.dynamo_db_result_item(),
        )

        # ---------------------------------------------------------------
        # IoT TwinMaker workspace
        # ---------------------------------------------------------------

        twinmaker_role = iam.Role(
            self,
            "TwinMakerRole",
            role_name="factorymind-twinmaker-role",
            assumed_by=iam.ServicePrincipal("iottwinmaker.amazonaws.com"),
        )
        self.twinmaker_scenes_bucket.grant_read_write(twinmaker_role)
        twinmaker_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "iotsitewise:DescribeAsset",
                    "iotsitewise:GetAssetPropertyValue",
                    "kinesisvideo:DescribeStream",
                ],
                resources=["*"],
            )
        )

        self.twinmaker_workspace = twinmaker.CfnWorkspace(
            self,
            "TwinMakerWorkspace",
            workspace_id="factorymind-workspace",
            role=twinmaker_role.role_arn,
            s3_location=self.twinmaker_scenes_bucket.bucket_arn,
        )

        # ---------------------------------------------------------------
        # Outputs
        # ---------------------------------------------------------------

        CfnOutput(
            self,
            "AppSyncEndpoint",
            value=self.appsync_api.graphql_url,
            description="AppSync GraphQL endpoint for FactoryMind dashboard",
            export_name="FactoryMindAppSyncEndpoint",
        )
        CfnOutput(
            self,
            "AppSyncApiKey",
            value=self.appsync_api.api_key or "",
            description="AppSync API key (rotate before production use)",
        )
        CfnOutput(
            self,
            "MLModelsBucket",
            value=self.ml_models_bucket.bucket_name,
            description="Upload SageMaker model artifacts here",
        )

    @staticmethod
    def _write_default_schema(schema_dir: Path) -> Path:
        """Write a minimal GraphQL schema if none exists.

        Creates infrastructure/cdk/schema/factorymind.graphql with the
        types, queries, mutations, and subscriptions needed by the dashboard.
        """
        schema_dir.mkdir(parents=True, exist_ok=True)
        schema_file = schema_dir / "factorymind.graphql"

        if schema_file.exists():
            return schema_file

        schema_file.write_text(
            """type Telemetry {
  vibration_mms: Float
  current_amps: Float
  coolant_lmin: Float
  acoustic_db: Float
}

type MachineState {
  machine_id: ID!
  plant_id: String!
  status: String
  health_score: Float
  last_telemetry: Telemetry
  active_alerts: [String]
  updated_at: String
}

input MachineStateInput {
  machine_id: ID!
  plant_id: String!
  status: String
  health_score: Float
  last_telemetry: TelemetryInput
  active_alerts: [String]
  updated_at: String
}

input TelemetryInput {
  vibration_mms: Float
  current_amps: Float
  coolant_lmin: Float
  acoustic_db: Float
}

type Query {
  getMachineState(machine_id: ID!): MachineState
}

type Mutation {
  updateMachineState(input: MachineStateInput!): MachineState
}

type Subscription {
  onMachineStateUpdated(machine_id: ID): MachineState
    @aws_subscribe(mutations: ["updateMachineState"])
}
""",
            encoding="utf-8",
        )
        return schema_file
