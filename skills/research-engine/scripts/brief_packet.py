#!/usr/bin/env python3
"""Packets for the semantic brief audit: every content line of both briefs with the records it cites.

  python3 brief_packet.py --project-dir D --brief-ru brief_RU.md --brief-en brief_EN.md --out-dir work/brief_packets \
      [--unaudited] [--batch 40]

Each line carries its line_hash: the hash of the language, the normalised line and the content and status of
every claim, ACH and source URL it cites. Record the auditor's answers with
  ledger.py --project-dir D add brief_audits @answers.json --packet work/brief_packets/brief_packet_N.json
validate.py --brief-* then requires a current ENTAILED or LIMITATION_OK audit for every line.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from re_lib import ContentHasher, load_contract  # noqa: E402
from validate import brief_lines, cited, evaluate_ach, evaluate_claims, line_hash, load, norm_url, url_texts  # noqa: E402

URL_TEXT_LIMIT = 2500


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--brief-ru", required=True)
    ap.add_argument("--brief-en", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--unaudited", action="store_true", help="only lines without a current brief audit")
    ap.add_argument("--batch", type=int, default=40)
    args = ap.parse_args()
    contract = load_contract()
    pdir = Path(args.project_dir)
    t = load(pdir, contract)
    hasher = ContentHasher(t)
    claims = evaluate_claims(t, contract, hasher)
    status = {c["claim_id"]: c["status"] for c in claims}
    ach = evaluate_ach(t, status, hasher)
    uts = url_texts(t)
    by_claim = {c["claim_id"]: c for c in t["claims"]}
    by_ach = {h["ach_id"]: h for h in t["hypotheses"]}
    by_url = {}
    for s in t["sources"]:
        if s.get("url"):
            by_url.setdefault(norm_url(s["url"]), s)
    done = {a["line_hash"] for a in t.get("brief_audits", [])}

    cur_ach = {}
    for x in sorted(t.get("ach_audits", []), key=lambda r: r.get("audited_at", "")):
        if x.get("ach_hash") == hasher.ach(x["ach_id"]):
            cur_ach[x["ach_id"]] = x

    def ach_audit_summary(rid):
        x = cur_ach.get(rid)
        return {"verdict": x["verdict"], "issues": x.get("issues", "")} if x else None

    def record(rid):
        if rid.startswith("ACH-"):
            h = by_ach.get(rid, {})
            return {"kind": "ACH", "status": ach.get(rid, {}).get("status"), "question": h.get("question"),
                    "hypotheses": [{"h_id": x["h_id"], "statement": x["statement"], "diagnosticity": x["diagnosticity"]}
                                   for x in h.get("hypotheses", [])],
                    "preferred_h_id": h.get("preferred_h_id"), "preference_reason": h.get("preference_reason"),
                    "causal_status": h.get("causal_status"), "pattern_claim_id": h.get("pattern_claim_id"),
                    "pattern_status": ach.get(rid, {}).get("pattern_status"),
                    "ach_audit": ach_audit_summary(rid)}
        if rid.startswith("C-"):
            c = by_claim.get(rid, {})
            return {"kind": "CLAIM", "status": status.get(rid), "claim_type": c.get("claim_type"),
                    "claim_class": c.get("claim_class"), "text": c.get("text"), "scope_limits": c.get("scope_limits"),
                    "hypothesis_label": c.get("hypothesis_label"),
                    "premises": [{"claim_id": p, "text": by_claim.get(p, {}).get("text"), "status": status.get(p)}
                                 for p in c.get("premise_claim_ids") or []]}
        s = by_url.get(norm_url(rid))
        if s:
            return {"kind": "SOURCE", "platform": s.get("platform"), "text": (s.get("text") or "")[:URL_TEXT_LIMIT]}
        return {"kind": "SOURCE", "note": "thread or page URL; its own text is not archived under this exact URL"}

    items = []
    for lang, path in (("RU", args.brief_ru), ("EN", args.brief_en)):
        prev = ""
        for it in brief_lines(Path(path).read_text(encoding="utf-8")):
            h = line_hash(lang, it["line"], status, ach, hasher, uts)
            ids, urls = cited(it["line"])
            if not (args.unaudited and h in done):
                items.append({"line_hash": h, "lang": lang, "section": it["section"], "previous_line": prev,
                              "line": it["line"], "cites": ids + urls})
            prev = it["line"]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for i in range(0, len(items), args.batch):
        chunk = items[i:i + args.batch]
        recs = {r: record(r) for it in chunk for r in it["cites"]}
        n += 1
        (out / f"brief_packet_{n:02d}.json").write_text(
            json.dumps({"records": recs, "lines": chunk}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(items)} lines in {n} packets in {out}")


if __name__ == "__main__":
    main()
