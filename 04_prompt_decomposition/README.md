# Prompt Decomposition Demo (Module 4)

A three-page Streamlit app that demonstrates **prompt decomposition** using the
frameworks from the Module 4 deck (*Prompt Engineering and Governance*). It
takes one messy, open-ended business question and shows how structure turns it
into an actionable, stakeholder-aware recommendation via Amazon Bedrock.

## The three acts (one per page)

| Page | Act | What it shows | Deck slide |
|------|-----|---------------|------------|
| **1 · Naive Baseline** | Act 1 | A single raw prompt → a generic, unstructured answer | Slide 18 "Before" |
| **2 · Dimensional Decomposition** | Act 2 | Split the question into Technical / Business / Risk, then answer each in isolation | Slide 19 |
| **3 · Step-by-Step Reasoning** | Act 3 | Run a dimension through the 6-step chain-of-thought structure, then synthesize all dimensions | Slide 18 "After" |

The scenario (editable on the home page) is a retailer deciding whether to
migrate its e-commerce platform to AWS.

## Prerequisites

- Python 3.9+
- AWS credentials available in your environment (AWS CLI profile, environment
  variables, or an IAM role) with permission to call Amazon Bedrock.
- **Model access** granted in the Bedrock console for the model you choose, in
  the region you choose. The default is Claude 3.5 Sonnet in `us-east-1`.

## Install and run

In bash, the quickest path is the launcher script, which creates the venv,
installs dependencies, and starts Streamlit:

```bash
cd /home/charlie/AdvDevGenAI/04_prompt_decomposition
./run.sh
```

Or do it manually:

```bash
cd /home/charlie/AdvDevGenAI/04_prompt_decomposition
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Then open the URL Streamlit prints (default http://localhost:8501) and set the
region and model ID in the sidebar.

## Files

```
prompt_decomposition_app/
├── app.py                      # Home page + shared sidebar wiring
├── shared.py                   # Session defaults + sidebar (no page side effects)
├── scenario.py                 # Scenario defaults + all prompt templates
├── bedrock_client.py           # Converse / Converse-stream helpers
├── requirements.txt
├── run.sh                      # Bash launcher: venv + install + streamlit run
└── pages/
    ├── 1_Naive_Baseline.py
    ├── 2_Dimensional_Decomposition.py
    └── 3_Step_by_Step_Reasoning.py
```

## Teaching flow

1. **Act 1**: run the naive prompt. Point out the answer is generic — no
   audience targeting, no cost/risk breakdown, not actionable.
2. **Act 2**: generate the decomposition (Technical / Business / Risk), then
   analyze each dimension. Each answer is now scoped to one stakeholder.
3. **Act 3**: stream the 6-step reasoning trail for a dimension live, then
   synthesize the dimensions into a single executive recommendation.

This maps cleanly into **Lab 2** (*Develop conversation pattern with Amazon
Bedrock APIs*): the same prompts run through the Converse API with streaming.

## Notes

- Toggle **Stream responses** in the sidebar for live token streaming (great
  for Act 1 and Act 3) or turn it off for a single blocking call.
- Dimension analyses are cached in session state, so you can run them on Act 2
  and still synthesize them on Act 3.
