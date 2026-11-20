"""
Shared model catalog for the Streamlit demos.

A single source of truth for the Bedrock model IDs offered in the demos. The
list lives in ``models.json`` at the repository root; every in-scope demo imports
this module (they all run under the shared root ``.venv``) and renders a dropdown
with a "Custom…" escape hatch instead of a free-text model-ID box.

Three entry points:

- ``load_catalog()``            -> parsed {"llm_models": [...], "embedding_models": [...]}
- ``resolve_options(kind, current_default)`` -> (options, index) — pure, no Streamlit
- ``model_selectbox(label, kind, current_default)`` -> selected model ID (Streamlit)

``resolve_options`` deliberately avoids importing Streamlit so it stays unit
testable. ``model_selectbox`` imports Streamlit lazily inside the function.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

# Sentinel label for the free-text escape hatch. Always the last option.
CUSTOM_LABEL = "Custom…"

# Valid catalog kinds -> key in models.json.
_KIND_TO_KEY = {
    "llm": "llm_models",
    "embedding": "embedding_models",
}


def _find_models_file(start_dir: Optional[str] = None) -> str:
    """Locate ``models.json`` by walking up from ``start_dir`` (or CWD).

    Demos are launched with ``streamlit run app.py`` from inside their own
    folder, so the catalog is found relative to the working directory by walking
    up toward the repository root. As a fallback we also walk up from this
    module's own location, which covers unusual working directories.
    """
    candidates = []
    if start_dir is not None:
        candidates.append(start_dir)
    candidates.append(os.getcwd())
    candidates.append(os.path.dirname(os.path.abspath(__file__)))

    for base in candidates:
        current = os.path.abspath(base)
        while True:
            candidate = os.path.join(current, "models.json")
            if os.path.isfile(candidate):
                return candidate
            parent = os.path.dirname(current)
            if parent == current:  # reached filesystem root
                break
            current = parent

    raise FileNotFoundError(
        "Could not locate models.json by walking up from "
        f"{candidates!r}. Expected it at the repository root."
    )


@lru_cache(maxsize=None)
def _load_cached(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def load_catalog(start_dir: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Load and parse ``models.json``.

    Returns a dict with ``llm_models`` and ``embedding_models`` lists (each entry
    a dict with at least ``id`` and ``label``). Missing lists default to empty.
    """
    path = _find_models_file(start_dir)
    data = json.loads(_load_cached(path))
    return {
        "llm_models": list(data.get("llm_models", [])),
        "embedding_models": list(data.get("embedding_models", [])),
    }


def _models_for_kind(kind: str, start_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    if kind not in _KIND_TO_KEY:
        raise ValueError(
            f"Unknown model kind {kind!r}; expected one of {sorted(_KIND_TO_KEY)}"
        )
    catalog = load_catalog(start_dir)
    return catalog[_KIND_TO_KEY[kind]]


def resolve_options(
    kind: str,
    current_default: Optional[str] = None,
    start_dir: Optional[str] = None,
) -> Tuple[List[Dict[str, str]], int]:
    """Build the ordered option list and the preselect index for a dropdown.

    Pure function (no Streamlit import) so it can be unit tested.

    Each option is a dict ``{"id", "label"}``. The returned list always ends with
    a ``Custom…`` option whose ``id`` is ``None``. Selection rules:

    - If ``current_default`` matches a catalog entry's id, that entry is
      preselected.
    - If ``current_default`` is set but not in the catalog, it is appended as a
      one-off option (so the demo's existing default is never lost) and
      preselected.
    - If ``current_default`` is falsy, the entry flagged ``"default": true`` is
      preselected, else the first entry.

    Returns ``(options, index)`` where ``options[index]`` is the preselected one.
    """
    models = _models_for_kind(kind, start_dir)

    options: List[Dict[str, str]] = [
        {"id": m["id"], "label": m.get("label", m["id"])} for m in models
    ]

    # Determine the preselect index.
    index: Optional[int] = None

    if current_default:
        for i, opt in enumerate(options):
            if opt["id"] == current_default:
                index = i
                break
        if index is None:
            # Preserve a demo's existing default even if it isn't in the catalog.
            options.append({"id": current_default, "label": f"{current_default} (current)"})
            index = len(options) - 1
    else:
        for i, m in enumerate(models):
            if m.get("default"):
                index = i
                break
        if index is None:
            index = 0 if options else 0

    # The Custom… escape hatch is always last.
    options.append({"id": None, "label": CUSTOM_LABEL})

    # If there were no models at all and no default, fall back to Custom…
    if not models and not current_default:
        index = 0  # points at Custom… (the only option)

    return options, index


def supports_temperature(model_id: str, start_dir: Optional[str] = None) -> bool:
    """Return whether ``model_id`` accepts a ``temperature`` inference parameter.

    Some Bedrock models (e.g. OpenAI gpt-oss and Claude Haiku 5.5) reject
    ``temperature`` in the Converse ``inferenceConfig`` and raise a
    ValidationException. The catalog carries a per-model ``supports_temperature``
    flag; this reads it.

    Default is ``True`` when the model is unknown or the flag is absent, so
    untagged catalog entries and the "Custom…" free-text option behave as before
    (temperature is sent). Tag a model ``"supports_temperature": false`` in
    models.json to stop sending the parameter for it.
    """
    try:
        models = _models_for_kind("llm", start_dir)
    except Exception:
        return True
    for m in models:
        if m.get("id") == model_id:
            return bool(m.get("supports_temperature", True))
    return True


def build_inference_config(
    model_id: str,
    max_tokens: int,
    temperature: Optional[float] = None,
    *,
    start_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Converse ``inferenceConfig`` dict, omitting unsupported params.

    ``maxTokens`` is always set. ``temperature`` is included only when it is not
    None and the selected model supports it (see :func:`supports_temperature`),
    so models that reject the parameter simply fall back to their default
    sampling instead of erroring.

    Pure (no Streamlit import) so it stays unit-testable.
    """
    cfg: Dict[str, Any] = {"maxTokens": max_tokens}
    if temperature is not None and supports_temperature(model_id, start_dir):
        cfg["temperature"] = temperature
    return cfg


def extract_text(response: Dict[str, Any]) -> str:
    """Pull the assistant text out of a Converse response, robustly.

    The Converse API returns a list of typed content blocks. For
    reasoning-capable models (e.g. Claude Haiku 5.5, OpenAI gpt-oss) the first
    block can be a non-text block such as ``reasoningContent`` or ``toolUse``,
    so indexing ``content[0]["text"]`` raises ``KeyError: 'text'``. This scans
    for the first block that actually carries ``text`` and returns it, falling
    back to an empty string when the turn produced no text block at all.
    """
    content_blocks = (
        response.get("output", {}).get("message", {}).get("content", []) or []
    )
    for block in content_blocks:
        if isinstance(block, dict) and "text" in block:
            return block["text"]
    return ""


def model_selectbox(
    label: str,
    kind: str = "llm",
    current_default: Optional[str] = None,
    *,
    key: Optional[str] = None,
    help: Optional[str] = None,
    start_dir: Optional[str] = None,
) -> str:
    """Render a Streamlit dropdown of catalog models plus a "Custom…" text box.

    Returns the selected model ID. When "Custom…" is chosen, a text input seeded
    with ``current_default`` is shown and its value returned.
    """
    import streamlit as st  # imported lazily so resolve_options stays pure

    options, index = resolve_options(kind, current_default, start_dir)
    labels = [opt["label"] for opt in options]

    select_key = key or f"model_select_{kind}_{label}"
    chosen_label = st.selectbox(label, labels, index=index, key=select_key, help=help)

    chosen = next(opt for opt in options if opt["label"] == chosen_label)

    if chosen["id"] is None:  # Custom… selected
        custom_key = f"{select_key}_custom"
        return st.text_input(
            f"{label} (custom)",
            value=current_default or "",
            key=custom_key,
            help="Enter any Bedrock model ID you have access to.",
        )

    return chosen["id"]
