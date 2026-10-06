import json

import httpx2
import numpy as np
import pytest
from typesafe_sdk import TypeSafeClient

from playlist_creator import cluster, jev, report
from playlist_creator.openrouter import parse_json
from playlist_creator.playlists import load_seed_playlists, slugify
from playlist_creator.store import Store
from playlist_creator.youtube import json3_to_text


def video(i, topic="a"):
    return {"id": f"v{i:03d}", "title": f"Video {i}", "kind": "short",
            "summary": {"summary": f"about {topic}", "objections_addressed": [topic], "themes": [topic]}}


def test_kmeans_recovers_planted_clusters():
    rng = np.random.default_rng(1)
    centers = np.eye(3, 8) * 5
    x = np.vstack([c + rng.normal(0, 0.3, (20, 8)) for c in centers])
    labels, _ = cluster.kmeans(cluster.normalize(x), 3)
    for block in range(3):
        assert len(set(labels[block * 20:(block + 1) * 20])) == 1
    assert len(set(labels)) == 3


def test_spectral_recovers_blocks_and_picks_k():
    rng = np.random.default_rng(2)
    n, groups = 30, 3
    truth = np.repeat(np.arange(groups), n // groups)
    s = np.where(truth[:, None] == truth[None, :], 0.85, 0.1) + rng.normal(0, 0.03, (n, n))
    s = np.clip((s + s.T) / 2, 0, 1)
    ids = [f"v{i}" for i in range(n)]
    found = cluster.spectral(ids, s)
    assert sorted(c["size"] for c in found) == [10, 10, 10]
    for c in found:
        assert len({truth[ids.index(i)] for i in c["video_ids"]}) == 1


def test_similarity_jobs_cover_each_pair_once(monkeypatch):
    monkeypatch.setattr(jev, "MAX_REQUEST_CHARS", 600)  # force several batches per anchor
    videos = [video(i) for i in range(7)]
    cache = {jev.pair_key("v000", "v001"): 0.5}
    pairs = [jev.pair_key(a["id"], o["id"]) for a, others in jev.similarity_jobs(videos, cache) for o in others]
    assert len(pairs) == len(set(pairs)) == 7 * 6 // 2 - 1
    assert jev.pair_key("v000", "v001") not in pairs


def test_similarity_matrix_is_symmetric():
    m = jev.similarity_matrix(["b", "a", "c"], {"a|b": 0.9, "b|c": 0.2})
    assert np.allclose(m, m.T) and m[0, 1] == 0.9 and m[0, 2] == 0.2 and m[1, 2] == 0.0


def mock_client(handler):
    return TypeSafeClient(api_key="test", transport=httpx2.MockTransport(handler))


def test_score_video_parses_jev_answers():
    playlists = load_seed_playlists()[:2]
    sent = {}

    def handler(request):
        body = json.loads(request.content)
        sent.update(body)
        answers = {name: {"type": "noul", "noul": 0.9} for name in body["questions"] if name.startswith("fit__")}
        answers["newcomer"] = {"type": "score", "score": 2.4, "confidence": 0.8,
                               "legend": {str(i): t for i, t in enumerate(jev.NEWCOMER_LEVELS)},
                               "probabilities": {"0": 0.1, "1": 0.1, "2": 0.1, "3": 0.7}}
        answers["primary"] = {"type": "choice", "choice": playlists[0]["slug"], "confidence": 0.7,
                              "probabilities": {playlists[0]["slug"]: 0.7, playlists[1]["slug"]: 0.2, "none": 0.1}}
        return httpx2.Response(200, json={"model": "jev-1.13.0", "usage": {}, "answers": answers})

    with mock_client(handler) as client:
        result = jev.score_video(client, video(1), playlists)
    assert sent["model"] == "jev-latest"
    assert sent["state"]["title"] == "Video 1"
    assert result["fit"] == {p["slug"]: 0.9 for p in playlists}
    assert result["newcomer"] == 2.4 and result["primary"] == playlists[0]["slug"]


def test_score_pairs_maps_answers_back_to_pairs():
    def handler(request):
        body = json.loads(request.content)
        answers = {name: {"type": "noul", "noul": 0.1 * (int(name[1:]) + 1)} for name in body["questions"]}
        return httpx2.Response(200, json={"model": "jev", "usage": {}, "answers": answers})

    with mock_client(handler) as client:
        out = jev.score_pairs(client, video(5), [video(1), video(9)])
    assert out == pytest.approx({"v001|v005": 0.1, "v005|v009": 0.2})


def test_report_thresholds_and_ordering():
    playlists = [{"slug": "x", "name": "X", "description": "x"}]
    videos = []
    for i, (fit, newcomer) in enumerate([(0.95, 0.0), (0.8, 3.0), (0.5, 1.0), (0.1, 1.0)]):
        v = video(i)
        v["jev"] = {"fit": {"x": fit}, "newcomer": newcomer, "primary": "x"}
        videos.append(v)
    built = report.build(videos, playlists, threshold=0.7, review_floor=0.4)
    p = built["playlists"][0]
    assert [r["id"] for r in p["videos"]] == ["v001", "v000"]  # newcomer-friendly first
    assert [r["id"] for r in p["review"]] == ["v002"]
    assert {r["id"] for r in built["unplaced"]} == {"v002", "v003"}
    assert "| X |" in report.to_markdown(built) or "[X]" in report.to_markdown(built)


def test_store_roundtrip(tmp_path):
    store = Store(tmp_path)
    store.update_video("abc", title="t")
    store.update_video("abc", transcript="hello")
    assert store.load_video("abc") == {"id": "abc", "title": "t", "transcript": "hello"}
    store.save_embeddings("org/model", {"abc": np.ones(3)})
    assert np.allclose(store.load_embeddings("org/model")["abc"], 1)


def test_helpers():
    assert json3_to_text({"events": [{"segs": [{"utf8": "hi "}, {"utf8": "there"}]}, {"segs": [{"utf8": "\n"}]}, {}]}) == "hi there"
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": 2} hope that helps') == {"a": 2}
    assert slugify("Who Are You to Judge?") == "who-are-you-to-judge"
    seeds = load_seed_playlists()
    assert len({p["slug"] for p in seeds}) == len(seeds)
