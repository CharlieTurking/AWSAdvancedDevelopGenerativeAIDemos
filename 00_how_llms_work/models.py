# Model loaders for the demo. Models are cached with st.cache_resource.
# Loading never touches the network unless download=True (the explicit "Download" button).
import os

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import streamlit as st

GPT2_NAME = "gpt2"  # GPT-2 small, 124M parameters
MINILM_NAME = "sentence-transformers/all-MiniLM-L6-v2"  # 384-dim sentence embeddings


class ModelNotAvailable(Exception):
    """Raised when a model is not in the local Hugging Face cache."""


@st.cache_resource(show_spinner="Loading GPT-2 ...")
def _load_gpt2():
    from transformers import AutoModelForCausalLM, AutoTokenizer

    try:
        tok = AutoTokenizer.from_pretrained(GPT2_NAME, local_files_only=True)
        # eager attention: the default (sdpa) does not return attention weights
        model = AutoModelForCausalLM.from_pretrained(GPT2_NAME, local_files_only=True, attn_implementation="eager")
    except Exception as exc:
        raise ModelNotAvailable(str(exc)) from exc
    model.eval()
    return model, tok


@st.cache_resource(show_spinner="Loading all-MiniLM-L6-v2 ...")
def _load_minilm():
    from sentence_transformers import SentenceTransformer

    try:
        return SentenceTransformer(MINILM_NAME, local_files_only=True, device="cpu")
    except Exception as exc:
        raise ModelNotAvailable(str(exc)) from exc


def load_gpt2():
    """Return (model, tokenizer) for GPT-2 small."""
    return _load_gpt2()


def load_minilm():
    """Return the MiniLM sentence-transformer."""
    return _load_minilm()


def download_model(name: str) -> None:
    """Download a model into the local cache (needs internet). Called by the Download button."""
    if name == GPT2_NAME:
        from transformers import AutoModelForCausalLM, AutoTokenizer

        AutoTokenizer.from_pretrained(GPT2_NAME)
        AutoModelForCausalLM.from_pretrained(GPT2_NAME)
    else:
        from sentence_transformers import SentenceTransformer

        SentenceTransformer(MINILM_NAME, device="cpu")
    # a failed earlier load is not cached by st.cache_resource, so no clearing is needed
