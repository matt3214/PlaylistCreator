"""Build the playlist list: hand-written seed playlists plus new ones discovered by clustering."""

import json
import re
from importlib import resources

from playlist_creator.openrouter import OpenRouter
from playlist_creator.summarize import summary_text

NAME_SYSTEM = """You are helping Abolitionists Rising (a Christian ministry working to abolish abortion) \
organize its YouTube videos into playlists that train newer abolitionists. You will see summaries of a \
group of videos that an embedding model clustered together. Describe what unites them as a playlist."""

NAME_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "description", "coherent"],
    "properties": {
        "name": {"type": "string", "description": "A playlist title of at most 70 characters."},
        "description": {"type": "string", "description": "1-2 sentences: what a video must address to belong in this playlist."},
        "coherent": {"type": "boolean", "description": "False if the videos share no meaningful topic beyond the general cause."},
    },
}

CURATE_SYSTEM = """You curate YouTube playlists for Abolitionists Rising. You get the existing playlists \
and candidate playlists discovered by clustering the channel's videos. Return only the candidates that cover \
a distinct, useful topic not already covered by an existing playlist; merge candidates that overlap each other. \
Prefer topics organized around a specific objection, talking point, or skill, since the goal is helping newer \
abolitionists answer particular arguments."""

CURATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["new_playlists"],
    "properties": {
        "new_playlists": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "description", "from_clusters", "why_distinct"],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "from_clusters": {"type": "array", "items": {"type": "integer"}},
                    "why_distinct": {"type": "string"},
                },
            },
        }
    },
}


def load_seed_playlists(path: str | None = None) -> list[dict]:
    if path:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return json.loads(resources.files("playlist_creator").joinpath("seed_playlists.json").read_text(encoding="utf-8"))


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "playlist"


def name_cluster(client: OpenRouter, model: str, cluster: dict, videos_by_id: dict, sample: int = 15) -> dict:
    members = [videos_by_id[v] for v in cluster["video_ids"][:sample] if v in videos_by_id]
    user = f"{cluster['size']} videos in this cluster. The {len(members)} most central:\n\n" + "\n\n---\n\n".join(
        summary_text(v) for v in members
    )
    return client.chat_json(model, NAME_SYSTEM, user, schema=NAME_SCHEMA, temperature=0.3)


def curate(client: OpenRouter, model: str, seeds: list[dict], clusters: list[dict]) -> list[dict]:
    """Return the cluster-derived playlists worth adding to the seeds."""
    candidates = [c for c in clusters if c.get("coherent", True) and c.get("name")]
    if not candidates:
        return []
    user = json.dumps({
        "existing_playlists": [{"name": p["name"], "description": p["description"]} for p in seeds],
        "candidates": [
            {"cluster": c["cluster"], "size": c["size"], "name": c["name"], "description": c["description"]}
            for c in candidates
        ],
    }, indent=2)
    result = client.chat_json(model, CURATE_SYSTEM, user, schema=CURATE_SCHEMA, temperature=0.2)
    taken = {p["slug"] for p in seeds}
    added = []
    for p in result.get("new_playlists", []):
        slug = slugify(p["name"])
        while slug in taken:
            slug += "-2"
        taken.add(slug)
        added.append({"slug": slug, "name": p["name"], "description": p["description"], "source": "cluster",
                      "from_clusters": p.get("from_clusters", []), "why_distinct": p.get("why_distinct", "")})
    return added
