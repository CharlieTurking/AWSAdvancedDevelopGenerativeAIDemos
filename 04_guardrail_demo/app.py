import os
import json
import sys
import streamlit as st
import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Make the repo-root shared helpers importable when launched via
# `streamlit run app.py` from inside this demo folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model_catalog import build_inference_config, model_selectbox  # noqa: E402

# --- Basic config ---
st.set_page_config(page_title="Bedrock Guardrail Demo", layout="wide")

st.title("Amazon Bedrock Guardrail Demo")

# --- Sidebar: AWS / model settings ---
st.sidebar.header("AWS & Model Settings")

default_region = os.getenv("AWS_REGION", "us-east-1")
region = st.sidebar.text_input("AWS Region", value=default_region)

with st.sidebar:
    model_id = model_selectbox(
        "Model ID",
        "llm",
        "global.anthropic.claude-haiku-4-5-20251001-v1:0",
        help="Must be a Bedrock model you have access to.",
    )

guardrail_version = st.sidebar.selectbox(
    "Guardrail Version",
    options=["DRAFT", "1", "2", "3", "4", "5"],
    index=0,
    help="Select or type a guardrail version.",
    key="guardrail_version"
)


# --- Front page: Guardrail ARN & prompt ---
st.subheader("Guardrail configuration")

guardrail_arn = st.text_input(
    "Guardrail ARN",
    placeholder="arn:aws:bedrock:us-east-1:123456789012:guardrail/your-guardrail-id",
    help="Paste the full ARN of an existing Bedrock guardrail."
)

st.subheader("Test prompt")

user_prompt = st.text_area(
    "User input",
    height=200,
    placeholder="Type something that might trigger your guardrail (e.g. PII, denied topics, etc.)"
)

run_button = st.button("Run with Guardrail")

# --- Helper: create client ---
def get_bedrock_runtime_client(region_name: str):
    return boto3.client("bedrock-runtime", region_name=region_name)


# --- Main action ---
if run_button:
    if not guardrail_arn:
        st.error("Please provide a Guardrail ARN.")
    elif not user_prompt.strip():
        st.error("Please provide a user prompt.")
    else:
        try:
            client = get_bedrock_runtime_client(region)

            st.info("Calling Bedrock with guardrail applied...")

            response = client.converse(
                modelId=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"text": user_prompt}
                        ],
                    }
                ],
                guardrailConfig={
                    "guardrailIdentifier": guardrail_arn,
                    "guardrailVersion": guardrail_version,
                    "trace": "enabled",
                },
                inferenceConfig=build_inference_config(model_id, 512, 0.7),
            )

            # --- Show model output ---
            st.subheader("Model response (after guardrail)")
            try:
                output_msg = response["output"]["message"]
                output_text_parts = [
                    c.get("text", "") for c in output_msg.get("content", [])
                    if "text" in c
                ]
                output_text = "\n".join(output_text_parts).strip()
            except Exception:
                output_text = "(Could not parse output text.)"

            st.write(output_text or "(Empty response)")

            # --- Show guardrail trace / assessment ---
            st.subheader("Guardrail trace / assessment (raw JSON)")
            st.code(
                json.dumps(response.get("trace", {}), indent=2),
                language="json",
                wrap_lines=True,
            )

            st.subheader("Full Bedrock response (raw JSON)")
            st.code(
                json.dumps(response, indent=2),
                language="json",
                wrap_lines=True,
            )

        except (BotoCoreError, ClientError) as e:
            st.error(f"Bedrock call failed: {e}")
        except Exception as e:
            st.error(f"Unexpected error: {e}")
