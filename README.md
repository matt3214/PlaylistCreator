# PlaylistCreator

Suggests YouTube playlists for the [Abolitionists Rising](https://www.youtube.com/@AbolitionistsRising) channel, and which videos belong in each, so newer abolitionists can find videos that answer a particular objection or talking point (moral relativism, bodily autonomy, the hard cases, and so on).

It uses two kinds of model:

- **OpenRouter LLMs** to transcribe videos when YouTube captions aren't available (Gemini watches the video from its URL), to summarize each video, and to explain the clusters it finds.
- **[Jev](https://typesafe.ai)** (TypeSafe's System One model, `jev-latest`) for every judgement that needs a number. Jev returns calibrated probabilities instead of text, and it is fast and cheap enough to ask thousands of questions.

## Pipeline

```
list ─► transcribe ─► summarize ─► discover ─► score ─► report
```

| Stage | What it does | Model |
|---|---|---|
| `list` | Lists the channel's Videos, Shorts and Live tabs. | yt-dlp |
| `transcribe` | Uses YouTube captions when it can. If YouTube blocks the request ("Sign in to confirm you're not a bot") or there are no captions, an LLM watches the video and transcribes it. | `google/gemini-3.1-flash-lite` |
| `summarize` | A structured summary of each video: format, objections raised, arguments made, themes, key moment. | `google/gemini-3.1-flash-lite` |
| `discover` | Clusters the videos to find topics the starter playlists miss (details below). An LLM explains each cluster as a playlist, then keeps only the ones that are distinct from the existing playlists. | Jev + `anthropic/claude-sonnet-5.5` |
| `score` | One Jev request per video. It asks whether the video belongs in each playlist (yes/no probability), how good it is for a newcomer (0–3), and which single playlist fits best. | Jev |
| `report` | Writes `output/playlists.md` and `output/assignments.csv`. | — |

### Clustering with Jev

`discover --cluster-with jev` (the default) asks Jev about **every pair** of summarized videos: *"Do these two videos address the same topic, objection, or talking point, so that they would belong in the same teaching playlist?"* Jev's yes-probability becomes the pair's similarity.

Each request sends one video as the state and batches about 100 of the other videos as separate questions, so 200 videos (19,900 pairs) take about 200 requests. The similarity matrix then goes through spectral clustering: an eigenvector embedding plus k-means, with k set so clusters average about 12 videos (between 5 and 40; override with `--k`). Pair scores are cached in `data/similarity-jev-latest.json`, so adding videos only asks about the new pairs.

`--cluster-with embeddings` is the cheaper alternative: it embeds the summaries (`voyageai/voyage-4-lite`), runs k-means and picks k by silhouette score.

## Sample results

`output/` holds a run on the newest 40 long videos and 160 Shorts (October 2026): `playlists.md`, `playlists.html` (open it in a browser), `assignments.csv`, the final `playlists.json`, and the explained Jev clusters in `clusters-jev.json`.

## Setup

```
python -m venv .venv && source .venv/bin/activate
pip install -e '.[test]'
export OPENROUTER_API_KEY=...   # https://openrouter.ai/keys
export TYPESAFE_API_KEY=...     # https://typesafe.ai
```

## Usage

Trial run on the newest uploads:

```
playlist-creator run --tabs videos,shorts --per-tab 25
```

Whole channel, one stage at a time (every stage caches into `data/` and skips work it has already done, so you can stop and resume):

```
playlist-creator list
playlist-creator transcribe            # --method captions|gemini|auto (default auto)
playlist-creator summarize
playlist-creator discover              # --cluster-with jev|embeddings, --k 15 to force the cluster count
playlist-creator score
playlist-creator report --threshold 0.7
```

Common options: `--workers 8`, `--kind short|video`, `--only id1,id2`, `--force`, and a model override for each step (`--summary-model`, `--video-model`, `--curate-model`, `--embedding-model`, `--jev-model`).

### Editing the playlists

The starter playlists are in `playlist_creator/seed_playlists.json`. After `discover`, the working list is `data/playlists.json`, which holds the seeds plus any playlists found by clustering. You can rename playlists, merge them, or rewrite their descriptions there. Jev judges fit against the **description**, so a sharper description gives sharper results. `score` re-runs automatically for any video whose playlist list has changed.

### Reading the report

- A video is **included** in a playlist when Jev's fit probability is at least `--threshold` (0.7). A video can appear in several playlists.
- Fits between `--review-floor` (0.4) and the threshold are listed as **borderline** for a human to decide.
- Within a playlist, videos that are both on topic and good for newcomers come first.
- A playlist with `"top": N` in its JSON (Start Here has `"top": 15`) is a ranking rather than a topic. It keeps its N best videos instead of applying the threshold.

### YouTube blocking

From cloud or server IPs, YouTube often refuses per-video requests. Listing the channel still works, and transcription falls back to Gemini automatically. On your own machine, captions usually work and are free. If YouTube asks you to sign in, pass `--cookies-from-browser chrome`.

## Cost (rough)

- Gemini watching video: about $0.004 per Short and $0.04–0.06 per 20-minute video. With captions, transcription is free.
- Summaries: well under $0.001 per video.
- Jev: about 260 input tokens per pair question and about 300 + 150 × playlists per scoring request.

## Tests

```
pytest -q
```

The tests run offline. Jev is mocked with an `httpx2.MockTransport`.
