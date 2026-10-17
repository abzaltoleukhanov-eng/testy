#!/usr/bin/env python3
"""Build the auditor's packet: claims plus the full stored text of every cited source (and its parent comment).

The packet deliberately omits the author's observations and reasoning, so the auditor reads primary text only.
  python3 audit_packet.py --project-dir D --claims C-0001,C-0002 > packet.json
  python3 audit_packet.py --project-dir D --unaudited > packet.json
  python3 audit_packet.py --project-dir D --ach ACH-0001,ACH-0003 > ach_packet.json
Every item carries the content hash it describes (claim_hash / ach_hash); record the audit with
ledger.py add ... --packet packet.json so the audit is bound to exactly what the auditor read.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from re_lib import ContentHasher, load_contract, read_jsonl, table_path  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--claims", help="comma list of claim ids")
    ap.add_argument("--unaudited", action="store_true", help="all claims without a current audit")
    ap.add_argument("--ach", help="comma list of ACH ids: build an ACH audit packet instead")
    args = ap.parse_args()
    c = load_contract()
    t = {n: read_jsonl(table_path(args.project_dir, n, c)) for n in ("sources", "evidence", "claims", "audits", "hypotheses")}
    hasher = ContentHasher(t)
    sources = {s["source_id"]: s for s in t["sources"]}
    by_obj = {(s["thread_id"], s["platform_object_id"]): s for s in t["sources"]}
    evidence = {e["evidence_id"]: e for e in t["evidence"]}
    audited = {a["claim_id"] for a in t["audits"] if a.get("claim_hash") == hasher.claim(a["claim_id"])}
    by_id = {x["claim_id"]: x for x in t["claims"]}
    if args.claims:
        wanted = set(args.claims.split(","))
        claims = [x for x in t["claims"] if x["claim_id"] in wanted]
    else:
        claims = [x for x in t["claims"] if not args.unaudited or x["claim_id"] not in audited]

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

    if args.ach:
        hyps = {h["ach_id"]: h for h in t["hypotheses"]}
        packet = []
        for aid in args.ach.split(","):
            h = hyps[aid]
            pat = by_id.get(h["pattern_claim_id"], {})
            eids = sorted({e for x in h["hypotheses"] for e in x.get("supporting_ids", []) + x.get("refuting_ids", [])})
            packet.append({"ach_id": aid, "ach_hash": hasher.ach(aid), "question": h["question"],
                           "pattern_claim": {"claim_id": pat.get("claim_id"), "text": pat.get("text")},
                           "hypotheses": h["hypotheses"], "preferred_h_id": h["preferred_h_id"],
                           "preference_reason": h["preference_reason"], "causal_status": h["causal_status"],
                           "evidence": [src_block(e) | {"quote_span": evidence[e].get("quote_span")}
                                        for e in eids if e in evidence]})
        json.dump(packet, sys.stdout, indent=1, ensure_ascii=False)
        return

    packet = []
    for x in claims:
        prem = [{"claim_id": pid, "text": by_id[pid]["text"], "claim_class": by_id[pid].get("claim_class")}
                for pid in x.get("premise_claim_ids") or [] if pid in by_id]
        packet.append({"claim_id": x["claim_id"], "claim_hash": hasher.claim(x["claim_id"]), "claim": x["text"], "claim_type": x["claim_type"],
                       "claim_class": x.get("claim_class"), "premises": prem,
                       "scope_limits": x.get("scope_limits"),
                       "supporting": [src_block(e) for e in x["supporting_evidence_ids"] if e in evidence],
                       "contradicting": [src_block(e) for e in x.get("contradicting_evidence_ids", []) if e in evidence]})
    json.dump(packet, sys.stdout, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
