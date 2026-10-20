#!/usr/bin/env python3
"""VOC collector for the creative-strategy skill.

Stores every retrieved post, comment and review with its own permalink, then accepts a quote only if it is
found verbatim in the stored text. Everything lives in one project folder (JSONL files), and `export` turns it
into rows for the Google Sheet.

Routes (see references/access.md):
  reddit-find / reddit-thread   Arctic Shift archive of Reddit: full threads, verbatim, one permalink per comment
  yt-find / yt-comments         YouTube search, comments and subtitles through yt-dlp, verbatim
  web-add / web-confirm         pages read with the agent's WebFetch tool (Trustpilot, Mumsnet, forums):
                                short exact quote + paraphrase; a second independent read confirms the quote
  web-page                      whole page text, verbatim: plain request, then real Chromium, then Wayback,
                                or --file saved by the user (never clicks a "verify you are human" check)
  user-add                      text the user pasted or showed on a screenshot, or that the agent read in the
                                user's own browser (--route BROWSER): Facebook groups, Amazon, Ad Library
  log-search                    log a web search done with the agent's own search tool

Then:
  show            print stored texts of a thread or page for reading
  add-quotes      add tagged quotes (batch, JSON); rejects any quote that is not verbatim in its source
  stats           volume, clusters with independent threads and authors, query balance, novelty, freshness
  check-insights  strength of each insight from its quotes and counter-searches (the script decides, not the model)
  packet          source texts for an independent auditor agent
  export          rows for the Google Sheet tabs VOC, Источники, Запросы
  stage           record or show which stages the user approved (the skill waits for approval after each)

Usage: python3 voc.py --project-dir research/<ID> <command> ...
"""
import argparse
import datetime
import hashlib
import html
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ARCHIVE = "https://arctic-shift.photon-reddit.com/api"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

# Source statuses, strongest first. SNIPPET (search-result text) is never stored as VOC.
STATUS = {
    "VERBATIM": "full text read by a script from the original or its archive",
    "BROWSER": "page text the agent read in the user's own browser (Claude in Chrome / desktop app)",
    "USER": "text the user pasted or showed on a screenshot",
    "WEB_CONFIRMED": "WebFetch quote confirmed by a second independent read",
    "WEB_QUOTE": "WebFetch quote, not yet confirmed",
    "WEB_UNCONFIRMED": "second read did not find the quote; do not use as a quote",
}
STRONG = {"VERBATIM", "BROWSER", "USER", "WEB_CONFIRMED"}

# Thresholds for check-insights. An insight is CONFIRMED only with all of them.
CONFIRMED = {"quotes": 5, "groups": 3, "authors": 5, "platforms_or_groups": (2, 4), "strong_quotes": 3,
             "counter_search": 1}

# Who is speaking. Each quote carries it; insights count only the speakers that can support their kind.
SPEAKERS = {"OUR_SKU": "наш SKU", "OUR_BRAND": "наш бренд", "COMPETITOR": "конкурент", "CATEGORY": "категория",
            "ALTERNATIVE": "альтернатива"}
RELATIONS = {"OWNER": "владеет", "SHOPPER": "выбирает", "NON_BUYER": "отказался / обходится", "UNKNOWN": "не ясно"}
# kind -> (speakers whose quotes count, thresholds that replace CONFIRMED for this kind)
INSIGHT_KINDS = {
    "PATTERN": (set(SPEAKERS), {}),                       # mass pain / desire / behaviour: any layer, not ours only
    "PRODUCT": ({"OUR_SKU"}, {"quotes": 3, "groups": 2, "authors": 3, "strong_quotes": 2}),
    "BRAND": ({"OUR_SKU", "OUR_BRAND"}, {"quotes": 3, "groups": 2, "authors": 3, "strong_quotes": 2}),
    "COMPETITOR_GAP": ({"COMPETITOR"}, {}),               # what competitors' buyers miss: their buyers only
    "BARRIER": ({"ALTERNATIVE", "CATEGORY", "COMPETITOR", "OUR_BRAND", "OUR_SKU"}, {}),  # why people don't buy
}
FRESH_MONTHS = 24

VOC_COLUMNS = ["ID", "Цитата (оригинал)", "Перевод", "Тип", "Тема", "Персона", "Эмоция", "Кластер", "Сила",
               "Рынок", "Площадка", "Источник ID", "URL", "Дата", "Рейтинг", "Статус проверки",
               "Что сделал человек", "Автор (ключ)", "Кто говорит", "Бренд", "Отношение к продукту"]
SOURCE_COLUMNS = ["ID", "Площадка", "Название / тред", "URL", "Рынок", "Тип", None, "Как получено",
                  "Статус", "Текстов сохранено", "Запрос", "Дата сбора"]
QUERY_COLUMNS = ["ID", "Дата", "Площадка", "Маршрут", "Запрос", "Ветка", "Тон", "Этап пути", "Почему (находка)",
                 "Найдено", "Статус"]
QUOTE_TYPES = ["Боль", "Желание", "Возражение", "Триггер", "Опыт", "Язык", "Решение", "Контрдовод"]
ACTIONS = ["", "NONE", "CONSIDERED", "POSTPONED", "BOUGHT", "REJECTED", "RETURNED", "SWITCHED", "USES",
           "STOPPED_USING", "WORKAROUND", "RECOMMENDS"]
POLARITY = ["PROBLEM", "NEUTRAL", "POSITIVE", "SWITCH", "COUNTER"]


# ---------- storage ----------

def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_jsonl(path, rows):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


class Project:
    def __init__(self, d):
        self.dir = Path(d)
        self.queries = self.dir / "queries.jsonl"
        self.sources = self.dir / "sources.jsonl"
        self.groups = self.dir / "groups.jsonl"
        self.voc = self.dir / "voc.jsonl"
        self.cache = self.dir / "raw"

    def meta(self):
        p = self.dir / "project.json"
        if not p.exists():
            raise SystemExit(f"{p} not found: run init first")
        return json.loads(p.read_text(encoding="utf-8"))


def next_id(rows, key, prefix, width):
    n = 0
    for r in rows:
        m = re.match(re.escape(prefix) + r"(\d+)$", str(r.get(key, "")))
        if m:
            n = max(n, int(m.group(1)))
    return f"{prefix}{n + 1:0{width}d}"


def norm(s):
    """Normalisation for verbatim checks: unify quotes, dashes, ellipses and whitespace; keep words and case."""
    s = html.unescape(s or "")
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("—", "-").replace("–", "-").replace(" ", " ").replace("…", "...")
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)  # markdown links -> their text
    s = s.replace("\\", "").replace("*", "")
    return re.sub(r"\s+", " ", s).strip()


def verbatim_in(quote, text):
    """True if every part of the quote (split on '...' / '…' cuts) appears in the text, in order."""
    parts = [p.strip() for p in re.split(r"\s*\.\.\.\s*|\s*\[\.\.\.\]\s*", norm(quote)) if p.strip()]
    t, pos = norm(text), 0
    if not parts:
        return False
    for p in parts:
        i = t.find(p, pos)
        if i < 0:
            return False
        pos = i + len(p)
    return True


def author_key(platform, name):
    if not name or name in ("[deleted]", "[removed]"):
        return ""
    return hashlib.sha1(f"{platform}:{name.lower()}".encode()).hexdigest()[:10]


def to_date(ts):
    if ts in (None, ""):
        return ""
    if isinstance(ts, (int, float)):
        return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date().isoformat()
    return str(ts)[:10]


# ---------- http ----------

class Fetcher:
    """GET with an on-disk cache and patient retries. Arctic Shift answers HTTP 200 with
    {"error": "Timeout. Maybe slow down a bit"} under load; that is retried like a 429."""

    def __init__(self, cache_dir, gap=2.0, retries=6):
        self.cache_dir, self.gap, self.retries, self.last = Path(cache_dir), gap, retries, 0.0

    def get_json(self, url, use_cache=True):
        cpath = self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".json")
        if use_cache and cpath.exists():
            return json.loads(cpath.read_text(encoding="utf-8")), True
        wait = 5
        err = None
        for attempt in range(self.retries + 1):
            time.sleep(max(0.0, self.last + self.gap - time.time()))
            self.last = time.time()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=90) as r:
                    payload = json.loads(r.read().decode("utf-8", errors="replace"))
                err = payload.get("error") if isinstance(payload, dict) else None
                if not err:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    cpath.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    return payload, False
                if "timeout" not in err.lower() and "slow down" not in err.lower():
                    return {"error": err}, False
            except urllib.error.HTTPError as e:
                err = f"HTTP {e.code}"
                if e.code not in (422, 429, 500, 502, 503, 504):  # Arctic Shift sends 422 under load too
                    return {"error": err}, False
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                err = str(e)
            if attempt < self.retries:
                print(f"  {err}; retry in {wait}s", file=sys.stderr, flush=True)
                time.sleep(wait)
                wait = min(wait * 2, 120)
        return {"error": err}, False


# ---------- shared writers ----------

def log_query(P, a, platform, route, q, found, status, extra=None):
    rows = read_jsonl(P.queries)
    qid = next_id(rows, "id", "SQ", 3)
    row = {"id": qid, "at": now_iso(), "platform": platform, "route": route, "q": q,
           "branch": getattr(a, "branch", "") or "", "polarity": getattr(a, "polarity", "") or "",
           "stage": getattr(a, "stage", "") or "", "why": getattr(a, "why", "") or "", "found": found,
           "status": status}
    row.update(extra or {})
    append_jsonl(P.queries, [row])
    return qid


def upsert_group(P, key, platform, title, url, route, status, market="", kind="VOC", query_id=""):
    """A group is one thread, video or page: the unit of independence. Returns its S-id."""
    rows = read_jsonl(P.groups)
    for g in rows:
        if g["key"] == key:
            return g["id"]
    gid = next_id(rows, "id", "S", 3)
    append_jsonl(P.groups, [{"id": gid, "key": key, "platform": platform, "title": title, "url": url,
                             "route": route, "status": status, "market": market, "kind": kind,
                             "query_id": query_id, "at": now_iso()}])
    return gid


def add_sources(P, rows):
    existing = {s["id"] for s in read_jsonl(P.sources)}
    new = [r for r in rows if r["id"] not in existing]
    append_jsonl(P.sources, new)
    return len(new), len(rows) - len(new)


# ---------- commands: setup and logging ----------

def cmd_init(a):
    P = Project(a.project_dir)
    p = P.dir / "project.json"
    if p.exists():
        raise SystemExit(f"{p} already exists")
    P.dir.mkdir(parents=True, exist_ok=True)
    meta = {"id": a.id, "product": a.product, "markets": a.markets, "decision": a.decision,
            "mode": a.mode, "created": now_iso(), "sheet_url": ""}
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"project {a.id} created in {P.dir}")


def cmd_log_search(a):
    P = Project(a.project_dir)
    print(log_query(P, a, a.platform, "WEBSEARCH", a.q, a.found, "OK"))


# ---------- commands: Reddit via Arctic Shift ----------

def thread_id_of(s):
    m = re.search(r"/comments/([a-z0-9]+)", s)
    return m.group(1) if m else re.sub(r"^t3_", "", s.strip())


def cmd_reddit_find(a):
    P = Project(a.project_dir)
    f = Fetcher(P.cache)
    params = {"subreddit": a.subreddit, "limit": str(a.limit), "sort": "desc",
              "fields": "id,title,num_comments,created_utc,score"}
    params["query" if a.kind == "posts" else "body"] = a.q
    endpoint = "posts" if a.kind == "posts" else "comments"
    if a.kind == "comments":
        params["fields"] = "id,link_id,body,created_utc"
    payload, cached = f.get_json(f"{ARCHIVE}/{endpoint}/search?" + urllib.parse.urlencode(params))
    data = payload.get("data") or []
    status = "OK" if "error" not in payload else f"ERROR: {payload['error']}"
    if a.kind == "posts":
        found = [(d["id"], d.get("num_comments"), d.get("title", "")) for d in data]
    else:
        by = {}
        for d in data:
            by.setdefault(d.get("link_id", "")[3:], []).append(d)
        found = [(tid, f"{len(cs)} match", norm(cs[0].get("body", ""))[:120]) for tid, cs in by.items()]
    qid = log_query(P, a, "reddit", "ARCHIVE", a.q, len(found), status, {"subreddit": a.subreddit, "kind": a.kind})
    print(f"{qid}: r/{a.subreddit} {a.kind} '{a.q}': {len(found)} threads ({status}{', cache' if cached else ''})")
    for tid, n, title in found:
        print(f"  {tid}  [{n}]  {title}")


def walk_tree(nodes, out, more):
    for n in nodes or []:
        if n.get("kind") == "more":
            more[0] += len((n.get("data") or {}).get("children") or [])
            continue
        d = n.get("data") or {}
        out.append(d)
        rep = d.get("replies")
        if isinstance(rep, dict):
            walk_tree((rep.get("data") or {}).get("children"), out, more)


def cmd_reddit_thread(a):
    P = Project(a.project_dir)
    f = Fetcher(P.cache)
    tid = thread_id_of(a.thread)
    post_payload, _ = f.get_json(f"{ARCHIVE}/posts/ids?" + urllib.parse.urlencode(
        {"ids": tid, "fields": "id,title,selftext,author,created_utc,num_comments,subreddit,score"}))
    posts = post_payload.get("data") or []
    if not posts:
        raise SystemExit(f"thread {tid}: not in archive ({post_payload.get('error', 'no data')})")
    post = posts[0]
    sub = post.get("subreddit", "")
    tree, _ = f.get_json(f"{ARCHIVE}/comments/tree?" + urllib.parse.urlencode({"link_id": tid, "limit": "9999"}))
    if "error" in tree:
        raise SystemExit(f"thread {tid}: comments not retrieved ({tree['error']})")
    comments, more = [], [0]
    walk_tree(tree.get("data"), comments, more)
    turl = f"https://www.reddit.com/r/{sub}/comments/{tid}/"
    gid = upsert_group(P, f"reddit:{tid}", "reddit", f"r/{sub}: {post.get('title', '')}", turl, "ARCHIVE",
                       "VERBATIM", a.market, query_id=a.query or "")
    rows = []
    body = (post.get("selftext") or "").strip()
    if body in ("[deleted]", "[removed]"):
        body = ""
    rows.append({"id": f"rd:{tid}", "group": gid, "platform": "reddit", "route": "ARCHIVE", "status": "VERBATIM",
                 "kind": "post", "url": turl, "author_key": author_key("reddit", post.get("author")),
                 "date": to_date(post.get("created_utc")), "title": post.get("title", ""),
                 "text": (post.get("title", "") + "\n" + body).strip(), "score": post.get("score"),
                 "retrieved_at": now_iso()})
    skipped = 0
    for c in comments:
        text = (c.get("body") or "").strip()
        if not text or text in ("[deleted]", "[removed]") or c.get("author") == "AutoModerator":
            skipped += 1
            continue
        cid = c["id"]
        rows.append({"id": f"rd:{cid}", "group": gid, "platform": "reddit", "route": "ARCHIVE",
                     "status": "VERBATIM", "kind": "comment",
                     "url": f"https://www.reddit.com/r/{sub}/comments/{tid}/comment/{cid}/",
                     "parent": (c.get("parent_id") or "")[3:], "author_key": author_key("reddit", c.get("author")),
                     "date": to_date(c.get("created_utc")), "text": text, "score": c.get("score"),
                     "retrieved_at": now_iso()})
    new, dup = add_sources(P, rows)
    print(f"{gid} thread {tid} r/{sub}: {post.get('title', '')}")
    print(f"  stored {new} new texts ({dup} already stored), skipped {skipped} deleted/bot, "
          f"archive reports {post.get('num_comments')} comments, {more[0]} hidden behind 'more' links")
    print("  archive snapshot: text is what the author wrote; it may since have been edited or deleted on Reddit")


# ---------- commands: YouTube via yt-dlp ----------

def ytdlp(args):
    cmd = [sys.executable, "-m", "yt_dlp"] + args
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except FileNotFoundError:
        raise SystemExit("yt-dlp missing: pip install yt-dlp")


def cmd_yt_find(a):
    P = Project(a.project_dir)
    r = ytdlp(["--flat-playlist", "--print", "%(id)s\t%(view_count)s\t%(channel)s\t%(title)s",
               f"ytsearch{a.n}:{a.q}"])
    if r.returncode != 0 and "No module named yt_dlp" in r.stderr:
        raise SystemExit("yt-dlp missing: pip install yt-dlp")
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    status = "OK" if r.returncode == 0 else f"ERROR: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else r.returncode}"
    qid = log_query(P, a, "youtube", "YTDLP", a.q, len(lines), status)
    print(f"{qid}: '{a.q}': {len(lines)} videos ({status})")
    for ln in lines:
        vid, views, ch, title = (ln.split("\t") + ["", "", "", ""])[:4]
        print(f"  https://www.youtube.com/watch?v={vid}  views={views}  {ch}: {title}")


def vtt_to_text(vtt):
    out, last = [], ""
    for ln in vtt.splitlines():
        ln = re.sub(r"<[^>]+>", "", ln).strip()
        if not ln or "-->" in ln or ln.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or ln.isdigit():
            continue
        if ln != last:
            out.append(ln)
            last = ln
    return " ".join(out)


def cmd_yt_comments(a):
    P = Project(a.project_dir)
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", a.url)
    vid = m.group(1) if m else a.url.strip()
    work = P.cache / "yt"
    work.mkdir(parents=True, exist_ok=True)
    args = ["--skip-download", "--write-comments", "--no-warnings",
            "--extractor-args", f"youtube:max_comments={a.max},all,all;comment_sort=top",
            "-o", str(work / "%(id)s"), f"https://www.youtube.com/watch?v={vid}"]
    if a.subs:
        args[1:1] = ["--write-auto-subs", "--write-subs", "--sub-langs", "en.*,en", "--sub-format", "vtt"]
    r = ytdlp(args)
    info_path = work / f"{vid}.info.json"
    if not info_path.exists():
        raise SystemExit(f"video {vid}: nothing retrieved\n{r.stderr[-800:]}")
    info = json.loads(info_path.read_text(encoding="utf-8"))
    vurl = f"https://www.youtube.com/watch?v={vid}"
    gid = upsert_group(P, f"youtube:{vid}", "youtube", f"{info.get('channel', '')}: {info.get('title', '')}", vurl,
                       "YTDLP", "VERBATIM", a.market, kind=a.kind, query_id=a.query or "")
    rows = [{"id": f"yt:{vid}", "group": gid, "platform": "youtube", "route": "YTDLP", "status": "VERBATIM",
             "kind": "video", "url": vurl, "author_key": author_key("youtube", info.get("channel_id")),
             "date": to_date(info.get("upload_date") and f"{info['upload_date'][:4]}-{info['upload_date'][4:6]}-{info['upload_date'][6:]}"),
             "title": info.get("title", ""), "text": (info.get("title", "") + "\n" + (info.get("description") or "")).strip(),
             "views": info.get("view_count"), "retrieved_at": now_iso()}]
    for sub in sorted(work.glob(f"{vid}*.vtt"))[:1]:
        rows.append({"id": f"yt:{vid}:transcript", "group": gid, "platform": "youtube", "route": "YTDLP",
                     "status": "VERBATIM", "kind": "transcript", "url": vurl, "author_key": rows[0]["author_key"],
                     "date": rows[0]["date"], "text": vtt_to_text(sub.read_text(encoding="utf-8", errors="replace")),
                     "notes": "subtitles (often auto-generated): good for speech rhythm, check words by ear",
                     "retrieved_at": now_iso()})
    for c in info.get("comments") or []:
        if not (c.get("text") or "").strip() or c.get("author_is_uploader") and a.skip_uploader:
            continue
        rows.append({"id": f"yt:{c['id']}", "group": gid, "platform": "youtube", "route": "YTDLP",
                     "status": "VERBATIM", "kind": "comment", "url": f"{vurl}&lc={c['id']}",
                     "parent": "" if c.get("parent") == "root" else c.get("parent", ""),
                     "author_key": author_key("youtube", c.get("author_id") or c.get("author")),
                     "date": to_date(c.get("timestamp")), "text": c["text"].strip(), "likes": c.get("like_count"),
                     "by_uploader": bool(c.get("author_is_uploader")), "retrieved_at": now_iso()})
    new, dup = add_sources(P, rows)
    print(f"{gid} video {vid}: {info.get('channel', '')}: {info.get('title', '')} (views {info.get('view_count')})")
    print(f"  stored {new} new texts ({dup} already stored); comments reported {info.get('comment_count')}")


# ---------- commands: WebFetch pages and user material ----------

def load_payload(s):
    return json.loads(Path(s[1:]).read_text(encoding="utf-8") if s.startswith("@") else s)


def cmd_web_add(a):
    P = Project(a.project_dir)
    posts = load_payload(a.payload)
    key = f"{a.platform}:{a.url.split('#')[0].rstrip('/')}"
    page_gid = None if a.each_independent else upsert_group(P, key, a.platform, a.title, a.url, "WEBFETCH",
                                                            "WEB_QUOTE", a.market, query_id=a.query or "")
    rows = []
    for i, p in enumerate(posts, 1):
        quote = (p.get("quote") or "").strip()
        if not quote:
            raise SystemExit(f"post {i}: empty quote; store only posts with an exact phrase returned by the tool")
        if len(quote) > 200:
            raise SystemExit(f"post {i}: quote longer than the reading tool returns verbatim; shorten to the exact part")
        gid = page_gid
        url = p.get("url") or a.url
        if a.each_independent:  # review sites: every review is its own person and its own group
            gid = upsert_group(P, f"{a.platform}:{url}#{p.get('author', '')}#{i}", a.platform,
                               f"{a.title}: {p.get('author', '')}", url, "WEBFETCH", "WEB_QUOTE", a.market,
                               query_id=a.query or "")
        oid = hashlib.sha1(f"{key}|{p.get('author', '')}|{quote}".encode()).hexdigest()[:10]
        rows.append({"id": f"wf:{oid}", "group": gid, "platform": a.platform, "route": "WEBFETCH",
                     "status": "WEB_QUOTE", "kind": "post", "url": url, "page": a.url,
                     "author_key": author_key(a.platform, p.get("author")), "date": to_date(p.get("date")),
                     "rating": p.get("rating"), "text": quote, "paraphrase": (p.get("paraphrase") or "").strip(),
                     "retrieved_at": now_iso()})
    new, dup = add_sources(P, rows)
    gids = sorted({r["group"] for r in rows})
    print(f"{','.join(gids)} {a.platform} {a.url}: stored {new} posts ({dup} already stored), status WEB_QUOTE")
    print("  next: confirm the quotes you will use with a second WebFetch read (see access.md), then web-confirm")


def cmd_web_confirm(a):
    P = Project(a.project_dir)
    rows = read_jsonl(P.sources)
    ids = set(a.ids)
    hit = 0
    for r in rows:
        if r["id"] in ids and r["route"] == "WEBFETCH":
            r["status"] = "WEB_CONFIRMED" if a.result == "yes" else "WEB_UNCONFIRMED"
            r["confirmed_at"] = now_iso()
            hit += 1
    write_jsonl(P.sources, rows)
    voc = read_jsonl(P.voc)
    for q in voc:
        if q["source"] in ids:
            q["status"] = "WEB_CONFIRMED" if a.result == "yes" else "WEB_UNCONFIRMED"
    write_jsonl(P.voc, voc)
    by_group = {}
    for r in rows:
        if r["route"] == "WEBFETCH":
            by_group.setdefault(r["group"], set()).add(r["status"])
    gs = read_jsonl(P.groups)
    for g in gs:
        st = by_group.get(g["id"])
        if st:
            g["status"] = st.pop() if len(st) == 1 else "MIXED"
    write_jsonl(P.groups, gs)
    print(f"{hit} sources marked {'WEB_CONFIRMED' if a.result == 'yes' else 'WEB_UNCONFIRMED'}")


def html_to_text(raw):
    s = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", raw)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>|</blockquote>|</article>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


BOT_CHECK = re.compile(r"(?i)verify you are (a )?human|just a moment|security verification|attention required"
                       r"|enable javascript")


def is_bot_check(text):
    return len(text) < 300 or bool(BOT_CHECK.search(text[:2000]))


def http_get(url, timeout=60):
    """GET with a browser user agent; gzip bodies (Wayback 'id_' snapshots keep the original encoding) are unpacked."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        if body[:2] == b"\x1f\x8b":
            import gzip
            body = gzip.decompress(body)
        return r.status, body.decode("utf-8", errors="replace")


def fetch_rendered(url, shot=None):
    """Open the page in a real Chromium (scripts/render_page.js). Returns the script's dict or None if no browser."""
    js = Path(__file__).with_name("render_page.js")
    try:
        root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=30).stdout.strip()
        env = dict(os.environ, NODE_PATH=root)
        out = subprocess.run(["node", str(js), url] + ([shot] if shot else []), capture_output=True, text=True,
                             timeout=180, env=env).stdout
        return json.loads(out or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def http_get_patient(url, timeout=60, waits=(20, 60)):
    """http_get that waits out rate limits (429/503), as the Wayback Machine gives after a burst of requests."""
    for w in list(waits) + [None]:
        try:
            return http_get(url, timeout)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or w is None:
                raise
            print(f"  HTTP {e.code}; retry in {w}s", file=sys.stderr)
            time.sleep(w)


def fetch_wayback(url):
    """Latest Wayback Machine snapshot of the page: (snapshot url, raw html, date), None if never archived,
    or a string with the reason it could not be read."""
    try:
        _, meta = http_get_patient("https://archive.org/wayback/available?url=" + urllib.parse.quote(url, safe=""))
        snap = (json.loads(meta).get("archived_snapshots") or {}).get("closest") or {}
        if snap.get("status") != "200":
            return None
        ts = snap["timestamp"]
        _, raw = http_get_patient(f"https://web.archive.org/web/{ts}id_/{url}", timeout=120)
        return f"https://web.archive.org/web/{ts}/{url}", raw, f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}" + (" (rate limit: try again in 10-30 min)" if e.code == 429 else "")
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as e:
        return f"unreachable ({e})"


def cmd_web_page(a):
    """Whole page text stored VERBATIM as one source; quotes are checked against it. Authors inside the page are
    not separated. Routes, tried in order until one gives real page text:
      DIRECT   plain request (forums without a bot check)
      RENDER   real Chromium: JS-built pages and passive bot checks ("Just a moment...")
      WAYBACK  latest Wayback Machine snapshot (the page as it was on that date: say so in the quote note)
      USER     --file: the page the user saved from their own browser (Save as > Webpage, HTML only, or .txt)
    An interactive check ("Verify you are human") is never clicked by the script: then the page needs the user's
    browser (Claude in Chrome / built-in browser, route BROWSER) or a saved file."""
    P = Project(a.project_dir)
    raw, route, status, url, date, tried = "", "", "VERBATIM", a.url, a.date, []
    if a.file:
        raw, route, status = Path(a.file).read_text(encoding="utf-8", errors="replace"), "USER", "USER"
    if not raw and not a.no_direct:
        try:
            code, body = http_get(a.url)
            if not is_bot_check(html_to_text(body)):
                raw, route = body, "DIRECT"
            else:
                tried.append(f"DIRECT {code}: bot check")
        except urllib.error.HTTPError as e:
            tried.append(f"DIRECT {e.code}")
        except (urllib.error.URLError, TimeoutError) as e:
            tried.append(f"DIRECT unreachable ({e})")
    if not raw:
        P.cache.mkdir(parents=True, exist_ok=True)
        shot = str(P.cache / f"render_{hashlib.sha1(a.url.encode()).hexdigest()[:8]}.png")
        r = fetch_rendered(a.url, shot)
        if r is None or r.get("error"):
            tried.append(f"RENDER unavailable ({(r or {}).get('error', 'no node/playwright')})")
        elif r.get("challenge") or is_bot_check(html_to_text(r.get("html", ""))):
            tried.append(f"RENDER {r.get('status')}: {r.get('challenge') or 'bot'} check, screenshot {shot}")
        else:
            raw, route = r["html"], "RENDER"
    if not raw:
        snap = fetch_wayback(a.url)
        if isinstance(snap, tuple) and not is_bot_check(html_to_text(snap[1])):
            url, raw, route = snap[0], snap[1], "WAYBACK"
            date = date or snap[2]
        else:
            tried.append("WAYBACK " + (snap if isinstance(snap, str) else "no snapshot" if snap is None
                                       else "snapshot is a bot check"))
    if not raw:
        print("not stored. Tried: " + "; ".join(tried))
        raise SystemExit("next: open it in the user's browser (Claude in Chrome, then user-add --route BROWSER), "
                         "or ask the user to save the page (Save as > Webpage, HTML only) and rerun with --file")
    text = html_to_text(raw)
    if is_bot_check(text):
        raise SystemExit("the saved file is the bot check page, not the content")
    title = a.title or html.unescape((re.search(r"(?is)<title[^>]*>(.*?)</title>", raw) or [None, a.url])[1].strip())
    gid = upsert_group(P, f"{a.platform}:{a.url.rstrip('/')}", a.platform, title, url, route, status, a.market,
                       kind=a.kind, query_id=a.query or "")
    oid = hashlib.sha1(a.url.encode()).hexdigest()[:10]
    note = "whole page text; several authors inside, count them by hand in the quote note"
    if route == "WAYBACK":
        note += f"; archive snapshot of {date}, the live page may differ"
    new, _ = add_sources(P, [{"id": f"pg:{oid}", "group": gid, "platform": a.platform, "route": route,
                              "status": status, "kind": "page", "url": url, "author_key": "",
                              "date": date, "title": title, "text": text, "retrieved_at": now_iso(), "notes": note}])
    print(f"{gid} pg:{oid} [{route}] {title[:80]}: {len(text)} chars stored ({'new' if new else 'already stored'})"
          + (f"  (before: {'; '.join(tried)})" if tried else ""))


def cmd_user_add(a):
    P = Project(a.project_dir)
    text = Path(a.text[1:]).read_text(encoding="utf-8") if a.text.startswith("@") else a.text
    url = a.url or ""
    status = "BROWSER" if a.route == "BROWSER" else "USER"
    gid = upsert_group(P, f"{a.platform}:{url or a.title}", a.platform, a.title, url, a.route, status, a.market,
                       kind=a.kind)
    oid = hashlib.sha1(f"{a.platform}|{url}|{a.author}|{text}".encode()).hexdigest()[:10]
    new, _ = add_sources(P, [{"id": f"us:{oid}", "group": gid, "platform": a.platform, "route": a.route,
                              "status": status, "kind": a.kind, "url": url,
                              "author_key": author_key(a.platform, a.author), "date": to_date(a.date),
                              "rating": a.rating, "text": text.strip(), "notes": a.notes, "retrieved_at": now_iso()}])
    print(f"{gid} us:{oid} stored ({'new' if new else 'already stored'})")


# ---------- commands: reading and quotes ----------

def cmd_show(a):
    P = Project(a.project_dir)
    groups = {g["id"]: g for g in read_jsonl(P.groups)}
    key = a.group
    if key not in groups:
        tid = thread_id_of(key)
        key = next((g["id"] for g in groups.values() if g["key"].endswith(":" + tid)), key)
    g = groups.get(key)
    if not g:
        raise SystemExit("unknown group; see stats --groups")
    used = {q["source"] for q in read_jsonl(P.voc)}
    print(f"{g['id']} {g['platform']} {g['title']}\n{g['url']}\n")
    for s in read_jsonl(P.sources):
        if s["group"] != key:
            continue
        if a.min_len and len(s["text"]) < a.min_len and s["kind"] == "comment":
            continue
        mark = " *used" if s["id"] in used else ""
        extra = f" rating={s['rating']}" if s.get("rating") is not None else ""
        par = f" parent={s['parent']}" if s.get("parent") else ""
        print(f"[{s['id']}] {s['kind']} {s['date']} {s['status']}{extra}{par}{mark}")
        if s.get("paraphrase"):
            print(f"  (paraphrase) {s['paraphrase']}")
        print(f"  {s['text'][:a.max_chars]}\n")


def cmd_add_quotes(a):
    P = Project(a.project_dir)
    items = load_payload(a.payload)
    sources = {s["id"]: s for s in read_jsonl(P.sources)}
    groups = {g["id"]: g for g in read_jsonl(P.groups)}
    voc = read_jsonl(P.voc)
    seen = {(q["source"], norm(q["quote"])) for q in voc}
    ok, rejected = [], []
    for i, it in enumerate(items, 1):
        s = sources.get(it.get("source"))
        why = None
        if not s:
            why = "unknown source id"
        elif s["status"] == "WEB_UNCONFIRMED":
            why = "source quote was not confirmed on the second read"
        elif not verbatim_in(it.get("quote", ""), s["text"]):
            why = "quote is not verbatim in the stored text"
        elif it.get("type") not in QUOTE_TYPES:
            why = f"type must be one of {QUOTE_TYPES}"
        elif it.get("action", "") not in ACTIONS:
            why = f"action must be one of {ACTIONS}"
        elif it.get("speaker") not in SPEAKERS:
            why = f"speaker must be one of {list(SPEAKERS)}"
        elif it["speaker"] == "COMPETITOR" and not (it.get("brand") or "").strip():
            why = "brand is required for a COMPETITOR speaker (which competitor)"
        elif it.get("relation", "UNKNOWN") not in RELATIONS:
            why = f"relation must be one of {list(RELATIONS)}"
        elif (s["id"], norm(it["quote"])) in seen:
            why = "duplicate"
        if why:
            rejected.append((i, it.get("source"), why, (it.get("quote") or "")[:80]))
            continue
        seen.add((s["id"], norm(it["quote"])))
        qid = next_id(voc + ok, "id", "Q", 3)
        ok.append({"id": qid, "source": s["id"], "group": s["group"], "quote": it["quote"].strip(),
                   "translation": it.get("translation", ""), "type": it["type"], "theme": it.get("theme", ""),
                   "persona": it.get("persona", ""), "emotion": it.get("emotion", ""),
                   "cluster": it.get("cluster", ""), "strength": it.get("strength", ""),
                   "market": it.get("market") or groups[s["group"]].get("market", ""),
                   "platform": s["platform"], "url": s["url"], "date": s.get("date", ""),
                   "rating": s.get("rating"), "status": s["status"], "action": it.get("action", ""),
                   "author_key": s.get("author_key", ""), "speaker": it["speaker"],
                   "brand": (it.get("brand") or ("Nordace" if it["speaker"].startswith("OUR_") else "")).strip(),
                   "relation": it.get("relation", "UNKNOWN"), "note": it.get("note", ""), "added_at": now_iso()})
    append_jsonl(P.voc, ok)
    print(f"added {len(ok)} quotes" + (f" ({ok[0]['id']}..{ok[-1]['id']})" if ok else "") + f", rejected {len(rejected)}")
    for i, src, why, q in rejected:
        print(f"  #{i} {src}: {why}: {q}")
    if rejected:
        sys.exit(1)


def cmd_retag(a):
    """Change tags (cluster, persona, type...) of existing quotes; the quote text itself cannot be edited."""
    P = Project(a.project_dir)
    changes = {c["id"]: c for c in load_payload(a.payload)}
    voc = read_jsonl(P.voc)
    n = 0
    for q in voc:
        c = changes.get(q["id"])
        if not c:
            continue
        if "speaker" in c and c["speaker"] not in SPEAKERS:
            raise SystemExit(f"{q['id']}: speaker must be one of {list(SPEAKERS)}")
        if "relation" in c and c["relation"] not in RELATIONS:
            raise SystemExit(f"{q['id']}: relation must be one of {list(RELATIONS)}")
        for k, v in c.items():
            if k in ("id", "quote", "source", "url", "status", "group"):
                continue
            q[k] = v
        n += 1
    write_jsonl(P.voc, voc)
    print(f"retagged {n} quotes")


# ---------- commands: analysis ----------

def months_old(d):
    try:
        dt = datetime.date.fromisoformat(d[:10])
    except (ValueError, TypeError):
        return None
    return (datetime.date.today() - dt).days / 30.4


def quote_strength(qs, groups):
    gset = {q["group"] for q in qs}
    authors = {q["author_key"] or f"anon:{q['id']}" for q in qs}
    platforms = {q["platform"] for q in qs}
    strong = sum(1 for q in qs if q["status"] in STRONG)
    return {"quotes": len(qs), "groups": len(gset), "authors": len(authors), "platforms": len(platforms),
            "strong": strong, "platform_list": sorted(platforms), "speakers": speaker_mix(qs)}


SHORT = {"OUR_SKU": "sku", "OUR_BRAND": "brand", "COMPETITOR": "comp", "CATEGORY": "cat", "ALTERNATIVE": "alt"}


def speaker_mix(qs):
    mix = {}
    for q in qs:
        k = q.get("speaker") or "UNTAGGED"
        mix[k] = mix.get(k, 0) + 1
    return mix


def mix_text(mix):
    order = list(SPEAKERS) + ["UNTAGGED"]
    return " ".join(f"{SHORT.get(k, '?')}{mix[k]}" for k in order if mix.get(k))


def cmd_stats(a):
    P = Project(a.project_dir)
    voc, groups, queries = read_jsonl(P.voc), {g["id"]: g for g in read_jsonl(P.groups)}, read_jsonl(P.queries)
    sources = read_jsonl(P.sources)
    print(f"Queries {len(queries)} · groups (threads/videos/pages) {len(groups)} · stored texts {len(sources)} · "
          f"quotes {len(voc)}")
    by_status = {}
    for q in voc:
        by_status[q["status"]] = by_status.get(q["status"], 0) + 1
    print("Quotes by status: " + ", ".join(f"{k} {v}" for k, v in sorted(by_status.items())))
    by_platform = {}
    for q in voc:
        by_platform[q["platform"]] = by_platform.get(q["platform"], 0) + 1
    print("Quotes by platform: " + ", ".join(f"{k} {v}" for k, v in sorted(by_platform.items(), key=lambda x: -x[1])))
    old = [q for q in voc if (months_old(q.get("date")) or 0) > FRESH_MONTHS]
    print(f"Older than {FRESH_MONTHS} months: {len(old)} of {len(voc)}")

    mix = speaker_mix(voc)
    if voc:
        print("Who speaks: " + ", ".join(f"{SPEAKERS.get(k, 'без пометки')} {v} ({v * 100 // len(voc)}%)"
                                          for k, v in sorted(mix.items(), key=lambda x: -x[1])))
        missing = [SPEAKERS[k] for k in SPEAKERS if mix.get(k, 0) < max(3, len(voc) // 20)]
        if missing:
            print("  thin layers (fewer than 5% or 3 quotes): " + ", ".join(missing) +
                  " -> offer the user to collect more there or name the gap")
        brands = {}
        for q in voc:
            if q.get("speaker") == "COMPETITOR":
                brands[q.get("brand", "?")] = brands.get(q.get("brand", "?"), 0) + 1
        if brands:
            print("  competitor buyers by brand: " + ", ".join(f"{b} {n}" for b, n in sorted(brands.items(), key=lambda x: -x[1])))
        if mix.get("UNTAGGED"):
            print(f"  {mix['UNTAGGED']} quotes have no speaker: retag them")

    pol = {}
    for q in queries:
        pol.setdefault(q.get("branch") or "-", set()).add(q.get("polarity") or "-")
    unbalanced = [b for b, ps in pol.items() if b != "-" and not ps & {"NEUTRAL", "POSITIVE"}]
    if unbalanced:
        print("Branches without NEUTRAL/POSITIVE queries (corpus skewed to complaints): " + ", ".join(sorted(unbalanced)))
    counter = [q for q in queries if q.get("polarity") == "COUNTER"]
    print(f"Counter-searches logged: {len(counter)}")

    clusters = {}
    for q in voc:
        clusters.setdefault(q.get("cluster") or "(none)", []).append(q)
    print("\nCluster | quotes | independent threads | authors | platforms | strong | who speaks | types")
    for c, qs in sorted(clusters.items(), key=lambda x: -quote_strength(x[1], groups)["groups"]):
        st = quote_strength(qs, groups)
        types = sorted({q["type"] for q in qs})
        print(f"{c:8} | {st['quotes']:3} | {st['groups']:3} | {st['authors']:3} | {','.join(st['platform_list'])} | "
              f"{st['strong']:3} | {mix_text(st['speakers'])} | {','.join(types)}")
    personas = {}
    for q in voc:
        personas[q.get("persona") or "(none)"] = personas.get(q.get("persona") or "(none)", 0) + 1
    print("\nPersonas: " + ", ".join(f"{k} {v}" for k, v in sorted(personas.items(), key=lambda x: -x[1])))
    if len(voc) >= 20:
        first_seen = {}
        for q in voc:
            first_seen.setdefault(q.get("cluster"), q["id"])
        last20 = {q["id"] for q in voc[-20:]}
        new = [c for c, qid in first_seen.items() if qid in last20 and c]
        print(f"Novelty: last 20 quotes opened {len(new)} new clusters" +
              (" -> saturation signal for this layer" if not new else f" ({', '.join(new)})"))
    if a.groups:
        print("\nGroups:")
        used = {}
        for q in voc:
            used[q["group"]] = used.get(q["group"], 0) + 1
        for g in groups.values():
            print(f"  {g['id']} {g['platform']:10} {g['status']:13} quotes={used.get(g['id'], 0):3} {g['title'][:80]}")


def cmd_check_insights(a):
    """insights.json: [{"id": "I01", "kind": "PATTERN", "statement": "...", "quotes": ["Q001", ...],
    "counter_quotes": [...], "counter_queries": ["SQ014", ...]}]. kind: PATTERN (default), PRODUCT, BRAND,
    COMPETITOR_GAP, BARRIER. Only quotes from the speakers that can support the kind are counted.
    Prints a verdict per insight; the model copies it to the Sheet as is."""
    P = Project(a.project_dir)
    voc = {q["id"]: q for q in read_jsonl(P.voc)}
    queries = {q["id"]: q for q in read_jsonl(P.queries)}
    groups = {g["id"]: g for g in read_jsonl(P.groups)}
    out = []
    for ins in load_payload(a.payload):
        missing = [x for x in ins.get("quotes", []) + ins.get("counter_quotes", []) if x not in voc]
        kind = ins.get("kind", "PATTERN")
        if kind not in INSIGHT_KINDS:
            raise SystemExit(f"{ins['id']}: kind must be one of {list(INSIGHT_KINDS)}")
        allowed, override = INSIGHT_KINDS[kind]
        th = dict(CONFIRMED, **override)
        cited = [voc[x] for x in ins.get("quotes", []) if x in voc]
        qs = [q for q in cited if q.get("speaker") in allowed]
        not_counted = [q["id"] for q in cited if q.get("speaker") not in allowed]
        st = quote_strength(qs, groups) if qs else {"quotes": 0, "groups": 0, "authors": 0, "platforms": 0,
                                                    "strong": 0, "platform_list": [], "speakers": {}}
        cq = [x for x in ins.get("counter_queries", []) if x in queries]
        gaps = []
        if not_counted:
            gaps.append(f"not counted for {kind} (wrong speaker): " + ",".join(not_counted))
        if st["quotes"] < th["quotes"]:
            gaps.append(f"quotes {st['quotes']}<{th['quotes']}")
        if st["groups"] < th["groups"]:
            gaps.append(f"independent threads {st['groups']}<{th['groups']}")
        if st["authors"] < th["authors"]:
            gaps.append(f"authors {st['authors']}<{th['authors']}")
        p_min, g_alt = th["platforms_or_groups"]
        if kind in ("PATTERN", "BARRIER", "COMPETITOR_GAP") and st["platforms"] < p_min and st["groups"] < g_alt:
            gaps.append(f"one platform needs >= {g_alt} threads")
        if st["strong"] < th["strong_quotes"]:
            gaps.append(f"verbatim/confirmed quotes {st['strong']}<{th['strong_quotes']}")
        if kind == "PATTERN" and qs and set(st["speakers"]) <= {"OUR_SKU", "OUR_BRAND"}:
            gaps.append("only our own buyers: a mass pattern needs category, competitor or alternative voices too")
        if kind == "COMPETITOR_GAP":
            brands = {q.get("brand") for q in qs}
            if len(brands) < 2:
                gaps.append(f"competitor brands {len(brands)}<2: one brand's flaw is not a category gap")
        if len(cq) < CONFIRMED["counter_search"]:
            gaps.append("no counter-search logged")
        if missing:
            gaps.append("unknown ids: " + ",".join(missing))
        verdict = "ПОДТВЕРЖДЁН" if not gaps else ("ГИПОТЕЗА" if st["groups"] < 2 else "СЛАБЫЙ")
        out.append({"id": ins["id"], "kind": kind, "verdict": verdict,
                    **{k: v for k, v in st.items() if k not in ("platform_list", "speakers")},
                    "platforms_list": st["platform_list"], "who_speaks": mix_text(speaker_mix(cited)),
                    "counter_quotes": len(ins.get("counter_quotes", [])), "counter_queries": len(cq), "gaps": gaps})
    for r in out:
        print(f"{r['id']} [{r['kind']}]: {r['verdict']}  quotes={r['quotes']} threads={r['groups']} authors={r['authors']} "
              f"platforms={','.join(r['platforms_list'])} strong={r['strong']} who={r['who_speaks']} "
              f"counter_quotes={r['counter_quotes']} counter_searches={r['counter_queries']}"
              + (f"\n    gaps: {'; '.join(r['gaps'])}" if r["gaps"] else ""))
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_packet(a):
    """Source texts for an independent auditor: the insight, every cited quote and the full stored text around it."""
    P = Project(a.project_dir)
    voc = {q["id"]: q for q in read_jsonl(P.voc)}
    sources = {s["id"]: s for s in read_jsonl(P.sources)}
    packet = []
    for ins in load_payload(a.payload):
        items = []
        for role, ids in (("supports", ins.get("quotes", [])), ("counter", ins.get("counter_quotes", []))):
            for x in ids:
                q = voc.get(x)
                if not q:
                    continue
                s = sources.get(q["source"], {})
                items.append({"quote_id": x, "role": role, "url": q["url"], "platform": q["platform"],
                              "speaker": SPEAKERS.get(q.get("speaker"), ""), "brand": q.get("brand", ""),
                              "status": q["status"], "source_text": s.get("text", "")[:3000],
                              "paraphrase_by_tool": s.get("paraphrase", "")})
        packet.append({"id": ins["id"], "kind": ins.get("kind", "PATTERN"), "statement": ins["statement"],
                       "evidence": items})
    print(json.dumps(packet, ensure_ascii=False, indent=1))


def cmd_export(a):
    """Rows for the Google Sheet, in tab column order, as a JSON array of arrays (for update_values).
    --since skips rows already written (by ID). None marks formula columns that must be left untouched."""
    P = Project(a.project_dir)
    groups = read_jsonl(P.groups)
    voc = read_jsonl(P.voc)
    if a.tab == "voc":
        rows = [[q["id"], q["quote"], q["translation"], q["type"], q["theme"], q["persona"], q["emotion"],
                 q["cluster"], q["strength"], q["market"], q["platform"], q["group"], q["url"], q["date"],
                 q["rating"] if q.get("rating") is not None else "", q["status"], q["action"], q["author_key"],
                 SPEAKERS.get(q.get("speaker"), ""), q.get("brand", ""), RELATIONS.get(q.get("relation"), "")]
                for q in voc]
        header = VOC_COLUMNS
    elif a.tab == "sources":
        texts, used = {}, {}
        for s in read_jsonl(P.sources):
            texts[s["group"]] = texts.get(s["group"], 0) + 1
        for q in voc:
            used[q["group"]] = used.get(q["group"], 0) + 1
        rows = [[g["id"], g["platform"], g["title"], g["url"], g.get("market", ""), g.get("kind", "VOC"), None,
                 g["route"], g["status"], texts.get(g["id"], 0), g.get("query_id", ""), g["at"][:10]]
                for g in groups if not a.used_only or used.get(g["id"])]
        header = SOURCE_COLUMNS
    else:
        rows = [[q["id"], q["at"][:10], q["platform"], q["route"], q["q"], q.get("branch", ""),
                 q.get("polarity", ""), q.get("stage", ""), q.get("why", ""), q.get("found", ""), q.get("status", "")]
                for q in read_jsonl(P.queries)]
        header = QUERY_COLUMNS
    if a.since:
        ids = [r[0] for r in rows]
        rows = rows[ids.index(a.since) + 1:] if a.since in ids else rows
    # update_values parses input like the Sheets UI: text starting with = + - @ would become a formula
    rows = [[("'" + v) if isinstance(v, str) and v and v[0] in "=+-@" else v for v in r] for r in rows]
    print(json.dumps(([header] if a.header else []) + rows, ensure_ascii=False))


STAGES = ["Вопрос, бриф и план сбора", "Правда о продукте", "Сбор голоса покупателя", "Разметка и кластеры",
          "Конкуренты и форматы", "Анализ и инсайты", "Персоны и речь", "Сообщение и концепты", "Хуки",
          "Приоритеты и тест", "Скрипт и бриф", "После запуска"]


def cmd_stage(a):
    """Without --n: print the stage log. With --n and --status: record it (review / approved / redo / skipped)."""
    P = Project(a.project_dir)
    path = P.dir / "project.json"
    meta = P.meta()
    log = meta.setdefault("stages", {})
    if a.n is not None:
        if not 0 <= a.n < len(STAGES):
            raise SystemExit(f"stage must be 0..{len(STAGES) - 1}")
        if not a.status:
            raise SystemExit("--status is required with --n")
        entry = log.setdefault(str(a.n), {"history": []})
        entry.update({"status": a.status, "at": now_iso()})
        entry["history"].append({"status": a.status, "at": now_iso(), "note": a.note})
        if a.note:
            entry["note"] = a.note
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for i, name in enumerate(STAGES):
        e = log.get(str(i), {})
        print(f"{i:2} {name:28} {e.get('status', '-'):9} {e.get('at', '')[:16]} {e.get('note', '')}")
    approved = [int(k) for k, v in log.items() if v.get("status") == "approved"]
    pending = [int(k) for k, v in log.items() if v.get("status") in ("review", "redo")]
    if pending:
        print(f"waiting for the user: stage {min(pending)}")
    elif approved:
        nxt = max(approved) + 1
        print(f"next: stage {nxt} {STAGES[nxt]}" if nxt < len(STAGES) else "all stages approved")
    else:
        print("next: stage 0")


# ---------- cli ----------

def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-dir", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def q_args(p):
        p.add_argument("--branch", default="", help="search branch, e.g. B03")
        p.add_argument("--polarity", default="", choices=[""] + POLARITY)
        p.add_argument("--stage", default="", help="TRIGGER / COMPARE / DECIDE / USE / EXIT")
        p.add_argument("--why", default="", help="finding (quote id) that led to this query")

    p = sub.add_parser("init")
    p.add_argument("--id", required=True)
    p.add_argument("--product", required=True)
    p.add_argument("--markets", default="US,UK")
    p.add_argument("--decision", default="", help="the decision this research must help make")
    p.add_argument("--mode", default="standard", choices=["quick", "standard", "deep"])
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("log-search")
    p.add_argument("--platform", required=True)
    p.add_argument("--q", required=True)
    p.add_argument("--found", type=int, default=0)
    q_args(p)
    p.set_defaults(func=cmd_log_search)

    p = sub.add_parser("reddit-find")
    p.add_argument("--subreddit", required=True)
    p.add_argument("--q", required=True, help="one or two words work best")
    p.add_argument("--kind", default="posts", choices=["posts", "comments"])
    p.add_argument("--limit", type=int, default=50)
    q_args(p)
    p.set_defaults(func=cmd_reddit_find)

    p = sub.add_parser("reddit-thread")
    p.add_argument("thread", help="thread URL or id")
    p.add_argument("--query", default="", help="SQ id that found it")
    p.add_argument("--market", default="")
    p.set_defaults(func=cmd_reddit_thread)

    p = sub.add_parser("yt-find")
    p.add_argument("--q", required=True)
    p.add_argument("--n", type=int, default=15)
    q_args(p)
    p.set_defaults(func=cmd_yt_find)

    p = sub.add_parser("yt-comments")
    p.add_argument("url")
    p.add_argument("--max", type=int, default=300)
    p.add_argument("--subs", action="store_true", help="also store the transcript (speech research)")
    p.add_argument("--kind", default="VOC", help="VOC / Конкурент / Формат / Эксперт / Наш бренд")
    p.add_argument("--skip-uploader", action="store_true")
    p.add_argument("--query", default="")
    p.add_argument("--market", default="")
    p.set_defaults(func=cmd_yt_comments)

    p = sub.add_parser("web-add")
    p.add_argument("--platform", required=True, help="trustpilot / mumsnet / forum name ...")
    p.add_argument("--url", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--market", default="")
    p.add_argument("--query", default="")
    p.add_argument("--each-independent", action="store_true", help="review sites: each post is its own group")
    p.add_argument("payload", help='@posts.json: [{"author","date","rating","quote","paraphrase","url"}]')
    p.set_defaults(func=cmd_web_add)

    p = sub.add_parser("web-confirm")
    p.add_argument("ids", nargs="+")
    p.add_argument("--result", required=True, choices=["yes", "no"])
    p.set_defaults(func=cmd_web_confirm)

    p = sub.add_parser("web-page")
    p.add_argument("url")
    p.add_argument("--platform", required=True)
    p.add_argument("--title", default="")
    p.add_argument("--date", default="")
    p.add_argument("--kind", default="VOC")
    p.add_argument("--market", default="")
    p.add_argument("--query", default="")
    p.add_argument("--file", default="", help="page saved by the user from their browser (.html or .txt)")
    p.add_argument("--no-direct", action="store_true", help="skip the plain request (known bot-checked site)")
    p.set_defaults(func=cmd_web_page)

    p = sub.add_parser("user-add")
    p.add_argument("--route", default="USER", choices=["USER", "BROWSER"])
    p.add_argument("--platform", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--url", default="")
    p.add_argument("--text", required=True, help="text or @file, exactly as the user gave it")
    p.add_argument("--author", default="")
    p.add_argument("--date", default="")
    p.add_argument("--rating", type=float)
    p.add_argument("--kind", default="VOC")
    p.add_argument("--market", default="")
    p.add_argument("--notes", default="")
    p.set_defaults(func=cmd_user_add)

    p = sub.add_parser("show")
    p.add_argument("group", help="S-id or Reddit thread id")
    p.add_argument("--max-chars", type=int, default=1200)
    p.add_argument("--min-len", type=int, default=0)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("add-quotes")
    p.add_argument("payload", help='@quotes.json: [{"source","quote","translation","type","theme","persona",'
                                   '"emotion","cluster","strength","market","action","speaker","brand","relation","note"}]')
    p.set_defaults(func=cmd_add_quotes)

    p = sub.add_parser("retag")
    p.add_argument("payload", help='@changes.json: [{"id": "Q012", "cluster": "P03", ...}]')
    p.set_defaults(func=cmd_retag)

    p = sub.add_parser("stats")
    p.add_argument("--groups", action="store_true")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("check-insights")
    p.add_argument("payload")
    p.add_argument("--json", default="")
    p.set_defaults(func=cmd_check_insights)

    p = sub.add_parser("packet")
    p.add_argument("payload")
    p.set_defaults(func=cmd_packet)

    p = sub.add_parser("export")
    p.add_argument("--tab", required=True, choices=["voc", "sources", "queries"])
    p.add_argument("--since", default="", help="last ID already in the sheet")
    p.add_argument("--header", action="store_true")
    p.add_argument("--used-only", action="store_true", help="sources: only groups that gave quotes")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("stage")
    p.add_argument("--n", type=int)
    p.add_argument("--status", choices=["review", "approved", "redo", "skipped"])
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_stage)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
