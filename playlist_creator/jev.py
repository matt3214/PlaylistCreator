"""Score how well each video fits each playlist with Jev (TypeSafe System One).

One request per video asks every question at once:
  fit__<slug>  noul   probability the video belongs in that playlist
  newcomer     score  0-3, how good a first video it is for a new abolitionist
  primary      choice the single best playlist (or "none")
Jev returns calibrated probabilities rather than generated text, so the numbers can be thresholded directly.
"""

import hashlib
import json

import numpy as np
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

DEFAULT_MODEL = "jev-latest"
TRANSCRIPT_EXCERPT_CHARS = 6_000

NEWCOMER_LEVELS = [
    "Not useful to a newcomer: assumes insider context, is mostly logistics or event news, or the argument is unclear.",
    "Somewhat useful: has a good point but is long, meandering, or needs background to follow.",
    "Useful: makes a clear argument most newcomers can follow.",
    "Excellent first video: short or well-paced, clear, persuasive, and models the abolitionist position well.",
]


def build_questions(playlists: list[dict]) -> dict:
    questions = {
        f"fit__{p['slug']}": Noul(
            instructions=(
                f"Should this video be included in the YouTube playlist \"{p['name']}\"? "
                "Include it only if the playlist's topic is a substantial part of the video, not a passing mention."
            ),
            criteria={
                "true": p["description"],
                "false": "The video does not substantially address this playlist's topic.",
            },
        )
        for p in playlists
    }
    questions["newcomer"] = Score(
        instructions="How well would this video serve someone who is new to abolitionism?",
        criteria=NEWCOMER_LEVELS,
    )
    criteria = {p["slug"]: f"{p['name']}: {p['description']}" for p in playlists}
    criteria["none"] = "None of these playlists fits the video well."
    questions["primary"] = Choice(instructions="Which single playlist is the best home for this video?", criteria=criteria)
    return questions


def video_state(video: dict) -> dict:
    s = video.get("summary") or {}
    transcript = video.get("transcript") or ""
    return {
        "title": video.get("title", ""),
        "kind": video.get("kind", "video"),
        "duration_seconds": video.get("duration"),
        "format": s.get("format"),
        "summary": s.get("summary"),
        "objections_addressed": s.get("objections_addressed", []),
        "arguments_made": s.get("arguments_made", []),
        "themes": s.get("themes", []),
        "key_moment": s.get("key_moment"),
        "transcript_excerpt": transcript[:TRANSCRIPT_EXCERPT_CHARS],
    }


def score_video(client: TypeSafeClient, video: dict, playlists: list[dict], model: str = DEFAULT_MODEL) -> dict:
    response = client.system_one(state=video_state(video), questions=build_questions(playlists), model=model)
    fit = {name.removeprefix("fit__"): answer.noul for name, answer in response.nouls.items()}
    newcomer = response.scores.get("newcomer")
    primary = response.choices.get("primary")
    return {
        "model": response.model,
        "fit": fit,
        "newcomer": newcomer.score if newcomer else None,
        "newcomer_confidence": newcomer.confidence if newcomer else None,
        "primary": primary.choice if primary else None,
        "primary_confidence": primary.confidence if primary else None,
        "playlists_hash": playlists_hash(playlists),
    }


def playlists_hash(playlists: list[dict]) -> str:
    """Changes whenever playlist names or descriptions change, so stale scores get re-run."""
    key = json.dumps([[p["slug"], p["name"], p["description"]] for p in playlists], sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:12]


# --- Pairwise similarity -----------------------------------------------------------------------
# Jev answers ~150 yes/no questions in well under a second, so asking about every pair of videos
# is practical: one request per anchor video, with many "is this other video about the same
# thing?" questions batched together. The resulting matrix feeds spectral clustering.

SIMILARITY_QUESTION = (
    "Do these two videos address the same topic, objection, or talking point, "
    "so that they would belong in the same teaching playlist?"
)
MAX_REQUEST_CHARS = 90_000  # Jev rejects requests above roughly 40k tokens; stay well under.


def compact(video: dict) -> dict:
    s = video.get("summary") or {}
    return {
        "title": video.get("title", ""),
        "summary": s.get("summary", ""),
        "objections_addressed": s.get("objections_addressed", []),
        "themes": s.get("themes", []),
    }


def pair_key(a: str, b: str) -> str:
    return f"{a}|{b}" if a < b else f"{b}|{a}"


def similarity_jobs(videos: list[dict], cache: dict) -> list[tuple[dict, list[dict]]]:
    """Batches of (anchor, others) covering every uncached unordered pair exactly once."""
    videos = sorted(videos, key=lambda v: v["id"])
    sizes = {v["id"]: len(json.dumps(compact(v))) + len(SIMILARITY_QUESTION) for v in videos}
    jobs = []
    for i, anchor in enumerate(videos):
        batch, chars = [], sizes[anchor["id"]]
        for other in videos[i + 1:]:
            if pair_key(anchor["id"], other["id"]) in cache:
                continue
            if batch and chars + sizes[other["id"]] > MAX_REQUEST_CHARS:
                jobs.append((anchor, batch))
                batch, chars = [], sizes[anchor["id"]]
            batch.append(other)
            chars += sizes[other["id"]]
        if batch:
            jobs.append((anchor, batch))
    return jobs


def score_pairs(client: TypeSafeClient, anchor: dict, others: list[dict], model: str = DEFAULT_MODEL) -> dict[str, float]:
    questions = {
        f"q{i}": Noul(instructions={"question": SIMILARITY_QUESTION, "other_video": compact(other)})
        for i, other in enumerate(others)
    }
    response = client.system_one(state={"video": compact(anchor)}, questions=questions, model=model)
    return {pair_key(anchor["id"], other["id"]): response.nouls[f"q{i}"].noul for i, other in enumerate(others)}


def similarity_matrix(ids: list[str], cache: dict) -> np.ndarray:
    n = len(ids)
    s = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            s[i, j] = s[j, i] = cache.get(pair_key(ids[i], ids[j]), 0.0)
    return s
