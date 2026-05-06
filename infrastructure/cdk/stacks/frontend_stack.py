"""Frontend Stack — S3 + CloudFront for the React dashboard.

Provisions:
  - S3 bucket holding the built dashboard (private, no public ACLs).
  - CloudFront distribution with Origin Access Control (OAC) — the bucket
    itself stays private; only CloudFront can read from it.
  - SPA-friendly error mappings: 403/404 → /index.html so React Router can
    take over client-side routing.

Outputs:
  - DashboardBucketName  — used by deploy.sh to upload the built `dist/`
  - DashboardURL         — the https CloudFront URL operators hand to users
  - CloudFrontDistributionId — used by deploy.sh to invalidate after upload
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3 as s3,
)
from constructs import Construct


class FrontendStack(Stack):
    """Static React dashboard hosting via S3 + CloudFront."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Private S3 bucket — only CloudFront reads from it via OAC.
        self.dashboard_bucket = s3.Bucket(
            self,
            "DashboardBucket",
            bucket_name=f"factorymind-dashboard-{self.account}-{self.region}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # SPA cache policy — short TTL on HTML, long TTL on hashed JS/CSS.
        # CloudFront's managed CACHING_OPTIMIZED is a sane default for hashed assets.
        self.distribution = cloudfront.Distribution(
            self,
            "DashboardDistribution",
            comment="FactoryMind ERP dashboard",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(
                    self.dashboard_bucket
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                compress=True,
            ),
            # SPA fallbacks: react-router uses client-side paths so any 403/404
            # against the bucket must still return index.html for the route
            # to resolve in the browser.
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.minutes(1),
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.minutes(1),
                ),
            ],
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
        )

        CfnOutput(
            self,
            "DashboardBucketName",
            value=self.dashboard_bucket.bucket_name,
            description="S3 bucket the dashboard build artifacts upload to",
            export_name="FactoryMindDashboardBucket",
        )
        CfnOutput(
            self,
            "DashboardURL",
            value=f"https://{self.distribution.distribution_domain_name}",
            description="Public dashboard URL — share this with operators",
            export_name="FactoryMindDashboardURL",
        )
        CfnOutput(
            self,
            "CloudFrontDistributionId",
            value=self.distribution.distribution_id,
            description="Distribution ID — used by deploy.sh for cache invalidation",
            export_name="FactoryMindCloudFrontId",
        )
