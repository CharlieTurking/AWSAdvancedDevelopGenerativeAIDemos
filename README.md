# AdvGenAIDev

WSL demos for the Advanced GenAI Development on AWS course.

## Shared Python environment

All the lightweight Streamlit demos (modules 01–04 and 06–10, excluding
everything under `00_misc/`) run from a single shared virtual environment at the
repo root. There is no longer a per-demo `.venv` for these demos.

```bash
cd ~/AdvDevGenAI
python3 -m venv .venv            # first time only
source .venv/bin/activate
pip install -r requirements.txt  # first time / when deps change
```

Then launch any demo from its own folder, e.g.:

```bash
source ~/AdvDevGenAI/.venv/bin/activate
streamlit run 09_llm_judge/app.py
# or: cd 09_llm_judge && streamlit run app.py
```

Demos under `00_misc/` (including `prompt-compression`, which needs `torch` /
LlamaIndex) keep their own environments and are out of scope for the shared venv.

## Choosing a model in the demos — `models.json`

The Streamlit demos read the list of selectable Bedrock models from
[`models.json`](./models.json) at the repo root. Each demo shows a dropdown of
these models plus a **Custom…** option (which reveals a free-text box for any
model ID you have access to).

To add, remove, or rename a model for **every** demo at once, edit
`models.json`:

```json
{
  "llm_models": [
    { "id": "us.anthropic.claude-haiku-5-5", "label": "Claude Haiku 5.5 (us)", "default": true }
  ],
  "embedding_models": [
    { "id": "amazon.titan-embed-text-v2:0", "label": "Titan Text Embeddings v2", "default": true }
  ]
}
```

- `id` — the exact Bedrock model ID passed to the Converse / embeddings API.
- `label` — the human-friendly name shown in the dropdown.
- `default` — optional; marks the entry preselected when a demo has no specific
  default of its own.
- `supports_temperature` — optional (LLM models only); set `false` for models
  that reject the `temperature` inference parameter (e.g. OpenAI gpt-oss and
  Claude Haiku 5.5). When `false`, the demos omit `temperature` from the Converse
  call and disable the temperature slider in the UI. Omitted or `true` means the
  parameter is sent as normal, so untagged and custom models behave as before.

No code changes are needed — relaunch a demo and the new list appears in every
dropdown. The shared loader lives in [`model_catalog.py`](./model_catalog.py),
which also exposes `supports_temperature()` and `build_inference_config()` used
by the demo Bedrock wrappers.
