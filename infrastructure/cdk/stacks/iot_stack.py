"""IoT Stack - AWS IoT Core, Kinesis, Firehose, EventBridge, SQS, SNS resources.

Provisions the real-time ingestion pipeline for aerospace CNC telemetry:
  Sensors → IoT Core (MQTT) → Kinesis Data Stream → Firehose → S3
                             → IoT Rule → Edge AI Lambda (real-time inference)
  EventBridge bus for inter-agent communication.
  SQS queue for work order processing.
  SNS topics for quality and maintenance alerts.
"""

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_events as events,
    aws_iam as iam,
    aws_iot as iot,
    aws_kinesis as kinesis,
    aws_kinesisfirehose as firehose,
    aws_s3 as s3,
    aws_sns as sns,
    aws_sqs as sqs,
)
from constructs import Construct


class IoTStack(Stack):
    """IoT ingestion infrastructure: IoT Core rules, Kinesis streams, Firehose delivery,
    EventBridge bus, SQS queues, and SNS topics for the FactoryMind platform."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ---------------------------------------------------------------
        # Amazon Kinesis Data Stream — sensor telemetry ingestion
        # ---------------------------------------------------------------

        # On-Demand mode: no shard management, autoscales with traffic.
        # Note: shard_count is omitted intentionally — incompatible with ON_DEMAND.
        self.sensor_stream = kinesis.Stream(
            self,
            "SensorStream",
            stream_name="factorymind-sensor-stream",
            retention_period=Duration.hours(24),
            stream_mode=kinesis.StreamMode.ON_DEMAND,
        )

        # ---------------------------------------------------------------
        # Amazon Kinesis Firehose — archive raw data to S3
        # ---------------------------------------------------------------

        # Reference the raw data bucket (created in StorageStack)
        raw_data_bucket = s3.Bucket.from_bucket_name(
            self,
            "RawDataBucketRef",
            bucket_name="factorymind-raw-data",
        )

        # IAM role for Firehose to read from Kinesis and write to S3
        firehose_role = iam.Role(
            self,
            "FirehoseDeliveryRole",
            role_name="factorymind-firehose-delivery-role",
            assumed_by=iam.ServicePrincipal("firehose.amazonaws.com"),
        )

        bucket_grant = raw_data_bucket.grant_read_write(firehose_role)
        stream_grant = self.sensor_stream.grant_read(firehose_role)

        self.delivery_stream = firehose.CfnDeliveryStream(
            self,
            "SensorDeliveryStream",
            delivery_stream_name="factorymind-sensor-delivery",
            delivery_stream_type="KinesisStreamAsSource",
            kinesis_stream_source_configuration=firehose.CfnDeliveryStream.KinesisStreamSourceConfigurationProperty(
                kinesis_stream_arn=self.sensor_stream.stream_arn,
                role_arn=firehose_role.role_arn,
            ),
            s3_destination_configuration=firehose.CfnDeliveryStream.S3DestinationConfigurationProperty(
                bucket_arn=raw_data_bucket.bucket_arn,
                role_arn=firehose_role.role_arn,
                prefix="telemetry/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/",
                error_output_prefix="errors/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/!{firehose:error-output-type}/",
                buffering_hints=firehose.CfnDeliveryStream.BufferingHintsProperty(
                    interval_in_seconds=60,
                    size_in_m_bs=5,
                ),
                compression_format="GZIP",
            ),
        )

        # Firehose validates the role's permissions on creation; ensure the
        # grant policies are attached before the stream is created.
        bucket_grant.apply_before(self.delivery_stream)
        stream_grant.apply_before(self.delivery_stream)

        # ---------------------------------------------------------------
        # Amazon EventBridge — inter-agent communication bus
        # ---------------------------------------------------------------

        self.event_bus = events.EventBus(
            self,
            "FactoryMindBus",
            event_bus_name="factorymind-bus",
        )

        # Archive all events for replay/debugging (7-day retention)
        events.Archive(
            self,
            "FactoryMindArchive",
            source_event_bus=self.event_bus,
            archive_name="factorymind-bus-archive",
            description="Archive of all FactoryMind inter-agent events",
            retention=Duration.days(7),
            event_pattern=events.EventPattern(
                source=events.Match.prefix("factorymind."),
            ),
        )

        # ---------------------------------------------------------------
        # Amazon SQS — work order processing queue
        # ---------------------------------------------------------------

        # Dead-letter queue for failed work order processing
        workorder_dlq = sqs.Queue(
            self,
            "WorkOrderDLQ",
            queue_name="factorymind-workorder-queue-dlq",
            retention_period=Duration.days(14),
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.workorder_queue = sqs.Queue(
            self,
            "WorkOrderQueue",
            queue_name="factorymind-workorder-queue",
            visibility_timeout=Duration.seconds(60),
            retention_period=Duration.days(7),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=workorder_dlq,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ---------------------------------------------------------------
        # Amazon SNS — alert notification topics
        # ---------------------------------------------------------------

        self.quality_alerts_topic = sns.Topic(
            self,
            "QualityAlertsTopic",
            topic_name="factorymind-quality-alerts",
            display_name="FactoryMind Quality Alerts",
        )

        self.maintenance_alerts_topic = sns.Topic(
            self,
            "MaintenanceAlertsTopic",
            topic_name="factorymind-maintenance-alerts",
            display_name="FactoryMind Maintenance Alerts",
        )

        # ---------------------------------------------------------------
        # AWS IoT Core — MQTT rules for CNC telemetry
        # ---------------------------------------------------------------

        # IAM role for IoT Core rules to put records into Kinesis
        iot_kinesis_role = iam.Role(
            self,
            "IoTKinesisRole",
            role_name="factorymind-iot-kinesis-role",
            assumed_by=iam.ServicePrincipal("iot.amazonaws.com"),
        )

        self.sensor_stream.grant_write(iot_kinesis_role)

        # IAM role for IoT Core rules to invoke Edge AI Lambda
        self.iot_lambda_role = iam.Role(
            self,
            "IoTLambdaRole",
            role_name="factorymind-iot-lambda-role",
            assumed_by=iam.ServicePrincipal("iot.amazonaws.com"),
        )

        # Grant Lambda invoke permission (the actual Lambda ARN will be
        # referenced by the compute stack; here we grant invoke on the
        # expected function name pattern)
        self.iot_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[
                    f"arn:aws:lambda:{self.region}:{self.account}:function:factorymind-edge-ai-manager",
                ],
            )
        )

        # Rule 1: Forward all CNC telemetry MQTT messages to Kinesis stream
        self.telemetry_to_kinesis_rule = iot.CfnTopicRule(
            self,
            "TelemetryToKinesisRule",
            rule_name="factorymind_telemetry_to_kinesis",
            topic_rule_payload=iot.CfnTopicRule.TopicRulePayloadProperty(
                description="Route aerospace CNC telemetry from MQTT to Kinesis for batch processing",
                sql="SELECT * FROM 'factory/aerospace/cnc/telemetry'",
                aws_iot_sql_version="2016-03-23",
                rule_disabled=False,
                actions=[
                    iot.CfnTopicRule.ActionProperty(
                        kinesis=iot.CfnTopicRule.KinesisActionProperty(
                            stream_name=self.sensor_stream.stream_name,
                            role_arn=iot_kinesis_role.role_arn,
                            partition_key="${machine_id}",
                        ),
                    ),
                ],
                error_action=iot.CfnTopicRule.ActionProperty(
                    cloudwatch_logs=iot.CfnTopicRule.CloudwatchLogsActionProperty(
                        log_group_name="/aws/iot/factorymind/errors",
                        role_arn=iot_kinesis_role.role_arn,
                    ),
                ),
            ),
        )

        # Rule 2: Trigger Edge AI Lambda directly for real-time inference
        self.telemetry_to_edge_ai_rule = iot.CfnTopicRule(
            self,
            "TelemetryToEdgeAIRule",
            rule_name="factorymind_telemetry_to_edge_ai",
            topic_rule_payload=iot.CfnTopicRule.TopicRulePayloadProperty(
                description="Route aerospace CNC telemetry to Edge AI Lambda for sub-10ms real-time inference",
                sql="SELECT * FROM 'factory/aerospace/cnc/telemetry'",
                aws_iot_sql_version="2016-03-23",
                rule_disabled=False,
                actions=[
                    iot.CfnTopicRule.ActionProperty(
                        lambda_=iot.CfnTopicRule.LambdaActionProperty(
                            function_arn=f"arn:aws:lambda:{self.region}:{self.account}:function:factorymind-edge-ai-manager",
                        ),
                    ),
                ],
                error_action=iot.CfnTopicRule.ActionProperty(
                    cloudwatch_logs=iot.CfnTopicRule.CloudwatchLogsActionProperty(
                        log_group_name="/aws/iot/factorymind/edge-ai-errors",
                        role_arn=self.iot_lambda_role.role_arn,
                    ),
                ),
            ),
        )
