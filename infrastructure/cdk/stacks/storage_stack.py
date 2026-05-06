"""Storage Stack — DynamoDB tables, S3 buckets, Timestream, ElastiCache Serverless.

Cloud-native posture:
- DynamoDB on-demand billing (no provisioned capacity)
- ElastiCache Serverless Redis (scales to zero, no instance management)
- VPC Gateway Endpoints for S3 + DynamoDB (free, eliminates NAT traffic for those services)
- Single small NAT gateway retained for Bedrock/EventBridge/SageMaker reachability
"""

from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
    aws_dynamodb as dynamodb,
    aws_ec2 as ec2,
    aws_elasticache as elasticache,
    aws_s3 as s3,
)
from constructs import Construct


class StorageStack(Stack):
    """Storage infrastructure: DynamoDB, S3, Timestream, ElastiCache Redis."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ---------------------------------------------------------------
        # DynamoDB Tables (PAY_PER_REQUEST, RemovalPolicy.DESTROY for dev)
        # ---------------------------------------------------------------

        self.machine_state_table = dynamodb.Table(
            self,
            "MachineStateTable",
            table_name="FactoryMind_MachineState",
            partition_key=dynamodb.Attribute(
                name="machine_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.machine_specs_table = dynamodb.Table(
            self,
            "MachineSpecsTable",
            table_name="FactoryMind_MachineSpecs",
            partition_key=dynamodb.Attribute(
                name="machine_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.quality_results_table = dynamodb.Table(
            self,
            "QualityResultsTable",
            table_name="FactoryMind_QualityResults",
            partition_key=dynamodb.Attribute(
                name="inspection_report_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.quality_thresholds_table = dynamodb.Table(
            self,
            "QualityThresholdsTable",
            table_name="FactoryMind_QualityThresholds",
            partition_key=dynamodb.Attribute(
                name="product_type", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.predictions_table = dynamodb.Table(
            self,
            "PredictionsTable",
            table_name="FactoryMind_Predictions",
            partition_key=dynamodb.Attribute(
                name="prediction_report_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.work_orders_table = dynamodb.Table(
            self,
            "WorkOrdersTable",
            table_name="FactoryMind_WorkOrders",
            partition_key=dynamodb.Attribute(
                name="work_order_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.energy_baselines_table = dynamodb.Table(
            self,
            "EnergyBaselinesTable",
            table_name="FactoryMind_EnergyBaselines",
            partition_key=dynamodb.Attribute(
                name="machine_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.sustainability_kpis_table = dynamodb.Table(
            self,
            "SustainabilityKPIsTable",
            table_name="FactoryMind_SustainabilityKPIs",
            partition_key=dynamodb.Attribute(
                name="report_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.twin_state_table = dynamodb.Table(
            self,
            "TwinStateTable",
            table_name="FactoryMind_TwinState",
            partition_key=dynamodb.Attribute(
                name="machine_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.floor_layout_table = dynamodb.Table(
            self,
            "FloorLayoutTable",
            table_name="FactoryMind_FloorLayout",
            partition_key=dynamodb.Attribute(
                name="plant_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.edge_thresholds_table = dynamodb.Table(
            self,
            "EdgeThresholdsTable",
            table_name="FactoryMind_EdgeThresholds",
            partition_key=dynamodb.Attribute(
                name="machine_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.edge_results_table = dynamodb.Table(
            self,
            "EdgeResultsTable",
            table_name="FactoryMind_EdgeResults",
            partition_key=dynamodb.Attribute(
                name="edge_result_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ---------------------------------------------------------------
        # S3 Buckets (RemovalPolicy.DESTROY + auto_delete_objects for dev)
        # ---------------------------------------------------------------

        self.raw_data_bucket = s3.Bucket(
            self,
            "RawDataBucket",
            bucket_name="factorymind-raw-data",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        self.product_images_bucket = s3.Bucket(
            self,
            "ProductImagesBucket",
            bucket_name="factorymind-product-images",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        self.defect_images_bucket = s3.Bucket(
            self,
            "DefectImagesBucket",
            bucket_name="factorymind-defect-images",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        self.reports_bucket = s3.Bucket(
            self,
            "ReportsBucket",
            bucket_name="factorymind-reports",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        self.twin_snapshots_bucket = s3.Bucket(
            self,
            "TwinSnapshotsBucket",
            bucket_name="factorymind-twin-snapshots",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # Timestream removed: workshop SCP blocks timestream:DescribeEndpoints.
        # Time-series sensor data is archived to RawDataBucket via Kinesis Firehose.

        # ---------------------------------------------------------------
        # VPC — required because ElastiCache (even Serverless) lives in a VPC.
        # We keep one small NAT gateway so VPC Lambdas can still reach
        # Bedrock / SageMaker / EventBridge / IoT control-plane APIs.
        # S3 + DynamoDB traffic is rerouted through Gateway Endpoints below.
        # ---------------------------------------------------------------

        self.vpc = ec2.Vpc(
            self,
            "FactoryMindVpc",
            max_azs=2,
            nat_gateways=1,
        )

        # Free Gateway Endpoints for S3 + DynamoDB — keeps that traffic
        # off the NAT gateway, dropping data-transfer costs significantly.
        self.vpc.add_gateway_endpoint(
            "S3GatewayEndpoint",
            service=ec2.GatewayVpcEndpointAwsService.S3,
        )
        self.vpc.add_gateway_endpoint(
            "DynamoDbGatewayEndpoint",
            service=ec2.GatewayVpcEndpointAwsService.DYNAMODB,
        )

        # ---------------------------------------------------------------
        # ElastiCache Serverless Redis — Digital Twin cache + Edge AI window.
        # Scales to zero, no instance management, billed per GB-hour + ECPU.
        # ---------------------------------------------------------------

        self.redis_security_group = ec2.SecurityGroup(
            self,
            "RedisSG",
            vpc=self.vpc,
            description="Security group for FactoryMind ElastiCache Serverless",
            allow_all_outbound=True,
        )
        self.redis_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(6379),
            description="Allow Redis access from within VPC",
        )

        self.redis_serverless = elasticache.CfnServerlessCache(
            self,
            "RedisServerless",
            serverless_cache_name="factorymind-redis",
            engine="redis",
            major_engine_version="7",
            description="FactoryMind Digital Twin cache + Edge AI sliding window",
            subnet_ids=[s.subnet_id for s in self.vpc.private_subnets],
            security_group_ids=[self.redis_security_group.security_group_id],
            # Tight cap so accidental hammering can't run up the bill.
            cache_usage_limits=elasticache.CfnServerlessCache.CacheUsageLimitsProperty(
                data_storage=elasticache.CfnServerlessCache.DataStorageProperty(
                    maximum=2,
                    unit="GB",
                ),
                ecpu_per_second=elasticache.CfnServerlessCache.ECPUPerSecondProperty(
                    maximum=5000,
                ),
            ),
        )

        # Outputs the Edge AI / Digital Twin Lambdas read at deploy time.
        CfnOutput(
            self,
            "RedisEndpointAddress",
            value=self.redis_serverless.attr_endpoint_address,
            description="ElastiCache Serverless endpoint host",
            export_name="FactoryMindRedisEndpoint",
        )
        CfnOutput(
            self,
            "RedisEndpointPort",
            value=self.redis_serverless.attr_endpoint_port,
            description="ElastiCache Serverless endpoint port",
            export_name="FactoryMindRedisPort",
        )
