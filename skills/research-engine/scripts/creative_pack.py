#!/usr/bin/env python3
"""Input pack for the creative layer (references/creative.md): what the mechanism agents may build on.

  python3 creative_pack.py --project-dir D > work/creative_pack.json

Run validate.py first (statuses come from gate_report.json). The pack holds:
  facts        FACT_APPROVED claims (may be asserted)
  hypotheses   HYPOTHESIS_UNTESTED claims (must stay labelled)
  ach          ACH_AUDITED analyses (ranking of explanations, causality not established)
  stories      DECISION evidence from usable sources: verbatim quote, action, situation, URL
  signals      EXTRACTOR sources (Mumsnet, Trustpilot, forums): paraphrase + short phrase, not proof
  product      verified product facts from project.json
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
    ap.add_argument("--max-signals", type=int, default=400)
    a = ap.parse_args()
    pdir = Path(a.project_dir)
    c = load_contract()
    rep = json.loads((pdir / "gate_report.json").read_text())
    st = {x["claim_id"]: x["status"] for x in rep["claims"]}
    t = {n: read_jsonl(table_path(pdir, n, c)) for n in ("claims", "evidence", "sources", "hypotheses")}
    src = {s["source_id"]: s for s in t["sources"]}
    usable = set(c["counting_rules"]["usable_access_status"])
    bad_ret = set(c["counting_rules"]["unusable_retrieval_without_recheck"])
    pack = {"facts": [], "hypotheses": [], "ach": [], "stories": [], "signals": [],
            "product": json.loads((pdir / "project.json").read_text()).get("product_facts_verified")}
    for cl in t["claims"]:
        s = st.get(cl["claim_id"])
        if s == "FACT_APPROVED":
            pack["facts"].append({"id": cl["claim_id"], "text": cl["text"], "scope": cl.get("scope_limits")})
        elif s == "HYPOTHESIS_UNTESTED":
            pack["hypotheses"].append({"id": cl["claim_id"], "text": cl["text"], "premises": cl.get("premise_claim_ids")})
    for h in t["hypotheses"]:
        if rep["ach"].get(h["ach_id"], {}).get("status") == "ACH_AUDITED":
            pack["ach"].append({"id": h["ach_id"], "question": h["question"], "preferred": h["preferred_h_id"],
                                "hypotheses": [{"h_id": x["h_id"], "statement": x["statement"]} for x in h["hypotheses"]],
                                "reason": h["preference_reason"]})
    for e in t["evidence"]:
        s = src.get(e["source_id"], {})
        if e.get("evidence_kind") == "DECISION" and s.get("access_status") in usable and s.get("retrieval_method") not in bad_ret:
            d = e.get("decision") or {}
            pack["stories"].append({"id": e["evidence_id"], "quote": e["quote_span"], "action": e.get("person_action"),
                                    "situation": e.get("usage_situation"), "trigger": d.get("decision_trigger"),
                                    "before": d.get("initial_situation"), "alternatives": d.get("alternatives_considered"),
                                    "outcome": d.get("reported_outcome"),
                                    "product_match": e.get("product_match"), "url": s.get("url")})
    for s in t["sources"]:
        if s.get("retrieval_method") == "EXTRACTOR" and len(pack["signals"]) < a.max_signals:
            pack["signals"].append({"id": s["source_id"], "platform": s["platform"], "thread": s["thread_id"],
                                    "author": s["author_key"], "date": s.get("source_date"), "text": s["text"],
                                    "url": s["url"]})
    pack["counts"] = {k: len(v) for k, v in pack.items() if isinstance(v, list)}
    json.dump(pack, sys.stdout, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
