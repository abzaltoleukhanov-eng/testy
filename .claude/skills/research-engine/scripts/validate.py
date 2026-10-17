#!/usr/bin/env python3
"""Compute every status of the research ledger. The model never writes a status; this script does.

  python3 validate.py --project-dir D                       -> gate_report.json + gate_report.md
  python3 validate.py --project-dir D --brief-ru R.md --brief-en E.md   -> also checks the briefs

Layers (contract 0.2 onwards):
  SCHEMA_VALID      fields, enums, ids, links (same checks as ledger.py, re-run on the whole ledger)
  STRUCTURAL_GATE   per claim_type: independent groups, threads, platforms/situations, decision evidence,
                    counter-search, product match; only usable sources count
  EVIDENCE_AUDITED  latest independent audit says SUPPORTS; every span the auditor cites is verbatim in the
                    stored source text; the gate is recomputed on the evidence the auditor confirmed
  FACT_APPROVED     all of the above and no open contradiction or scope issue
Contract 0.4 adds claim classes, the premise audit for hypotheses (RESEARCH_QUESTION), computed CORPUS_STATISTIC,
ACH validity, and brief checks for unreferenced analytic statements and stale generated statistics.
Contract 0.5 binds every audit to a content hash (a stale audit counts as no audit, recursively through premises),
adds the substantive ACH audit (ACH_PRELIMINARY / PATTERN_VALID / ACH_AUDITED / ACH_REJECTED) and replaces the
heading-based brief lint with an independent audit of every brief line (brief_audits.jsonl).
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ledger import check_record  # noqa: E402
from re_lib import ContentHasher, content_hash, load_contract, norm_text, now_iso, read_jsonl, span_in, table_path  # noqa: E402

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
    # consolidated situation clusters, not free-text usage_situation (raw labels inflate the count)
    situations = {e.get("situation_cluster_id") for e in evs if e.get("situation_cluster_id") not in (None, "", "UNKNOWN")}
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


def claim_class(c, contract):
    return c.get("claim_class") or contract["class_rules"]["legacy_class_by_type"].get(c.get("claim_type"), "WORLD_CLAIM")


def hypothesis_status(a, premise_problems=None):
    """A label never bypasses the audit, and a hypothesis status never raises the evidence level of its premises.

    BLOCKED              contradicted, or the text asserts an unobserved fact
    RESEARCH_QUESTION    framed as forward-looking, but a premise is not FACT_APPROVED, the auditor found an
                         uncovered factual premise, or the link from premises to conclusion is an unsupported leap
    HYPOTHESIS_UNTESTED  forward-looking, every factual premise approved, link plausible but untested
    NEEDS_REVIEW         not audited or the audit is incomplete
    """
    if not a:
        return "NEEDS_REVIEW", ["hypothesis not audited yet"]
    hc = a.get("hypothesis_check")
    if a.get("verdict") == "CONTRADICTS":
        return "BLOCKED", [f"contradicted by audit {a['audit_id']}: {a.get('reasoning', '')[:200]}"]
    if hc == "ASSERTS_UNOBSERVED_FACT":
        return "BLOCKED", [f"presents an unobserved fact as a hypothesis: {a.get('scope_issue') or a.get('reasoning', '')}"[:300]]
    if hc != "FORWARD_LOOKING_OK":
        if a.get("verdict") == "DOES_NOT_SUPPORT":
            return "BLOCKED", ["auditor DOES_NOT_SUPPORT and no hypothesis framing check"]
        return "NEEDS_REVIEW", ["auditor did not judge hypothesis framing (hypothesis_check missing)"]
    rq = list(premise_problems or [])
    if a.get("uncovered_premises"):
        rq.append(f"uncovered factual premise(s): {a['uncovered_premises']}"[:300])
    if a.get("link_check") == "UNSUPPORTED_LEAP":
        rq.append(f"unsupported leap from premises to conclusion: {a.get('reasoning', '')}"[:300])
    elif a.get("link_check") is None:
        return "NEEDS_REVIEW", ["auditor did not assess the premise-to-conclusion link (link_check missing)"]
    if rq:
        return "RESEARCH_QUESTION", rq
    return "HYPOTHESIS_UNTESTED", []


def corpus_statistic_check(c, t):
    """Recompute a CORPUS_STATISTIC from the ledger; the numbers in the text must match."""
    spec = c.get("corpus_stat") or {}
    reasons = []
    unit = spec.get("unit")
    qids = set(spec.get("denominator_query_ids") or [])
    num_ids = spec.get("numerator_evidence_ids") or []
    if unit not in ("comment", "author", "thread", "story") or not qids or not num_ids:
        return False, ["corpus_stat needs unit, denominator_query_ids and numerator_evidence_ids"], {}
    sources = {s["source_id"]: s for s in t["sources"]}
    evidence = {e["evidence_id"]: e for e in t["evidence"]}
    queries = {q["query_id"]: q for q in t["queries"]}

    def key(src, ev=None):
        if unit == "comment":
            return src["source_id"]
        if unit == "author":
            return (src["platform"], src["author_key"])
        if unit == "thread":
            return src["thread_id"]
        return (ev or {}).get("story_id") or src["source_id"]

    denom_units = {key(s) for s in t["sources"] if s.get("query_id") in qids}
    num_units = set()
    for eid in num_ids:
        e = evidence.get(eid)
        if not e or e["source_id"] not in sources:
            reasons.append(f"numerator evidence {eid} missing")
            continue
        src = sources[e["source_id"]]
        if src.get("query_id") not in qids:
            reasons.append(f"numerator evidence {eid} is outside the denominator corpus")
            continue
        num_units.add(key(src, e))
    n, d = len(num_units), len(denom_units)
    text = c.get("text", "")
    if not re.search(rf"\b{n}\b", text) or not re.search(rf"\b{d}\b", text):
        reasons.append(f"recomputed {n} of {d} {unit}s; the text must state these numbers")
    if not re.search(r"(?i)\bcorpus\b|корпус", text):
        reasons.append("text must name the corpus it describes")
    pol = [queries[q].get("polarity") for q in qids if q in queries]
    if pol and sum(p == "PROBLEM" for p in pol) / len(pol) > 0.5 and not spec.get("bias_note"):
        reasons.append("corpus built mostly from PROBLEM queries: bias_note required")
    return not reasons, reasons, {"numerator": n, "denominator": d, "unit": unit}


def evaluate_one(c, t, contract, ctx, statuses):
    sources, evidence, queries, audits, rules, stale = ctx
    res = {"claim_id": c["claim_id"], "claim_type": c.get("claim_type"), "claim_class": claim_class(c, contract),
           "critical": c.get("critical"), "text": c.get("text"), "reasons": []}
    ctype = c.get("claim_type")
    cls = res["claim_class"]
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
        return res
    latest = sorted(audits.get(c["claim_id"], []), key=lambda a: a.get("audited_at", ""))[-1:] or [None]
    a = latest[0]
    if a:
        res["audit_id"] = a["audit_id"]
    elif stale.get(c["claim_id"]):
        res["stale_audits"] = stale[c["claim_id"]]
        res["reasons"].append(f"audit {', '.join(stale[c['claim_id']])} is stale: the claim, its evidence, a source text "
                              "or a premise changed after the audit; audit the current version")

    if cls in contract["class_rules"]["hypothesis_classes"] or ctype in ("HYPOTHESIS", "SITUATION_REACH"):
        if ctype == "HYPOTHESIS" and not c.get("hypothesis_label"):
            res.update(status="NEEDS_REVIEW", reasons=["missing hypothesis_label"])
            return res
        if ctype == "SITUATION_REACH":
            s_ok, s_reasons, s_stats = gate_check(ctype, usable, sources, queries, c, contract)
            res["structural_gate"] = {"pass": s_ok, "reasons": s_reasons, "stats": s_stats}
            if not s_ok:
                res.update(status="NEEDS_REVIEW", reasons=s_reasons)
                return res
        premise_problems = []
        for pid in c.get("premise_claim_ids") or []:
            st = statuses.get(pid)
            if st != "FACT_APPROVED":
                premise_problems.append(f"premise {pid} is {st or 'missing'}, not FACT_APPROVED")
        st, why = hypothesis_status(a, premise_problems)
        res.update(status=st, reasons=res["reasons"] + why)
        return res

    if cls == "CORPUS_STATISTIC":
        s_ok, s_reasons, stats = corpus_statistic_check(c, t)
        res["corpus_stat_recomputed"] = stats
    else:
        s_ok, s_reasons, s_stats = gate_check(ctype, usable, sources, queries, c, contract)
        res["structural_gate"] = {"pass": s_ok, "reasons": s_reasons, "stats": s_stats}

    audited_ok, a_reasons, confirmed = False, list(res["reasons"]), []
    if not a:
        a_reasons.append("no current independent audit")
    else:
        if a.get("verdict") == "CONTRADICTS":
            res.update(status="BLOCKED", reasons=[f"contradicted by audit {a['audit_id']}: {a.get('reasoning', '')[:200]}"])
            return res
        for ch in a.get("evidence_checks", []):
            ev = evidence.get(ch.get("evidence_id"))
            if not ev or ev not in usable or not ch.get("supports"):
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
        if cls != "CORPUS_STATISTIC":
            g_ok, g_reasons, g_stats = gate_check(ctype, confirmed, sources, queries, c, contract)
            res["audited_gate"] = {"pass": g_ok, "reasons": g_reasons, "stats": g_stats}
            if not g_ok:
                a_reasons += [f"after audit: {r}" for r in g_reasons]
        audited_ok = not a_reasons
    res["evidence_audited"] = audited_ok
    res.update(status="FACT_APPROVED" if (s_ok and audited_ok) else "NEEDS_REVIEW", reasons=s_reasons + a_reasons)
    return res


def evaluate_claims(t, contract, hasher=None):
    sources = {r["source_id"]: r for r in t["sources"]}
    evidence = {r["evidence_id"]: r for r in t["evidence"]}
    queries = {r["query_id"]: r for r in t["queries"]}
    hasher = hasher or ContentHasher(t)
    audits, stale = defaultdict(list), defaultdict(list)
    for a in t["audits"]:
        # contract 0.5: an audit counts only for the exact content it was made for
        if a.get("claim_hash") and a["claim_hash"] == hasher.claim(a["claim_id"]):
            audits[a["claim_id"]].append(a)
        else:
            stale[a["claim_id"]].append(a["audit_id"])
    ctx = (sources, evidence, queries, audits, contract["counting_rules"], stale)
    hyp = set(contract["class_rules"]["hypothesis_classes"])
    # facts first: hypotheses read their premises' statuses
    order = sorted(t["claims"], key=lambda c: claim_class(c, contract) in hyp
                   or c.get("claim_type") in ("HYPOTHESIS", "SITUATION_REACH"))
    statuses, results = {}, {}
    for c in order:
        r = evaluate_one(c, t, contract, ctx, statuses)
        statuses[c["claim_id"]] = r["status"]
        results[c["claim_id"]] = r
    return [results[c["claim_id"]] for c in t["claims"]]


def evaluate_ach(t, claim_status, hasher=None):
    """ACH_PRELIMINARY   pattern claim not FACT_APPROVED
    PATTERN_VALID     pattern approved, the analysis itself has no current SOUND audit
    ACH_AUDITED       pattern approved and a current audit judged explanations, evidence and preference SOUND
    ACH_REJECTED      the current audit says UNSOUND, or the last audit said UNSOUND and the analysis was edited
                      without a new audit (cannot be cited)"""
    hasher = hasher or ContentHasher(t)
    sources = {r["source_id"]: r for r in t["sources"]}
    evidence = {r["evidence_id"]: r for r in t["evidence"]}
    by_ach, stale = defaultdict(list), defaultdict(list)
    for a in t.get("ach_audits", []):
        (by_ach if a.get("ach_hash") == hasher.ach(a["ach_id"]) else stale)[a["ach_id"]].append(a)
    out = {}
    for h in t["hypotheses"]:
        aid = h["ach_id"]
        st = claim_status.get(h.get("pattern_claim_id"))
        a = (sorted(by_ach[aid], key=lambda x: x.get("audited_at", ""))[-1:] or [None])[0]
        reasons = []
        if not a:
            reasons.append("no current ACH audit" + (f" (stale: {[x['ach_audit_id'] for x in stale[aid]]})" if stale[aid] else ""))
        else:
            for ch in a.get("evidence_checks", []):
                ev = evidence.get(ch.get("evidence_id"))
                if ch.get("holds") and (not ev or not span_in(ch.get("located_span", ""), sources.get(ev["source_id"], {}).get("text", ""))):
                    reasons.append(f"ACH audit span for {ch.get('evidence_id')} is not verbatim in the source")
            if a.get("verdict") != "SOUND":
                reasons.append(f"ACH audit {a['ach_audit_id']} verdict {a.get('verdict')}: {a.get('issues') or a.get('reasoning', '')}"[:300])
        last_stale = (sorted(stale[aid], key=lambda x: x.get("audited_at", ""))[-1:] or [None])[0]
        if a and a.get("verdict") == "UNSOUND":
            status = "ACH_REJECTED"
        elif not a and last_stale and last_stale.get("verdict") == "UNSOUND":
            # an edit does not clear a rejection: only a new audit of the edited analysis can
            status = "ACH_REJECTED"
            reasons.append(f"rejected by {last_stale['ach_audit_id']} (UNSOUND) and edited since; audit the new version")
        elif st != "FACT_APPROVED":
            status = "ACH_PRELIMINARY"
            reasons.insert(0, f"pattern {h.get('pattern_claim_id')} is {st}")
        elif a and not reasons:
            status = "ACH_AUDITED"
        else:
            status = "PATTERN_VALID"
        out[aid] = {"status": status, "pattern_claim_id": h.get("pattern_claim_id"), "pattern_status": st,
                    "ach_audit_id": a and a["ach_audit_id"], "reasons": reasons}
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
        planned = {s["source"] for s in caps.get("sources", []) if s.get("planned")}
        reachable = {s["source"] for s in caps.get("sources", []) if s.get("can_retrieve_text") or s.get("can_retrieve_comments")}
        for name in sorted(planned - reachable):
            cov["limited_reasons"].append(f"planned source not retrievable by any tested route: {name}")
    unbalanced = [b for b, v in cov["branches"].items() if not v["balanced"]]
    if unbalanced:
        cov["limited_reasons"].append(f"branches without NEUTRAL/POSITIVE queries: {unbalanced}")
    cov["status"] = "COVERAGE_LIMITED" if cov["limited_reasons"] else "COVERAGE_OK"
    cov["matrix"] = dict(cov["matrix"])
    return cov


LABELS = {"RU": {"HYPOTHESIS_UNTESTED": "гипотез", "RESEARCH_QUESTION": "вопрос", "PRELIMINARY": "предварительн"},
          "EN": {"HYPOTHESIS_UNTESTED": "hypothes", "RESEARCH_QUESTION": "question", "PRELIMINARY": "preliminary"}}
SOURCES_HEADINGS = ("источники", "sources")
REF = re.compile(r"\[(C-\d{4}|ACH-\d{4})\]")
URL = re.compile(r"https?://[^\s<>\]\)\"'«»]+")
QUOTED = re.compile(r"«([^»]{12,})»|\"([^\"]{12,})\"|“([^”]{12,})”")


def brief_lines(txt):
    """Content lines of a brief that the semantic audit must cover (contract 0.6): every line, headings and table
    header rows included, except blank lines, rules, the generated STATS block, table separator rows and bare URL
    bullets under the Sources heading. HTML comments are rejected by the lint, not audited."""
    out, section, in_stats = [], "", False
    lines = txt.splitlines()
    for i, line in enumerate(lines):
        st = line.strip()
        if st.startswith("<!-- STATS:BEGIN"):
            in_stats = True
        if in_stats:
            in_stats = not st.startswith("<!-- STATS:END")
            continue
        if not st or st == "---" or st.startswith("<!--"):
            continue
        if st.startswith("#"):
            section = st.lstrip("#").strip()
            out.append({"section": section, "line": st})
            continue
        if re.fullmatch(r"\|[\s:|-]+\|", st):
            continue
        if any(section.lower().startswith(h) for h in SOURCES_HEADINGS) and re.fullmatch(r"-\s*https?://\S+", st):
            continue
        out.append({"section": section, "line": st})
    return out


def cited(line):
    return sorted(set(REF.findall(line))), sorted(set(URL.findall(line)))


def line_hash(lang, line, claim_status, ach, hasher, url_text):
    """Hash of a brief line plus the content and status of everything it cites (claims, ACH, source URLs)."""
    ids, urls = cited(line)
    cites = {}
    for i in ids:
        if i.startswith("ACH-"):
            cites[i] = [hasher.ach(i), (ach.get(i) or {}).get("status")]
        else:
            cites[i] = [hasher.claim(i), claim_status.get(i)]
    for u in urls:
        cites[u] = url_text.get(norm_url(u))
    return content_hash({"lang": lang, "line": norm_text(line), "cites": cites})


def norm_url(u):
    return u.rstrip(".,;:/")


def url_texts(t, hasher=None):
    """{normalised url: sorted hashes of the archived text and provenance of each source at that url}."""
    from re_lib import text_hash
    out = defaultdict(list)
    for s in t["sources"]:
        if s.get("url"):
            prov = hasher.provenance(s) if hasher else None
            out[norm_url(s["url"])].append(text_hash(s.get("text", "")) if prov is None
                                           else content_hash([text_hash(s.get("text", "")), prov]))
    return {k: sorted(v) for k, v in out.items()}


def check_briefs(ru_path, en_path, claim_status, ach_status=None, project_dir=None, t=None, hasher=None, contract=None):
    """Layer 1, structural lint (script). Layer 2, semantic audit: every content line needs a current brief audit
    (brief_audits.jsonl) saying ENTAILED or LIMITATION_OK."""
    issues = []
    ach_status = ach_status or {}
    ru = Path(ru_path).read_text(encoding="utf-8")
    en = Path(en_path).read_text(encoding="utf-8")
    if re.search("[\u0400-\u052f\u2de0-\u2dff\ua640-\ua69f]", en):
        bad = sorted(set(re.findall("[\u0400-\u052f]", en)))[:10]
        issues.append(f"EN brief contains Cyrillic characters: {''.join(bad)}")
    ref = re.compile(r"\[(C-\d{4})\]")
    aref = re.compile(r"\[(ACH-\d{4})\]")
    sources_by_url = {}
    if t:
        for s in t["sources"]:
            if s.get("url"):
                sources_by_url.setdefault(norm_url(s["url"]), []).append(s)
    for name, txt in (("RU", ru), ("EN", en)):
        lab = LABELS[name]
        for c in re.findall(r"<!--(.*?)-->", txt, re.S):
            if c.strip() not in ("STATS:BEGIN", "STATS:END"):
                issues.append(f"{name}: HTML comment in the brief (only the STATS markers are allowed): {c.strip()[:60]}")
        for line in txt.splitlines():
            low = line.lower()
            for cid in ref.findall(line):
                st = claim_status.get(cid)
                if st is None:
                    issues.append(f"{name}: {cid} referenced but not in claims")
                elif st in ("HYPOTHESIS_UNTESTED", "RESEARCH_QUESTION") and lab[st] not in low:
                    issues.append(f"{name}: {cid} is {st} but its line has no '{lab[st]}' label")
                elif st not in ("FACT_APPROVED", "HYPOTHESIS_UNTESTED", "RESEARCH_QUESTION"):
                    issues.append(f"{name}: {cid} has status {st} and cannot appear in a brief")
            for aid in aref.findall(line):
                a = ach_status.get(aid)
                if a is None:
                    issues.append(f"{name}: {aid} referenced but not in hypotheses")
                elif a["status"] == "ACH_REJECTED":
                    issues.append(f"{name}: {aid} is ACH_REJECTED and cannot appear in a brief")
                elif a["status"] != "ACH_AUDITED" and lab["PRELIMINARY"] not in low:
                    issues.append(f"{name}: {aid} is {a['status']} (not ACH_AUDITED) but its line has no "
                                  f"'{lab['PRELIMINARY']}' label")
            # a URL is never a citation; a quote next to a URL must be verbatim in the archived source
            urls = URL.findall(line)
            if urls and t:
                srcs = []
                for u in urls:
                    nu = norm_url(u)
                    # a thread URL covers the comments archived under it
                    srcs += sources_by_url.get(nu) or [s for k, v in sources_by_url.items() if k.startswith(nu + "/") for s in v]
                if QUOTED.search(line) and not srcs:
                    issues.append(f"{name}: quoted text cites a URL that is not in the archive: {urls[0][:80]}")
                for m in QUOTED.finditer(line):
                    q = next(g for g in m.groups() if g)
                    # an excerpt may be trimmed with an ellipsis; every remaining fragment must be verbatim
                    frags = [f.strip() for f in re.split(r"…|\.\.\.", q) if len(f.strip()) >= 8]
                    if srcs and frags and not any(all(span_in(f, s.get("text", "")) for f in frags) for s in srcs):
                        issues.append(f"{name}: quoted text is not verbatim in the source at the cited URL (write a "
                                      f"paraphrase without quotation marks): {q[:60]}")
        if t:
            sec = ""
            for line in txt.splitlines():
                st = line.strip()
                if st.startswith("#"):
                    sec = st.lstrip("#").strip().lower()
                elif any(sec.startswith(h) for h in SOURCES_HEADINGS):
                    for u in URL.findall(st):
                        if norm_url(u) not in sources_by_url:
                            issues.append(f"{name}: Sources lists a URL that is not in the archive: {u[:80]}")
    for rx, what in ((ref, "claim ids"), (aref, "ACH ids")):
        a, b = set(rx.findall(ru)), set(rx.findall(en))
        if a != b:
            issues.append(f"{what} differ RU vs EN: only RU {sorted(a - b)}, only EN {sorted(b - a)}")
    u_ru, u_en = set(URL.findall(ru)), set(URL.findall(en))
    if u_ru != u_en:
        issues.append(f"source links differ RU vs EN: only RU {len(u_ru - u_en)}, only EN {len(u_en - u_ru)}")
    if project_dir:
        from render_stats import consistency_issues
        issues += consistency_issues(project_dir, claim_status, {"RU": ru_path, "EN": en_path})
    if t is not None:
        issues += semantic_issues({"RU": ru, "EN": en}, claim_status, ach_status, t, hasher or ContentHasher(t))
    return issues


def semantic_issues(texts, claim_status, ach_status, t, hasher):
    uts = url_texts(t, hasher)
    audits = {}
    for a in sorted(t.get("brief_audits", []), key=lambda x: x.get("audited_at", "")):
        audits[a["line_hash"]] = a
    issues, unaudited = [], Counter()
    for lang, txt in texts.items():
        for item in brief_lines(txt):
            h = line_hash(lang, item["line"], claim_status, ach_status, hasher, uts)
            a = audits.get(h)
            if not a:
                unaudited[lang] += 1
                issues.append(f"{lang}: line has no current brief audit (new, edited, or a cited record changed): "
                              f"{item['line'][:90]}")
            elif a.get("verdict") not in ("ENTAILED", "LIMITATION_OK"):
                issues.append(f"{lang}: brief audit {a['brief_audit_id']} says {a['verdict']}: {a.get('issue', '')[:160]} "
                              f"| {item['line'][:80]}")
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
    L += ["", "## ACH", ""] + [f"- {k}: **{v['status']}** (pattern {v['pattern_claim_id']} is {v['pattern_status']})"
                                + (f"; {'; '.join(v['reasons'])}" if v.get("reasons") else "")
                                for k, v in report.get("ach", {}).items()]
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
    for table in ("evidence", "claims", "hypotheses", "audits", "ach_audits", "brief_audits"):
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

    hasher = ContentHasher(t)
    claims = evaluate_claims(t, contract, hasher)
    claim_status = {c["claim_id"]: c["status"] for c in claims}
    ach = evaluate_ach(t, claim_status, hasher)
    srcs = t["sources"]
    report = {
        "project_id": project["project_id"], "computed_at": now_iso(), "contract_version": contract["contract_version"],
        "schema_errors": schema_errors, "claims": claims, "ach": ach, "coverage": coverage(t, contract, project),
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
        report["brief_issues"] = check_briefs(args.brief_ru, args.brief_en, claim_status, ach, pdir, t, hasher, contract)
    (pdir / "gate_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=list), encoding="utf-8")
    write_md(report, pdir / "gate_report.md")
    print(f"schema errors: {len(schema_errors)}; claims: {report['corpus']['claim statuses']}; "
          f"coverage: {report['coverage']['status']}"
          + (f"; brief issues: {len(report['brief_issues'])}" if "brief_issues" in report else ""))
    fail = schema_errors or report.get("brief_issues")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
