#!/usr/bin/env python3
"""Compute every status of the research ledger. The model never writes a status; this script does.

  python3 validate.py --project-dir D                       -> gate_report.json + gate_report.md
  python3 validate.py --project-dir D --brief-ru R.md --brief-en E.md   -> also checks the briefs

Layers, as agreed in contract v0.2:
  SCHEMA_VALID      fields, enums, ids, links (same checks as ledger.py, re-run on the whole ledger)
  STRUCTURAL_GATE   per claim_type: independent groups, threads, platforms/situations, decision evidence,
                    counter-search, product match; only usable sources count
  EVIDENCE_AUDITED  latest independent audit says SUPPORTS; every span the auditor cites is verbatim in the
                    stored source text; the gate is recomputed on the evidence the auditor confirmed
  APPROVED          all of the above and no open contradiction or scope issue
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ledger import check_record  # noqa: E402
from re_lib import load_contract, now_iso, read_jsonl, span_in, table_path  # noqa: E402

BAD_RECHECK = {"QUOTE_MISMATCH", "UNAVAILABLE_ON_RECHECK", "CLAIM_CONTRADICTED"}


def load(project_dir, contract):
    t = {name: read_jsonl(table_path(project_dir, name, contract)) for name in contract["tables"]}
    return t


def usable_source(src, rules):
    if not src:
        return False, "source missing"
    if src.get("access_status") not in rules["usable_access_status"]:
        return False, f"access_status {src.get('access_status')}"
    if src.get("retrieval_method") in rules["unusable_retrieval_without_recheck"] and src.get("recheck_status") != "OK":
        return False, f"retrieved via {src['retrieval_method']} without verbatim recheck"
    if src.get("recheck_status") in BAD_RECHECK:
        return False, f"recheck {src['recheck_status']}"
    return True, ""


def independence_key(ev, src):
    g = ev.get("independence_group")
    if g and g != "UNKNOWN":
        return g
    return "thread:" + (src or {}).get("thread_id", "?")


def gate_check(claim_type, evs, sources, queries, claim, contract):
    """evs: list of evidence rows already filtered to usable ones. Returns (passed, reasons, stats)."""
    g = contract["gates"][claim_type]
    rules = contract["counting_rules"]
    srcs = [sources.get(e["source_id"]) for e in evs]
    groups = {independence_key(e, s) for e, s in zip(evs, srcs)}
    threads = {s.get("thread_id") for s in srcs if s}
    platforms = {s.get("platform") for s in srcs if s}
    situations = {e.get("usage_situation") for e in evs if e.get("usage_situation") not in (None, "", "UNKNOWN")}
    decision_groups = {independence_key(e, s) for e, s in zip(evs, srcs)
                       if e.get("evidence_kind") == "DECISION" and e.get("person_action") in rules["decision_actions"]}
    stats = {"evidence": len(evs), "groups": len(groups), "threads": len(threads), "platforms": len(platforms),
             "situations": len(situations), "decision_groups": len(decision_groups)}
    reasons = []
    if "min_groups" in g and len(groups) < g["min_groups"]:
        reasons.append(f"independent groups {len(groups)} < {g['min_groups']}")
    if "min_threads" in g and len(threads) < g["min_threads"]:
        reasons.append(f"distinct threads {len(threads)} < {g['min_threads']}")
    if "min_platforms_or_situations" in g and max(len(platforms), len(situations)) < g["min_platforms_or_situations"]:
        reasons.append(f"platforms {len(platforms)} and situations {len(situations)} both < {g['min_platforms_or_situations']}")
    if "min_decision_groups" in g and len(decision_groups) < g["min_decision_groups"]:
        reasons.append(f"independent DECISION evidence {len(decision_groups)} < {g['min_decision_groups']}")
    if "allowed_product_match" in g and not any(e.get("product_match") in g["allowed_product_match"] for e in evs):
        reasons.append(f"no evidence with product_match in {g['allowed_product_match']}")
    if g.get("requires_exact_sku"):
        ok = any(e.get("product_match") == "EXACT_SKU" and s and (
            s.get("retrieval_method") in ("USER_UPLOAD", "SCREENSHOT") or
            (s.get("platform") == "official" and s.get("access_status") == "READ_FULL")) for e, s in zip(evs, srcs))
        if not ok:
            reasons.append("PRODUCT_FACT needs exact-SKU evidence from the official page READ_FULL or a user screenshot/upload")
    if g.get("counter_search_required"):
        counter_q = [queries[q] for q in claim.get("counter_search_query_ids", []) if q in queries]
        has_counter_query = any(q.get("polarity") in ("NEUTRAL", "POSITIVE", "SWITCH") for q in counter_q)
        if not claim.get("contradicting_evidence_ids") and not has_counter_query:
            reasons.append("no contradicting evidence and no logged NEUTRAL/POSITIVE/SWITCH counter-search")
    return not reasons, reasons, stats


def evaluate_claims(t, contract):
    sources = {r["source_id"]: r for r in t["sources"]}
    evidence = {r["evidence_id"]: r for r in t["evidence"]}
    queries = {r["query_id"]: r for r in t["queries"]}
    audits = defaultdict(list)
    for a in t["audits"]:
        audits[a["claim_id"]].append(a)
    rules = contract["counting_rules"]
    out = []
    for c in t["claims"]:
        res = {"claim_id": c["claim_id"], "claim_type": c.get("claim_type"), "critical": c.get("critical"),
               "text": c.get("text"), "reasons": []}
        ctype = c.get("claim_type")
        gate = contract["gates"].get(ctype, {})

        sup = [evidence[e] for e in c.get("supporting_evidence_ids", []) if e in evidence]
        usable, dropped = [], []
        for e in sup:
            ok, why = usable_source(sources.get(e["source_id"]), rules)
            if ok and span_in(e.get("quote_span", ""), sources[e["source_id"]]["text"]):
                usable.append(e)
            else:
                dropped.append(f"{e['evidence_id']}: {why or 'quote_span not verbatim'}")
        res["unusable_evidence"] = dropped

        if ctype == "CREATIVE_PERFORMANCE":
            res.update(status="BLOCKED", reasons=[gate.get("note", "not supported")])
            out.append(res)
            continue
        if ctype == "HYPOTHESIS":
            res.update(status="HYPOTHESIS_LABELED" if c.get("hypothesis_label") else "NEEDS_REVIEW",
                       reasons=[] if c.get("hypothesis_label") else ["missing hypothesis_label"])
            out.append(res)
            continue

        s_ok, s_reasons, s_stats = gate_check(ctype, usable, sources, queries, c, contract)
        res["structural_gate"] = {"pass": s_ok, "reasons": s_reasons, "stats": s_stats}

        latest = sorted(audits.get(c["claim_id"], []), key=lambda a: a.get("audited_at", ""))[-1:] or [None]
        a = latest[0]
        audited_ok, a_reasons, confirmed = False, [], []
        if not a:
            a_reasons.append("no independent audit yet")
        else:
            res["audit_id"] = a["audit_id"]
            if a.get("verdict") == "CONTRADICTS":
                res.update(status="CONTRADICTED", reasons=[f"audit {a['audit_id']}: {a.get('reasoning', '')[:200]}"])
                out.append(res)
                continue
            for ch in a.get("evidence_checks", []):
                ev = evidence.get(ch.get("evidence_id"))
                if not ev or ev not in usable:
                    continue
                if not ch.get("supports"):
                    continue
                if not span_in(ch.get("located_span", ""), sources[ev["source_id"]]["text"]):
                    a_reasons.append(f"auditor span for {ev['evidence_id']} is not verbatim in the source")
                    continue
                confirmed.append(ev)
            unchecked = [e["evidence_id"] for e in usable
                         if e["evidence_id"] not in {ch.get("evidence_id") for ch in a.get("evidence_checks", [])}]
            if unchecked:
                a_reasons.append(f"auditor did not check: {unchecked}")
            if a.get("verdict") != "SUPPORTS":
                a_reasons.append(f"audit verdict {a.get('verdict')}")
            if a.get("scope_issue"):
                a_reasons.append(f"scope issue: {a['scope_issue']}")
            if a.get("open_contradiction"):
                a_reasons.append("open contradiction flagged by auditor")
            g_ok, g_reasons, g_stats = gate_check(ctype, confirmed, sources, queries, c, contract)
            res["audited_gate"] = {"pass": g_ok, "reasons": g_reasons, "stats": g_stats}
            if not g_ok:
                a_reasons += [f"after audit: {r}" for r in g_reasons]
            audited_ok = not a_reasons
        res["evidence_audited"] = audited_ok

        reasons = s_reasons + a_reasons
        if ctype == "SITUATION_REACH":
            status = "HYPOTHESIS_LABELED" if s_ok else "NEEDS_REVIEW"
            reasons = reasons or ["reach is never a fact from corpus frequency; labeled proxy only"]
        else:
            status = "APPROVED" if (s_ok and audited_ok) else "NEEDS_REVIEW"
        res.update(status=status, reasons=reasons)
        out.append(res)
    return out


def coverage(t, contract, project):
    cov = {"matrix": Counter(), "branches": {}, "novelty": {}, "limited_reasons": []}
    for q in t["queries"]:
        cov["matrix"][f"{q.get('journey_stage')}|{q.get('scope')}|{q.get('market')}"] += 1
        b = cov["branches"].setdefault(q["branch_id"], {"queries": 0, "polarities": set(), "results_found": 0,
                                                         "threads_retrieved": 0})
        b["queries"] += 1
        b["polarities"].add(q.get("polarity"))
        b["results_found"] += q.get("results_found") or 0
        b["threads_retrieved"] += q.get("results_retrieved") or 0
    need = set(contract["saturation"]["branch_closed_requires_polarity"])
    for b in cov["branches"].values():
        b["balanced"] = bool(b["polarities"] & need)
        b["polarities"] = sorted(p for p in b["polarities"] if p)

    sources = {r["source_id"]: r for r in t["sources"]}
    qbranch = {q["query_id"]: q["branch_id"] for q in t["queries"]}
    n = contract["saturation"]["novelty_window"]
    by_branch = defaultdict(list)
    for e in t["evidence"]:
        by_branch[qbranch.get(sources.get(e["source_id"], {}).get("query_id"), "UNLINKED")].append(e)
    by_branch["ALL"] = list(t["evidence"])
    for branch, evs in by_branch.items():
        seen_s, seen_b, new_tail = set(), set(), 0
        for i, e in enumerate(evs):
            is_new = e.get("situation_cluster_id") not in seen_s or e.get("behavior_pattern_id") not in seen_b
            seen_s.add(e.get("situation_cluster_id"))
            seen_b.add(e.get("behavior_pattern_id"))
            if i >= len(evs) - n and is_new:
                new_tail += 1
        cov["novelty"][branch] = {"evidence": len(evs), "situation_clusters": len(seen_s),
                                  "behavior_patterns": len(seen_b), f"new_in_last_{n}": new_tail,
                                  "saturated_signal": len(evs) >= n and new_tail == 0}

    markets = project.get("markets", [])
    searched = {q.get("market") for q in t["queries"]}
    for m in markets:
        if m not in searched and "ANY" not in searched:
            cov["limited_reasons"].append(f"market {m} has no queries")
    caps_path = Path(project["_dir"]) / "capabilities.json"
    if caps_path.exists():
        caps = json.loads(caps_path.read_text())
        for s in caps.get("sources", []):
            if s.get("planned") and not s.get("can_retrieve_text"):
                cov["limited_reasons"].append(f"planned source not retrievable: {s['source']}")
    unbalanced = [b for b, v in cov["branches"].items() if not v["balanced"]]
    if unbalanced:
        cov["limited_reasons"].append(f"branches without NEUTRAL/POSITIVE queries: {unbalanced}")
    cov["status"] = "COVERAGE_LIMITED" if cov["limited_reasons"] else "COVERAGE_OK"
    cov["matrix"] = dict(cov["matrix"])
    return cov


def check_briefs(ru_path, en_path, claim_status):
    issues = []
    ru = Path(ru_path).read_text(encoding="utf-8")
    en = Path(en_path).read_text(encoding="utf-8")
    if re.search("[Ѐ-ԯⷠ-ⷿꙀ-ꚟ]", en):
        bad = sorted(set(re.findall("[Ѐ-ԯ]", en)))[:10]
        issues.append(f"EN brief contains Cyrillic characters: {''.join(bad)}")
    ref = re.compile(r"\[(C-\d{4})\]")
    for name, txt, label in (("RU", ru, "гипотез"), ("EN", en, "hypothes")):
        for line in txt.splitlines():
            for cid in ref.findall(line):
                st = claim_status.get(cid)
                if st is None:
                    issues.append(f"{name}: {cid} referenced but not in claims")
                elif st == "HYPOTHESIS_LABELED" and label not in line.lower():
                    issues.append(f"{name}: {cid} is a hypothesis but its line has no '{label}' label")
                elif st not in ("APPROVED", "HYPOTHESIS_LABELED"):
                    issues.append(f"{name}: {cid} has status {st} and cannot appear as a finding")
    ids_ru, ids_en = set(ref.findall(ru)), set(ref.findall(en))
    if ids_ru != ids_en:
        issues.append(f"claim ids differ RU vs EN: only RU {sorted(ids_ru - ids_en)}, only EN {sorted(ids_en - ids_ru)}")
    url = re.compile(r"https?://[^\s<>\]\)\"']+")
    u_ru, u_en = set(url.findall(ru)), set(url.findall(en))
    if u_ru != u_en:
        issues.append(f"source links differ RU vs EN: only RU {len(u_ru - u_en)}, only EN {len(u_en - u_ru)}")
    return issues


def write_md(report, path):
    L = [f"# Gate report: {report['project_id']}", "", f"Computed {report['computed_at']} by validate.py "
         f"(contract {report['contract_version']}). Statuses here are computed, not self-declared.", ""]
    L.append(f"**Schema errors:** {len(report['schema_errors'])}")
    for e in report["schema_errors"][:30]:
        L.append(f"- {e}")
    L += ["", "## Claims", "", "| Claim | Type | Status | Why |", "|---|---|---|---|"]
    for c in report["claims"]:
        why = "; ".join(c["reasons"])[:300] or "all checks passed"
        L.append(f"| {c['claim_id']} | {c['claim_type']} | **{c['status']}** | {why} |")
    cov = report["coverage"]
    L += ["", f"## Coverage: {cov['status']}"] + [f"- {r}" for r in cov["limited_reasons"]]
    L += ["", "| Branch | Queries | Polarities | Threads read | Balanced |", "|---|---|---|---|---|"]
    for b, v in cov["branches"].items():
        L.append(f"| {b} | {v['queries']} | {', '.join(v['polarities'])} | {v['threads_retrieved']} | {v['balanced']} |")
    L += ["", "| Branch | Evidence | Situation clusters | Behaviour patterns | Saturation signal |", "|---|---|---|---|---|"]
    for b, v in cov["novelty"].items():
        L.append(f"| {b} | {v['evidence']} | {v['situation_clusters']} | {v['behavior_patterns']} | {v['saturated_signal']} |")
    L += ["", "## Corpus", ""]
    for k, v in report["corpus"].items():
        L.append(f"- {k}: {v}")
    if report.get("brief_issues") is not None:
        L += ["", "## Brief check", ""] + ([f"- {i}" for i in report["brief_issues"]] or ["- PASS"])
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--brief-ru")
    ap.add_argument("--brief-en")
    args = ap.parse_args()
    contract = load_contract()
    pdir = Path(args.project_dir)
    project = json.loads((pdir / "project.json").read_text())
    project["_dir"] = str(pdir)
    t = load(pdir, contract)

    schema_errors = []
    for table in ("evidence", "claims", "hypotheses", "audits"):
        key = contract["tables"][table]["key"]
        seen = set()
        for r in t[table]:
            if r.get(key) in seen:
                schema_errors.append(f"{table} {r.get(key)}: duplicate id")
            seen.add(r.get(key))
            for e in check_record(table, r, contract, pdir):
                schema_errors.append(f"{table} {r.get(key)}: {e}")
    for r in t["sources"]:
        missing = [f for f in contract["tables"]["sources"]["required"] if r.get(f) in (None, "")]
        if missing:
            schema_errors.append(f"sources {r.get('source_id')}: missing {missing}")

    claims = evaluate_claims(t, contract)
    srcs = t["sources"]
    report = {
        "project_id": project["project_id"], "computed_at": now_iso(), "contract_version": contract["contract_version"],
        "schema_errors": schema_errors, "claims": claims, "coverage": coverage(t, contract, project),
        "corpus": {
            "sources": len(srcs),
            "threads": len({s["thread_id"] for s in srcs}),
            "authors (within platform)": len({(s["platform"], s["author_key"]) for s in srcs}),
            "retrieval methods": dict(Counter(s["retrieval_method"] for s in srcs)),
            "edited since archive (SOURCE_CHANGED)": sum(1 for s in srcs if s.get("recheck_status") == "SOURCE_CHANGED"),
            "evidence rows": len(t["evidence"]),
            "decision evidence": sum(1 for e in t["evidence"] if e.get("evidence_kind") == "DECISION"),
            "queries": len(t["queries"]),
            "claim statuses": dict(Counter(c["status"] for c in claims)),
        },
    }
    if args.brief_ru and args.brief_en:
        report["brief_issues"] = check_briefs(args.brief_ru, args.brief_en, {c["claim_id"]: c["status"] for c in claims})
    (pdir / "gate_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=list), encoding="utf-8")
    write_md(report, pdir / "gate_report.md")
    print(f"schema errors: {len(schema_errors)}; claims: {report['corpus']['claim statuses']}; "
          f"coverage: {report['coverage']['status']}"
          + (f"; brief issues: {len(report['brief_issues'])}" if "brief_issues" in report else ""))
    fail = schema_errors or report.get("brief_issues")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
