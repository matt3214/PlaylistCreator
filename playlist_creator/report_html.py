"""Self-contained HTML page for browsing the suggested playlists, clusters, and unplaced videos."""

import json

TEMPLATE = r"""<title>Abolitionist Playlist Builder</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,500;8..60,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: masthead, then a playlist index rail beside the open playlist; the rail stacks above on phones. */
:root {
  --bg: #f4f5f2;
  --surface: #ffffff;
  --fg: #1c211e;
  --muted: #5d665f;
  --line: #dde1db;
  --accent: #9a2a2a;
  --accent-soft: #f5e4e2;
  --fit: #2d5e50;
  --fit-track: #e3e9e5;
  --warn: #8a5a00;
  --font-display: "Source Serif 4", Georgia, "Times New Roman", serif;
  --font-body: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-data: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #141816; --surface: #1b201d; --fg: #e6eae6; --muted: #9aa49d; --line: #2c332f;
    --accent: #e07a6f; --accent-soft: #3a2220; --fit: #7cc2a9; --fit-track: #26302b; --warn: #e2b04d;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #141816; --surface: #1b201d; --fg: #e6eae6; --muted: #9aa49d; --line: #2c332f;
  --accent: #e07a6f; --accent-soft: #3a2220; --fit: #7cc2a9; --fit-track: #26302b; --warn: #e2b04d;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--fg); font: 15px/1.55 var(--font-body); }
.wrap { max-width: 1180px; margin: 0 auto; padding-inline: 16px; padding-block: 28px 64px; }
a { color: inherit; }
a:focus-visible, button:focus-visible, input:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
header { display: grid; gap: 10px; padding-bottom: 22px; border-bottom: 1px solid var(--line); }
.eyebrow { font: 500 12px/1 var(--font-data); letter-spacing: .08em; text-transform: uppercase; color: var(--accent); }
h1 { font: 700 clamp(28px, 4.2vw, 42px)/1.1 var(--font-display); margin: 0; text-wrap: balance; }
.lede { color: var(--muted); max-width: 68ch; margin: 0; }
.stats { display: flex; flex-wrap: wrap; gap: 6px 22px; font: 13px var(--font-data); color: var(--muted); font-variant-numeric: tabular-nums; }
.stats b { color: var(--fg); font-weight: 500; }
nav.tabs { display: flex; flex-wrap: wrap; gap: 4px; margin: 18px 0 20px; }
nav.tabs button { font: 500 14px var(--font-body); padding: 8px 14px; border-radius: 999px; border: 1px solid var(--line); background: transparent; color: var(--muted); cursor: pointer; }
nav.tabs button[aria-selected="true"] { background: var(--fg); color: var(--bg); border-color: var(--fg); }
.layout { display: grid; grid-template-columns: minmax(240px, 300px) minmax(0, 1fr); gap: 28px; align-items: start; }
@media (max-width: 820px) { .layout { grid-template-columns: minmax(0, 1fr); } }
.rail { display: grid; gap: 2px; position: sticky; top: calc(env(safe-area-inset-top, 0px) + 12px); max-height: calc(100vh - 24px); overflow-y: auto; }
@media (max-width: 820px) { .rail { position: static; max-height: 260px; border: 1px solid var(--line); border-radius: 8px; padding: 4px; } }
.rail button { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 10px; text-align: left; padding: 9px 12px; border: 0; border-left: 3px solid transparent; background: transparent; color: var(--fg); cursor: pointer; font: inherit; border-radius: 0 6px 6px 0; }
.rail button:hover { background: var(--surface); }
.rail button[aria-current="true"] { background: var(--surface); border-left-color: var(--accent); }
.rail .name { font-weight: 500; font-size: 14px; line-height: 1.35; }
.rail .count { font: 13px var(--font-data); color: var(--muted); font-variant-numeric: tabular-nums; }
.rail .src { grid-column: 1 / -1; font: 11px var(--font-data); color: var(--muted); letter-spacing: .04em; text-transform: uppercase; }
.rail .src.found { color: var(--accent); }
.panel { min-width: 0; display: grid; gap: 18px; }
.panel h2 { font: 700 26px/1.2 var(--font-display); margin: 0; text-wrap: balance; }
.desc { margin: 0; max-width: 70ch; color: var(--muted); }
.why { margin: 0; padding: 10px 14px; background: var(--accent-soft); border-radius: 6px; font-size: 14px; max-width: 70ch; }
.toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.toolbar input { flex: 1 1 220px; min-width: 0; font: inherit; padding: 8px 12px; border-radius: 6px; border: 1px solid var(--line); background: var(--surface); color: var(--fg); }
.toolbar label { display: flex; gap: 6px; white-space: nowrap; align-items: center; font-size: 13px; color: var(--muted); }
.list { display: grid; border-top: 1px solid var(--line); }
.row { display: grid; grid-template-columns: 2.2em minmax(0, 1fr) 150px; gap: 4px 16px; padding: 14px 0; border-bottom: 1px solid var(--line); }
@media (max-width: 560px) { .row { grid-template-columns: 2em minmax(0, 1fr); } .row .meters { grid-column: 2; } }
.rank { font: 13px var(--font-data); color: var(--muted); padding-top: 2px; font-variant-numeric: tabular-nums; }
.title { font-weight: 600; text-decoration: none; }
.title:hover { text-decoration: underline; }
.meta { display: flex; flex-wrap: wrap; gap: 8px; margin: 3px 0 6px; font: 12px var(--font-data); color: var(--muted); }
.chip { padding: 1px 7px; border-radius: 999px; border: 1px solid var(--line); }
.chip.short { border-color: var(--accent); color: var(--accent); }
.sum { margin: 0; font-size: 14px; color: var(--muted); max-width: 72ch; }
.sum q { color: var(--fg); }
.meters { display: grid; gap: 8px; align-content: start; font: 12px var(--font-data); font-variant-numeric: tabular-nums; }
.meter { display: grid; grid-template-columns: 5.6em minmax(0, 1fr) 3.2em; gap: 6px; align-items: center; color: var(--muted); }
.bar { height: 6px; border-radius: 3px; background: var(--fit-track); overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--fit); }
.bar.newc i { background: var(--accent); }
.val { text-align: right; color: var(--fg); }
details.review { border: 1px solid var(--line); border-radius: 8px; padding: 10px 14px; background: var(--surface); }
details.review summary { cursor: pointer; font-weight: 500; }
details.review .row { grid-template-columns: minmax(0, 1fr) 150px; }
@media (max-width: 560px) { details.review .row { grid-template-columns: minmax(0, 1fr); } details.review .row .meters { grid-column: 1; } }
.empty { color: var(--muted); font-style: italic; }
button.more { justify-self: start; font: 500 14px var(--font-body); padding: 8px 14px; border-radius: 6px; border: 1px solid var(--line); background: var(--surface); color: var(--fg); cursor: pointer; }
.clusters { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr)); gap: 16px; }
.cluster { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 16px 18px; display: grid; gap: 8px; align-content: start; min-width: 0; }
.cluster h3 { font: 700 19px/1.25 var(--font-display); margin: 0; text-wrap: balance; }
.cluster .meta { margin: 0; }
.cluster ol { margin: 0; padding-left: 1.3em; font-size: 14px; display: grid; gap: 3px; }
.cluster ol a { text-decoration: none; }
.cluster ol a:hover { text-decoration: underline; }
.flag { color: var(--warn); }
.note { font-size: 13px; color: var(--muted); max-width: 72ch; margin: 0 0 16px; }
footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--line); font-size: 13px; color: var(--muted); max-width: 80ch; }
</style>

<div class="wrap">
  <header>
    <div class="eyebrow">Abolitionists Rising · playlist suggestions</div>
    <h1>Playlists for newer abolitionists</h1>
    <p class="lede">Each video was transcribed and summarized by an LLM, then Jev judged how likely it is to belong in each playlist and how well it serves someone new to abolition. Playlists marked <em>found by clustering</em> came from grouping videos Jev rated as covering the same topic or talking point.</p>
    <div class="stats" id="stats"></div>
  </header>
  <nav class="tabs" role="tablist" aria-label="Views">
    <button role="tab" id="tab-playlists" aria-selected="true" data-view="playlists">Playlists</button>
    <button role="tab" id="tab-clusters" aria-selected="false" data-view="clusters">Jev clusters</button>
    <button role="tab" id="tab-unplaced" aria-selected="false" data-view="unplaced">Not placed</button>
  </nav>
  <main id="view"></main>
  <footer id="foot"></footer>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById("data").textContent);
// Rows arrive as [id, fit] / id references into DATA.videos; expand them once.
const V = DATA.videos;
const hyd = ([id, fit]) => ({ ...V[id], id, fit });
DATA.report.playlists.forEach(p => { p.videos = p.videos.map(hyd); p.review = p.review.map(hyd); });
DATA.report.unplaced = DATA.report.unplaced.map(id => hyd([id, null]));
DATA.clusters.forEach(c => { c.videos = c.videos.map(id => V[id]); });
const PAGE = 150;
let showAll = false;
const view = document.getElementById("view");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pct = x => Math.round(x * 100) + "%";
const dur = s => s ? (s >= 3600 ? Math.floor(s/3600) + "h " : "") + Math.floor((s % 3600) / 60) + ":" + String(Math.round(s % 60)).padStart(2, "0") : "";
const playlists = DATA.report.playlists;
let current = playlists.length ? playlists[0].slug : null;
let filter = "", shortsOnly = false;
try { const saved = localStorage.getItem("pl-current"); if (saved && playlists.some(p => p.slug === saved)) current = saved; } catch (e) {}

document.getElementById("stats").innerHTML = [
  ["videos scored", DATA.report.scored_videos],
  ["playlists", playlists.length],
  ["found by clustering", playlists.filter(p => p.source === "cluster").length],
  ["fit threshold", pct(DATA.report.threshold)],
  ["Jev pair judgements", DATA.pairs.toLocaleString()],
].map(([k, v]) => `<span><b>${esc(v)}</b> ${esc(k)}</span>`).join("");
document.getElementById("foot").textContent = DATA.footer;

function meters(r) {
  const fit = r.fit == null ? "" : `<div class="meter"><span>fit</span><span class="bar"><i style="width:${pct(r.fit)}"></i></span><span class="val">${pct(r.fit)}</span></div>`;
  return `<div class="meters">${fit}<div class="meter"><span>newcomer</span><span class="bar newc"><i style="width:${pct(r.newcomer / 3)}"></i></span><span class="val">${r.newcomer.toFixed(1)}/3</span></div></div>`;
}
function row(r, i) {
  const kind = r.kind === "short" ? `<span class="chip short">Short</span>` : `<span class="chip">Video</span>`;
  const moment = r.key_moment ? ` <q>${esc(r.key_moment)}</q>` : "";
  return `<div class="row">${i != null ? `<span class="rank">${i + 1}</span>` : ""}
    <div style="min-width:0"><a class="title" href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>
      <div class="meta">${kind}${r.duration ? `<span>${dur(r.duration)}</span>` : ""}${r.views ? `<span>${Number(r.views).toLocaleString()} views</span>` : ""}</div>
      <p class="sum">${esc(r.summary)}${moment}</p></div>
    ${meters(r)}</div>`;
}
const match = r => (!shortsOnly || r.kind === "short") && (!filter || (r.title + " " + r.summary).toLowerCase().includes(filter));

function renderPlaylists() {
  const p = playlists.find(x => x.slug === current);
  const rail = playlists.map(x => `<button data-slug="${esc(x.slug)}" aria-current="${x.slug === current}">
      <span class="name">${esc(x.name)}</span><span class="count">${x.videos.length}</span>
      <span class="src ${x.source === "cluster" ? "found" : ""}">${x.source === "cluster" ? "found by clustering" : "starter playlist"}</span></button>`).join("");
  let body = `<p class="empty">No playlists.</p>`;
  if (p) {
    const allVids = p.videos.filter(match), rev = p.review.filter(match);
    const vids = showAll ? allVids : allVids.slice(0, PAGE);
    const more = allVids.length > vids.length ? `<button class="more" id="more">Show all ${allVids.length} videos</button>` : "";
    body = `<h2>${esc(p.name)}</h2><p class="desc">${esc(p.description)}</p>
      ${p.why_distinct ? `<p class="why"><strong>Why this is its own playlist:</strong> ${esc(p.why_distinct)}</p>` : ""}
      <div class="toolbar"><input id="q" type="search" placeholder="Filter by title or summary" value="${esc(filter)}" aria-label="Filter videos">
        <label><input id="shorts" type="checkbox" ${shortsOnly ? "checked" : ""}> Shorts only</label></div>
      <div class="list">${vids.length ? vids.map(row).join("") : `<p class="empty">No videos cleared the ${pct(DATA.report.threshold)} threshold${filter || shortsOnly ? " with this filter" : ""}.</p>`}</div>${more}
      ${rev.length ? `<details class="review"><summary>${rev.length} borderline (${pct(DATA.report.review_floor)}–${pct(DATA.report.threshold)}) to review</summary><div class="list">${rev.map(r => row(r, null)).join("")}</div></details>` : ""}`;
  }
  view.innerHTML = `<div class="layout"><div class="rail" role="list">${rail}</div><section class="panel">${body}</section></div>`;
  const m = view.querySelector("#more");
  if (m) m.onclick = () => { showAll = true; renderPlaylists(); };
  view.querySelectorAll(".rail button").forEach(b => b.onclick = () => { current = b.dataset.slug; showAll = false; try { localStorage.setItem("pl-current", current); } catch (e) {} renderPlaylists(); });
  const q = view.querySelector("#q");
  if (q) q.oninput = () => { filter = q.value.trim().toLowerCase(); const pos = q.selectionStart; renderPlaylists(); const n = view.querySelector("#q"); n.focus(); n.setSelectionRange(pos, pos); };
  const s = view.querySelector("#shorts");
  if (s) s.onchange = () => { shortsOnly = s.checked; renderPlaylists(); };
}

function renderClusters() {
  if (!DATA.clusters.length) { view.innerHTML = `<p class="empty">No clustering run yet.</p>`; return; }
  view.innerHTML = `<p class="note">${esc(DATA.cluster_note)}</p><div class="clusters">${DATA.clusters.map(c => `
    <article class="cluster"><h3>${esc(c.name || "Cluster " + c.cluster)}</h3>
      <div class="meta"><span>${c.size} videos</span><span>avg. similarity ${pct(c.cohesion)}</span>${c.coherent === false ? `<span class="flag">loose grouping</span>` : ""}</div>
      <p class="sum">${esc(c.description || "")}</p>
      <ol>${c.videos.slice(0, 8).map(v => `<li><a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.title)}</a></li>`).join("")}</ol>
      ${c.videos.length > 8 ? `<div class="meta">+ ${c.videos.length - 8} more</div>` : ""}</article>`).join("")}</div>`;
}

function renderUnplaced() {
  const rows = DATA.report.unplaced.slice(0, 400);
  view.innerHTML = `<p class="note">Videos that did not reach the ${pct(DATA.report.threshold)} fit threshold for any playlist. Many are short clips whose point depends on the full conversation; some may suggest a playlist that doesn't exist yet.</p>
    <div class="list">${rows.length ? rows.map(r => row(r, null)).join("") : `<p class="empty">Every scored video landed in at least one playlist.</p>`}</div>`;
}

const renders = { playlists: renderPlaylists, clusters: renderClusters, unplaced: renderUnplaced };
document.querySelectorAll("nav.tabs button").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav.tabs button").forEach(x => x.setAttribute("aria-selected", x === b));
  renders[b.dataset.view]();
});
renderPlaylists();
</script>
"""


STANDALONE_HEAD = '<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'


def render(report: dict, clusters: list[dict], videos_by_id: dict, pairs: int, cluster_method: str,
           standalone: bool = True) -> str:
    """The page as HTML. standalone=False omits the doctype/meta head (for hosts that add their own).

    Each video is stored once in "videos"; playlists, clusters and the unplaced list refer to it by id.
    """
    from playlist_creator.youtube import video_url

    videos: dict[str, dict] = {}

    def ref(row_or_id) -> str:
        vid = row_or_id if isinstance(row_or_id, str) else row_or_id["id"]
        if vid not in videos:
            v = videos_by_id.get(vid, {"id": vid})
            s = v.get("summary") or {}
            videos[vid] = {
                "title": v.get("title", vid),
                "url": v.get("url") or video_url(vid, v.get("kind") == "short"),
                "kind": v.get("kind", "video"),
                "duration": v.get("duration"),
                "views": v.get("view_count"),
                "newcomer": round((v.get("jev") or {}).get("newcomer") or 0.0, 2),
                "summary": s.get("summary", ""),
                "key_moment": s.get("key_moment", ""),
            }
        return vid

    slim_report = {
        **{k: report[k] for k in ("threshold", "review_floor", "scored_videos")},
        "playlists": [
            {k: p.get(k) for k in ("slug", "name", "description", "source", "why_distinct", "top")}
            | {"videos": [[ref(r), round(r["fit"], 3)] for r in p["videos"]],
               "review": [[ref(r), round(r["fit"], 3)] for r in p["review"]]}
            for p in report["playlists"]
        ],
        "unplaced": [ref(r) for r in report["unplaced"]],
    }
    slim_clusters = [
        {k: c.get(k) for k in ("cluster", "name", "description", "coherent", "size", "cohesion")}
        | {"videos": [ref(i) for i in c["video_ids"][:8]]}
        for c in clusters
    ]
    method = ("Jev rated every pair of videos for whether they cover the same topic or talking point; spectral "
              "clustering grouped them, and an LLM named and explained each group."
              if cluster_method == "jev" else
              "Video summaries were embedded and grouped with k-means; an LLM named and explained each group.")
    data = {
        "report": slim_report,
        "videos": videos,
        "clusters": slim_clusters,
        "pairs": pairs,
        "cluster_note": method + " Videos are listed most central first. Clusters that duplicate a starter playlist were not added as new playlists.",
        "footer": "Generated by PlaylistCreator. Fit and newcomer scores are Jev's probabilities, not human judgements. "
                  "Review borderline videos before publishing a playlist.",
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = TEMPLATE.replace("__DATA__", payload)
    return STANDALONE_HEAD + page if standalone else page
