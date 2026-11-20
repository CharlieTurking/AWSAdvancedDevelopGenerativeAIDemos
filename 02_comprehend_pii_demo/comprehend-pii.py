import os
import json
import streamlit as st
import boto3
from botocore.exceptions import BotoCoreError, ClientError

st.set_page_config(page_title="Amazon Comprehend PII Demo", layout="wide")
st.title("Real-time PII Detection with Amazon Comprehend")

# --- Sidebar: AWS settings ---
st.sidebar.header("AWS Settings")

default_region = os.getenv("AWS_REGION", "us-east-1")
region = st.sidebar.text_input("AWS Region", value=default_region)

language_code = st.sidebar.selectbox(
    "Language",
    options=["en"],
    index=0,
    help="Comprehend PII currently supports English (en).",
)

st.sidebar.header("Redaction Settings")
reveal_mapping = st.sidebar.checkbox(
    "Reveal name token mapping",
    value=False,
    help="Show which original name each <NAME_n> token stands for. Off by default since it's sensitive.",
)
if st.sidebar.button("Reset name token mapping"):
    st.session_state["name_token_map"] = {}
    st.session_state["name_reverse_map"] = {}

# --- Main input area ---
st.subheader("Input text")

text = st.text_area(
    "Type or paste text containing possible PII",
    height=200,
    placeholder="Example: My name is John Smith and my email is john.smith@example.com.",
)

auto_run = st.checkbox("Detect PII in real time (on every change)", value=True)
run_button = st.button("Detect PII now")


def get_comprehend_client(region_name: str):
    return boto3.client("comprehend", region_name=region_name)


def detect_pii(text: str, region_name: str, language: str = "en"):
    client = get_comprehend_client(region_name)
    return client.detect_pii_entities(
        Text=text,
        LanguageCode=language,
    )


# --- Name tokenization ---
# Names get replaced with a stable, reversible token (<NAME_1>, <NAME_2>, ...).
# The mapping lives in session_state so the same name always maps to the same
# token within a session, and can optionally be revealed via the sidebar.

def get_name_token(original_name: str) -> str:
    mapping = st.session_state.setdefault("name_token_map", {})
    reverse = st.session_state.setdefault("name_reverse_map", {})

    key = original_name.strip().lower()
    if key not in mapping:
        token = f"<NAME_{len(mapping) + 1}>"
        mapping[key] = token
        reverse[token] = original_name
    return mapping[key]


# --- Email masking ---
# Emails are masked (not tokenized/reversible) - first character of the local
# part and the domain's TLD are kept so the value still "reads" as an email,
# everything else is replaced with asterisks.

def mask_email(email: str) -> str:
    if "@" not in email:
        return "*" * len(email)

    local, domain = email.split("@", 1)
    domain_parts = domain.split(".")

    masked_local = (local[0] + "*" * (len(local) - 1)) if local else "*"

    first_label = domain_parts[0]
    masked_first_label = (first_label[0] + "*" * (len(first_label) - 1)) if first_label else "*"
    masked_domain = ".".join([masked_first_label] + domain_parts[1:])

    return f"{masked_local}@{masked_domain}"


def redact_text(original_text: str, entities) -> str:
    """Rebuild the input text, substituting NAME entities with tokens and
    EMAIL entities with masked values. Other entity types are left as-is
    since this demo only handles name tokenization + email masking."""
    # Sort by position and guard against overlaps
    sorted_entities = sorted(entities, key=lambda e: e.get("BeginOffset", 0))

    pieces = []
    cursor = 0
    for e in sorted_entities:
        start = e.get("BeginOffset")
        end = e.get("EndOffset")
        etype = e.get("Type")

        if start is None or end is None or start < cursor:
            continue  # skip malformed / overlapping entities

        pieces.append(original_text[cursor:start])
        original_value = original_text[start:end]

        if etype == "NAME":
            pieces.append(get_name_token(original_value))
        elif etype == "EMAIL":
            pieces.append(mask_email(original_value))
        else:
            pieces.append(original_value)

        cursor = end

    pieces.append(original_text[cursor:])
    return "".join(pieces)


def render_pii_results(response, original_text: str):
    entities = response.get("Entities", [])
    if not entities:
        st.success("No PII entities detected.")
        return

    st.subheader("Detected PII entities")
    for e in entities:
        st.markdown(
            f"- **Type:** `{e.get('Type')}`  "
            f"**Score:** {e.get('Score'):.3f}  "
            f"**Offset:** {e.get('BeginOffset')}–{e.get('EndOffset')}"
        )

    st.subheader("Redacted text")
    st.caption("Names tokenized (reversible within this session), emails masked.")
    redacted = redact_text(original_text, entities)
    st.text_area("Output", value=redacted, height=200, disabled=True)

    name_map = st.session_state.get("name_reverse_map", {})
    if name_map:
        with st.expander("Name token mapping"):
            if reveal_mapping:
                for token, original_name in name_map.items():
                    st.markdown(f"- `{token}` → {original_name}")
            else:
                st.info(
                    f"{len(name_map)} name token(s) mapped this session. "
                    "Enable 'Reveal name token mapping' in the sidebar to view them."
                )

    st.subheader("Raw response (JSON)")
    st.code(json.dumps(response, indent=2), language="json")


def should_run_detection(text_value: str) -> bool:
    if not text_value or not text_value.strip():
        return False
    if auto_run:
        return True
    return run_button


# --- Real-time / on-demand detection ---
if should_run_detection(text):
    try:
        st.info("Calling Amazon Comprehend for PII detection...")
        resp = detect_pii(text, region, language_code)
        render_pii_results(resp, text)
    except (BotoCoreError, ClientError) as e:
        st.error(f"Comprehend call failed: {e}")
    except Exception as e:
        st.error(f"Unexpected error: {e}")