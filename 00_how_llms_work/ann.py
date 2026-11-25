# Toy approximate nearest-neighbour indexes (IVF and HNSW) on 2D points, for teaching.
# No Streamlit here. These are small, readable versions of the real algorithms, not the
# production code in FAISS / OpenSearch / pgvector. They return a "trace" of what the search
# did, step by step, so a page can animate it.
import numpy as np


# ---------------------------------------------------------------- data
def make_points(n=300, n_blobs=6, seed=7):
    """A 2D cloud of n points in n_blobs loose clusters (stand-in for embedding vectors)."""
    rng = np.random.default_rng(seed)
    centres = rng.uniform(1.5, 8.5, size=(n_blobs, 2))
    which = rng.integers(0, n_blobs, size=n)
    return centres[which] + rng.normal(0, 0.9, size=(n, 2))


def make_query(points, seed):
    rng = np.random.default_rng(1000 + int(seed))
    return points[rng.integers(len(points))] + rng.normal(0, 0.6, size=2)


def exact_knn(points, q, k):
    """Brute force: measure the distance to every point. The ground truth."""
    return [int(i) for i in np.argsort(np.linalg.norm(points - q, axis=1))[:k]]


# ---------------------------------------------------------------- IVF
def build_ivf(points, nlist=8, seed=3, iters=25):
    """k-means: choose nlist centroids and file every point under its nearest one."""
    rng = np.random.default_rng(seed)
    cents = points[rng.choice(len(points), nlist, replace=False)].copy()
    for _ in range(iters):
        assign = np.argmin(np.linalg.norm(points[:, None] - cents[None], axis=2), axis=1)
        for c in range(nlist):
            members = points[assign == c]
            if len(members):
                cents[c] = members.mean(axis=0)
    assign = np.argmin(np.linalg.norm(points[:, None] - cents[None], axis=2), axis=1)
    return {"centroids": cents, "assign": assign, "nlist": nlist}


def ivf_search(points, ivf, q, nprobe=1, k=5):
    """Compare q with the centroids, then scan only the nprobe closest cells."""
    cents, assign = ivf["centroids"], ivf["assign"]
    order = [int(c) for c in np.argsort(np.linalg.norm(cents - q, axis=1))]
    probed = order[: max(1, int(nprobe))]
    scanned = [int(i) for i in np.where(np.isin(assign, probed))[0]]
    scanned.sort(key=lambda i: float(np.linalg.norm(points[i] - q)))
    return {
        "centroid_order": order,
        "probed": probed,
        "scanned": scanned,
        "result": scanned[:k],
        "distance_calcs": len(cents) + len(scanned),
    }


# ---------------------------------------------------------------- HNSW
def build_hnsw(points, M=4, seed=1, max_level=2):
    """Layered graph. Each point gets a random top layer (higher layers have far fewer points).
    On every layer each point is linked to its M nearest points on that layer."""
    rng = np.random.default_rng(seed)
    n = len(points)
    m_l = 1.0 / np.log(max(M, 2))
    levels = np.minimum((-np.log(1 - rng.random(n)) * m_l).astype(int), max_level)
    top = int(levels.max())
    layers = []
    for lvl in range(top + 1):
        nodes = np.where(levels >= lvl)[0]
        adj = {int(i): set() for i in nodes}
        if len(nodes) > 1:
            d = np.linalg.norm(points[nodes][:, None] - points[nodes][None], axis=2)
            for a, i in enumerate(nodes):
                for b in np.argsort(d[a])[1 : M + 1]:
                    adj[int(i)].add(int(nodes[b]))
                    adj[int(nodes[b])].add(int(i))
        _connect_components(adj, points)
        layers.append(adj)
    return {"layers": layers, "entry": int(np.argmax(levels)), "levels": levels, "M": M}


def _connect_components(adj, points):
    """Make sure the layer is one connected graph (a search can always reach every point)."""
    while True:
        seen, comps = set(), []
        for s in adj:
            if s in seen:
                continue
            comp, stack = set(), [s]
            while stack:
                x = stack.pop()
                if x in comp:
                    continue
                comp.add(x)
                stack.extend(adj[x] - comp)
            seen |= comp
            comps.append(sorted(comp))
        if len(comps) <= 1:
            return
        a, b = comps[0], comps[1]
        d = np.linalg.norm(points[a][:, None] - points[b][None], axis=2)
        i, j = np.unravel_index(np.argmin(d), d.shape)
        adj[a[i]].add(b[j])
        adj[b[j]].add(a[i])


def hnsw_search(g, points, q, k=5, ef=8):
    """Greedy walk down the upper layers, then a small beam search (width ef) on layer 0.

    Returns dict(events=[...], result=[...], distance_calcs=int). Each event is one step:
    {layer, current, examined, kind}.
    """
    layers = g["layers"]

    def dist(i):
        return float(np.linalg.norm(points[i] - q))

    evaluated = {g["entry"]}
    events = []
    cur = g["entry"]
    dcur = dist(cur)
    for lvl in range(len(layers) - 1, 0, -1):
        while True:
            nbrs = sorted(layers[lvl][cur])
            evaluated.update(nbrs)
            events.append({"layer": lvl, "current": cur, "examined": nbrs, "kind": "greedy"})
            best = min(nbrs, key=dist) if nbrs else None
            if best is not None and dist(best) < dcur:
                cur, dcur = best, dist(best)
            else:
                break

    ef = max(int(ef), k)
    visited = {cur}
    cand = [(dcur, cur)]
    results = [(dcur, cur)]
    while cand:
        cand.sort()
        d, c = cand.pop(0)
        if len(results) >= ef and d > max(results)[0]:
            break
        new = [n for n in sorted(layers[0][c]) if n not in visited]
        visited.update(new)
        evaluated.update(new)
        for n in new:
            dn = dist(n)
            if len(results) < ef or dn < max(results)[0]:
                cand.append((dn, n))
                results.append((dn, n))
                results = sorted(results)[:ef]
        events.append({"layer": 0, "current": c, "examined": new, "kind": "beam"})
    return {
        "events": events,
        "result": [i for _, i in sorted(results)[:k]],
        "distance_calcs": len(evaluated),
    }


# ---------------------------------------------------------------- speed vs accuracy
def recall(found, truth):
    return len(set(found) & set(truth)) / max(len(truth), 1)


def sweep(points, nlist, M, k=5, n_queries=60, seed=11):
    """Average recall and distance calculations over many queries, for a range of settings."""
    ivf = build_ivf(points, nlist)
    g = build_hnsw(points, M)
    queries = [make_query(points, seed * 1000 + s) for s in range(n_queries)]
    truths = [exact_knn(points, q, k) for q in queries]
    rows = []
    for nprobe in range(1, nlist + 1):
        rs = [ivf_search(points, ivf, q, nprobe, k) for q in queries]
        rows.append({
            "index": "IVF", "setting": f"nprobe={nprobe}",
            "distance_calcs": float(np.mean([r["distance_calcs"] for r in rs])),
            "recall": float(np.mean([recall(r["result"], t) for r, t in zip(rs, truths)])),
        })
    for ef in (k, 8, 12, 20, 32, 60):
        rs = [hnsw_search(g, points, q, k, ef) for q in queries]
        rows.append({
            "index": "HNSW", "setting": f"ef={ef}",
            "distance_calcs": float(np.mean([r["distance_calcs"] for r in rs])),
            "recall": float(np.mean([recall(r["result"], t) for r, t in zip(rs, truths)])),
        })
    return rows
