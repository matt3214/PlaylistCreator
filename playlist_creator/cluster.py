"""Embed video summaries and group them with k-means so unseen topics surface as candidate playlists."""

import numpy as np


def normalize(x: np.ndarray) -> np.ndarray:
    return x / np.clip(np.linalg.norm(x, axis=1, keepdims=True), 1e-12, None)


def kmeans(x: np.ndarray, k: int, seed: int = 0, iters: int = 100) -> tuple[np.ndarray, np.ndarray]:
    """Spherical k-means with k-means++ init. Returns (labels, centroids) for unit-normalized rows."""
    rng = np.random.default_rng(seed)
    n = len(x)
    centroids = [x[rng.integers(n)]]
    for _ in range(1, k):
        dist = np.clip(1 - np.max(x @ np.array(centroids).T, axis=1), 0, None)
        probs = dist / dist.sum() if dist.sum() > 0 else np.full(n, 1 / n)
        centroids.append(x[rng.choice(n, p=probs)])
    centroids = np.array(centroids)
    labels = np.full(n, -1)
    for _ in range(iters):
        new_labels = np.argmax(x @ centroids.T, axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for j in range(k):
            members = x[labels == j]
            # Re-seed an empty cluster with the point farthest from its centroid.
            centroids[j] = members.mean(axis=0) if len(members) else x[np.argmin(np.max(x @ centroids.T, axis=1))]
        centroids = normalize(centroids)
    return labels, centroids


def silhouette(x: np.ndarray, labels: np.ndarray) -> float:
    """Mean silhouette score with cosine distance."""
    dist = 1 - x @ x.T
    scores = []
    for i in range(len(x)):
        same = labels == labels[i]
        if same.sum() <= 1:
            scores.append(0.0)
            continue
        a = dist[i, same].sum() / (same.sum() - 1)
        b = min(dist[i, labels == j].mean() for j in set(labels.tolist()) if j != labels[i])
        scores.append((b - a) / max(a, b) if max(a, b) > 0 else 0.0)
    return float(np.mean(scores))


def choose_k(x: np.ndarray, k_min: int = 6, k_max: int = 30, seed: int = 0, sample: int = 1500) -> int:
    """Pick k by silhouette score on a sample (silhouette is O(n^2))."""
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(x), size=min(sample, len(x)), replace=False)
    xs = x[idx]
    k_max = min(k_max, len(xs) - 1)
    best_k, best = k_min, -1.0
    for k in range(k_min, k_max + 1):
        labels, _ = kmeans(xs, k, seed)
        score = silhouette(xs, labels)
        if score > best:
            best_k, best = k, score
    return best_k


def cluster(ids: list[str], vectors: np.ndarray, k: int | None = None, seed: int = 0, k_min: int = 6) -> list[dict]:
    """Cluster videos; each cluster lists member ids nearest-to-centroid first."""
    x = normalize(np.asarray(vectors, dtype=float))
    k = k or choose_k(x, k_min=min(k_min, len(x) - 1), seed=seed)
    labels, centroids = kmeans(x, k, seed)
    clusters = []
    for j in range(k):
        members = np.where(labels == j)[0]
        if not len(members):
            continue
        sims = x[members] @ centroids[j]
        order = members[np.argsort(-sims)]
        clusters.append({"cluster": j, "size": len(members), "video_ids": [ids[i] for i in order],
                         "cohesion": float(sims.mean())})
    return sorted(clusters, key=lambda c: -c["size"])


def spectral(ids: list[str], similarity: np.ndarray, k: int | None = None, seed: int = 0,
             k_min: int = 2, k_max: int = 30) -> list[dict]:
    """Spectral clustering on a precomputed similarity matrix (e.g. Jev pair probabilities).

    Embeds each video with the leading eigenvectors of the normalized affinity matrix, then runs
    k-means in that space. Cohesion is the mean similarity of each member to the rest of its cluster.
    """
    w = np.clip((similarity + similarity.T) / 2, 0, 1)
    np.fill_diagonal(w, 0)
    d = w.sum(axis=1)
    inv_sqrt = 1 / np.sqrt(np.clip(d, 1e-12, None))
    affinity = inv_sqrt[:, None] * w * inv_sqrt[None, :]
    eigvals, eigvecs = np.linalg.eigh(affinity)  # ascending
    eigvals, eigvecs = eigvals[::-1], eigvecs[:, ::-1]
    if k is None:
        # Eigengap heuristic: k where the gap between consecutive eigenvalues is largest.
        hi = min(k_max, len(ids) - 1)
        lo = min(k_min, hi)
        gaps = eigvals[lo - 1:hi] - eigvals[lo:hi + 1]
        k = lo + int(np.argmax(gaps)) if len(gaps) else lo
    x = normalize(eigvecs[:, :k])
    labels, _ = kmeans(x, k, seed)
    clusters = []
    for j in range(k):
        members = np.where(labels == j)[0]
        if not len(members):
            continue
        inner = w[np.ix_(members, members)]
        per_member = inner.sum(axis=1) / max(len(members) - 1, 1)
        order = members[np.argsort(-per_member)]
        clusters.append({"cluster": j, "size": len(members), "video_ids": [ids[i] for i in order],
                         "cohesion": float(per_member.mean())})
    return sorted(clusters, key=lambda c: -c["size"])
