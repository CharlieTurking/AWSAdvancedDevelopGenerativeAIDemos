"""Unit tests for the shared model catalog helper (model_catalog.py).

These cover the pure, Streamlit-free surface: load_catalog() and
resolve_options(). The Streamlit model_selectbox() is a thin wrapper over
resolve_options() and is exercised manually in the demos.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

# Make the repo root importable regardless of where pytest is invoked from.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import model_catalog  # noqa: E402
from model_catalog import (  # noqa: E402
    CUSTOM_LABEL,
    build_inference_config,
    extract_text,
    load_catalog,
    resolve_options,
    supports_temperature,
)


# ----------------------------- load_catalog ------------------------------


def test_load_catalog_finds_and_parses_both_lists():
    catalog = load_catalog(start_dir=REPO_ROOT)
    assert "llm_models" in catalog
    assert "embedding_models" in catalog
    assert isinstance(catalog["llm_models"], list)
    assert isinstance(catalog["embedding_models"], list)
    assert catalog["llm_models"], "expected at least one LLM model"
    assert catalog["embedding_models"], "expected at least one embedding model"
    # Every entry carries an id.
    for entry in catalog["llm_models"] + catalog["embedding_models"]:
        assert "id" in entry


def test_load_catalog_contains_all_current_demo_defaults():
    """No demo may regress: every currently-defaulted ID must be present."""
    catalog = load_catalog(start_dir=REPO_ROOT)
    llm_ids = {m["id"] for m in catalog["llm_models"]}
    embed_ids = {m["id"] for m in catalog["embedding_models"]}

    required_llm = {
        "us.anthropic.claude-haiku-5-5",
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    }
    required_embed = {"amazon.titan-embed-text-v2:0"}

    assert required_llm <= llm_ids
    assert required_embed <= embed_ids


def test_load_catalog_falls_back_to_module_dir(tmp_path):
    """From an unrelated dir, the module-location fallback still finds the file.

    _find_models_file walks up from start_dir, then CWD, then this module's own
    directory (the repo root). So even a temp dir with no models.json resolves to
    the repo-root catalog rather than failing — the robustness the fallback buys.
    """
    catalog = load_catalog(start_dir=str(tmp_path))
    assert catalog["llm_models"], "fallback to module dir should find the catalog"


def test_find_models_file_raises_when_truly_unreachable(tmp_path, monkeypatch):
    """When no candidate path can reach a models.json, raise FileNotFoundError."""
    # Point the module's own directory at an empty temp tree and run from one too,
    # so none of the three candidate roots contain models.json.
    fake_module_file = tmp_path / "fake_pkg" / "model_catalog.py"
    fake_module_file.parent.mkdir(parents=True)
    monkeypatch.setattr(model_catalog, "__file__", str(fake_module_file))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        model_catalog._find_models_file(start_dir=str(tmp_path))


# ---------------------------- resolve_options ----------------------------


def test_custom_is_always_last_and_has_none_id():
    options, _ = resolve_options("llm", start_dir=REPO_ROOT)
    assert options[-1]["label"] == CUSTOM_LABEL
    assert options[-1]["id"] is None
    # Custom appears exactly once.
    assert [o["label"] for o in options].count(CUSTOM_LABEL) == 1


def test_matching_default_is_preselected():
    target = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    options, index = resolve_options("llm", target, start_dir=REPO_ROOT)
    assert options[index]["id"] == target


def test_catalog_default_flag_preselected_when_no_current_default():
    options, index = resolve_options("llm", None, start_dir=REPO_ROOT)
    # The seeded models.json marks Claude Haiku 5.5 as default.
    assert options[index]["id"] == "us.anthropic.claude-haiku-5-5"


def test_unknown_current_default_is_appended_and_preselected():
    unknown = "some.custom.model-not-in-catalog:0"
    options, index = resolve_options("llm", unknown, start_dir=REPO_ROOT)
    assert options[index]["id"] == unknown
    # It is appended just before the Custom… sentinel.
    assert options[-1]["label"] == CUSTOM_LABEL
    assert options[-2]["id"] == unknown


def test_embedding_kind_resolves_independently():
    options, index = resolve_options(
        "embedding", "amazon.titan-embed-text-v2:0", start_dir=REPO_ROOT
    )
    assert options[index]["id"] == "amazon.titan-embed-text-v2:0"
    assert options[-1]["label"] == CUSTOM_LABEL


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        resolve_options("not-a-kind", start_dir=REPO_ROOT)


# ------------------------- temperature capability ------------------------


def test_supports_temperature_known_offenders_are_false():
    # Both of these reject the temperature inference parameter.
    assert supports_temperature("openai.gpt-oss-20b-1:0", start_dir=REPO_ROOT) is False
    assert supports_temperature("us.anthropic.claude-haiku-5-5", start_dir=REPO_ROOT) is False


def test_supports_temperature_supporting_model_is_true():
    assert supports_temperature(
        "us.anthropic.claude-haiku-4-5-20251001-v1:0", start_dir=REPO_ROOT
    ) is True
    assert supports_temperature("amazon.nova-pro-v1:0", start_dir=REPO_ROOT) is True


def test_supports_temperature_unknown_model_defaults_true():
    # Unknown / custom model ids default to supported so behavior is unchanged.
    assert supports_temperature("some.custom.model:0", start_dir=REPO_ROOT) is True


def test_build_inference_config_omits_temperature_for_unsupported():
    cfg = build_inference_config(
        "openai.gpt-oss-20b-1:0", 512, 0.3, start_dir=REPO_ROOT
    )
    assert cfg == {"maxTokens": 512}
    assert "temperature" not in cfg


def test_build_inference_config_includes_temperature_for_supported():
    cfg = build_inference_config(
        "us.anthropic.claude-haiku-4-5-20251001-v1:0", 512, 0.3, start_dir=REPO_ROOT
    )
    assert cfg == {"maxTokens": 512, "temperature": 0.3}


def test_build_inference_config_omits_temperature_when_none():
    cfg = build_inference_config(
        "us.anthropic.claude-haiku-4-5-20251001-v1:0", 256, None, start_dir=REPO_ROOT
    )
    assert cfg == {"maxTokens": 256}


def test_build_inference_config_always_has_max_tokens():
    for mid in [
        "openai.gpt-oss-20b-1:0",
        "us.anthropic.claude-haiku-5-5",
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    ]:
        cfg = build_inference_config(mid, 1024, 0.7, start_dir=REPO_ROOT)
        assert cfg["maxTokens"] == 1024


# ----------------------------- extract_text ------------------------------


def _resp(content_blocks):
    return {"output": {"message": {"content": content_blocks}}}


def test_extract_text_first_block_is_text():
    assert extract_text(_resp([{"text": "hello"}])) == "hello"


def test_extract_text_skips_leading_reasoning_block():
    # Reasoning models (Haiku 5.5, gpt-oss) put reasoningContent first; the old
    # content[0]["text"] raised KeyError: 'text' on exactly this shape.
    resp = _resp([
        {"reasoningContent": {"reasoningText": {"text": "thinking..."}}},
        {"text": "the answer"},
    ])
    assert extract_text(resp) == "the answer"


def test_extract_text_no_text_block_returns_empty_string():
    resp = _resp([{"reasoningContent": {"reasoningText": {"text": "only thinking"}}}])
    assert extract_text(resp) == ""


def test_extract_text_empty_or_malformed_response():
    assert extract_text({}) == ""
    assert extract_text({"output": {"message": {}}}) == ""
    assert extract_text(_resp([])) == ""
