"""Stack: CloudFront + private S3 site, API Gateway, one Lambda that calls Comprehend."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigateway as apigw,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
)
from constructs import Construct

# Stage-wide API throttle. It limits how fast anyone can call the API; it is not a
# spend cap, so use the IP allow-list and tear the stack down when you are done.
THROTTLE_RATE_PER_SECOND = 10
THROTTLE_BURST = 20


class ComprehendDemoStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        lambda_dir: Path,
        site_dir: Path,
        allowed_ips: list[str],
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ------------------------------------------------------------------
        # Lambda: the only thing that talks to Comprehend
        # ------------------------------------------------------------------
        api_function = lambda_.Function(
            self,
            "ApiFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="api_handler.lambda_handler",
            code=lambda_.Code.from_asset(str(lambda_dir)),
            memory_size=256,
            timeout=Duration.seconds(25),  # API Gateway gives up at 29s
            log_group=logs.LogGroup(
                self,
                "ApiFunctionLogs",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=RemovalPolicy.DESTROY,
            ),
            description="Comprehend demo API: PII, masking, sentiment, toxicity",
        )
        # These Comprehend actions do not support resource-level permissions.
        api_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "comprehend:DetectPiiEntities",
                    "comprehend:BatchDetectSentiment",
                    "comprehend:DetectToxicContent",
                ],
                resources=["*"],
            )
        )

        # ------------------------------------------------------------------
        # API Gateway (optionally restricted to an IP allow-list)
        # ------------------------------------------------------------------
        resource_policy = None
        if allowed_ips:
            resource_policy = iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        effect=iam.Effect.ALLOW,
                        principals=[iam.AnyPrincipal()],
                        actions=["execute-api:Invoke"],
                        resources=["execute-api:/*"],
                    ),
                    iam.PolicyStatement(
                        effect=iam.Effect.DENY,
                        principals=[iam.AnyPrincipal()],
                        actions=["execute-api:Invoke"],
                        resources=["execute-api:/*"],
                        conditions={"NotIpAddress": {"aws:SourceIp": allowed_ips}},
                    ),
                ]
            )

        api = apigw.RestApi(
            self,
            "Api",
            rest_api_name="ComprehendDemo-Api",
            description="API for the Amazon Comprehend demo website",
            policy=resource_policy,
            cloud_watch_role=False,
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                throttling_rate_limit=THROTTLE_RATE_PER_SECOND,
                throttling_burst_limit=THROTTLE_BURST,
            ),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,  # no cookies or credentials are used
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["Content-Type"],
            ),
        )
        integration = apigw.LambdaIntegration(api_function)
        for path, method in [
            ("pii", "POST"),
            ("mask", "POST"),
            ("sentiment", "POST"),
            ("toxicity", "POST"),
            ("info", "GET"),
        ]:
            api.root.add_resource(path).add_method(method, integration)

        # ------------------------------------------------------------------
        # Website: private bucket served only through CloudFront
        # ------------------------------------------------------------------
        site_bucket = s3.Bucket(
            self,
            "SiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            comment="Amazon Comprehend demo",
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
                compress=True,
            ),
        )

        s3deploy.BucketDeployment(
            self,
            "DeploySite",
            destination_bucket=site_bucket,
            distribution=distribution,
            distribution_paths=["/*"],
            sources=[
                s3deploy.Source.asset(str(site_dir)),
                # Written at deploy time so the page knows where its API is.
                s3deploy.Source.data("config.js", f"window.COMPREHEND_API_URL = '{api.url}';\n"),
            ],
        )

        # ------------------------------------------------------------------
        # Outputs
        # ------------------------------------------------------------------
        CfnOutput(self, "SiteUrl", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "ApiUrl", value=api.url)
        CfnOutput(self, "DistributionId", value=distribution.distribution_id)
        CfnOutput(self, "SiteBucketName", value=site_bucket.bucket_name)
        CfnOutput(self, "RestrictedToIps", value=", ".join(allowed_ips) if allowed_ips else "none (public, throttled)")
