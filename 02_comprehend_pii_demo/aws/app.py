#!/usr/bin/env python3
"""CDK app for the deployed Amazon Comprehend demo (website + API).

Before synthesising, this stages two clean folders under build/ so the repo keeps
a single copy of everything:

    build/lambda/  aws/lambda_functions/*  +  ../comprehend_core.py   (shared with Streamlit)
    build/site/    aws/website/*           +  ../sample_data/         (shared with Streamlit)

Optional context:  cdk deploy -c allowed_ips=203.0.113.7/32,198.51.100.0/24
restricts the API to those addresses (see scripts/deploy.sh --allow-my-ip).
"""

import os
import shutil
from pathlib import Path

import aws_cdk as cdk

from stack.comprehend_demo_stack import ComprehendDemoStack

HERE = Path(__file__).resolve().parent
DEMO_DIR = HERE.parent  # 02_comprehend_pii_demo


def stage_assets() -> tuple[Path, Path]:
    build = HERE / "build"
    shutil.rmtree(build, ignore_errors=True)
    lambda_dir, site_dir = build / "lambda", build / "site"

    shutil.copytree(HERE / "lambda_functions", lambda_dir, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(DEMO_DIR / "comprehend_core.py", lambda_dir / "comprehend_core.py")

    shutil.copytree(HERE / "website", site_dir)
    shutil.copytree(DEMO_DIR / "sample_data", site_dir / "sample_data")
    return lambda_dir, site_dir


app = cdk.App()

allowed = app.node.try_get_context("allowed_ips") or ""
allowed_ips = [ip.strip() for ip in str(allowed).split(",") if ip.strip()]

lambda_dir, site_dir = stage_assets()

ComprehendDemoStack(
    app,
    "ComprehendDemoStack",
    description="Amazon Comprehend demo: PII detection, PII masking and bias signals",
    lambda_dir=lambda_dir,
    site_dir=site_dir,
    allowed_ips=allowed_ips,
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=os.getenv("CDK_DEFAULT_REGION"),
    ),
)

app.synth()
