# Page 3: semantic search over a corpus of IT sentences
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ann
import ann_plots
import core
import models
import ui

DATA = Path(__file__).resolve().parent.parent / "data"

st.title("3. Vector search: finding by meaning")
st.caption(
    "Embed every sentence in a small corpus once. To search, embed the query the same way and "
    "return the sentences whose vectors point in the closest direction (cosine similarity)."
)
ui.init_state()
minilm = ui.require_model(models.load_minilm, "all-MiniLM-L6-v2", models.MINILM_NAME, "90 MB")

corpus = json.loads((DATA / "corpus.json").read_text())
texts = [c["text"] for c in corpus]
topics = [c["topic"] for c in corpus]


@st.cache_resource(show_spinner="Embedding the corpus ...")
def corpus_vectors(_model, key):  # key = file contents, so edits to corpus.json re-embed
    return core.embed_texts(texts, _model)


cvecs = corpus_vectors(minilm, "\n".join(texts))

st.session_state.setdefault("vs_query", "server is down")
p1, p2, p3 = st.columns(3)
if p1.button("server is down"):
    st.session_state["vs_query"] = "server is down"
if p2.button("outage"):
    st.session_state["vs_query"] = "outage"
if p3.button("someone stole our passwords"):
    st.session_state["vs_query"] = "someone stole our passwords"
query = st.text_input("Search query", key="vs_query")
k = st.slider("Top-k results", 1, 10, 5)
if not query.strip():
    st.info("Type a query above.")
    st.stop()

qvec = core.embed_texts([query], minilm)[0]
sem = core.semantic_search(qvec, cvecs, k)
kw = core.keyword_search(query, texts, k)

st.subheader("Keyword search vs semantic search")
left, right = st.columns(2)
with left:
    st.markdown("**Keyword search** (shared words)")
    if kw:
        st.dataframe(
            pd.DataFrame({"shared words": [s for _, s in kw], "sentence": [texts[i] for i, _ in kw]}),
            hide_index=True,
        )
    else:
        st.warning("No sentence shares a word with the query: zero results.")
with right:
    st.markdown("**Semantic search** (vector similarity)")
    st.dataframe(
        pd.DataFrame(
            {"cosine": [round(s, 3) for _, s in sem], "sentence": [texts[i] for i, _ in sem], "topic": [topics[i] for i, _ in sem]}
        ),
        hide_index=True,
    )
st.caption(
    "Keyword search needs the same words. Search 'server is down' and it misses 'Major outage ...' and "
    "'Unplanned downtime ...', and it may match a sentence that only shares the word 'server'. "
    "Semantic search compares meaning, so these are found. It is not magic: scores for a short "
    "query are modest, and an odd result can still appear."
)

st.subheader("The corpus in 2D")
cxy, qxy, var = core.project_2d(cvecs, qvec)
hit = {i for i, _ in sem}
fig = go.Figure()
for topic in sorted(set(topics)):
    idx = [i for i, t in enumerate(topics) if t == topic]
    fig.add_trace(
        go.Scatter(
            x=cxy[idx, 0], y=cxy[idx, 1], mode="markers", name=topic,
            text=[texts[i] for i in idx], hovertemplate="%{text}<extra></extra>",
            marker=dict(size=[16 if i in hit else 9 for i in idx],
                        line=dict(width=[3 if i in hit else 0 for i in idx], color="black")),
        )
    )
fig.add_trace(
    go.Scatter(
        x=[qxy[0]], y=[qxy[1]], mode="markers+text", name="your query", text=["query"],
        textposition="top center", marker=dict(symbol="star", size=22, color="red"),
        hovertemplate=query + "<extra></extra>",
    )
)
fig.update_layout(height=520, xaxis_title="PCA 1", yaxis_title="PCA 2", margin=dict(t=20))
st.plotly_chart(fig, width="stretch")
st.caption(
    f"Each sentence has {cvecs.shape[1]} numbers. This picture squashes them to 2 with PCA, which keeps only "
    f"{var:.0%} of the variation, so points that look close here can be far apart in the full space, "
    "and the black-ringed top-k may not look like the nearest dots. Use the table for the real ranking."
)

# ------------------------------------------------------------------ scaling up: IVF and HNSW
st.header("Scaling up: how a million vectors are searched")
st.markdown(
    "With 35 sentences we compare the query with every one (**exact search**). With millions of vectors that is far "
    "too slow, because each comparison is hundreds of multiplications. Vector databases build an **index** that "
    "looks at only a small fraction of the vectors and accepts that the answer is *approximately* the nearest "
    "(**ANN**, approximate nearest neighbour). Two designs dominate: **IVF** and **HNSW**."
)
st.caption(
    "The animations below use 300 made-up 2D points so you can see the geometry. Real vectors have hundreds of "
    "dimensions, and these are simplified teaching versions of the algorithms (the code is under "
    "'Show the code' at the bottom)."
)

POINTS = ann.make_points()
c1, c2, c3 = st.columns(3)
nlist = c1.slider("IVF: number of cells (nlist)", 4, 10, 8)
M = c2.slider("HNSW: links per point (M)", 2, 8, 4)
kk = c3.slider("Neighbours wanted (k)", 1, 8, 5, key="ann_k")
sc1, sc2 = st.columns([1, 3])
qseed = sc1.number_input("Query number", min_value=0, max_value=999, value=2, step=1,
                         help="Each number is a different query point. Query 2 shows IVF missing a neighbour.")
sc2.caption("Try other query numbers. IVF misses neighbours when the query sits near the edge between two cells.")


@st.cache_resource(show_spinner=False)
def build_indexes(nlist, M):
    return ann.build_ivf(POINTS, nlist), ann.build_hnsw(POINTS, M)


ivf, hnsw = build_indexes(nlist, M)
Q = ann.make_query(POINTS, int(qseed))
TRUTH = ann.exact_knn(POINTS, Q, kk)

tab_ivf, tab_hnsw, tab_cmp = st.tabs(["IVF (clusters)", "HNSW (layered graph)", "Speed vs accuracy"])

with tab_ivf:
    st.markdown(
        "**IVF = Inverted File index.** Think of a library sorted into sections.\n\n"
        "1. **Build once:** group the vectors into `nlist` clusters with k-means. Each cluster has a centroid.\n"
        "2. **Search:** compare the query with the centroids only, pick the closest `nprobe` clusters, and scan just "
        "the vectors inside them.\n\n"
        "The catch: if a true neighbour sits in a cluster you skipped, you miss it. Raise `nprobe` to look in more "
        "clusters: better recall, slower search."
    )
    nprobe = st.slider("nprobe: how many cells to search", 1, nlist, 1)
    ivf_trace = ann.ivf_search(POINTS, ivf, Q, nprobe, kk)
    st.plotly_chart(ann_plots.ivf_figure(POINTS, ivf, Q, ivf_trace, TRUTH, kk), width="stretch", key="ivf_fig")
    st.caption("Press Play, or drag the Step slider to move through it at your own pace.")
    got = len(set(ivf_trace["result"]) & set(TRUTH))
    m1, m2, m3 = st.columns(3)
    m1.metric("Distance calculations", ivf_trace["distance_calcs"], f"{ivf_trace['distance_calcs'] - len(POINTS)} vs exact",
              delta_color="inverse")
    m2.metric("Exact search would use", len(POINTS))
    m3.metric(f"True top-{kk} found", f"{got} of {kk}")

with tab_hnsw:
    st.markdown(
        "**HNSW = Hierarchical Navigable Small World.** Think of a road network: motorways between cities, main "
        "roads inside a city, streets at the end.\n\n"
        "1. **Build once:** every point is linked to its `M` nearest neighbours. Each point is also randomly "
        "promoted to higher layers, and each higher layer has far fewer points, so its links cover long distances.\n"
        "2. **Search:** start at the top layer and keep stepping to whichever linked point is closest to the query. "
        "When no link gets you closer, drop down a layer and carry on from the same spot. On the bottom layer, "
        "explore outward and keep the best `ef` candidates.\n\n"
        "It rarely examines more than a few dozen points, even for millions of vectors. The cost is memory (the "
        "links) and a slower build. Raise `ef` for better recall at the price of more work."
    )
    ef = st.slider("ef: how many candidates to keep on the bottom layer (ef_search)", kk, 40, 8)
    h_trace = ann.hnsw_search(hnsw, POINTS, Q, kk, ef)
    st.plotly_chart(ann_plots.hnsw_figure(POINTS, hnsw, Q, h_trace, TRUTH, kk, max(ef, kk)), width="stretch", key="hnsw_fig")
    st.caption("Press Play, or drag the Step slider. The red line is the path the search walked.")
    got = len(set(h_trace["result"]) & set(TRUTH))
    m1, m2, m3 = st.columns(3)
    m1.metric("Distance calculations", h_trace["distance_calcs"], f"{h_trace['distance_calcs'] - len(POINTS)} vs exact",
              delta_color="inverse")
    m2.metric("Exact search would use", len(POINTS))
    m3.metric(f"True top-{kk} found", f"{got} of {kk}")

with tab_cmp:
    st.markdown(
        "Averaged over 60 random queries, each setting gives a point: how many distance calculations it needs "
        "(left is cheaper) and what share of the true nearest neighbours it finds (higher is better). "
        "Every ANN index lets you slide along a curve like this."
    )

    @st.cache_data(show_spinner="Running 60 queries per setting ...")
    def run_sweep(nlist, M, k):
        return ann.sweep(POINTS, nlist, M, k)

    rows = pd.DataFrame(run_sweep(nlist, M, kk))
    sfig = go.Figure()
    for name, colour in (("IVF", "#EF553B"), ("HNSW", "#2b4c9b")):
        d = rows[rows["index"] == name]
        sfig.add_trace(go.Scatter(x=d["distance_calcs"], y=d["recall"], mode="lines+markers+text", name=name,
                                  text=d["setting"], textposition="bottom right", line=dict(color=colour)))
    sfig.add_trace(go.Scatter(x=[len(POINTS)], y=[1.0], mode="markers+text", name="Exact (brute force)",
                              text=["exact"], textposition="top left", marker=dict(size=12, color="black", symbol="diamond")))
    sfig.update_layout(height=430, xaxis_title="Average distance calculations per query (lower is cheaper)",
                       yaxis_title=f"Recall@{kk} (share of true neighbours found)", yaxis=dict(range=[0, 1.05]),
                       margin=dict(t=20))
    st.plotly_chart(sfig, width="stretch", key="sweep_fig")
    st.markdown(
        "| | IVF | HNSW |\n|---|---|---|\n"
        "| Idea | Sort into clusters, search the closest few | Layered graph, walk towards the query |\n"
        "| Knob for accuracy | `nprobe` (FAISS), `probes` (pgvector `ivfflat`) | `ef_search` (OpenSearch, pgvector `hnsw`) |\n"
        "| Build knobs | `nlist` | `M`, `ef_construction` |\n"
        "| Build cost | Fast (k-means) | Slower, and uses more memory |\n"
        "| Typical failure | Neighbour sits in a skipped cell | Search settles in a poor local area (raise `ef`) |\n"
        "| Seen in | FAISS, pgvector, many large-scale systems | OpenSearch, pgvector, Qdrant, Pinecone and others |\n"
    )
    st.caption(
        "On 300 points everything is fast and the gap looks small. The saving matters at millions of vectors, "
        "where exact search is the cost you cannot pay. Index choice and the settings are tuned per workload."
    )

ui.code_expander("toy IVF and HNSW (ann.py)", ann.build_ivf, ann.ivf_search, ann.build_hnsw, ann.hnsw_search)
ui.code_expander("semantic and keyword search", core.embed_texts, core.semantic_search, core.keyword_search, core.project_2d)
ui.presenter_notes(
    """
- Press "server is down", then "outage". Show that 'outage' finds the matching incident sentences and a keyword search cannot.
- Show a keyword hit that is wrong ('server room' cooling): same word, different meaning.
- Try "someone stole our passwords": no shared words with the security sentences, yet they come back.
- The 2D plot is a sketch. The ranking is computed in 384 dimensions.
- This is the retrieval step in RAG: embed documents once, embed the question, take nearest neighbours, give them to the LLM.
- Note this uses the embedding model, not GPT-2. Searching does not generate text.
- Scaling section: exact search compares against every vector, which does not work at millions. ANN indexes trade a little accuracy for a lot of speed.
- IVF tab: press Play. Cells, then query vs centroids only, then scan the chosen cell. With nprobe=1 on query 2 a true neighbour is missed (red cross). Raise nprobe to fix it and watch the distance calculations grow.
- HNSW tab: press Play. Top layer long hops, drop down, finish on the bottom layer. Compare the calculation count with the exact total.
- Speed vs accuracy tab: every setting is a point on a curve. Nothing is free: more recall costs more work.
- Honest caveat: 2D toy data and simplified algorithms. Real vectors are 384+ dimensions and real indexes (FAISS, OpenSearch, pgvector) have more engineering.
"""
)
