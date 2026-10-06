"""Command line: run the whole pipeline or any single stage.

    playlist-creator run --per-tab 50          # small trial
    playlist-creator list | transcribe | summarize | discover | score | report
"""

import argparse
import sys
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from playlist_creator import cluster as clustering
from playlist_creator import jev, playlists, report, report_html, summarize, youtube
from playlist_creator.openrouter import OpenRouter
from playlist_creator.store import Store

DEFAULT_CHANNEL = "https://www.youtube.com/@AbolitionistsRising"
DEFAULTS = {
    "summary_model": "google/gemini-3.1-flash-lite",
    "video_model": "google/gemini-3.1-flash-lite",
    "curate_model": "anthropic/claude-sonnet-5.5",
    "embedding_model": "voyageai/voyage-4-lite",
    "jev_model": jev.DEFAULT_MODEL,
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def parallel(items, fn, workers: int, label: str, on_progress=None) -> int:
    """Run fn over items in threads; log failures and keep going. Returns the success count.

    on_progress(done) is called from the main thread after every completed item.
    """
    done = ok = 0
    every = max(25, len(items) // 40)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, item): item for item in items}
        for future in as_completed(futures):
            done += 1
            item = futures[future]
            try:
                future.result()
                ok += 1
            except Exception as exc:  # noqa: BLE001 - one bad video must not stop the batch
                log(f"  [{label}] {item.get('id')} failed: {str(exc)[:200]}")
            if done % every == 0 or done == len(futures):
                log(f"  [{label}] {done}/{len(futures)}")
            if on_progress:
                on_progress(done)
    return ok


def cmd_list(args, store: Store) -> None:
    tabs = args.tabs.split(",")
    found = []
    for tab in tabs:
        found += youtube.list_channel(args.channel, tabs=[tab], limit=args.per_tab)
    for i, item in enumerate(found):
        video = store.load_video(item["id"])
        # Keep richer fields from earlier runs; flat listings only refresh title/views.
        video.update({k: v for k, v in item.items() if v is not None and (k not in video or k in ("title", "view_count"))})
        video.setdefault("list_order", i)
        store.save_video(video)
    log(f"Listed {len(found)} videos from {args.channel} ({', '.join(tabs)}).")


class CaptionBreaker:
    """Stop asking YouTube for captions after repeated bot-checks; Gemini takes over."""

    def __init__(self, limit: int = 3):
        self.limit, self.failures, self.lock = limit, 0, threading.Lock()

    @property
    def open(self) -> bool:
        return self.failures >= self.limit

    def record(self, success: bool) -> None:
        with self.lock:
            self.failures = 0 if success else self.failures + 1
            if self.failures == self.limit:
                log("  YouTube is blocking caption requests from this IP; using Gemini for the rest.")


def cmd_transcribe(args, store: Store) -> None:
    """Captions first (free), then Gemini watching the video.

    --method captions  only captions; re-run it to retry videos YouTube refused (rate limits are per IP)
    --method gemini    only Gemini, skipping videos longer than --max-minutes
    --method auto      captions, falling back to Gemini; stops asking YouTube after repeated bot-checks
    """
    todo = [v for v in select(store, args) if not v.get("transcript")]
    if args.method == "captions":
        todo = [v for v in todo if v.get("captions") != "none"]
    if args.method != "captions" and args.max_minutes:
        skipped = [v for v in todo if (v.get("duration") or 0) > args.max_minutes * 60]
        todo = [v for v in todo if v not in skipped]
        if skipped:
            log(f"Skipping {len(skipped)} videos longer than {args.max_minutes} minutes (raise --max-minutes to include them).")
    client = OpenRouter() if args.method != "captions" else None
    breaker = CaptionBreaker() if args.method == "auto" else None

    def work(video: dict) -> None:
        if args.method == "captions" or (args.method == "auto" and not breaker.open):
            try:
                details = youtube.fetch_details(video["id"], args.cookies_from_browser)
                if breaker:
                    breaker.record(True)
                found = bool(details["transcript"])
                details = {k: v for k, v in details.items() if v not in (None, "", [])}
                video = store.update_video(video["id"], captions="found" if found else "none", **details)
                if found or args.method == "captions":
                    return
            except Exception as exc:  # noqa: BLE001
                if args.method == "captions":
                    raise
                breaker.record(False)
                log(f"  captions failed for {video['id']}: {str(exc)[:120]}")
        url = video.get("url") or youtube.video_url(video["id"], video.get("kind") == "short")
        text = client.transcribe_youtube(args.video_model, url)
        store.update_video(video["id"], transcript=text, transcript_source=f"llm:{args.video_model}")

    log(f"Transcribing {len(todo)} videos ({args.method}).")
    ok = parallel(todo, work, args.workers, "transcribe")
    log(f"Transcribed or checked {ok}/{len(todo)}.")


def cmd_summarize(args, store: Store) -> None:
    client = OpenRouter()
    todo = [v for v in select(store, args) if v.get("transcript") and (args.force or not v.get("summary"))]

    def work(video: dict) -> None:
        store.update_video(video["id"], summary=summarize.summarize_video(client, args.summary_model, video),
                           summary_model=args.summary_model)

    log(f"Summarizing {len(todo)} videos with {args.summary_model}.")
    parallel(todo, work, args.workers, "summarize")


def cmd_discover(args, store: Store) -> None:
    """Cluster videos, name the clusters, and keep the ones the seed playlists don't cover.

    --cluster-with jev        Jev rates every pair of videos (same topic / talking point?) -> spectral clustering
    --cluster-with embeddings embedding vectors of the summaries -> k-means
    """
    seeds = playlists.load_seed_playlists(args.seeds)
    for p in seeds:
        p.setdefault("source", "seed")
    videos = [v for v in select(store, args) if v.get("summary")]
    if len(videos) < 12 or args.no_discover:
        store.save_json("playlists.json", seeds)
        log(f"Using {len(seeds)} seed playlists (discovery skipped: {len(videos)} summarized videos).")
        return
    client = OpenRouter()
    ids = [v["id"] for v in videos]
    if args.cluster_with == "jev":
        groups = clustering.spectral(ids, jev_similarity(args, store, videos), k=args.k, k_min=args.k_min)
    else:
        groups = clustering.cluster(ids, embeddings(args, store, client, videos), k=args.k, k_min=args.k_min)
    log(f"Found {len(groups)} clusters with {args.cluster_with}; explaining them with {args.curate_model}.")
    by_id = {v["id"]: v for v in videos}

    def name(group: dict) -> None:
        group.update(playlists.name_cluster(client, args.curate_model, group, by_id))

    parallel(groups, name, args.workers, "name")
    for g in groups:
        g["titles"] = [by_id[i]["title"] for i in g["video_ids"]]
    store.save_json(f"clusters-{args.cluster_with}.json", groups)
    added = playlists.curate(client, args.curate_model, seeds, groups)
    store.save_json("playlists.json", seeds + added)
    log(f"Playlists: {len(seeds)} seed + {len(added)} discovered -> {store.root / 'playlists.json'} (edit it freely).")


def jev_similarity(args, store: Store, videos: list[dict]) -> np.ndarray:
    from typesafe_sdk import TypeSafeClient

    cache_name = f"similarity-{args.jev_model}.json"
    cache = store.load_json(cache_name, {})
    jobs = jev.similarity_jobs(videos, cache)
    pairs = sum(len(others) for _, others in jobs)
    log(f"Jev similarity: {pairs} new pairs in {len(jobs)} requests ({len(cache)} cached).")
    lock = threading.Lock()

    def checkpoint(done: int) -> None:
        if done % 2000 == 0:  # a crash costs at most ~2000 requests
            with lock:
                snapshot = dict(cache)
            store.save_json(cache_name, snapshot, indent=None)

    with TypeSafeClient(timeout=120) as client:
        def work(job) -> None:
            result = jev.score_pairs(client, job[0], job[1], args.jev_model)
            with lock:
                cache.update(result)

        parallel([{"id": a["id"], "job": (a, o)} for a, o in jobs], lambda item: work(item["job"]),
                 args.workers, "pairs", on_progress=checkpoint)
    store.save_json(cache_name, cache, indent=None)
    return jev.similarity_matrix([v["id"] for v in videos], cache)


def embeddings(args, store: Store, client: OpenRouter, videos: list[dict]) -> np.ndarray:
    cache = store.load_embeddings(args.embedding_model)
    missing = [v for v in videos if v["id"] not in cache]
    if missing:
        log(f"Embedding {len(missing)} summaries with {args.embedding_model}.")
        vectors = client.embed(args.embedding_model, [summarize.summary_text(v) for v in missing])
        cache.update({v["id"]: np.asarray(vec, dtype=np.float32) for v, vec in zip(missing, vectors)})
        store.save_embeddings(args.embedding_model, cache)
    return np.stack([cache[v["id"]] for v in videos])


def cmd_score(args, store: Store) -> None:
    from typesafe_sdk import TypeSafeClient

    plist = store.load_json("playlists.json") or playlists.load_seed_playlists(args.seeds)
    current = jev.playlists_hash(plist)
    todo = [v for v in select(store, args)
            if v.get("summary") and (args.force or (v.get("jev") or {}).get("playlists_hash") != current)]
    log(f"Scoring {len(todo)} videos against {len(plist)} playlists with Jev ({args.jev_model}).")
    with TypeSafeClient(timeout=60) as client:
        def work(video: dict) -> None:
            store.update_video(video["id"], jev=jev.score_video(client, video, plist, args.jev_model))

        parallel(todo, work, args.workers, "jev")


def cmd_report(args, store: Store) -> None:
    plist = store.load_json("playlists.json") or playlists.load_seed_playlists(args.seeds)
    built = report.build(select(store, args), plist, args.threshold, args.review_floor)
    store.save_json("report.json", built)
    paths = report.write(built, args.out, args.top)
    method = "jev" if store.load_json("clusters-jev.json") is not None else "embeddings"
    clusters = store.load_json(f"clusters-{method}.json", [])
    pairs = len(store.load_json(f"similarity-{args.jev_model}.json", {}))
    html_path = Path(args.out) / "playlists.html"
    by_id = {v["id"]: v for v in store.videos()}
    html_path.write_text(report_html.render(built, clusters, by_id, pairs, method), encoding="utf-8")
    log("Wrote " + ", ".join(str(p) for p in paths + [html_path, store.root / "report.json"]))


def cmd_run(args, store: Store) -> None:
    for stage in (cmd_list, cmd_transcribe, cmd_summarize, cmd_discover, cmd_score, cmd_report):
        stage(args, store)


def select(store: Store, args) -> list[dict]:
    videos = store.videos()
    if getattr(args, "kind", "all") != "all":
        videos = [v for v in videos if v.get("kind") == args.kind]
    if getattr(args, "only", None):
        wanted = set(args.only.split(","))
        videos = [v for v in videos if v["id"] in wanted]
    return videos


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="playlist-creator", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default="data", help="cache directory (default: data)")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workers", type=int, default=8)
    common.add_argument("--kind", choices=["all", "video", "short"], default="all")
    common.add_argument("--only", help="comma-separated video ids to process")
    common.add_argument("--force", action="store_true", help="redo work that is already cached")
    common.add_argument("--seeds", help="JSON file of seed playlists (default: built-in)")
    for key, value in DEFAULTS.items():
        common.add_argument(f"--{key.replace('_', '-')}", default=value)

    stages = {
        "list": (cmd_list, "list channel uploads"),
        "transcribe": (cmd_transcribe, "captions, or Gemini watching the video"),
        "summarize": (cmd_summarize, "structured summaries via OpenRouter"),
        "discover": (cmd_discover, "embed + cluster summaries to propose new playlists"),
        "score": (cmd_score, "Jev fit probabilities for every video x playlist"),
        "report": (cmd_report, "write playlists.md / assignments.csv"),
        "run": (cmd_run, "all stages in order"),
    }
    for name, (fn, help_text) in stages.items():
        p = sub.add_parser(name, parents=[common], help=help_text)
        p.set_defaults(fn=fn)
        if name in ("list", "run"):
            p.add_argument("--channel", default=DEFAULT_CHANNEL)
            p.add_argument("--tabs", default="videos,shorts,streams")
            p.add_argument("--per-tab", type=int, help="newest N uploads per tab (for a trial run)")
        if name in ("transcribe", "run"):
            p.add_argument("--method", choices=["auto", "captions", "gemini"], default="auto")
            p.add_argument("--cookies-from-browser", help="e.g. chrome or firefox, if YouTube asks you to sign in")
            p.add_argument("--max-minutes", type=float, help="don't send videos longer than this to Gemini")
        if name in ("discover", "run"):
            p.add_argument("--k", type=int, help="number of clusters (default: chosen automatically)")
            p.add_argument("--k-min", type=int, default=5, help="smallest k the automatic choice considers")
            p.add_argument("--cluster-with", choices=["jev", "embeddings"], default="jev",
                           help="jev: all-pairs Jev similarity + spectral clustering (default); embeddings: k-means")
            p.add_argument("--no-discover", action="store_true", help="only use seed playlists")
        if name in ("report", "run"):
            p.add_argument("--threshold", type=float, default=0.7)
            p.add_argument("--review-floor", type=float, default=0.4)
            p.add_argument("--top", type=int, default=25)
            p.add_argument("--out", default="output")

    args = parser.parse_args(argv)
    args.fn(args, Store(args.data))


if __name__ == "__main__":
    main()
