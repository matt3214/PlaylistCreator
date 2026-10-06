import pytest

from playlist_creator import publish


class FakeResponse:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload or {}, text

    def json(self):
        return self._payload


class FakeSession:
    """Records calls; fails with quota after `quota_after` posts, 404s for ids in `missing`."""

    def __init__(self, quota_after=None, missing=()):
        self.calls, self.quota_after, self.missing = [], quota_after, set(missing)

    def post(self, url, params, json, headers, timeout):
        if self.quota_after is not None and len(self.calls) >= self.quota_after:
            return FakeResponse(403, text='{"error": {"errors": [{"reason": "quotaExceeded"}]}}')
        self.calls.append((url.rsplit("/", 1)[1], json))
        if url.endswith("/playlists"):
            return FakeResponse(200, {"id": f"PL{len(self.calls)}"})
        if json["snippet"]["resourceId"]["videoId"] in self.missing:
            return FakeResponse(404, text='{"error": {"errors": [{"reason": "videoNotFound"}]}}')
        return FakeResponse(200, {"id": "item"})


class Creds:
    token, expired = "t", False


REPORT = {"playlists": [
    {"slug": "a", "name": "A <test>", "description": "about a", "videos": [{"id": f"v{i}"} for i in range(5)]},
    {"slug": "b", "name": "B", "description": "about b", "videos": [{"id": "w1"}]},
    {"slug": "empty", "name": "E", "description": "e", "videos": []},
]}


def run(session, state, slugs=None, top=3):
    saved = []
    publish.publish(publish.YouTube(Creds(), session), publish.plan(REPORT, slugs, top), state, "private", "AR: ",
                    lambda st: saved.append(True), lambda msg: None)
    return saved


def test_plan_takes_top_n_and_skips_empty():
    assert [(p["slug"], p["video_ids"]) for p in publish.plan(REPORT, None, 3)] == [("a", ["v0", "v1", "v2"]), ("b", ["w1"])]
    assert [p["slug"] for p in publish.plan(REPORT, ["b"], 3)] == ["b"]


def test_publish_creates_playlists_in_order_and_cleans_titles():
    session, state = FakeSession(), {}
    run(session, state)
    kinds = [c[0] for c in session.calls]
    assert kinds == ["playlists", "playlistItems", "playlistItems", "playlistItems", "playlists", "playlistItems"]
    assert session.calls[0][1]["snippet"]["title"] == "AR: A test"
    assert session.calls[0][1]["status"]["privacyStatus"] == "private"
    assert state["a"]["added"] == ["v0", "v1", "v2"] and state["b"]["added"] == ["w1"]


def test_publish_resumes_after_quota_without_duplicates():
    state = {}
    with pytest.raises(publish.QuotaExceeded):
        run(FakeSession(quota_after=2), state)
    assert state["a"]["added"] == ["v0"]
    session = FakeSession()
    run(session, state)
    assert [c[1]["snippet"]["resourceId"]["videoId"] for c in session.calls if c[0] == "playlistItems"] == ["v1", "v2", "w1"]
    assert sum(1 for c in session.calls if c[0] == "playlists") == 1  # only "b" is new


def test_missing_video_is_skipped_not_fatal():
    state = {}
    run(FakeSession(missing={"v1"}), state)
    assert state["a"]["added"] == ["v0", "v2"] and state["a"]["skipped"] == ["v1"]
