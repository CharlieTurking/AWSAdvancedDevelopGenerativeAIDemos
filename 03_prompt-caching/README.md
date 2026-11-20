# Prompt Caching with Amazon Bedrock

A Jupyter notebook demo showing how prompt caching on Amazon Bedrock reduces
latency and input token cost by caching a large, stable prompt prefix and
reusing it across multiple queries.

Notebook: `prompt_caching_bedrock_demo.ipynb`

## Prerequisites

- Python 3.12 (a `.venv` is used for an isolated environment)
- AWS credentials configured (`aws configure`, or `AWS_*` environment variables)
- Amazon Bedrock model access enabled for `us.anthropic.claude-sonnet-4-6`
  in the `us-east-1` region

## First-time setup

```bash
cd 03_prompt-caching
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Start JupyterLab

With the venv activated:

```bash
jupyter lab
```

Or without activating:

```bash
.venv/bin/jupyter lab
```

JupyterLab opens in your browser at `http://localhost:8888/lab`. Open
`prompt_caching_bedrock_demo.ipynb` and run the cells top to bottom. Press
`Ctrl+C` in the terminal to stop the server.

Useful variations:

```bash
jupyter lab prompt_caching_bedrock_demo.ipynb  # open this notebook on launch
jupyter lab --no-browser                       # don't auto-open; copy the URL yourself
jupyter lab --port 8889                        # use a different port if 8888 is taken
```

## What the notebook demonstrates

1. A baseline call with no caching (full context processed every time)
2. A cache WRITE call (first use — Bedrock processes and saves the prefix)
3. Cache READ calls (subsequent uses — prefix retrieved from cache, faster and cheaper)
4. A side-by-side comparison of latency and token usage

## Notes

- The notebook title says "Run in windows," but nothing in it is
  Windows-specific; it runs fine on Linux/macOS.
- Cached prefixes have a time-to-live (around 5 minutes of inactivity for many
  models), so run the cached calls in reasonably quick succession to see cache hits.
