"""Monitoring Stack — CloudWatch dashboards, alarms, and alerting.

Provisions:
  - SNS topic for SLA breach alerts (operations team)
  - CloudWatch alarms per agent for SLA breaches and error rates
  - Composite CloudWatch dashboard showing SLA compliance, error rates,
    invocation counts, and Edge AI inference latency.
  - Per-agent X-Ray tracing is enabled in ComputeStack on each Lambda.
"""

from aws_cdk import (
    Duration,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_lambda as _lambda,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subs,
)
from constructs import Construct


# Per-agent SLA targets (milliseconds), mirroring agents/shared/constants.py
SLA_MS = {
    "factorymind-edge-ai-manager": 10,
    "factorymind-iot-ingestion-manager": 500,
    "factorymind-digital-twin-manager": 500,
    "factorymind-quality-vision-manager": 3000,
    "factorymind-predictive-maintenance-manager": 3000,
    "factorymind-sustainability-manager": 5000,
    "factorymind-brain-agent": 2000,
}


class MonitoringStack(Stack):
    """CloudWatch dashboards, alarms, and SNS alerting for FactoryMind."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ---------------------------------------------------------------
        # SNS topic for operations alerts
        # ---------------------------------------------------------------

        self.ops_alerts_topic = sns.Topic(
            self,
            "OpsAlertsTopic",
            topic_name="factorymind-ops-alerts",
            display_name="FactoryMind Operations Alerts",
        )

        # Subscribe a default email if provided via context. Operators can also
        # add subscriptions manually after deploy.
        ops_email = self.node.try_get_context("ops_email")
        if ops_email:
            self.ops_alerts_topic.add_subscription(
                sns_subs.EmailSubscription(ops_email)
            )

        # ---------------------------------------------------------------
        # Per-agent alarms — error rate + duration SLA
        # ---------------------------------------------------------------

        dashboard_widgets: list[cloudwatch.IWidget] = []

        for fn_name, sla_target_ms in SLA_MS.items():
            fn_ref = _lambda.Function.from_function_name(
                self,
                f"{fn_name}-Ref",
                function_name=fn_name,
            )

            errors_metric = fn_ref.metric_errors(
                period=Duration.minutes(1),
                statistic="Sum",
            )
            duration_metric = fn_ref.metric_duration(
                period=Duration.minutes(1),
                statistic="p99",
            )
            invocations_metric = fn_ref.metric_invocations(
                period=Duration.minutes(1),
                statistic="Sum",
            )

            error_alarm = cloudwatch.Alarm(
                self,
                f"{fn_name}-ErrorAlarm",
                alarm_name=f"{fn_name}-error-rate",
                alarm_description=f"Error rate alarm for {fn_name}",
                metric=errors_metric,
                threshold=5,
                evaluation_periods=2,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )
            error_alarm.add_alarm_action(cw_actions.SnsAction(self.ops_alerts_topic))

            sla_alarm = cloudwatch.Alarm(
                self,
                f"{fn_name}-SLAAlarm",
                alarm_name=f"{fn_name}-sla-breach",
                alarm_description=(
                    f"P99 duration > {sla_target_ms}ms SLA for {fn_name}"
                ),
                metric=duration_metric,
                threshold=sla_target_ms,
                evaluation_periods=3,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )
            sla_alarm.add_alarm_action(cw_actions.SnsAction(self.ops_alerts_topic))

            dashboard_widgets.append(
                cloudwatch.GraphWidget(
                    title=f"{fn_name} — Duration (p50/p99) vs SLA={sla_target_ms}ms",
                    left=[
                        fn_ref.metric_duration(
                            period=Duration.minutes(1),
                            statistic="p50",
                            label="p50",
                        ),
                        duration_metric,
                    ],
                    left_annotations=[
                        cloudwatch.HorizontalAnnotation(
                            value=sla_target_ms,
                            label=f"SLA {sla_target_ms}ms",
                            color=cloudwatch.Color.RED,
                        ),
                    ],
                    width=12,
                    height=6,
                )
            )
            dashboard_widgets.append(
                cloudwatch.GraphWidget(
                    title=f"{fn_name} — Invocations & Errors",
                    left=[invocations_metric],
                    right=[errors_metric],
                    width=12,
                    height=6,
                )
            )

        # ---------------------------------------------------------------
        # Custom Edge AI inference latency widget
        # ---------------------------------------------------------------
        # Edge AI Lambda emits inference_time_ms via aws-lambda-powertools metrics.

        edge_inference_metric = cloudwatch.Metric(
            namespace="FactoryMind",
            metric_name="EdgeInferenceTimeMs",
            statistic="p99",
            period=Duration.minutes(1),
        )

        dashboard_widgets.append(
            cloudwatch.GraphWidget(
                title="Edge AI — ONNX Inference Latency (p99) vs 10ms SLA",
                left=[edge_inference_metric],
                left_annotations=[
                    cloudwatch.HorizontalAnnotation(
                        value=10,
                        label="SLA 10ms",
                        color=cloudwatch.Color.RED,
                    ),
                ],
                width=24,
                height=6,
            )
        )

        # ---------------------------------------------------------------
        # CloudWatch Dashboard
        # ---------------------------------------------------------------

        self.dashboard = cloudwatch.Dashboard(
            self,
            "FactoryMindDashboard",
            dashboard_name="FactoryMind-Operations",
            widgets=[
                # Lay out as rows of two widgets each, then the wide edge widget.
                dashboard_widgets[i : i + 2]
                for i in range(0, len(dashboard_widgets), 2)
            ],
        )
