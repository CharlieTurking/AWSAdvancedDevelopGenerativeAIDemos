# Plotly figures for the training page (no Streamlit). Animated like ann_plots.py: frames, Play/Pause, slider.
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
def _controls(fig, labels, prefix, duration):
    steps = [
        dict(method="animate", label=str(lab),
             args=[[str(i)], dict(mode="immediate", frame=dict(duration=0, redraw=True), transition=dict(duration=0))])
        for i, lab in enumerate(labels)
    ]
    fig.update_layout(
        updatemenus=[dict(
            type="buttons", direction="left", x=0.0, y=-0.12, xanchor="left", yanchor="top", showactive=False,
            buttons=[
                dict(label="Play", method="animate",
                     args=[None, dict(frame=dict(duration=duration, redraw=True), fromcurrent=True, transition=dict(duration=0))]),
                dict(label="Pause", method="animate",
                     args=[[None], dict(mode="immediate", frame=dict(duration=0, redraw=False), transition=dict(duration=0))]),
            ],
        )],
        sliders=[dict(active=0, steps=steps, x=0.18, len=0.8, y=-0.12, yanchor="top",
                      currentvalue=dict(prefix=prefix, font=dict(size=13)))],
    )
def loss_figure(losses, baseline, max_frames=50, duration=120):
    """Loss curve that draws itself epoch by epoch. Dashed line = loss of guessing uniformly at random."""
    losses = np.asarray(losses, dtype=float)
    n = len(losses)
    idx = sorted(set(np.linspace(0, n - 1, min(max_frames, n)).round().astype(int).tolist()))
    x = np.arange(n)
    def traces(k):
        return [
            go.Scatter(x=x[:k + 1], y=losses[:k + 1], mode="lines", line=dict(color="#636EFA", width=3), name="loss"),
            go.Scatter(x=[k], y=[losses[k]], mode="markers", marker=dict(color="#EF553B", size=11), name="now"),
        ]
    frames = [go.Frame(name=str(i), data=traces(k)) for i, k in enumerate(idx)]
    fig = go.Figure(data=traces(0), frames=frames)
    top = float(max(losses.max(), baseline)) * 1.08
    fig.add_hline(y=baseline, line=dict(color="#9aa0a6", dash="dash"),
                  annotation_text="random guessing", annotation_position="top right")
    fig.update_layout(
        height=420, margin=dict(t=20, b=10, l=10, r=10), showlegend=False,
        xaxis=dict(title="epoch (one pass over all the training text)", range=[0, max(n - 1, 1)]),
        yaxis=dict(title="loss (average surprise, in nats)", range=[0, top]),
    )
    _controls(fig, idx, "Epoch ", duration)
    return fig
def predictions_figure(panels):
    """panels: list of (title, [(word, prob), ...]). Side-by-side horizontal bars on a shared 0-1 axis."""
    fig = make_subplots(rows=1, cols=len(panels), subplot_titles=[t for t, _ in panels], shared_xaxes=True)
    for c, (_, top) in enumerate(panels, start=1):
        words = [w for w, _ in top][::-1]
        probs = [p for _, p in top][::-1]
        fig.add_trace(go.Bar(x=probs, y=words, orientation="h", text=[f"{p:.0%}" for p in probs],
                             textposition="outside", marker_color="#636EFA", cliponaxis=False), row=1, col=c)
        fig.update_xaxes(range=[0, 1.15], tickformat=".0%", row=1, col=c)
    fig.update_layout(height=330, margin=dict(t=40, b=10, l=10, r=10), showlegend=False)
    return fig
def embedding_figure(xy_by_step, labels, steps, label_idx, duration=250):
    """Word embeddings squashed to 2D at each training snapshot. label_idx: which vocabulary rows to draw."""
    label_idx = list(label_idx)
    allpts = np.vstack([xy[label_idx] for xy in xy_by_step])
    pad = 0.15 * float(np.ptp(allpts, axis=0).max() or 1.0)
    def trace(xy):
        return go.Scatter(x=xy[label_idx, 0], y=xy[label_idx, 1], mode="markers+text",
                          text=[labels[i] for i in label_idx], textposition="top center",
                          marker=dict(size=9, color="#636EFA"), hoverinfo="text")
    frames = [go.Frame(name=str(i), data=[trace(xy)]) for i, xy in enumerate(xy_by_step)]
    fig = go.Figure(data=[trace(xy_by_step[0])], frames=frames)
    fig.update_layout(
        height=480, margin=dict(t=20, b=10, l=10, r=10), showlegend=False, plot_bgcolor="white",
        xaxis=dict(range=[allpts[:, 0].min() - pad, allpts[:, 0].max() + pad], visible=False),
        yaxis=dict(range=[allpts[:, 1].min() - pad, allpts[:, 1].max() + pad], visible=False),
    )
    _controls(fig, steps, "Epoch ", duration)
    return fig
