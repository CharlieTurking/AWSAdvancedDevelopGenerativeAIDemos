#!/usr/bin/env bash
#
# One-shot runner for the local SHAP explainability demo.
#
# It will (idempotently):
#   1. create a .venv if one doesn't exist and install requirements
#   2. generate the synthetic dataset
#   3. train the model
#   4. produce the global + local SHAP plots and the bias table
#
# Then, unless you pass --no-app, it launches the interactive Streamlit app.
#
# Usage:
#   ./run_all.sh                 # full pipeline, then launch Streamlit
#   ./run_all.sh --no-app        # pipeline only (writes PNGs to outputs/)
#   ./run_all.sh --row 7         # explain a different applicant row
#   ./run_all.sh --row 7 --no-app
#
set -euo pipefail

# Always run from this script's own directory.
cd "$(dirname "$0")"

ROW=0
LAUNCH_APP=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-app) LAUNCH_APP=0; shift ;;
    --row)    ROW="${2:?--row needs a value}"; shift 2 ;;
    -h|--help)
      sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# --- 1. venv + deps ---
if [[ ! -d .venv ]]; then
  echo "== Creating virtual environment =="
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "== Installing requirements =="
pip install -q --upgrade pip
pip install -q -r requirements.txt

# --- 2-4. pipeline ---
echo "== Generating synthetic data =="
python generate_data.py

echo "== Training model =="
python train_model.py

echo "== Producing SHAP explanations (row ${ROW}) =="
python explain_shap.py --row "${ROW}"

echo
echo "Pipeline complete. Plots are in: $(pwd)/outputs"

# --- optional app ---
if [[ "${LAUNCH_APP}" -eq 1 ]]; then
  echo
  echo "== Launching Streamlit app (Ctrl+C to stop) =="
  echo "   If a browser doesn't open, go to http://localhost:8501"
  exec streamlit run app.py
else
  echo "Skipping Streamlit app (--no-app)."
fi
