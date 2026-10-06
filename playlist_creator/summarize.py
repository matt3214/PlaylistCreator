"""Turn each transcript into a structured summary an abolitionist curator (and Jev) can use."""

from playlist_creator.openrouter import OpenRouter

MAX_TRANSCRIPT_CHARS = 60_000

SYSTEM = """You catalogue videos from Abolitionists Rising, a Christian abolitionist ministry that \
calls for the immediate, total abolition of abortion as murder, equal protection for preborn children, \
and repentance, and that critiques incremental "pro-life" regulation. Many videos are street \
conversations with pro-choice people; others are sermons, commentary, legislative updates, or testimonies.

Summarize the video for someone building teaching playlists. Be concrete and faithful to what is actually \
said; do not invent content that is not in the transcript. Name the specific objections or talking points \
raised by the other side and the specific arguments abolitionists give in response."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "format", "objections_addressed", "arguments_made", "themes", "key_moment", "suitable_for_newcomers"],
    "properties": {
        "summary": {"type": "string", "description": "3-5 sentences on what happens and what is argued."},
        "format": {
            "type": "string",
            "enum": ["street conversation", "campus debate", "sermon or teaching", "commentary", "interview or podcast",
                     "legislative or political update", "testimony", "event or rally", "other"],
        },
        "objections_addressed": {
            "type": "array", "items": {"type": "string"},
            "description": "Pro-choice or pro-life objections raised, e.g. 'bodily autonomy', 'who are you to judge', 'what about rape'.",
        },
        "arguments_made": {
            "type": "array", "items": {"type": "string"},
            "description": "The abolitionist arguments or talking points used in reply, each in one short sentence.",
        },
        "themes": {"type": "array", "items": {"type": "string"}, "description": "2-6 short topic labels."},
        "key_moment": {"type": "string", "description": "The single most quotable or decisive exchange, paraphrased."},
        "suitable_for_newcomers": {"type": "string", "description": "One sentence on whether this would help a new abolitionist and why."},
    },
}


def summarize_video(client: OpenRouter, model: str, video: dict) -> dict:
    transcript = video.get("transcript") or ""
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + " [...transcript truncated]"
    user = (
        f"Title: {video.get('title', '')}\n"
        f"Kind: {video.get('kind', 'video')}, duration {video.get('duration') or '?'} s\n"
        f"Description: {(video.get('description') or '')[:1500]}\n\n"
        f"Transcript:\n{transcript or '[no transcript available; summarize from title and description only]'}"
    )
    return client.chat_json(model, SYSTEM, user, schema=SCHEMA, temperature=0.2)


def summary_text(video: dict) -> str:
    """Compact text used for embeddings and as Jev's view of the video."""
    s = video.get("summary") or {}
    lines = [f"Title: {video.get('title', '')}"]
    if s:
        lines += [
            f"Format: {s.get('format', '')}",
            f"Summary: {s.get('summary', '')}",
            f"Objections addressed: {'; '.join(s.get('objections_addressed', []))}",
            f"Arguments made: {'; '.join(s.get('arguments_made', []))}",
            f"Themes: {', '.join(s.get('themes', []))}",
            f"Key moment: {s.get('key_moment', '')}",
        ]
    return "\n".join(lines)
