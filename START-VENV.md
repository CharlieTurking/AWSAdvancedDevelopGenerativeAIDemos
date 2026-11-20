# Start the shared venv

One venv at the repo root serves all the demos (except those under `00_misc/`).

## Every time

```bash
wsl -d Ubuntu                                  # from Windows, if not already in WSL
source ~/AdvDevGenAI/.venv/bin/activate        # prompt now starts with (.venv)
```

Then run a demo:

```bash
cd ~/AdvDevGenAI/02_comprehend_pii_demo
streamlit run app.py
```

Stop a demo with `Ctrl+C`. Leave the venv with `deactivate`.

## First time only (or after deleting `.venv`)

```bash
cd ~/AdvDevGenAI
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Check it worked

```bash
which python        # should end in /AdvDevGenAI/.venv/bin/python
streamlit --version
```

AWS credentials come from your environment (CLI profile or env vars). Set the region with `export AWS_REGION=us-east-1` if needed.
