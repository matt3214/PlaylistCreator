"""Turn Jev scores into playlist suggestions: Markdown for reading, CSV/JSON for tooling."""

import csv
from pathlib import Path

from playlist_creator.youtube import video_url


def build(videos: list[dict], playlists: list[dict], threshold: float = 0.7, review_floor: float = 0.4) -> dict:
    """Assign videos to playlists by Jev fit probability.

    A video joins every playlist whose fit >= threshold (videos can live in several playlists).
    Fits between review_floor and threshold go to a human review list instead.
    Within a playlist, videos that are both on-topic and newcomer-friendly come first.

    A playlist with "top": N is a ranking rather than a topic (e.g. "Start Here"): it takes its N
    best-ranked videos with fit >= review_floor, and the next N go to review.
    """
    scored = [v for v in videos if v.get("jev")]
    result = []
    for p in playlists:
        members, review = [], []
        for v in scored:
            fit = v["jev"]["fit"].get(p["slug"])
            if fit is None:
                continue
            row = _row(v, fit)
            if fit >= threshold:
                members.append(row)
            elif fit >= review_floor:
                review.append(row)
        members.sort(key=lambda r: -r["rank"])
        review.sort(key=lambda r: -r["fit"])
        if p.get("top"):
            ranked = sorted(members + review, key=lambda r: -r["rank"])
            members, review = ranked[:p["top"]], ranked[p["top"]:2 * p["top"]]
        result.append({**p, "videos": members, "review": review})
    placed = {r["id"] for p in result for r in p["videos"]}
    unplaced = [_row(v, None) for v in scored if v["id"] not in placed]
    return {"threshold": threshold, "review_floor": review_floor, "scored_videos": len(scored),
            "playlists": result, "unplaced": unplaced}


def _row(v: dict, fit: float | None) -> dict:
    newcomer = v["jev"].get("newcomer") or 0.0
    s = v.get("summary") or {}
    return {
        "id": v["id"],
        "title": v.get("title", ""),
        "url": v.get("url") or video_url(v["id"], v.get("kind") == "short"),
        "kind": v.get("kind", "video"),
        "duration": v.get("duration"),
        "views": v.get("view_count"),
        "fit": fit,
        "newcomer": newcomer,
        "primary": v["jev"].get("primary"),
        "summary": s.get("summary", ""),
        "key_moment": s.get("key_moment", ""),
        # Rank inside a playlist: fit, nudged up by newcomer-friendliness (0-3 scale).
        "rank": (fit or 0) * (0.5 + newcomer / 6),
    }


def write(report: dict, out_dir: str | Path, top: int = 25) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md, csv_path = out / "playlists.md", out / "assignments.csv"
    md.write_text(to_markdown(report, top), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["playlist", "status", "video_id", "title", "url", "kind", "fit", "newcomer", "primary"])
        for p in report["playlists"]:
            for status, rows in (("include", p["videos"]), ("review", p["review"])):
                for r in rows:
                    w.writerow([p["name"], status, r["id"], r["title"], r["url"], r["kind"],
                                f"{r['fit']:.3f}", f"{r['newcomer']:.2f}", r["primary"]])
    return [md, csv_path]


def to_markdown(report: dict, top: int = 25) -> str:
    lines = [
        "# Suggested playlists",
        "",
        f"{report['scored_videos']} videos scored by Jev. A video is included when Jev's fit probability is "
        f"at least {report['threshold']:.0%}; {report['review_floor']:.0%} to {report['threshold']:.0%} is listed for review "
        "(ranked playlists such as Start Here keep their best N instead). "
        "Newcomer is Jev's 0-3 rating of how well the video serves someone new to abolition.",
        "",
        "| Playlist | Included | Review | Source |",
        "|---|---:|---:|---|",
    ]
    for p in report["playlists"]:
        lines.append(f"| [{p['name']}](#{_anchor(p['name'])}) | {len(p['videos'])} | {len(p['review'])} | {p.get('source', 'seed')} |")
    for p in report["playlists"]:
        lines += ["", f"## {p['name']}", "", p["description"], ""]
        if p.get("why_distinct"):
            lines += [f"*Discovered by clustering:* {p['why_distinct']}", ""]
        if not p["videos"]:
            lines.append("_No videos cleared the threshold._")
        else:
            lines += ["| # | Video | Fit | Newcomer | Summary |", "|---:|---|---:|---:|---|"]
            for i, r in enumerate(p["videos"][:top], 1):
                lines.append(f"| {i} | [{_esc(r['title'])}]({r['url']}) {'(Short)' if r['kind'] == 'short' else ''} "
                             f"| {r['fit']:.0%} | {r['newcomer']:.1f} | {_esc(r['summary'])} |")
            if len(p["videos"]) > top:
                lines.append(f"\n…and {len(p['videos']) - top} more in `assignments.csv`.")
        if p["review"]:
            lines += ["", f"<details><summary>{len(p['review'])} borderline videos to review</summary>", ""]
            lines += [f"- [{_esc(r['title'])}]({r['url']}): {r['fit']:.0%}" for r in p["review"][:top]]
            lines += ["", "</details>"]
    if report["unplaced"]:
        lines += ["", "## Not placed in any playlist", ""]
        lines += [f"- [{_esc(r['title'])}]({r['url']})" for r in report["unplaced"][:100]]
    return "\n".join(lines) + "\n"


def _esc(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _anchor(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9 -]", "", name.lower()).replace(" ", "-")
