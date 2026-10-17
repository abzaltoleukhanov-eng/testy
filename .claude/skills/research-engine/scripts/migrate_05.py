#!/usr/bin/env python3
"""One-off migration of a contract 0.4 project to 0.5: bind existing audits to content hashes, verifiably.

  python3 migrate_05.py --project-dir D [--write]

An audit gets claim_hash only if the packet its auditor read (work/audit_packet_N.json, paired with
work/audits_N.json) shows exactly the claim's current content: same text, type, scope, cited evidence ids,
the same stored source texts, and the same premise ids and texts. Anything else gets claim_hash
"LEGACY_UNVERIFIED", which never matches, so that claim goes back to review. Nothing is guessed.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from re_lib import ContentHasher, load_contract, norm_text, read_jsonl, table_path, write_jsonl  # noqa: E402


def same_audit(a, b):
    return (a.get("claim_id") == b.get("claim_id") and a.get("verdict") == b.get("verdict")
            and norm_text(a.get("reasoning", "")) == norm_text(b.get("reasoning", "")))


def packet_matches(item, claim, claims, evidence, sources):
    why = []
    if norm_text(item.get("claim", "")) != norm_text(claim.get("text", "")):
        why.append("text")
    if item.get("claim_type") != claim.get("claim_type"):
        why.append("claim_type")
    if norm_text(item.get("scope_limits") or "") != norm_text(claim.get("scope_limits") or ""):
        why.append("scope_limits")
    for key, field in (("supporting", "supporting_evidence_ids"), ("contradicting", "contradicting_evidence_ids")):
        blocks = item.get(key) or []
        if sorted(b["evidence_id"] for b in blocks) != sorted(claim.get(field) or []):
            why.append(field)
        for b in blocks:
            e = evidence.get(b["evidence_id"])
            s = sources.get(e["source_id"]) if e else None
            if not s or norm_text(s.get("text", "")) != norm_text(b.get("source_text") or ""):
                why.append(f"source text of {b['evidence_id']}")
    prem = item.get("premises")
    cur = claim.get("premise_claim_ids") or []
    if prem is None:
        if cur:
            why.append("premises added after audit")
    else:
        if sorted(p["claim_id"] for p in prem) != sorted(cur):
            why.append("premise ids")
        for p in prem:
            if norm_text(p.get("text", "")) != norm_text(claims.get(p["claim_id"], {}).get("text", "")):
                why.append(f"premise text {p['claim_id']}")
    return why


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    pdir = Path(args.project_dir)
    c = load_contract()
    t = {n: read_jsonl(table_path(pdir, n, c)) for n in ("claims", "evidence", "sources", "hypotheses", "audits")}
    hasher = ContentHasher(t)
    claims = {x["claim_id"]: x for x in t["claims"]}
    evidence = {e["evidence_id"]: e for e in t["evidence"]}
    sources = {s["source_id"]: s for s in t["sources"]}
    raw = {}
    for f in sorted((pdir / "work").glob("audits_*.json")):
        n = f.stem.split("_", 1)[1]
        raw[n] = json.loads(f.read_text(encoding="utf-8"))
    out, report = [], []
    for a in t["audits"]:
        if a.get("claim_hash"):
            out.append(a)
            continue
        found = [n for n, rows in raw.items() if any(same_audit(a, r) for r in rows)]
        verdict, basis = None, None
        for n in found:
            pk = pdir / "work" / f"audit_packet_{n}.json"
            if not pk.exists():
                continue
            item = next((x for x in json.loads(pk.read_text(encoding="utf-8")) if x.get("claim_id") == a["claim_id"]), None)
            if item is None:
                continue
            why = packet_matches(item, claims[a["claim_id"]], claims, evidence, sources)
            if not why:
                verdict, basis = hasher.claim(a["claim_id"]), f"migrated to 0.5: current content verified equal to work/{pk.name}"
                break
            basis = f"not migrated: work/{pk.name} differs from current claim in {sorted(set(why))}"
        if verdict is None:
            basis = basis or "not migrated: no audit packet paired with this audit in work/"
            verdict = "LEGACY_UNVERIFIED"
        a = dict(a, claim_hash=verdict, hash_basis=basis)
        out.append(a)
        report.append((a["audit_id"], a["claim_id"], verdict != "LEGACY_UNVERIFIED", basis))
    for r in report:
        print(("OK  " if r[2] else "STALE"), r[0], r[1], r[3])
    print(f"{sum(r[2] for r in report)} bound, {sum(not r[2] for r in report)} left stale")
    if args.write:
        write_jsonl(table_path(pdir, "audits", c), out)
        print("written")


if __name__ == "__main__":
    main()
