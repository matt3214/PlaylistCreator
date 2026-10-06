"""List a channel's videos and pull caption transcripts with yt-dlp.

Captions are free but YouTube often answers server IPs with "Sign in to confirm you're not a bot";
the pipeline then falls back to having Gemini watch the video (see `OpenRouter.transcribe_youtube`).
"""

import json
import re

import yt_dlp

TABS = ("videos", "shorts", "streams")
CAPTION_LANGS = ("en", "en-orig", "en-US", "en-GB")
# The android_vr client is least likely to hit "Sign in to confirm you're not a bot" from server IPs.
PLAYER_CLIENTS = ["android_vr", "default"]


class _QuietLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def _ydl(**opts) -> yt_dlp.YoutubeDL:
    return yt_dlp.YoutubeDL({
        "quiet": True,
        "no_warnings": True,
        "logger": _QuietLogger(),
        "skip_download": True,
        "extractor_args": {"youtube": {"player_client": PLAYER_CLIENTS}},
        **opts,
    })


def list_channel(channel_url: str, tabs=TABS, limit: int | None = None) -> list[dict]:
    """Flat-list every upload on the channel's tabs. Fast: one request per page, no per-video calls."""
    channel_url = channel_url.rstrip("/")
    videos: dict[str, dict] = {}
    with _ydl(extract_flat="in_playlist", ignoreerrors=True) as ydl:
        for tab in tabs:
            info = ydl.extract_info(f"{channel_url}/{tab}", download=False)
            for entry in (info or {}).get("entries") or []:
                if not entry or not entry.get("id") or entry["id"] in videos:
                    continue
                videos[entry["id"]] = {
                    "id": entry["id"],
                    "title": entry.get("title") or "",
                    "duration": entry.get("duration"),
                    "view_count": entry.get("view_count"),
                    "kind": "short" if tab == "shorts" else "video",
                    "url": video_url(entry["id"], tab == "shorts"),
                }
                if limit and len(videos) >= limit:
                    return list(videos.values())
    return list(videos.values())


def video_url(video_id: str, short: bool = False) -> str:
    return f"https://www.youtube.com/shorts/{video_id}" if short else f"https://www.youtube.com/watch?v={video_id}"


def fetch_details(video_id: str, cookies_from_browser: str | None = None) -> dict:
    """Per-video metadata plus caption transcript (empty string when the video has no captions)."""
    opts = {"cookiesfrombrowser": (cookies_from_browser,)} if cookies_from_browser else {}
    with _ydl(**opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        transcript, source = _captions(ydl, info)
    return {
        "title": info.get("title") or "",
        "description": info.get("description") or "",
        "duration": info.get("duration"),
        "upload_date": info.get("upload_date"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "tags": info.get("tags") or [],
        "transcript": transcript,
        "transcript_source": source,
    }


def _captions(ydl: yt_dlp.YoutubeDL, info: dict) -> tuple[str, str | None]:
    for source, tracks in (("manual", info.get("subtitles") or {}), ("auto", info.get("automatic_captions") or {})):
        for lang in CAPTION_LANGS:
            fmt = next((f for f in tracks.get(lang, []) if f.get("ext") == "json3"), None)
            if fmt:
                data = json.loads(ydl.urlopen(fmt["url"]).read())
                text = json3_to_text(data)
                if text:
                    return text, f"{source}:{lang}"
    return "", None


def json3_to_text(data: dict) -> str:
    """Flatten YouTube's json3 caption format into plain text."""
    parts = ("".join(seg.get("utf8", "") for seg in event.get("segs") or []) for event in data.get("events") or [])
    return re.sub(r"\s+", " ", " ".join(parts)).strip()
