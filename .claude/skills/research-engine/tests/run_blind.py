#!/usr/bin/env python3
"""Run a blind gate benchmark (ChatGPT format) through the research engine without changing its rules.

  prepare   inputs.jsonl -> literal anchor checks + auditor packets (batches) in OUT/
  finalize  auditor outputs in OUT/audit_*.json -> predictions.json

Pipeline per case, same as a real project:
  1. Python literal check: every quote anchor must be verbatim in the stored source text (ledger.py rule).
  2. LLM auditor (fresh agent, sees only its packet): entailment verdict, located span, scope issue,
     plus the evidence labels an author would normally write (product match, action, evidence kind, situation).
  3. Python gate (validate.gate_check, unchanged) on usable, anchored, auditor-confirmed evidence.
  4. Engine status -> benchmark verdict, mapping fixed before scoring:
       FACT_APPROVED -> APPROVE_SCOPED; HYPOTHESIS_UNTESTED -> APPROVE_HYPOTHESIS_UNTESTED;
       RESEARCH_QUESTION -> RESEARCH_QUESTION (contract 0.4)
       literal mismatch, CONTRADICTED, BLOCKED type, auditor DOES_NOT_SUPPORT -> BLOCK
       anything else (NEEDS_REVIEW) -> NEEDS_REVIEW
Adapter weakness, stated openly: there is no separate author here, so the auditor's labels stand in for the
author's evidence labels. The adapter has no claim ledger: a case may carry "claim_class" and "premises"
([{"claim_id", "text", "status"}]); they go into the packet and premise statuses into hypothesis_status, but
content hashing, stale audits, ACH and brief checks are only exercised on a real project (run_integration.py).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from re_lib import load_contract, span_in  # noqa: E402
from validate import gate_check, hypothesis_status, usable_source  # noqa: E402

OFFICIAL_PLATFORMS = {"brandpdp", "officialpdp", "official"}


def to_engine_source(s):
    """Translate a benchmark source into contract vocabulary (format only, no judgement)."""
    platform = "official" if s.get("platform", "").lower() in OFFICIAL_PLATFORMS else s.get("platform", "")
    src = {"source_id": s["source_id"], "platform": platform, "url": s.get("url"), "thread_id": s.get("thread_id"),
           "author_key": s.get("author_key"), "access_status": s.get("access_status"),
           "retrieval_method": s.get("retrieval_method"), "context_captured": s.get("context_captured"),
           "source_origin": s.get("source_origin"), "text": s.get("raw_text", "")}
    rr = s.get("recheck_result")
    if rr in load_contract()["enums"]["recheck_status"]:
        src["recheck_status"] = rr
    return src


def literal(case):
    anchors = case["claim"].get("quote_anchors") or []
    if not anchors:
        return "NOT_APPLICABLE", []
    srcs = {s["source_id"]: s for s in case["sources"]}
    res = []
    for a in anchors:
        s = srcs.get(a.get("source_id"))
        res.append({"source_id": a.get("source_id"), "match": bool(s) and span_in(a.get("exact_text", ""), s.get("raw_text", ""))})
    return ("MATCH" if all(r["match"] for r in res) else "MISMATCH"), res


def cmd_prepare(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = [json.loads(l) for l in Path(args.inputs).read_text(encoding="utf-8").splitlines() if l.strip()]
    lit = {}
    packets = []
    for c in cases:
        verdict, detail = literal(c)
        lit[c["test_id"]] = {"literal_anchor": verdict, "anchors": detail}
        packets.append({"case_id": c["test_id"], "claim": c["claim"]["text"], "claim_type": c["claim"]["claim_type"],
                        "claim_class": c["claim"].get("claim_class"),
                        "premises": [{"claim_id": x.get("claim_id"), "text": x.get("text"), "claim_class": x.get("claim_class")}
                                     for x in c["claim"].get("premises") or []],
                        "evidence_items": [{"evidence_id": f"{c['test_id']}:{a.get('source_id')}:{i}",
                                            "source_id": a.get("source_id"), "cited_span": a.get("exact_text")}
                                           for i, a in enumerate(c["claim"].get("quote_anchors") or [])],
                        "sources": c["sources"]})
    (out / "literal.json").write_text(json.dumps(lit, indent=1, ensure_ascii=False))
    for i in range(0, len(packets), args.batch):
        (out / f"packet_{i // args.batch + 1:02d}.json").write_text(
            json.dumps(packets[i:i + args.batch], indent=1, ensure_ascii=False))
    print(f"{len(cases)} cases, {sum(v['literal_anchor'] == 'MISMATCH' for v in lit.values())} literal mismatches, "
          f"{(len(packets) + args.batch - 1) // args.batch} packets in {out}")


def cmd_finalize(args):
    out = Path(args.out)
    contract = load_contract()
    rules = contract["counting_rules"]
    cases = {json.loads(l)["test_id"]: json.loads(l) for l in Path(args.inputs).read_text(encoding="utf-8").splitlines() if l.strip()}
    lit = json.loads((out / "literal.json").read_text())
    audits = {}
    for f in sorted(out.glob("audit_*.json")):
        for a in json.loads(f.read_text()):
            audits[a["case_id"]] = a
    preds = {}
    for tid, case in cases.items():
        ctype = case["claim"]["claim_type"]
        L = lit[tid]
        a = audits.get(tid)
        sources = {s["source_id"]: to_engine_source(s) for s in case["sources"]}
        decided_by, reasons = [], []

        # 1. literal
        literal_ok = L["literal_anchor"] != "MISMATCH"
        if not literal_ok:
            reasons.append("quote anchor not verbatim in stored source text (ledger rejects the evidence)")
            decided_by.append("python:literal")

        # 3. gate on usable anchored evidence, labelled by the auditor
        checks = {ch["evidence_id"]: ch for ch in (a or {}).get("evidence_checks", [])}
        evs, unusable, confirmed = [], [], []
        for i, anc in enumerate(case["claim"].get("quote_anchors") or []):
            eid = f"{tid}:{anc.get('source_id')}:{i}"
            src = sources.get(anc.get("source_id"))
            if not src or not span_in(anc.get("exact_text", ""), src["text"]):
                continue
            ok, why = usable_source(src, rules)
            ch = checks.get(eid, {})
            ev = {"evidence_id": eid, "source_id": src["source_id"], "quote_span": anc["exact_text"],
                  "product_match": ch.get("product_match", "UNKNOWN"), "person_action": ch.get("person_action", "NONE"),
                  "evidence_kind": ch.get("evidence_kind", "OBSERVATION"),
                  "usage_situation": ch.get("usage_situation", "UNKNOWN")}
            if not ok:
                unusable.append(f"{src['source_id']}: {why}")
                continue
            evs.append(ev)
            if ch.get("supports") and span_in(ch.get("located_span", ""), src["text"]):
                confirmed.append(ev)
        claim = {"counter_search_query_ids": [], "contradicting_evidence_ids": []}

        hyp_type = ctype in ("HYPOTHESIS", "SITUATION_REACH") or case["claim"].get("claim_class") in \
            contract["class_rules"]["hypothesis_classes"]
        premise_problems = [f"premise {x.get('claim_id')} is {x.get('status') or 'of unknown status'}, not FACT_APPROVED"
                            for x in case["claim"].get("premises") or [] if x.get("status") != "FACT_APPROVED"]

        # structural = schema-level validity only (agreed with the benchmark owner): literal anchors present and
        # verbatim, sources usable. Evidence sufficiency (counts, independence, counter-search) is reported apart.
        if not literal_ok:
            structural = "FAIL"
        elif unusable and not evs and not hyp_type:
            structural, reasons = "REVIEW", reasons + unusable
            decided_by.append("python:source_usability")
        else:
            structural = "PASS"
        if ctype == "CREATIVE_PERFORMANCE":
            sufficiency, s_reasons = "FAIL", [contract["gates"][ctype]["note"]]
            decided_by.append("python:type_rule")
        elif ctype == "HYPOTHESIS" or (hyp_type and ctype != "SITUATION_REACH"):
            sufficiency, s_reasons = "NOT_APPLICABLE", []
        else:
            g_ok, s_reasons, _ = gate_check(ctype, evs, sources, {}, claim, contract)
            sufficiency = "PASS" if g_ok else "FAIL"
            if not g_ok:
                decided_by.append("python:evidence_sufficiency")
        reasons += s_reasons

        # 2. substantive (auditor); for hypothesis types the auditor judges framing, not proof
        if not a:
            substantive = "REVIEW"
            reasons.append("no auditor output")
        elif hyp_type:
            hc = a.get("hypothesis_check")
            if a.get("verdict") == "CONTRADICTS" or hc == "ASSERTS_UNOBSERVED_FACT":
                substantive = "FAIL"
            elif hc == "FORWARD_LOOKING_OK" and not a.get("uncovered_premises") and a.get("link_check") != "UNSUPPORTED_LEAP":
                substantive = "PASS"
            elif hc == "FORWARD_LOOKING_OK":
                substantive = "REVIEW"
            else:
                substantive = "FAIL" if a.get("verdict") == "DOES_NOT_SUPPORT" else "REVIEW"
            if substantive != "PASS":
                decided_by.append("llm:auditor")
                reasons.append(f"auditor {a.get('verdict')}/{hc}: {a.get('scope_issue') or a.get('reasoning', '')}"[:400])
        else:
            v = a.get("verdict")
            if v in ("DOES_NOT_SUPPORT", "CONTRADICTS"):
                substantive = "FAIL"
            elif v == "SUPPORTS" and not a.get("scope_issue") and not a.get("open_contradiction"):
                substantive = "PASS"
            else:
                substantive = "REVIEW"
            if substantive != "PASS":
                decided_by.append("llm:auditor")
                reasons.append(f"auditor {v}: {a.get('scope_issue') or a.get('reasoning', '')}"[:400])
        if a:
            fake = [eid for eid, ch in checks.items() if ch.get("supports") and ch.get("located_span")
                    and not any(span_in(ch["located_span"], s["text"]) for s in sources.values())]
            if fake:
                reasons.append(f"auditor span not verbatim for {fake}")
                decided_by.append("python:auditor_span_check")

        # 3. audited gate (engine recomputes on auditor-confirmed evidence)
        audited_gate_ok = True
        if not hyp_type and ctype != "CREATIVE_PERFORMANCE" and a:
            audited_gate_ok, ag_reasons, _ = gate_check(ctype, confirmed, sources, {}, claim, contract)
            if not audited_gate_ok and sufficiency == "PASS":
                reasons += [f"after audit: {r}" for r in ag_reasons]
                decided_by.append("python:audited_gate")

        # 4. engine status (validate.py rules) -> benchmark final
        if not literal_ok:
            engine_status = "NEEDS_REVIEW"
        elif ctype == "CREATIVE_PERFORMANCE":
            engine_status = "BLOCKED"
        elif ctype == "HYPOTHESIS" or (hyp_type and ctype != "SITUATION_REACH"):
            engine_status, h_reasons = hypothesis_status(a, premise_problems)
            if engine_status != "HYPOTHESIS_UNTESTED":
                reasons += [r for r in h_reasons if r.startswith("premise")]
        elif ctype == "SITUATION_REACH":
            engine_status = hypothesis_status(a, premise_problems)[0] if sufficiency == "PASS" else "NEEDS_REVIEW"
            if sufficiency != "PASS" and a and (a.get("hypothesis_check") == "ASSERTS_UNOBSERVED_FACT"
                                                or a.get("verdict") == "DOES_NOT_SUPPORT"):
                engine_status = "BLOCKED"
        elif a and a.get("verdict") == "CONTRADICTS":
            engine_status = "BLOCKED"
        elif structural == "PASS" and sufficiency == "PASS" and substantive == "PASS" and audited_gate_ok:
            engine_status = "FACT_APPROVED"
        else:
            engine_status = "NEEDS_REVIEW"

        if engine_status == "FACT_APPROVED":
            final = "APPROVE_SCOPED"
        elif engine_status == "RESEARCH_QUESTION":
            final = "RESEARCH_QUESTION"
        elif engine_status == "HYPOTHESIS_UNTESTED":
            final = "APPROVE_HYPOTHESIS_UNTESTED"
        elif (not literal_ok or engine_status == "BLOCKED"
              or (a and a.get("verdict") == "DOES_NOT_SUPPORT")):
            final = "BLOCK"
        else:
            final = "NEEDS_REVIEW"

        preds[tid] = {
            "literal_anchor": L["literal_anchor"], "structural": structural, "evidence_sufficiency": sufficiency,
            "substantive": substantive, "final": final, "hypothesis_check": (a or {}).get("hypothesis_check", ""),
            "uncovered_premises": (a or {}).get("uncovered_premises", []), "link_check": (a or {}).get("link_check", ""),
            "engine_status": engine_status,
            "grounded_span": next((ch.get("located_span") for ch in checks.values() if ch.get("supports")), ""),
            "speaker_attribution": (a or {}).get("speaker_attribution", ""),
            "context_used": (a or {}).get("context_used", ""),
            "original_or_translation": (a or {}).get("original_or_translation", ""),
            "rationale": "; ".join(reasons) or "all engine checks passed",
            "decided_by": sorted(set(decided_by)) or ["all components passed"],
        }
    (out / "predictions.json").write_text(json.dumps(preds, indent=1, ensure_ascii=False))
    from collections import Counter
    print("final:", dict(Counter(p["final"] for p in preds.values())), "| missing audits:",
          [t for t in cases if t not in audits])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["prepare", "finalize"])
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--batch", type=int, default=6)
    args = ap.parse_args()
    {"prepare": cmd_prepare, "finalize": cmd_finalize}[args.cmd](args)


if __name__ == "__main__":
    main()
