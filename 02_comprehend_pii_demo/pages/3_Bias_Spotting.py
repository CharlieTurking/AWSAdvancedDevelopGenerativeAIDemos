# Page 3: use Amazon Comprehend signals (sentiment, toxicity) to surface possible bias
import pandas as pd
import streamlit as st
from botocore.exceptions import BotoCoreError, ClientError

from comprehend_utils import (
    SAMPLE_DIR,
    detect_sentiments,
    detect_toxicity,
    net_sentiment,
    show_code,
    sidebar,
)

MAX_UPLOAD_ROWS = 300

st.title("Spotting possible bias with Amazon Comprehend")

region, language_code = sidebar()

st.info(
    "**Comprehend has no bias-detection API.** What it gives you are signals: sentiment and "
    "toxicity. This page uses them two ways: (1) compare sentiment across demographic groups "
    "for text that should be treated alike, and (2) flag hateful or abusive wording. A gap is a "
    "prompt to investigate, not proof of bias. For statistical bias audits of datasets and "
    "models, use Amazon SageMaker Clarify."
)

tab_sentiment, tab_toxicity = st.tabs(["Sentiment by group", "Toxic and hateful language"])


# ==========================================================================
# Tab 1: sentiment gap between groups
# ==========================================================================
with tab_sentiment:
    st.markdown(
        "Run text about different groups through Comprehend's sentiment analysis and compare "
        "the averages. If equivalent situations get systematically more negative wording for "
        "one group, that is a bias signal."
    )
    show_code(detect_sentiments, net_sentiment)

    source = st.radio("Data", ["Sample dataset", "Upload my own CSV"], horizontal=True)
    sample_path = SAMPLE_DIR / "bias_dataset.csv"

    if source == "Sample dataset":
        sample = pd.read_csv(sample_path)
        scenario = st.selectbox("Scenario", list(dict.fromkeys(sample["scenario"])))
        data = sample[sample["scenario"] == scenario][["group", "text"]].reset_index(drop=True)
        dataset_key = f"sample|{scenario}"
        st.download_button(
            "Download the sample dataset (CSV)",
            data=sample_path.read_bytes(),
            file_name="bias_dataset.csv",
            mime="text/csv",
        )
    else:
        uploaded = st.file_uploader("CSV with the columns `group` and `text`", type="csv")
        data, dataset_key = None, None
        if uploaded is not None:
            frame = pd.read_csv(uploaded)
            frame.columns = [c.strip().lower() for c in frame.columns]
            if not {"group", "text"} <= set(frame.columns):
                st.error("The CSV needs `group` and `text` columns.")
            else:
                frame = frame[["group", "text"]].dropna()
                if len(frame) > MAX_UPLOAD_ROWS:
                    st.warning(f"Using the first {MAX_UPLOAD_ROWS} rows to keep the demo quick.")
                data = frame.head(MAX_UPLOAD_ROWS).reset_index(drop=True)
                dataset_key = f"upload|{uploaded.name}|{len(data)}"

    if data is not None:
        st.dataframe(data, hide_index=True, height=220)

        if st.button("Analyse sentiment with Comprehend", type="primary"):
            try:
                with st.spinner(f"Calling Amazon Comprehend for {len(data)} texts..."):
                    results = detect_sentiments(data["text"].tolist(), region, language_code)
                scored = data.copy()
                scored["sentiment"] = [r["Sentiment"] for r in results]
                scored["net_sentiment"] = [round(net_sentiment(r), 3) for r in results]
                st.session_state["bias_sentiment"] = {"key": dataset_key, "frame": scored}
            except (BotoCoreError, ClientError, RuntimeError) as e:
                st.error(f"Comprehend call failed: {e}")

    saved = st.session_state.get("bias_sentiment")
    if data is not None and saved and saved["key"] == dataset_key:
        scored = saved["frame"]
        grouped = scored.groupby("group")
        summary = pd.DataFrame(
            {
                "texts": grouped.size(),
                "avg_net_sentiment": grouped["net_sentiment"].mean().round(3),
                "% negative": grouped["sentiment"].apply(lambda s: (s == "NEGATIVE").mean() * 100).round(0),
                "% mixed": grouped["sentiment"].apply(lambda s: (s == "MIXED").mean() * 100).round(0),
                "% positive": grouped["sentiment"].apply(lambda s: (s == "POSITIVE").mean() * 100).round(0),
            }
        )

        st.subheader("Sentiment by group")
        threshold = st.slider(
            "Flag a gap in average net sentiment of at least",
            0.05, 1.0, 0.25, 0.05,
            help="Net sentiment = Positive score minus Negative score, from -1 to +1.",
        )
        st.dataframe(summary)
        st.bar_chart(summary["avg_net_sentiment"])

        highest, lowest = summary["avg_net_sentiment"].idxmax(), summary["avg_net_sentiment"].idxmin()
        gap = summary["avg_net_sentiment"].max() - summary["avg_net_sentiment"].min()
        if len(summary) < 2:
            st.info("Only one group in this data, so there is nothing to compare.")
        elif gap >= threshold:
            st.warning(
                f"**Possible bias signal.** Text about **{lowest}** averages {gap:.2f} lower net "
                f"sentiment than text about **{highest}** (flag threshold {threshold:.2f}). "
                "Check that the texts describe comparable situations, then look at the wording below."
            )
        else:
            st.success(
                f"No large sentiment gap between groups (gap {gap:.2f}, flag threshold {threshold:.2f})."
            )
        st.caption("Small samples are noisy. A real review needs far more data and a significance test.")

        with st.expander("Every text and its sentiment"):
            st.dataframe(scored.sort_values(["group", "net_sentiment"]), hide_index=True)


# ==========================================================================
# Tab 2: toxic and hateful language
# ==========================================================================
with tab_toxicity:
    st.markdown(
        "Comprehend's toxicity detection scores each text from 0 to 1 and labels it: "
        "`HATE_SPEECH`, `INSULT`, `HARASSMENT_OR_ABUSE`, `VIOLENCE_OR_THREAT`, `PROFANITY`, "
        "`SEXUAL` and `GRAPHIC`. `HATE_SPEECH` is the label closest to bias."
    )
    show_code(detect_toxicity)

    default_lines = (SAMPLE_DIR / "toxicity_samples.txt").read_text(encoding="utf-8")
    lines_text = st.text_area("One text per line", value=default_lines, height=240)
    lines = [line.strip() for line in lines_text.splitlines() if line.strip()]
    flag_at = st.slider("Flag a label scoring at least", 0.1, 0.95, 0.5, 0.05)

    if st.button("Check toxicity with Comprehend", type="primary", disabled=not lines):
        try:
            with st.spinner(f"Calling Amazon Comprehend for {len(lines)} texts..."):
                tox_results = detect_toxicity(lines, region, language_code)
            st.session_state["bias_toxicity"] = {"lines": lines, "results": tox_results}
        except (BotoCoreError, ClientError) as e:
            st.error(f"Comprehend call failed: {e}")

    saved_tox = st.session_state.get("bias_toxicity")
    if saved_tox:
        rows = []
        for line, res in zip(saved_tox["lines"], saved_tox["results"]):
            labels = {lab["Name"]: round(lab["Score"], 2) for lab in res["Labels"]}
            flagged = [name for name, score in labels.items() if score >= flag_at]
            rows.append(
                {
                    "Text": line,
                    "Toxicity": round(res["Toxicity"], 2),
                    "Flagged as": ", ".join(flagged) if flagged else "-",
                    **labels,
                }
            )
        table = pd.DataFrame(rows)
        st.dataframe(
            table,
            hide_index=True,
            column_config={"Toxicity": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0)},
        )
        st.caption(
            "Toxicity detection catches hostile language. Polite or subtle stereotypes can score "
            "low, so use it alongside the group comparison rather than instead of it."
        )
