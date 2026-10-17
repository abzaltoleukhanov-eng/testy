#!/usr/bin/env python3
"""Store pages read through the agent's web-reading tool (WebFetch) for sites closed to direct HTTP from the cloud:
Mumsnet, Trustpilot, forums, competitor review pages. The tool passes Cloudflare but returns a model-written
extraction: post-level paraphrases plus short verbatim phrases (at most ~125 characters).

  python3 webextract.py --project-dir D log-search --platform mumsnet --query "..." --branch B07 --market UK \
      --stage USE --scope CATEGORY --situation commute --polarity PROBLEM --found 10 --why "..."
  python3 webextract.py --project-dir D add-page --platform mumsnet --url URL --title "..." --query-id Q-0031 @posts.json
      posts.json: [{"author": "...", "date": "2023-12-20", "paraphrase": "...", "quote": "<short exact phrase or ''>",
                    "rating": null}]

Each post becomes one source row: retrieval_method EXTRACTOR, access_status READ_PARTIAL, context COMMENT_ONLY,
text = "PARAPHRASE: ... || QUOTE: ...". Under the contract, EXTRACTOR sources cannot support FACT_APPROVED claims
without a verbatim recheck. They are signals for patterns, mechanisms, hypotheses and the creative layer, and they
count authors and threads for coverage. Keep the quote exactly as the tool returned it; never write your own words
into "quote".
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from re_lib import append_jsonl, author_key, load_contract, next_id, now_iso, read_jsonl, table_path, text_hash  # noqa: E402


def project_id(pdir):
    return json.loads((Path(pdir) / "project.json").read_text())["project_id"]


def thread_key(platform, url):
    m = re.search(r"/(\d{5,})[-/]", url) or re.search(r"/review/([^/?#]+)", url)
    return f"{platform}:{m.group(1) if m else text_hash(url)}"


def cmd_log_search(a):
    c = load_contract()
    path = table_path(a.project_dir, "queries", c)
    rows = read_jsonl(path)
    qid = next_id(rows, "query_id", "Q-")
    append_jsonl(path, [{"query_id": qid, "project_id": project_id(a.project_dir), "branch_id": a.branch,
                         "query_text": a.query, "platform": a.platform, "executed_at": now_iso(), "market": a.market,
                         "journey_stage": a.stage, "scope": a.scope, "usage_situation": a.situation,
                         "polarity": a.polarity, "results_found": a.found, "results_retrieved": 0,
                         "parent_finding": a.why, "notes": "web search via agent tool; pages read with WebFetch"}])
    print(qid)


def cmd_add_page(a):
    c = load_contract()
    posts = json.loads(Path(a.payload[1:]).read_text(encoding="utf-8") if a.payload.startswith("@") else a.payload)
    spath = table_path(a.project_dir, "sources", c)
    existing = {s["source_id"] for s in read_jsonl(spath)}
    tk = thread_key(a.platform, a.url)
    pid = project_id(a.project_dir)
    rows = []
    for i, p in enumerate(posts, 1):
        quote = (p.get("quote") or "").strip()
        if len(quote) > 200:
            raise SystemExit(f"post {i}: quote longer than the tool's verbatim limit; it is not a verbatim quote")
        text = f"PARAPHRASE: {p['paraphrase'].strip()}" + (f" || QUOTE: {quote}" if quote else "")
        if p.get("rating") is not None:
            text = f"RATING: {p['rating']}/5 || " + text
        sid = f"WX-{tk.split(':', 1)[1][:24]}-{i:03d}"
        if sid in existing:
            continue
        rows.append({"source_id": sid, "project_id": pid, "platform": a.platform, "url": a.url,
                     "platform_object_id": f"{tk}#{i}", "thread_id": tk,
                     "author_key": author_key(a.platform, p.get("author") or f"anon-{tk}-{i}"),
                     "source_date": p.get("date"), "retrieved_at": now_iso(), "retrieval_method": "EXTRACTOR",
                     "access_status": "READ_PARTIAL", "content_available": "TEXT", "context_captured": "COMMENT_ONLY",
                     "source_origin": "PUBLIC", "text": text, "source_version": text_hash(text),
                     "title": a.title, "lang": a.lang, "query_id": a.query_id, "kind": "post",
                     "notes": "WebFetch extraction: paraphrase by the reading tool; QUOTE is the tool's short verbatim excerpt, "
                              "not checked against raw HTML"})
    append_jsonl(spath, rows)
    qpath = table_path(a.project_dir, "queries", c)
    qs = read_jsonl(qpath)
    for q in qs:
        if q["query_id"] == a.query_id:
            q["results_retrieved"] = (q.get("results_retrieved") or 0) + 1
    from re_lib import write_jsonl
    write_jsonl(qpath, qs)
    print(f"{len(rows)} posts stored from {a.url} as thread {tk}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-dir", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("log-search")
    for f in ("platform", "query", "branch", "market", "stage", "scope", "situation", "polarity", "why"):
        s.add_argument(f"--{f}", required=True)
    s.add_argument("--found", type=int, required=True)
    p = sub.add_parser("add-page")
    for f in ("platform", "url", "title", "query-id"):
        p.add_argument(f"--{f}", required=True)
    p.add_argument("--lang", default="en")
    p.add_argument("payload")
    a = ap.parse_args()
    {"log-search": cmd_log_search, "add-page": cmd_add_page}[a.cmd](a)


if __name__ == "__main__":
    main()
