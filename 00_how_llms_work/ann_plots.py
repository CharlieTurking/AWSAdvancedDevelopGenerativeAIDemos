# Animated Plotly figures for the IVF and HNSW searches in ann.py.
# Each figure is a set of frames (one per step) with a Play button and a step slider.
import numpy as np
import plotly.graph_objects as go

PALETTE = ["#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A", "#19D3F3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52"]
GREY, FADED = "#9aa0a6", "#e3e5e8"


def _xy(points, idx):
    idx = list(idx)
    return points[idx, 0] if idx else [], points[idx, 1] if idx else []


def _segments(points, pairs):
    xs, ys = [], []
    for a, b in pairs:
        xs += [points[a][0], points[b][0], None]
        ys += [points[a][1], points[b][1], None]
    return xs, ys


def _ring(points, idx, colour, symbol="circle-open", size=17, width=3, name=""):
    x, y = _xy(points, idx)
    return go.Scatter(x=x, y=y, mode="markers", name=name, hoverinfo="skip",
                      marker=dict(symbol=symbol, size=size, color=colour, line=dict(color=colour, width=width)))


def _finish(frames, title_first, height=560, duration=1300):
    steps = [
        dict(method="animate", label=str(i + 1),
             args=[[f.name], dict(mode="immediate", frame=dict(duration=0, redraw=True), transition=dict(duration=0))])
        for i, f in enumerate(frames)
    ]
    fig = go.Figure(data=frames[0].data, frames=frames)
    fig.update_layout(
        title=dict(text=title_first, x=0.01, font=dict(size=15)),
        height=height, margin=dict(t=70, b=10, l=10, r=10), showlegend=False,
        xaxis=dict(visible=False, range=[-1.5, 11.5]),
        yaxis=dict(visible=False, scaleanchor="x", range=[-1.5, 11.5]),
        plot_bgcolor="white",
        updatemenus=[dict(
            type="buttons", direction="left", x=0.0, y=-0.02, xanchor="left", yanchor="top", showactive=False,
            buttons=[
                dict(label="Play", method="animate",
                     args=[None, dict(frame=dict(duration=duration, redraw=True), fromcurrent=True, transition=dict(duration=0))]),
                dict(label="Pause", method="animate",
                     args=[[None], dict(mode="immediate", frame=dict(duration=0, redraw=False), transition=dict(duration=0))]),
            ],
        )],
        sliders=[dict(active=0, steps=steps, x=0.18, len=0.8, y=-0.02, yanchor="top",
                      currentvalue=dict(prefix="Step ", font=dict(size=13)))],
    )
    return fig


def _frame(name, title, traces):
    return go.Frame(name=str(name), data=traces, layout=dict(title=dict(text=title, x=0.01, font=dict(size=15))))


# ---------------------------------------------------------------- IVF
def ivf_figure(points, ivf, q, trace, truth, k):
    cents, assign, nlist = ivf["centroids"], ivf["assign"], ivf["nlist"]
    colours = [PALETTE[a % len(PALETTE)] for a in assign]
    probed = set(trace["probed"])
    nprobe = len(probed)
    scanned = set(trace["scanned"])
    result = trace["result"]
    missed = [i for i in truth if i not in result]
    found = len(truth) - len(missed)
    cent_colours = [PALETTE[c % len(PALETTE)] for c in range(nlist)]

    def traces(point_colours, show_cents, lines=None, line_colour=GREY, ring=(), res=(), miss=(), show_q=True):
        lx, ly = ([], [])
        if lines:
            lx, ly = _segments(np.vstack([points, cents, q[None]]),
                               [(len(points) + nlist, len(points) + c) for c in lines])
        cx, cy = (cents[:, 0], cents[:, 1]) if show_cents else ([], [])
        return [
            go.Scatter(x=points[:, 0], y=points[:, 1], mode="markers", hoverinfo="skip",
                       marker=dict(size=7, color=point_colours)),
            go.Scatter(x=cx, y=cy, mode="markers", hoverinfo="skip",
                       marker=dict(symbol="diamond", size=17, color=cent_colours, line=dict(color="black", width=2))),
            go.Scatter(x=lx, y=ly, mode="lines", hoverinfo="skip", line=dict(color=line_colour, width=2, dash="dot")),
            _ring(points, ring, "black", size=15, width=2),
            _ring(points, res, "#0a8f3c", size=22, width=4),
            _ring(points, miss, "#d62728", symbol="x-open", size=22, width=4),
            go.Scatter(x=[q[0]] if show_q else [], y=[q[1]] if show_q else [], mode="markers", hoverinfo="skip",
                       marker=dict(symbol="star", size=24, color="#d62728", line=dict(color="black", width=1))),
        ]

    n = len(points)
    faded = [colours[i] if assign[i] in probed else FADED for i in range(n)]
    stages = [
        (f"Start: {n} vectors. Brute force would measure the distance to every one of them.",
         traces([GREY] * n, False, show_q=False)),
        (f"Build (done once, ahead of time): k-means picks {nlist} centroids (diamonds). Every vector is filed under its nearest centroid, shown by colour.",
         traces(colours, True, show_q=False)),
        ("A query arrives (red star).", traces(colours, True)),
        (f"Step 1: compare the query with only the {nlist} centroids, not with all {n} vectors.",
         traces(colours, True, lines=range(nlist))),
        (f"Step 2: keep the nprobe={nprobe} closest cell(s). All other cells are ignored.",
         traces(faded, True, lines=trace["probed"], line_colour="#d62728")),
        (f"Step 3: measure the distance to the {len(scanned)} vectors inside the chosen cell(s) (black rings).",
         traces(faded, True, ring=scanned)),
        (f"Result: green rings are the top {k} found. {found} of the true {k} nearest neighbours found"
         + (f"; red crosses are true neighbours that sat in a cell we skipped." if missed else ".")
         + f" {trace['distance_calcs']} distance calculations instead of {n}.",
         traces(faded, True, ring=scanned, res=result, miss=missed)),
    ]
    frames = [_frame(i, t, tr) for i, (t, tr) in enumerate(stages)]
    return _finish(frames, stages[0][0], duration=1800)


# ---------------------------------------------------------------- HNSW
def hnsw_figure(points, g, q, trace, truth, k, ef):
    layers, top = g["layers"], len(g["layers"]) - 1
    events = trace["events"]
    result = trace["result"]
    missed = [i for i in truth if i not in result]
    found = len(truth) - len(missed)
    n = len(points)

    def edges(layer):
        return sorted({(min(a, b), max(a, b)) for a, nb in layers[layer].items() for b in nb})

    def traces(layer, show_q=True, seen=(), examined=(), current=None, path=(), res=(), miss=()):
        ex, ey = _segments(points, edges(layer))
        nodes = list(layers[layer].keys()) if layer > 0 else []
        path_x, path_y = ([points[i][0] for i in path], [points[i][1] for i in path])
        return [
            go.Scatter(x=points[:, 0], y=points[:, 1], mode="markers", hoverinfo="skip",
                       marker=dict(size=6, color="#c9ccd1")),
            go.Scatter(x=ex, y=ey, mode="lines", hoverinfo="skip", line=dict(color="#9db7e8", width=1)),
            go.Scatter(x=points[nodes, 0] if nodes else [], y=points[nodes, 1] if nodes else [], mode="markers",
                       hoverinfo="skip", marker=dict(size=10, color="#2b4c9b")),
            go.Scatter(x=path_x, y=path_y, mode="lines", hoverinfo="skip", line=dict(color="#d62728", width=3)),
            _ring(points, seen, "#f2b66d", symbol="circle", size=11, width=0),
            _ring(points, examined, "#ff7f0e", symbol="circle", size=14, width=0),
            _ring(points, [current] if current is not None else [], "#d62728", symbol="circle", size=19, width=0),
            _ring(points, res, "#0a8f3c", size=24, width=4),
            _ring(points, miss, "#d62728", symbol="x-open", size=24, width=4),
            go.Scatter(x=[q[0]] if show_q else [], y=[q[1]] if show_q else [], mode="markers", hoverinfo="skip",
                       marker=dict(symbol="star", size=24, color="#d62728", line=dict(color="black", width=1))),
        ]

    names = {0: "Layer 0 (bottom): every point, short links to its nearest neighbours, like street level."}
    for lvl in range(1, top + 1):
        n_l = len(layers[lvl])
        names[lvl] = (f"Layer {lvl}{' (top)' if lvl == top else ''}: only {n_l} of the {n} points (dark blue), "
                      + ("linked over long distances, like motorways." if lvl == top else "linked over medium distances, like main roads."))
    stages = [(f"Build (done once): each point is randomly assigned a top layer. {names[lvl]}", traces(lvl, show_q=False))
              for lvl in range(top, -1, -1)]
    stages.append((f"A query arrives. The search starts at a fixed entry point in the top layer (red dot).",
                   traces(top, current=g["entry"], seen=[g["entry"]])))

    seen, path = {g["entry"]}, [g["entry"]]
    for idx, ev in enumerate(events):
        seen |= set(ev["examined"])
        nxt = events[idx + 1] if idx + 1 < len(events) else None
        if ev["kind"] == "greedy":
            if nxt and nxt["layer"] == ev["layer"] and nxt["current"] != ev["current"]:
                msg = f"Layer {ev['layer']}: look at the links of the current point (orange), step to the one closest to the query."
            else:
                msg = f"Layer {ev['layer']}: no linked point is closer to the query, so drop down to layer {ev['layer'] - 1}, starting from here."
            if ev["current"] not in path:
                path.append(ev["current"])
        else:
            msg = f"Layer 0: take the best unexplored candidate, check its links (orange), keep the best {ef} found so far."
        stages.append((msg, traces(ev["layer"], seen=seen, examined=ev["examined"], current=ev["current"], path=path)))
    stages.append((
        f"Result: green rings are the top {k} found. {found} of the true {k} nearest neighbours found"
        + ("; red crosses were missed." if missed else ".")
        + f" {trace['distance_calcs']} distance calculations instead of {n}. Light orange dots are everything the search measured.",
        traces(0, seen=seen, path=path, res=result, miss=missed)))
    frames = [_frame(i, t, tr) for i, (t, tr) in enumerate(stages)]
    return _finish(frames, stages[0][0], duration=1100)
