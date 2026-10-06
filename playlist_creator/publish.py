"""Create the suggested playlists on a YouTube account through the YouTube Data API v3.

Sign-in happens once in a browser (OAuth "Desktop app" client); the token is cached.
Progress is recorded per playlist, so a run stopped by the daily quota resumes where it left off.

Quota: a new Google Cloud project gets 10,000 units/day. Creating a playlist and adding one video
each cost 50 units, so about 200 additions per day.
"""

import re
from pathlib import Path

import requests

API = "https://www.googleapis.com/youtube/v3"
SCOPES = ["https://www.googleapis.com/auth/youtube"]
TITLE_MAX = 150
DESCRIPTION_MAX = 5000


class QuotaExceeded(RuntimeError):
    pass


class YouTubeError(RuntimeError):
    pass


class SkipVideo(Exception):
    """The video can't be added (deleted, private); the playlist carries on without it."""


def sign_in(client_secrets: str | Path, token_file: str | Path):
    """Return OAuth credentials, opening a browser the first time and caching the token after."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_file = Path(token_file)
    creds = Credentials.from_authorized_user_file(str(token_file), SCOPES) if token_file.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
        creds = flow.run_local_server(port=0)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


class YouTube:
    def __init__(self, creds, session: requests.Session | None = None):
        self.creds = creds
        self.session = session or requests.Session()

    def _post(self, path: str, part: str, body: dict) -> dict:
        if getattr(self.creds, "expired", False):
            from google.auth.transport.requests import Request

            self.creds.refresh(Request())
        resp = self.session.post(f"{API}/{path}", params={"part": part}, json=body,
                                 headers={"Authorization": f"Bearer {self.creds.token}"}, timeout=60)
        if resp.status_code == 403 and "quota" in resp.text.lower():
            raise QuotaExceeded("YouTube API daily quota used up. Run publish again after midnight Pacific time.")
        if resp.status_code >= 400:
            raise YouTubeError(f"{resp.status_code}: {resp.text[:400]}")
        return resp.json()

    def create_playlist(self, title: str, description: str, privacy: str) -> str:
        body = {"snippet": {"title": title, "description": description, "defaultLanguage": "en"},
                "status": {"privacyStatus": privacy}}
        return self._post("playlists", "snippet,status", body)["id"]

    def add_video(self, playlist_id: str, video_id: str) -> None:
        body = {"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}
        try:
            self._post("playlistItems", "snippet", body)
        except YouTubeError as exc:
            # A deleted or private video can't be added; skip it rather than stop the playlist.
            if "videoNotFound" in str(exc) or "forbidden" in str(exc).lower():
                raise SkipVideo(str(exc)) from exc
            raise


def clean(text: str, limit: int) -> str:
    """YouTube rejects '<' and '>' in playlist titles and descriptions."""
    text = re.sub(r"[<>]", "", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def plan(report: dict, slugs: list[str] | None, top: int) -> list[dict]:
    """The playlists to publish, each with its top-ranked video ids in order."""
    chosen = []
    for p in report["playlists"]:
        if slugs and p["slug"] not in slugs:
            continue
        ids = [r["id"] for r in p["videos"][:top]]
        if ids:
            chosen.append({"slug": p["slug"], "name": p["name"], "description": p["description"], "video_ids": ids})
    return chosen


def publish(youtube: YouTube, playlists: list[dict], state: dict, privacy: str, prefix: str,
            save_state, log) -> dict:
    """Create missing playlists and add missing videos. state[slug] = {"playlist_id", "added", "skipped"}."""
    for p in playlists:
        entry = state.setdefault(p["slug"], {"added": [], "skipped": []})
        if not entry.get("playlist_id"):
            description = clean(p["description"] + "\n\nSuggested with PlaylistCreator (LLM summaries, Jev scoring).",
                                DESCRIPTION_MAX)
            entry["playlist_id"] = youtube.create_playlist(clean(prefix + p["name"], TITLE_MAX), description, privacy)
            save_state(state)
            log(f"Created {p['name']}: https://www.youtube.com/playlist?list={entry['playlist_id']}")
        done = set(entry["added"]) | set(entry["skipped"])
        for vid in p["video_ids"]:
            if vid in done:
                continue
            try:
                youtube.add_video(entry["playlist_id"], vid)
                entry["added"].append(vid)
            except SkipVideo as exc:
                entry["skipped"].append(vid)
                log(f"  skipped {vid}: {str(exc)[:120]}")
            save_state(state)
        log(f"  {p['name']}: {len(entry['added'])} videos")
    return state
