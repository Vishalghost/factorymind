"""Storage Stack - DynamoDB tables, S3 buckets, Timestream, ElastiCache."""

from aws_cdk import (
    RemovalPolicy,
    Stack,
    aws_dynamodb as dynamodb,
    aws_ec2 as ec2,
    aws_elasticache as elasticache,
    aws_s3 as s3,
    aws_timestream as timestream,
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

        # ---------------------------------------------------------------
        # Amazon Timestream - Sensor and Energy time-series data
        # ---------------------------------------------------------------

        self.timestream_database = timestream.CfnDatabase(
            self,
            "TimestreamDatabase",
            database_name="FactoryMindSensors",
        )

        self.sensor_readings_table = timestream.CfnTable(
            self,
            "SensorReadingsTable",
            database_name=self.timestream_database.database_name,
            table_name="SensorReadings",
            retention_properties={
                "MemoryStoreRetentionPeriodInHours": "72",
                "MagneticStoreRetentionPeriodInDays": "365",
            },
        )
        self.sensor_readings_table.add_dependency(self.timestream_database)

        self.energy_readings_table = timestream.CfnTable(
            self,
            "EnergyReadingsTable",
            database_name=self.timestream_database.database_name,
            table_name="EnergyReadings",
            retention_properties={
                "MemoryStoreRetentionPeriodInHours": "72",
                "MagneticStoreRetentionPeriodInDays": "365",
            },
        )
        self.energy_readings_table.add_dependency(self.timestream_database)

        # ---------------------------------------------------------------
        # ElastiCache Redis - Digital Twin state cache & Edge AI window
        # ---------------------------------------------------------------

        # VPC for ElastiCache (required)
        self.vpc = ec2.Vpc(
            self,
            "FactoryMindVpc",
            max_azs=2,
            nat_gateways=1,
        )

        self.redis_security_group = ec2.SecurityGroup(
            self,
            "RedisSG",
            vpc=self.vpc,
            description="Security group for FactoryMind Redis cluster",
            allow_all_outbound=True,
        )

        self.redis_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(6379),
            description="Allow Redis access from within VPC",
        )

        self.redis_subnet_group = elasticache.CfnSubnetGroup(
            self,
            "RedisSubnetGroup",
            description="Subnet group for FactoryMind Redis cluster",
            subnet_ids=[
                subnet.subnet_id for subnet in self.vpc.private_subnets
            ],
            cache_subnet_group_name="factorymind-redis-subnet-group",
        )

        self.redis_cluster = elasticache.CfnCacheCluster(
            self,
            "RedisCluster",
            cluster_name="factorymind-redis",
            engine="redis",
            cache_node_type="cache.t3.small",
            num_cache_nodes=1,
            vpc_security_group_ids=[
                self.redis_security_group.security_group_id
            ],
            cache_subnet_group_name=self.redis_subnet_group.cache_subnet_group_name,
        )
        self.redis_cluster.add_dependency(self.redis_subnet_group)
