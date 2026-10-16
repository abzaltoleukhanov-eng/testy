#!/usr/bin/env python3
"""Build the auditor's packet: claims plus the full stored text of every cited source (and its parent comment).

The packet deliberately omits the author's observations and reasoning, so the auditor reads primary text only.
  python3 audit_packet.py --project-dir D --claims C-0001,C-0002 > packet.json
  python3 audit_packet.py --project-dir D --unaudited > packet.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from re_lib import load_contract, read_jsonl, table_path  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--claims", help="comma list of claim ids")
    ap.add_argument("--unaudited", action="store_true", help="all non-HYPOTHESIS claims without an audit")
    args = ap.parse_args()
    c = load_contract()
    t = {n: read_jsonl(table_path(args.project_dir, n, c)) for n in ("sources", "evidence", "claims", "audits")}
    sources = {s["source_id"]: s for s in t["sources"]}
    by_obj = {(s["thread_id"], s["platform_object_id"]): s for s in t["sources"]}
    evidence = {e["evidence_id"]: e for e in t["evidence"]}
    audited = {a["claim_id"] for a in t["audits"]}
    if args.claims:
        wanted = set(args.claims.split(","))
        claims = [x for x in t["claims"] if x["claim_id"] in wanted]
    else:
        claims = [x for x in t["claims"] if x["claim_type"] != "HYPOTHESIS" and (not args.unaudited or x["claim_id"] not in audited)]

    def src_block(eid):
        e = evidence[eid]
        s = sources.get(e["source_id"], {})
        block = {"evidence_id": eid, "source_id": e["source_id"], "url": s.get("url"),
                 "platform": s.get("platform"), "thread_title": None, "source_text": s.get("text")}
        post = by_obj.get((s.get("thread_id"), s.get("thread_id")))
        if post:
            block["thread_title"] = post.get("title")
        parent = by_obj.get((s.get("thread_id"), s.get("parent_object_id")))
        if parent and parent is not s:
            block["parent_text"] = parent.get("text")
        return block

    packet = []
    for x in claims:
        packet.append({"claim_id": x["claim_id"], "claim": x["text"], "claim_type": x["claim_type"],
                       "scope_limits": x.get("scope_limits"),
                       "supporting": [src_block(e) for e in x["supporting_evidence_ids"] if e in evidence],
                       "contradicting": [src_block(e) for e in x.get("contradicting_evidence_ids", []) if e in evidence]})
    json.dump(packet, sys.stdout, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
