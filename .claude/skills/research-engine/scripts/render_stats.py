#!/usr/bin/env python3
"""Consistency gate: brief statistics and the project snapshot are generated from the ledger, never typed.

  python3 render_stats.py --project-dir D --write      rewrites the STATS block in brief_RU.md / brief_EN.md
                                                       and the ledger_snapshot in project.json
validate.py --brief-* re-renders the block and fails the export if the briefs or project.json are stale.
The STATS block sits between <!-- STATS:BEGIN --> and <!-- STATS:END -->.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from re_lib import load_contract, read_jsonl, table_path  # noqa: E402

BEGIN, END = "<!-- STATS:BEGIN -->", "<!-- STATS:END -->"
STATS_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)


def snapshot(project_dir, claim_status):
    c = load_contract()
    t = {n: read_jsonl(table_path(project_dir, n, c)) for n in ("sources", "evidence", "claims", "queries")}
    reddit = [s for s in t["sources"] if s["platform"] == "reddit"]
    user = [s for s in t["sources"] if s.get("source_origin") == "USER_PROVIDED"]
    st = Counter(claim_status.values())
    ctype = {cl["claim_id"]: cl.get("claim_type") for cl in t["claims"]}
    fact = [cid for cid, s in claim_status.items() if s == "FACT_APPROVED"]
    return {
        "queries": len(t["queries"]),
        "reddit_threads": len({s["thread_id"] for s in reddit}),
        "reddit_objects": len(reddit),
        "reddit_authors": len({s["author_key"] for s in reddit}),
        "user_sources": len(user),
        "evidence": len(t["evidence"]),
        "decision_evidence": sum(1 for e in t["evidence"] if e.get("evidence_kind") == "DECISION"),
        "claims": len(t["claims"]),
        "status": {k: st.get(k, 0) for k in c["enums"]["claim_status"]},
        "fact_product": sum(1 for cid in fact if ctype.get(cid) == "PRODUCT_FACT"),
        "fact_other": sum(1 for cid in fact if ctype.get(cid) != "PRODUCT_FACT"),
        "approved_product_facts": sorted(cid for cid in fact if ctype.get(cid) == "PRODUCT_FACT"),
        "contract_version": c["contract_version"],
    }


def used_hypotheses(brief_text, claim_status):
    body = STATS_RE.sub("", brief_text)
    ids = set(re.findall(r"\[(C-\d{4})\]", body))
    return sum(1 for i in ids if claim_status.get(i) == "HYPOTHESIS_UNTESTED")


def ru_plural(k, one, few, many):
    if k % 10 == 1 and k % 100 != 11:
        return one
    if 2 <= k % 10 <= 4 and not 12 <= k % 100 <= 14:
        return few
    return many


def render(snap, lang, n_used):
    s = snap["status"]
    if lang == "RU":
        n = lambda k, *forms: f"{k} {ru_plural(k, *forms)}"
        lines = [BEGIN,
                 f"**Объём** (сгенерировано из журнала, контракт {snap['contract_version']}):",
                 f"- {n(snap['queries'], 'поисковый запрос', 'поисковых запроса', 'поисковых запросов')}, "
                 f"{n(snap['reddit_threads'], 'тред', 'треда', 'тредов')} Reddit, "
                 f"{snap['reddit_objects']} постов и комментариев, "
                 f"{n(snap['reddit_authors'], 'уникальный автор', 'уникальных автора', 'уникальных авторов')} Reddit; "
                 f"{n(snap['user_sources'], 'источник', 'источника', 'источников')} от пользователя;",
                 f"- {n(snap['evidence'], 'доказательство', 'доказательства', 'доказательств')}, "
                 f"из них {n(snap['decision_evidence'], 'история решения', 'истории решений', 'историй решений')};",
                 f"- {n(snap['claims'], 'утверждение', 'утверждения', 'утверждений')}: **{s['FACT_APPROVED']} FACT_APPROVED** ({snap['fact_other']} о людях и бренде, "
                 f"{snap['fact_product']} о продукте), {s['HYPOTHESIS_UNTESTED']} HYPOTHESIS_UNTESTED (в брифе использовано {n_used}), "
                 f"{s['RESEARCH_QUESTION']} RESEARCH_QUESTION, {s['NEEDS_REVIEW']} NEEDS_REVIEW, {s['BLOCKED']} BLOCKED.",
                 END]
    else:
        lines = [BEGIN,
                 f"**Volume** (generated from the ledger, contract {snap['contract_version']}):",
                 f"- {snap['queries']} search queries, {snap['reddit_threads']} Reddit threads, "
                 f"{snap['reddit_objects']} posts and comments, {snap['reddit_authors']} unique Reddit authors; "
                 f"{snap['user_sources']} user-provided sources;",
                 f"- {snap['evidence']} evidence rows, {snap['decision_evidence']} of them decision stories;",
                 f"- {snap['claims']} claims: **{s['FACT_APPROVED']} FACT_APPROVED** ({snap['fact_other']} about people and the brand, "
                 f"{snap['fact_product']} about the product), {s['HYPOTHESIS_UNTESTED']} HYPOTHESIS_UNTESTED ({n_used} used in this brief), "
                 f"{s['RESEARCH_QUESTION']} RESEARCH_QUESTION, {s['NEEDS_REVIEW']} NEEDS_REVIEW, {s['BLOCKED']} BLOCKED.",
                 END]
    return "\n".join(lines)


def consistency_issues(project_dir, claim_status, briefs):
    """briefs: {'RU': path, 'EN': path}. Returns a list of issues; empty means consistent."""
    issues = []
    snap = snapshot(project_dir, claim_status)
    for lang, path in briefs.items():
        txt = Path(path).read_text(encoding="utf-8")
        m = STATS_RE.search(txt)
        if not m:
            issues.append(f"{lang}: no generated STATS block ({BEGIN} ... {END})")
            continue
        want = render(snap, lang, used_hypotheses(txt, claim_status))
        if " ".join(m.group(0).split()) != " ".join(want.split()):
            issues.append(f"{lang}: STATS block is stale; run render_stats.py --write")
    proj = json.loads((Path(project_dir) / "project.json").read_text())
    ls = proj.get("ledger_snapshot")
    keep = {k: v for k, v in snap.items()}
    if not ls or {k: ls.get(k) for k in keep} != keep:
        issues.append("project.json ledger_snapshot is missing or stale; run render_stats.py --write")
    return issues


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    pdir = Path(args.project_dir)
    report = json.loads((pdir / "gate_report.json").read_text())
    claim_status = {c["claim_id"]: c["status"] for c in report["claims"]}
    snap = snapshot(pdir, claim_status)
    print(json.dumps(snap, ensure_ascii=False))
    if not args.write:
        return
    for lang in ("RU", "EN"):
        p = pdir / f"brief_{lang}.md"
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8")
        block = render(snap, lang, used_hypotheses(txt, claim_status))
        txt = STATS_RE.sub(lambda _: block, txt) if STATS_RE.search(txt) else txt
        p.write_text(txt, encoding="utf-8")
    proj_path = pdir / "project.json"
    proj = json.loads(proj_path.read_text())
    proj["ledger_snapshot"] = snap
    proj_path.write_text(json.dumps(proj, indent=2, ensure_ascii=False))
    print("written")


if __name__ == "__main__":
    main()
