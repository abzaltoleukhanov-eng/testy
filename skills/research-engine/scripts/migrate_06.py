#!/usr/bin/env python3
"""One-off migration of a contract 0.5 project to 0.6 (source provenance in the content hash), verifiably.

  python3 migrate_06.py --project-dir D --brief-ru brief_RU.md --brief-en brief_EN.md [--write]

0.6 adds every non-volatile source field to the hash, so every 0.5 hash changes. An audit is re-bound to its 0.6
hash only if (1) its stored hash equals the 0.5 hash of the current content, i.e. nothing it covered changed, and
(2) no source it depends on changed provenance in any committed version of archive/sources.jsonl (git history plus
the working tree). Everything else stays bound to the old hash and is therefore stale.
Brief audits are re-bound the same way, line by line.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from re_lib import ContentHasher, load_contract, table_path, write_jsonl  # noqa: E402
from validate import brief_lines, evaluate_ach, evaluate_claims, line_hash, load, url_texts  # noqa: E402

LEGACY_05 = {"source_hash_volatile_fields": []}


def provenance_history(pdir, contract):
    """{source_id: set of distinct provenance JSONs seen in git history and the working tree}."""
    rel = table_path(pdir, "sources", contract)
    root = subprocess.check_output(["git", "-C", str(pdir), "rev-parse", "--show-toplevel"], text=True).strip()
    relpath = str(Path(rel).resolve().relative_to(root))
    commits = subprocess.check_output(["git", "-C", root, "log", "--format=%H", "--", relpath], text=True).split()
    vol = set(contract["source_hash_volatile_fields"])
    seen = {}
    versions = [subprocess.run(["git", "-C", root, "show", f"{c}:{relpath}"], capture_output=True, text=True).stdout
                for c in commits] + [Path(rel).read_text(encoding="utf-8")]
    for txt in versions:
        for line in txt.splitlines():
            if line.strip():
                s = json.loads(line)
                seen.setdefault(s["source_id"], set()).add(
                    json.dumps({k: v for k, v in s.items() if k not in vol}, sort_keys=True, ensure_ascii=False))
    return seen, len(commits)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--brief-ru", required=True)
    ap.add_argument("--brief-en", required=True)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    pdir = Path(args.project_dir)
    contract = load_contract()
    t = load(pdir, contract)
    old, new = ContentHasher(t, LEGACY_05), ContentHasher(t, contract)

    hist, n_commits = provenance_history(pdir, contract)
    changed = {sid for sid, v in hist.items() if len(v) > 1}
    print(f"provenance checked over {n_commits} commits + working tree: {len(changed)} sources changed {sorted(changed)[:10]}")
    ev = {e["evidence_id"]: e for e in t["evidence"]}
    claims = {c["claim_id"]: c for c in t["claims"]}

    def touches_changed(cid, stack=()):
        c = claims.get(cid) or {}
        if cid in stack:
            return False
        eids = (c.get("supporting_evidence_ids") or []) + (c.get("contradicting_evidence_ids") or [])
        return (any(ev.get(e, {}).get("source_id") in changed for e in eids)
                or any(touches_changed(p, stack + (cid,)) for p in c.get("premise_claim_ids") or []))

    # statuses and line hashes as 0.5 computed them, before any re-binding
    st_old = {c["claim_id"]: c["status"] for c in evaluate_claims(t, contract, old)}
    ach_old = evaluate_ach(t, st_old, old)
    uts_old = url_texts(t, None)

    stats = {"audits": [0, 0], "ach_audits": [0, 0], "brief_audits": [0, 0]}
    for a in t["audits"]:
        if a.get("claim_hash") == old.claim(a["claim_id"]) and not touches_changed(a["claim_id"]):
            a["claim_hash"] = new.claim(a["claim_id"])
            a["hash_basis"] = (a.get("hash_basis", "") + "; " if a.get("hash_basis") else "") + \
                "re-bound to 0.6: 0.5 hash matched current content and source provenance unchanged in git history"
            stats["audits"][0] += 1
        else:
            stats["audits"][1] += 1
    for a in t["ach_audits"]:
        h = next(x for x in t["hypotheses"] if x["ach_id"] == a["ach_id"])
        eids = {e for x in h["hypotheses"] for e in x.get("supporting_ids", []) + x.get("refuting_ids", [])}
        clean = not any(ev.get(e, {}).get("source_id") in changed for e in eids) and not touches_changed(h["pattern_claim_id"])
        if a.get("ach_hash") == old.ach(a["ach_id"]) and clean:
            a["ach_hash"] = new.ach(a["ach_id"])
            a["hash_basis"] = "re-bound to 0.6: 0.5 hash matched current content and source provenance unchanged"
            stats["ach_audits"][0] += 1
        else:
            stats["ach_audits"][1] += 1

    st_new = {c["claim_id"]: c["status"] for c in evaluate_claims(t, contract, new)}
    ach_new = evaluate_ach(t, st_new, new)
    uts_new = url_texts(t, new)
    remap = {}
    for lang, path in (("RU", args.brief_ru), ("EN", args.brief_en)):
        for it in brief_lines(Path(path).read_text(encoding="utf-8")):
            ho = line_hash(lang, it["line"], st_old, ach_old, old, uts_old)
            hn = line_hash(lang, it["line"], st_new, ach_new, new, uts_new)
            remap[ho] = hn
    for a in t["brief_audits"]:
        if a["line_hash"] in remap:
            a["line_hash"] = remap[a["line_hash"]]
            a["hash_basis"] = "re-bound to 0.6: same line, cited records unchanged in content and status"
            stats["brief_audits"][0] += 1
        else:
            stats["brief_audits"][1] += 1
    print({k: f"{v[0]} re-bound, {v[1]} left on the old hash" for k, v in stats.items()})
    print(f"statuses unchanged by re-binding: {st_old == st_new}; ACH: {({k: v['status'] for k, v in ach_old.items()}) == ({k: v['status'] for k, v in ach_new.items()})}")
    if args.write:
        for name in ("audits", "ach_audits", "brief_audits"):
            write_jsonl(table_path(pdir, name, contract), t[name])
        print("written")


if __name__ == "__main__":
    main()
