#!/usr/bin/env python3
"""Reddit acquisition for the research engine.

Live text comes from Reddit RSS (works from cloud IPs, about 1 request per minute).
Reply structure (parent ids) comes from the Arctic Shift archive and is merged by comment id, never by text.
Every search is logged in queries.jsonl, every retrieved object in archive/sources.jsonl.

Commands:
  search         RSS search (all of Reddit or one subreddit) -> candidate threads
  archive-search Arctic Shift comment search inside one subreddit (body text) -> candidate threads
  thread         fetch one thread: live RSS comments + archive parents -> sources + completeness record
  show           print a stored thread for reading (ids, parents, text)
"""
import argparse
import html
import json
import re
import signal
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from re_lib import (Fetcher, append_jsonl, author_key, load_contract, next_id, now_iso, norm_text,  # noqa: E402
                    read_jsonl, table_path, text_hash)

RSS = "https://www.reddit.com"
ARCHIVE = "https://arctic-shift.photon-reddit.com/api"


def fetcher(project_dir):
    return Fetcher(cache_dir=Path(project_dir) / "archive" / "raw")


def html_to_text(raw):
    s = html.unescape(raw or "")
    s = re.sub(r"<!-- SC_(ON|OFF) -->", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</blockquote>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"submitted by\s+/u/\S+.*$", "", s, flags=re.S)
    s = re.sub(r"\[link\]\s*\[comments\]\s*$", "", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def parse_feed(xml):
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        def tag(name):
            m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", e, re.S)
            return html.unescape(m.group(1)).strip() if m else ""
        link = re.search(r'<link href="([^"]+)"', e)
        author = re.search(r"<author>\s*<name>(.*?)</name>", e, re.S)
        out.append({
            "fullname": tag("id"),
            "title": tag("title"),
            "url": html.unescape(link.group(1)) if link else "",
            "author": (author.group(1).strip().replace("/u/", "") if author else ""),
            "updated": tag("updated") or tag("published"),
            "text": html_to_text(tag("content")),
        })
    return out


def same_content(markdown_body, rss_text):
    """Compare archive markdown with live RSS text ignoring markup: links, escapes, punctuation, spacing."""
    def plain(s):
        s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s or "")
        s = s.replace("\\", "")
        return re.sub(r"[^0-9a-z]+", "", html.unescape(s).lower())
    return plain(markdown_body) == plain(rss_text)


def thread_id_from(s):
    m = re.search(r"/comments/([a-z0-9]+)", s)
    if m:
        return m.group(1)
    s = s.strip()
    return s[3:] if s.startswith("t3_") else s


def log_query(project_dir, args, query_text, platform, results_found, status_code, extra=None):
    path = table_path(project_dir, "queries")
    rows = read_jsonl(path)
    qid = next_id(rows, "query_id", "Q-")
    row = {
        "query_id": qid, "project_id": args.project_id, "branch_id": args.branch, "query_text": query_text,
        "platform": platform, "executed_at": now_iso(), "market": args.market, "journey_stage": args.stage,
        "scope": args.scope, "usage_situation": args.situation, "polarity": args.polarity,
        "results_found": results_found, "results_retrieved": 0, "status_code": status_code,
    }
    if args.why:
        row["parent_finding"] = args.why
    if extra:
        row.update(extra)
    append_jsonl(path, [row])
    return qid


def save_candidates(project_dir, qid, cands):
    path = Path(project_dir) / "archive" / "candidates.jsonl"
    seen = {(c["query_id"], c["thread_id"]) for c in read_jsonl(path)}
    rows = [dict(c, query_id=qid) for c in cands if (qid, c["thread_id"]) not in seen]
    append_jsonl(path, rows)


def cmd_search(args):
    q = args.q
    if args.subreddit:
        url = (f"{RSS}/r/{args.subreddit}/search.rss?q={urllib.parse.quote_plus(q)}"
               f"&restrict_sr=on&sort={args.sort}&t={args.t}&limit=100")
    else:
        url = f"{RSS}/search.rss?q={urllib.parse.quote_plus(q)}&sort={args.sort}&t={args.t}&limit=100"
    status, body, cached = fetcher(args.project_dir).get(url)
    entries = parse_feed(body) if status == 200 else []
    cands = []
    for e in entries:
        if not e["fullname"].startswith("t3_"):
            continue
        sub = re.search(r"/r/([^/]+)/", e["url"])
        cands.append({"thread_id": e["fullname"][3:], "url": e["url"], "title": e["title"],
                      "subreddit": sub.group(1) if sub else "", "snippet": e["text"][:400]})
    qid = log_query(args.project_dir, args, q, "reddit", len(cands), status,
                    {"subreddit": args.subreddit or "ALL", "cached": cached})
    save_candidates(args.project_dir, qid, cands)
    print(f"{qid}: HTTP {status}{' (cache)' if cached else ''}, {len(cands)} threads")
    for c in cands:
        print(f"  {c['thread_id']}  r/{c['subreddit']}  {c['title'][:90]}")
        if args.verbose and c["snippet"]:
            print(f"      {c['snippet'][:200]}")


def cmd_archive_search(args):
    params = {"subreddit": args.subreddit, "body": args.q, "limit": str(args.limit),
              "fields": "id,link_id,parent_id,body,created_utc,score"}
    url = f"{ARCHIVE}/comments/search?" + urllib.parse.urlencode(params)
    status, body, cached = fetcher(args.project_dir).get(url)
    data = []
    err = None
    if status == 200:
        try:
            payload = json.loads(body)
            data = payload.get("data") or []
            err = payload.get("error")
        except ValueError:
            err = "invalid JSON"
    by_thread = {}
    for c in data:
        tid = (c.get("link_id") or "")[3:]
        by_thread.setdefault(tid, []).append(c)
    cands = [{"thread_id": tid, "url": f"{RSS}/r/{args.subreddit}/comments/{tid}/", "title": "",
              "subreddit": args.subreddit, "snippet": norm_text(cs[0].get("body", ""))[:400],
              "matching_comments": len(cs)} for tid, cs in by_thread.items()]
    qid = log_query(args.project_dir, args, args.q, "reddit-archive", len(cands), status,
                    {"subreddit": args.subreddit, "cached": cached, "archive_error": err,
                     "notes": "Archive comment search; texts are snapshots and may be stale."})
    save_candidates(args.project_dir, qid, cands)
    print(f"{qid}: HTTP {status}{' (cache)' if cached else ''}, {len(data)} comments in {len(cands)} threads"
          + (f", archive error: {err}" if err else ""))
    for c in sorted(cands, key=lambda c: -c["matching_comments"]):
        print(f"  {c['thread_id']}  x{c['matching_comments']}  {c['snippet'][:150]}")


def archive_comments(f, tid, max_pages=10):
    out, after = {}, None
    for _ in range(max_pages):
        params = {"link_id": tid, "limit": "100", "sort": "asc",
                  "fields": "id,parent_id,body,author,created_utc,score"}
        if after:
            params["after"] = str(after)
        status, body, _ = f.get(f"{ARCHIVE}/comments/search?" + urllib.parse.urlencode(params))
        if status != 200:
            return out, f"HTTP {status}"
        try:
            data = json.loads(body).get("data") or []
        except ValueError:
            return out, "invalid JSON"
        new = [c for c in data if c["id"] not in out]
        for c in new:
            out[c["id"]] = c
        if len(data) < 100 or not new:
            break
        after = max(c["created_utc"] for c in data)
    return out, None


def cmd_thread(args):
    f = fetcher(args.project_dir)
    tid = thread_id_from(args.thread)
    contract = load_contract()
    src_path = table_path(args.project_dir, "sources", contract)
    existing = {r["source_id"] for r in read_jsonl(src_path)}

    status, body, cached = f.get(f"{RSS}/comments/{tid}/.rss?limit=500")
    entries = parse_feed(body) if status == 200 else []
    if status != 200 or not entries:
        print(f"thread {tid}: RSS HTTP {status}, nothing retrieved")
        return
    post = next((e for e in entries if e["fullname"] == f"t3_{tid}"), None)
    comments = [e for e in entries if e["fullname"].startswith("t1_")]

    arch, arch_err = ({}, "skipped") if args.no_archive else archive_comments(f, tid)
    meta_status, meta_body, _ = (None, "", False) if args.no_archive else f.get(
        f"{ARCHIVE}/posts/ids?ids={tid}&fields=id,title,num_comments,subreddit,created_utc")
    arch_reported = None
    if meta_status == 200:
        try:
            d = json.loads(meta_body).get("data") or []
            arch_reported = d[0].get("num_comments") if d else None
        except ValueError:
            pass

    now = now_iso()
    subreddit = (re.search(r"/r/([^/]+)/", (post or comments[0])["url"]) or [None, ""])[1]
    rows, conflicts, parents_missing = [], 0, 0

    def base(e, oid, kind):
        return {"project_id": args.project_id, "platform": "reddit", "url": e["url"], "platform_object_id": oid,
                "thread_id": tid, "author_key": author_key("reddit", e["author"]), "source_date": e["updated"],
                "retrieved_at": now, "retrieval_method": "RSS", "access_status": "READ_FULL",
                "content_available": "TEXT", "source_origin": "PUBLIC", "text": e["text"],
                "source_version": text_hash(e["text"]), "lang": "en", "subreddit": subreddit, "kind": kind}

    if post:
        r = base(post, tid, "post")
        r.update({"source_id": f"RD-{tid}", "title": post["title"], "context_captured": "COMMENT_ONLY"})
        if not r["text"]:
            # title-only post (link or crosspost): keep the title as the text, mark it partial
            r.update({"text": post["title"], "access_status": "READ_PARTIAL", "source_version": text_hash(post["title"]),
                      "notes": "Post body empty in RSS (title only); text is the title."})
        if args.query_id:
            r["query_id"] = args.query_id
        rows.append(r)

    live_ids = set()
    for e in comments:
        cid = e["fullname"][3:]
        live_ids.add(cid)
        r = base(e, cid, "comment")
        r["source_id"] = f"RD-{cid}"
        a = arch.get(cid)
        if a:
            r["parent_object_id"] = a.get("parent_id", "")[3:]
            r["context_captured"] = "PARENT_ONLY"
            r["score"] = a.get("score")
            if a.get("body") and a["body"] not in ("[deleted]", "[removed]") and not same_content(a["body"], e["text"]):
                r["recheck_status"] = "SOURCE_CHANGED"
                r["notes"] = "Archive snapshot text differs from live RSS text (edited after archiving); live text kept."
                conflicts += 1
        else:
            r["context_captured"] = "COMMENT_ONLY"
            parents_missing += 1
        if args.query_id:
            r["query_id"] = args.query_id
        rows.append(r)

    archive_only = 0
    if args.include_archive_only:
        for cid, a in arch.items():
            if cid in live_ids or a.get("body") in (None, "[deleted]", "[removed]"):
                continue
            archive_only += 1
            rows.append({"source_id": f"RD-{cid}", "project_id": args.project_id, "platform": "reddit",
                         "url": f"{RSS}/r/{subreddit}/comments/{tid}/comment/{cid}/", "platform_object_id": cid,
                         "parent_object_id": a.get("parent_id", "")[3:], "thread_id": tid,
                         "author_key": author_key("reddit", a.get("author")), "source_date": a.get("created_utc"),
                         "retrieved_at": now, "retrieval_method": "ARCHIVE", "access_status": "READ_FULL",
                         "content_available": "TEXT", "context_captured": "PARENT_ONLY", "source_origin": "PUBLIC",
                         "text": a["body"], "source_version": text_hash(a["body"]), "lang": "en",
                         "subreddit": subreddit, "kind": "comment", "score": a.get("score"),
                         "notes": "Archive snapshot only; not present in live RSS (may be deleted, edited or beyond the RSS window)."})

    new_rows = [r for r in rows if r["source_id"] not in existing]
    append_jsonl(src_path, new_rows)

    thread_row = {"thread_id": tid, "platform": "reddit", "url": (post or comments[0])["url"].split("/comment/")[0],
                  "title": post["title"] if post else "", "retrieved_at": now, "subreddit": subreddit,
                  "rss_count": len(comments), "archive_count": len(arch), "archive_reported_count": arch_reported,
                  "reported_comment_count": None, "merged_unique": len(live_ids | set(arch)) if arch else len(live_ids),
                  "source_changed": conflicts, "parents_missing": parents_missing,
                  "notes": ("live total unknown: reddit.com HTML/JSON is blocked from this environment; "
                            "archive counts are snapshots") + (f"; archive: {arch_err}" if arch_err else "")}
    append_jsonl(table_path(args.project_dir, "threads", contract), [thread_row])

    if args.query_id:
        qpath = table_path(args.project_dir, "queries", contract)
        qs = read_jsonl(qpath)
        for q in qs:
            if q["query_id"] == args.query_id:
                q["results_retrieved"] = q.get("results_retrieved", 0) + 1
        from re_lib import write_jsonl
        write_jsonl(qpath, qs)

    print(f"thread {tid} r/{subreddit}: {post['title'] if post else '(no post entry)'}")
    print(f"  live RSS comments {len(comments)}, archive {len(arch)} (archive reported {arch_reported}), "
          f"archive-only added {archive_only}, edited since archive {conflicts}, parents missing {parents_missing}, "
          f"new sources {len(new_rows)}")


def cmd_show(args):
    tid = thread_id_from(args.thread)
    rows = [r for r in read_jsonl(table_path(args.project_dir, "sources")) if r["thread_id"] == tid]
    if not rows:
        print("not stored; run `thread` first")
        return
    for r in rows:
        if r.get("kind") == "post":
            print(f"[{r['source_id']}] POST: {r.get('title', '')}\n{r['text']}\n")
    for r in rows:
        if r.get("kind") == "comment":
            parent = r.get("parent_object_id") or "?"
            flag = f" !{r['recheck_status']}" if r.get("recheck_status") else ""
            via = "" if r["retrieval_method"] == "RSS" else f" via {r['retrieval_method']}"
            print(f"[{r['source_id']}] parent={parent}{flag}{via}\n{r['text'][:args.max_chars]}\n")


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--project-id", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def query_args(p):
        p.add_argument("--branch", required=True, help="search branch id, e.g. B01")
        p.add_argument("--why", default="", help="finding or evidence id that triggered this query")
        p.add_argument("--market", default="ANY")
        p.add_argument("--stage", default="ANY", help="TRIGGER/COMPARE/DECIDE/USE/EXIT or ANY")
        p.add_argument("--scope", default="ANY", help="OUR_SKU/OUR_BRAND/COMPETITOR/CATEGORY/NON_COMMERCIAL_ALT or ANY")
        p.add_argument("--situation", default="ANY")
        p.add_argument("--polarity", required=True, help="PROBLEM/NEUTRAL/POSITIVE/SWITCH")

    p = sub.add_parser("search")
    p.add_argument("--q", required=True)
    p.add_argument("--subreddit")
    p.add_argument("--sort", default="relevance")
    p.add_argument("--t", default="all")
    p.add_argument("--verbose", action="store_true")
    query_args(p)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("archive-search")
    p.add_argument("--q", required=True)
    p.add_argument("--subreddit", required=True)
    p.add_argument("--limit", type=int, default=100)
    query_args(p)
    p.set_defaults(func=cmd_archive_search)

    p = sub.add_parser("thread")
    p.add_argument("--thread", required=True, help="thread id or URL")
    p.add_argument("--query-id")
    p.add_argument("--no-archive", action="store_true")
    p.add_argument("--include-archive-only", action="store_true")
    p.set_defaults(func=cmd_thread)

    p = sub.add_parser("show")
    p.add_argument("--thread", required=True)
    p.add_argument("--max-chars", type=int, default=1500)
    p.set_defaults(func=cmd_show)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
