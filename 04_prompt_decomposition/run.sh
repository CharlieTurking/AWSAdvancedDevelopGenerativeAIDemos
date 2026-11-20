#!/usr/bin/env bash
# Set up the venv (if needed) and launch the Prompt Decomposition Streamlit app.
set -euo pipefail

# Run from the directory this script lives in, regardless of where it's called.
cd "$(dirname "$0")"

# Create the virtual environment on first run.
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

# Activate it and install dependencies.
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# Launch the app.
exec streamlit run app.py
