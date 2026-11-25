# Shared UI helpers for all pages.
import html
import inspect

import streamlit as st

import models

DEFAULT_SENTENCE = "The server went down because the database ran out of"
CHIP_COLOURS = ["#cfe8ff", "#ffe2c2", "#d7f5d3", "#f5d3ee", "#fff3b0", "#d9d4ff"]


def init_state():
    st.session_state.setdefault("sentence", DEFAULT_SENTENCE)


def sentence_input(page_key):
    """Editable starting sentence shared by every page (kept in st.session_state['sentence'])."""
    init_state()
    key = f"sentence_widget_{page_key}"
    # once the widget has state, passing value= as well makes Streamlit warn when a callback has set that state
    kwargs = {} if key in st.session_state else {"value": st.session_state["sentence"]}
    value = st.text_input("Starting sentence (shared by all pages)", key=key, **kwargs)
    st.session_state["sentence"] = value
    return value


def require_model(loader, label, name, size):
    """Load a model, or show a clear message with a download button and stop the page."""
    try:
        return loader()
    except models.ModelNotAvailable:
        st.error(
            f"The model **{label}** is not downloaded yet (about {size}). "
            "This demo runs fully offline once the model is cached."
        )
        st.caption("One-time download, needs internet. You can also run the command in the README.")
        if st.button(f"Download {label}", key=f"dl_{name}"):
            with st.spinner(f"Downloading {label} ..."):
                try:
                    models.download_model(name)
                except Exception as exc:  # network errors etc.
                    st.error(f"Download failed: {exc}")
                    st.stop()
            st.rerun()
        st.stop()


def code_expander(title, *objs):
    """Show the real source of the functions the page runs."""
    with st.expander(f"Show the code: {title}"):
        for obj in objs:
            st.code(inspect.getsource(obj), language="python")


def presenter_notes(text):
    with st.expander("Presenter notes"):
        st.markdown(text)


def chips_html(pieces):
    """Coloured chips, one per token. Spaces are shown as a visible dot."""
    spans = []
    for i, p in enumerate(pieces):
        shown = html.escape(p).replace(" ", "&middot;").replace("\n", "&crarr;") or "&nbsp;"
        spans.append(
            f'<span style="background:{CHIP_COLOURS[i % len(CHIP_COLOURS)]};color:#111;'
            'padding:3px 6px;margin:2px;border-radius:5px;display:inline-block;'
            f'font-family:monospace;font-size:1.05rem;">{shown}</span>'
        )
    return "".join(spans)
def weighted_chips_html(pieces, weights, selected):
    """Chips shaded by attention weight (0-1). Tokens after `selected` are grey: a causal model cannot see them."""
    spans = []
    for i, p in enumerate(pieces):
        shown = html.escape(p).replace(" ", "&middot;").replace("\n", "&crarr;") or "&nbsp;"
        if i > selected:
            bg, tip, border = "#eceef1", "cannot be seen yet (it comes later)", "1px dashed #b5b9bf"
        else:
            w = float(min(max(weights[i], 0.0), 1.0))
            bg = f"rgb({round(255 - 190 * w)},{round(255 - 120 * w)},255)"
            tip, border = f"weight {w:.3f}", "2px solid #111" if i == selected else "1px solid #c3d4ea"
        spans.append(
            f'<span title="{tip}" style="background:{bg};color:{"#999" if i > selected else "#111"};border:{border};'
            'padding:3px 6px;margin:2px;border-radius:5px;display:inline-block;'
            f'font-family:monospace;font-size:1.05rem;">{shown}<sub style="font-size:0.65rem;">{i}</sub></span>'
        )
    return "".join(spans)
