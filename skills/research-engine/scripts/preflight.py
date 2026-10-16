#!/usr/bin/env python3
"""Layer 0: source capability preflight. Writes <project>/capabilities.json (Source Capability Registry).

Probes only HTTP-level routes this script can reach. Tool-level routes (the assistant's web search and page
extractor) are recorded by the assistant with `record`, after trying them in the session.

  python3 preflight.py --project-dir D probe --sources reddit,mumsnet,trustpilot,official
  python3 preflight.py --project-dir D record --source mumsnet --method EXTRACTOR --can-retrieve-text yes --note "..."
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from re_lib import Fetcher, now_iso  # noqa: E402

DIMS = ["can_search", "can_retrieve_text", "can_retrieve_comments", "can_inspect_images", "can_inspect_video",
        "can_obtain_metrics"]

PROBES = {
    # (label, url, capability, marker that real content must contain)
    "reddit": [("RSS search", "https://www.reddit.com/search.rss?q=tote+bag&limit=5", "can_search", "<entry>"),
               ("RSS thread", "https://www.reddit.com/comments/1x38inx/.rss", "can_retrieve_comments", "<entry>"),
               ("direct HTML", "https://www.reddit.com/r/HerOneBag/", "can_retrieve_text", "shreddit-post")],
    "reddit-archive": [("Arctic Shift", "https://arctic-shift.photon-reddit.com/api/posts/ids?ids=1x38inx",
                        "can_retrieve_comments", '"num_comments"')],
    "mumsnet": [("direct", "https://www.mumsnet.com/talk/style_and_beauty", "can_retrieve_text", "talk/style_and_beauty/")],
    "trustpilot": [("direct", "https://www.trustpilot.com/review/nordace.com", "can_retrieve_text", "review")],
    "official": [("direct", "https://nordace.com/", "can_retrieve_text", "Nordace")],
    "youtube": [("search HTML", "https://www.youtube.com/results?search_query=tote+bag", "can_search", "videoRenderer")],
    "tiktok": [("direct", "https://www.tiktok.com/search?q=tote%20bag", "can_search", "SIGI_STATE")],
    "meta-ad-library": [("direct", "https://www.facebook.com/ads/library/", "can_search", "Ad Library")],
    "amazon": [("direct", "https://www.amazon.com/s?k=work+tote+bag", "can_search", "s-search-result")],
}


def load(path):
    return json.loads(path.read_text()) if path.exists() else {"sources": []}


def upsert(reg, entry):
    reg["sources"] = [s for s in reg["sources"] if not (s["source"] == entry["source"] and s["method"] == entry["method"])]
    reg["sources"].append(entry)


def looks_blocked(body):
    b = body[:4000].lower()
    return any(k in b for k in ("just a moment", "cf-chl", "captcha", "you've been blocked", "whoa there"))


def cmd_probe(args):
    path = Path(args.project_dir) / "capabilities.json"
    reg = load(path)
    f = Fetcher(cache_dir=Path(args.project_dir) / "archive" / "raw")
    planned = set(args.planned.split(",")) if args.planned else set()
    for name in args.sources.split(","):
        for label, url, dim, marker in PROBES.get(name, []):
            status, body, _ = f.get(url, use_cache=False)
            ok = status == 200 and marker in body and not looks_blocked(body)
            entry = {"source": name, "method": f"script:{label}", "tested_at": now_iso(), "http_status": status,
                     "planned": name in planned, **{d: None for d in DIMS}}
            entry[dim] = ok
            if dim == "can_retrieve_comments" and ok:
                entry["can_retrieve_text"] = True
            if not ok:
                entry["note"] = ("HTTP 200 but no real content (bot protection or JS shell)" if status == 200
                                 else f"HTTP {status}")
            upsert(reg, entry)
            print(f"{name:16s} {label:14s} HTTP {status}  {'OK' if ok else 'BLOCKED'}")
    reg["updated_at"] = now_iso()
    path.write_text(json.dumps(reg, indent=2, ensure_ascii=False))


def cmd_record(args):
    path = Path(args.project_dir) / "capabilities.json"
    reg = load(path)
    yn = {"yes": True, "no": False, None: None}
    entry = {"source": args.source, "method": f"tool:{args.method}", "tested_at": now_iso(),
             "planned": args.planned, "note": args.note}
    for d in DIMS:
        entry[d] = yn[getattr(args, d)]
    upsert(reg, entry)
    reg["updated_at"] = now_iso()
    path.write_text(json.dumps(reg, indent=2, ensure_ascii=False))
    print("recorded", entry)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-dir", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe")
    p.add_argument("--sources", default="reddit,reddit-archive,mumsnet,trustpilot,official")
    p.add_argument("--planned", default="", help="comma list of sources this project plans to use")
    p.set_defaults(func=cmd_probe)
    p = sub.add_parser("record")
    p.add_argument("--source", required=True)
    p.add_argument("--method", required=True, help="e.g. WebSearch, WebFetch-EXTRACTOR, user-screenshot")
    p.add_argument("--planned", action="store_true")
    p.add_argument("--note", default="")
    for d in DIMS:
        p.add_argument("--" + d.replace("_", "-"), dest=d, choices=["yes", "no"])
    p.set_defaults(func=cmd_record)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
