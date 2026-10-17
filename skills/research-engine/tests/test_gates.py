#!/usr/bin/env python3
"""Trap tests for the Gate Contract. Each trap must be caught; one clean case must pass.

Fixture texts are synthetic (labelled FIXTURE), stored in a temp project; no network.
Run: python3 tests/test_gates.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from re_lib import ContentHasher, append_jsonl, read_jsonl, text_hash, write_jsonl  # noqa: E402

FIXTURE_SOURCES = [
    # thread A: three comments in one thread
    ("RD-a1", "tA", "FIXTURE: My tote is so heavy with the laptop that my shoulder aches by lunch."),
    ("RD-a2", "tA", "FIXTURE: Same, I switched to a backpack for the commute because the tote hurt my shoulder."),
    ("RD-a3", "tA", "FIXTURE: Mine too, heavy totes are the worst on the train."),
    # thread B and C: independent threads, different situations
    ("RD-b1", "tB", "FIXTURE: I returned the leather tote after a week, with my laptop it was too heavy to carry to work."),
    ("RD-c1", "tC", "FIXTURE: On travel days the tote with my laptop gets heavy and I end up dragging it through the airport."),
    ("RD-c2", "tC", "FIXTURE: I keep using my heavy tote because it looks professional and backpacks look like school."),
    # thread D: professional style, no age, no purchase
    ("RD-d1", "tD", "FIXTURE: I like a structured tote for the office, it looks more put together."),
    ("RD-e1", "tE", "FIXTURE: A big tote looks polished in meetings."),
    # snippet-only source
    ("SN-f1", "tF", "FIXTURE: totes are heavy"),
]


def run(cmd, expect_ok=None):
    p = subprocess.run([sys.executable] + cmd, capture_output=True, text=True)
    if expect_ok is not None and (p.returncode == 0) != expect_ok:
        print(p.stdout, p.stderr)
        raise AssertionError(f"unexpected exit {p.returncode} for {cmd[:3]}")
    return p


def add(pdir, table, rec, expect_ok=True):
    return run([str(SCRIPTS / "ledger.py"), "--project-dir", pdir, "add", table, json.dumps(rec)], expect_ok)


def tables(pdir):
    return {n: read_jsonl(Path(pdir, f)) for n, f in (("claims", "claims.jsonl"), ("evidence", "evidence.jsonl"),
            ("sources", "archive/sources.jsonl"), ("hypotheses", "hypotheses.jsonl"))}


def rewrite(pdir, fname, key, rid, **fields):
    rows = read_jsonl(Path(pdir, fname))
    for r in rows:
        if r[key] == rid:
            r.update(fields)
    write_jsonl(Path(pdir, fname), rows)


def ev(source_id, span, **kw):
    base = {"source_id": source_id, "quote_span": span, "observation": "fixture", "observed_behavior": "fixture",
            "person_action": "USES", "journey_stage": "USE", "scope": "CATEGORY", "product_match": "CATEGORY_GENERAL",
            "usage_situation": "work", "situation_cluster_id": "S1", "behavior_pattern_id": "BP1",
            "market_grounding": "UNKNOWN", "polarity": "PROBLEM", "evidence_kind": "OBSERVATION",
            "what_it_does_not_prove": "prevalence; purchase motive"}
    base.update(kw)
    return base


def main():
    pdir = tempfile.mkdtemp(prefix="re_test_")
    Path(pdir, "project.json").write_text(json.dumps({"project_id": "TEST", "markets": ["ANY"]}))
    srcs = []
    for sid, tid, text in FIXTURE_SOURCES:
        snippet = sid.startswith("SN-")
        srcs.append({"source_id": sid, "project_id": "TEST", "platform": "reddit", "url": f"https://example.test/{sid}",
                     "platform_object_id": sid, "thread_id": tid, "author_key": "k" + sid, "retrieved_at": "2026-10-16",
                     "retrieval_method": "SEARCH_SNIPPET" if snippet else "RSS",
                     "access_status": "INDEXED_ONLY" if snippet else "READ_FULL", "content_available": "TEXT",
                     "context_captured": "EXCERPT_ONLY" if snippet else "COMMENT_ONLY", "source_origin": "PUBLIC",
                     "text": text, "source_version": text_hash(text), **({"query_id": "Q-0001"} if tid == "tA" else {})})
    append_jsonl(Path(pdir, "archive/sources.jsonl"), srcs)
    append_jsonl(Path(pdir, "queries.jsonl"), [
        {"query_id": "Q-0001", "project_id": "TEST", "branch_id": "B1", "query_text": "tote heavy", "platform": "reddit",
         "executed_at": "x", "market": "ANY", "journey_stage": "USE", "scope": "CATEGORY", "usage_situation": "work",
         "polarity": "PROBLEM", "results_found": 1, "results_retrieved": 1},
        {"query_id": "Q-0002", "project_id": "TEST", "branch_id": "B1", "query_text": "love my tote", "platform": "reddit",
         "executed_at": "x", "market": "ANY", "journey_stage": "USE", "scope": "CATEGORY", "usage_situation": "work",
         "polarity": "POSITIVE", "results_found": 1, "results_retrieved": 1}])

    # Insert-time traps
    p = add(pdir, "evidence", ev("RD-a1", "my shoulder is destroyed"), expect_ok=False)
    assert "not verbatim" in p.stdout, "T7 fabricated quote must be rejected"
    p = add(pdir, "evidence", dict(ev("RD-a1", "shoulder aches"), status="APPROVED"), expect_ok=False)
    assert "computed by validate.py" in p.stdout, "T11 self-declared status must be rejected"
    p = add(pdir, "evidence", ev("RD-b1", "I returned the leather tote", evidence_kind="DECISION"), expect_ok=False)
    assert "DECISION evidence needs" in p.stdout, "decision evidence without decision fields must be rejected"

    E = {}
    for key, rec in {
        "a1": ev("RD-a1", "my shoulder aches by lunch"),
        "a2": ev("RD-a2", "the tote hurt my shoulder", person_action="SWITCHED", evidence_kind="DECISION",
                 decision={"initial_situation": "commute with tote", "alternatives_considered": "backpack",
                           "decision_trigger": "shoulder pain", "action_taken": "switched to backpack",
                           "reported_outcome": "not stated", "reason_basis": "EXPLICIT", "unverified_assumptions": "age, market"}),
        "a3": ev("RD-a3", "heavy totes are the worst"),
        "b1": ev("RD-b1", "I returned the leather tote after a week", person_action="RETURNED", evidence_kind="DECISION",
                 decision={"initial_situation": "bought leather tote", "alternatives_considered": "not stated",
                           "decision_trigger": "too heavy with laptop", "action_taken": "returned",
                           "reported_outcome": "not stated", "reason_basis": "EXPLICIT", "unverified_assumptions": "which brand"}),
        "c1": ev("RD-c1", "gets heavy and I end up dragging it", usage_situation="travel", situation_cluster_id="S2"),
        "c2": ev("RD-c2", "it looks professional", polarity="NEUTRAL", behavior_pattern_id="BP2"),
        "d1": ev("RD-d1", "it looks more put together", polarity="POSITIVE", behavior_pattern_id="BP2"),
        "e1": ev("RD-e1", "A big tote looks polished in meetings", polarity="POSITIVE", behavior_pattern_id="BP2",
                 usage_situation="meetings", situation_cluster_id="S3"),
        "f1": ev("SN-f1", "totes are heavy"),
    }.items():
        add(pdir, "evidence", rec)
        E[key] = f"E-{len(E) + 1:04d}"

    def claim(text, ctype, sup, counter=("Q-0002",), contra=(), **kw):
        rec = {"text": text, "claim_type": ctype, "critical": True, "scope_limits": "fixture",
               "supporting_evidence_ids": [E[s] for s in sup], "contradicting_evidence_ids": [E[s] for s in contra],
               "counter_search_query_ids": list(counter)}
        rec.update(kw)
        return rec

    claims = [
        ("T1 one thread", claim("Heavy totes hurt shoulders", "PATTERN", ["a1", "a2", "a3"])),
        ("T2 no audit", claim("Heavy laptop totes cause pain across contexts", "PATTERN", ["a1", "b1", "c1"])),
        ("T3 fake auditor span", claim("Heavy laptop totes cause pain across contexts (b)", "PATTERN", ["a1", "b1", "c1"])),
        ("T4 complaints as purchase driver", claim("Weight drives returns", "PURCHASE_DRIVER", ["a1", "a3", "c1"])),
        ("T5 product fact from category", claim("Levant tote is light", "PRODUCT_FACT", ["a1"])),
        ("T6 snippet only", claim("Totes are heavy (snippet)", "PERSONAL_EXPERIENCE", ["f1"])),
        ("T9 clean pattern", claim("Laptop weight in a tote becomes a problem in several situations", "PATTERN", ["a1", "b1", "c1"])),
        ("T10 40-50 professional", claim("Women 40-50 buy big totes to look professional", "PATTERN", ["c2", "d1", "e1"])),
        ("T12 hypothesis", claim("Maybe structure signals competence", "HYPOTHESIS", ["d1"], hypothesis_label="analyst hypothesis")),
        ("T13 no counter-search", claim("Heavy laptop totes cause pain (no counter)", "PATTERN", ["a1", "b1", "c1"], counter=())),
        ("T14 hypothesis asserting a fact", claim("Our UGC video already doubled ROAS last week", "HYPOTHESIS", ["d1"], hypothesis_label="analyst hypothesis")),
        ("T15 hypothesis not audited", claim("Structure may signal competence to colleagues", "HYPOTHESIS", ["d1"], hypothesis_label="analyst hypothesis")),
        ("T16 reach as a share", claim("21% of US women have shoulder pain from totes", "SITUATION_REACH", ["a1", "b1", "c1"])),
        ("T21 corpus statistic correct", claim("In this complaint-search corpus, 2 of 3 comments describe shoulder pain or hurting.",
                                               "PATTERN", ["a1", "a2"], claim_class="CORPUS_STATISTIC",
                                               corpus_stat={"unit": "comment", "denominator_query_ids": ["Q-0001"],
                                                            "numerator_evidence_ids": [], "bias_note": "complaint-only search"})),
        ("T22 corpus statistic wrong numbers", claim("In this corpus, 5 of 3 comments describe shoulder pain.",
                                                     "PATTERN", ["a1", "a2"], claim_class="CORPUS_STATISTIC",
                                                     corpus_stat={"unit": "comment", "denominator_query_ids": ["Q-0001"],
                                                                  "numerator_evidence_ids": [], "bias_note": "complaint-only search"})),
    ]
    C = {}
    for name, rec in claims:
        if rec.get("corpus_stat"):
            rec["corpus_stat"]["numerator_evidence_ids"] = [E["a1"], E["a2"]]
        add(pdir, "claims", rec)
        C[name] = f"C-{len(C) + 1:04d}"
    # contract 0.4 premise traps: hypotheses that point to their premises as claims
    premise_traps = [
        ("T17 premise not approved (H18 class)", C["T1 one thread"], {}),
        ("T18 uncovered premise", C["T9 clean pattern"], {"uncovered_premises": ["no reviews exist anywhere online"]}),
        ("T19 unsupported leap", C["T9 clean pattern"], {"link_check": "UNSUPPORTED_LEAP"}),
        ("T20 clean hypothesis on approved premise", C["T9 clean pattern"], {}),
    ]
    for name, premise, _ in premise_traps:
        add(pdir, "claims", claim(f"{name}: a lighter tote might reduce shoulder pain", "HYPOTHESIS", [],
                                  counter=(), hypothesis_label="analyst hypothesis", claim_class="FUTURE_HYPOTHESIS",
                                  premise_claim_ids=[premise]))
        C[name] = f"C-{len(C) + 1:04d}"

    def audit(cid, checks, verdict="SUPPORTS", scope_issue="", open_c=False, hc=None, **more):
        extra = {"hypothesis_check": hc} if hc else {}
        if hc == "FORWARD_LOOKING_OK":
            extra.update({"uncovered_premises": [], "link_check": "PLAUSIBLE_UNTESTED"})
        extra.update(more)
        return {"claim_id": cid, "claim_hash": ContentHasher(tables(pdir)).claim(cid),
                "auditor": "fixture-auditor", "verdict": verdict, "scope_issue": scope_issue,
                "open_contradiction": open_c, "reasoning": "fixture", **extra,
                "evidence_checks": [{"evidence_id": E[k], "located_span": s, "supports": True, "note": ""} for k, s in checks]}

    good = [("a1", "my shoulder aches by lunch"), ("b1", "with my laptop it was too heavy"), ("c1", "the tote with my laptop gets heavy")]
    add(pdir, "audits", audit(C["T3 fake auditor span"], [("a1", "my shoulder aches by lunch"), ("b1", "too heavy, I hated it"),
                                                         ("c1", "the tote with my laptop gets heavy")]))
    add(pdir, "audits", audit(C["T9 clean pattern"], good))
    add(pdir, "audits", audit(C["T12 hypothesis"], [], verdict="PARTIAL", hc="FORWARD_LOOKING_OK"))
    add(pdir, "audits", audit(C["T14 hypothesis asserting a fact"], [], verdict="DOES_NOT_SUPPORT", hc="ASSERTS_UNOBSERVED_FACT",
                              scope_issue="states an observed ROAS result"))
    add(pdir, "audits", audit(C["T16 reach as a share"], good, verdict="DOES_NOT_SUPPORT", hc="ASSERTS_UNOBSERVED_FACT",
                              scope_issue="corpus share presented as a population percentage"))
    add(pdir, "audits", audit(C["T13 no counter-search"], good))
    for name, _, more in premise_traps:
        add(pdir, "audits", audit(C[name], [], verdict="PARTIAL", hc="FORWARD_LOOKING_OK", **more))
    for name in ("T21 corpus statistic correct", "T22 corpus statistic wrong numbers"):
        add(pdir, "audits", audit(C[name], [("a1", "my shoulder aches by lunch"), ("a2", "the tote hurt my shoulder")]))
    add(pdir, "audits", audit(C["T10 40-50 professional"], [("c2", "it looks professional"), ("d1", "looks more put together"),
                                                           ("e1", "looks polished in meetings")],
                              scope_issue="age 40-50 not established; no purchase stated"))

    run([str(SCRIPTS / "validate.py"), "--project-dir", pdir])
    report = json.loads(Path(pdir, "gate_report.json").read_text())
    st = {c["claim_id"]: c for c in report["claims"]}
    expect = {
        "T1 one thread": "NEEDS_REVIEW", "T2 no audit": "NEEDS_REVIEW", "T3 fake auditor span": "NEEDS_REVIEW",
        "T4 complaints as purchase driver": "NEEDS_REVIEW", "T5 product fact from category": "NEEDS_REVIEW",
        "T6 snippet only": "NEEDS_REVIEW", "T9 clean pattern": "FACT_APPROVED", "T10 40-50 professional": "NEEDS_REVIEW",
        "T12 hypothesis": "HYPOTHESIS_UNTESTED", "T13 no counter-search": "NEEDS_REVIEW",
        "T14 hypothesis asserting a fact": "BLOCKED", "T15 hypothesis not audited": "NEEDS_REVIEW",
        "T16 reach as a share": "BLOCKED",
        "T17 premise not approved (H18 class)": "RESEARCH_QUESTION", "T18 uncovered premise": "RESEARCH_QUESTION",
        "T19 unsupported leap": "RESEARCH_QUESTION", "T20 clean hypothesis on approved premise": "HYPOTHESIS_UNTESTED",
        "T21 corpus statistic correct": "FACT_APPROVED", "T22 corpus statistic wrong numbers": "NEEDS_REVIEW",
    }
    failures = 0
    for name, want in expect.items():
        got = st[C[name]]["status"]
        mark = "ok  " if got == want else "FAIL"
        failures += got != want
        print(f"{mark} {name:36s} -> {got:18s} {'; '.join(st[C[name]]['reasons'])[:110]}")

    # Brief traps. ACH-0001 explains the unapproved T1 pattern (ACH_PRELIMINARY); ACH-0002 the approved T9 pattern.
    def ach_rec(pattern):
        return {"pattern_claim_id": pattern, "question": "why", "preferred_h_id": "H1",
                "preference_reason": "fixture: H1 fits the cited comments better than H2", "causal_status": "NOT_ESTABLISHED",
                "hypotheses": [{"h_id": "H1", "statement": "load on one shoulder", "supporting_ids": [E["a1"]],
                                "refuting_ids": [], "diagnosticity": "HIGH", "missing_evidence": "x"},
                               {"h_id": "H2", "statement": "fashion", "supporting_ids": [], "refuting_ids": [E["a1"]],
                                "diagnosticity": "LOW", "missing_evidence": "y"}]}
    add(pdir, "hypotheses", ach_rec(C["T1 one thread"]))
    add(pdir, "hypotheses", ach_rec(C["T9 clean pattern"]))
    t9, t12 = C["T9 clean pattern"], C["T12 hypothesis"]
    Path(pdir, "ru.md").write_text(
        f"## Главное\nИнсайт [{t9}] https://example.test/x\nЕщё [{C['T1 one thread']}]\nГипотеза: [{t12}]\n"
        f"Главный риск бренда — отзывы.\nПочему уходят [ACH-0001]\nОбъяснение [ACH-0002]\n"
        f"- «my shoulder is destroyed by noon» https://example.test/RD-a1\n"
        f"## Источники\n- https://example.test/RD-a1\n- https://example.test/not-archived\n", encoding="utf-8")
    Path(pdir, "en.md").write_text(
        f"## Main points\nInsight [{t9}] https://example.test/x\nAlso [{C['T1 one thread']}]\n[{t12}] structure signals "
        f"competence. Привет\nThe main brand risk is reviews.\nWhy people leave [ACH-0001]\nExplanation [ACH-0002]\n"
        f"- \"my shoulder is destroyed by noon\" https://example.test/RD-a1\n"
        f"## Sources\n- https://example.test/RD-a1\n- https://example.test/not-archived\n", encoding="utf-8")
    brief_args = ["--brief-ru", f"{pdir}/ru.md", "--brief-en", f"{pdir}/en.md"]

    def brief_issues():
        run([str(SCRIPTS / "validate.py"), "--project-dir", pdir] + brief_args)
        rep = json.loads(Path(pdir, "gate_report.json").read_text())
        return rep["brief_issues"], {c["claim_id"]: c for c in rep["claims"]}, rep["ach"]

    def check(name, ok):
        nonlocal failures
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {name}")

    issues, _, ach = brief_issues()
    for needle, name in (("Cyrillic", "T8a EN Cyrillic"), ("cannot appear", "T8b unapproved claim in brief"),
                         ("no 'hypothes' label", "T8c unlabeled hypothesis"),
                         ("ACH-0001 is ACH_PRELIMINARY", "T8e ACH on an unapproved pattern without label"),
                         ("STATS block", "T8f brief statistics not generated from the ledger"),
                         ("ledger_snapshot", "T8g project snapshot missing"),
                         ("ACH-0002 is PATTERN_VALID", "T29a approved pattern but unaudited ACH cited without label"),
                         ("not verbatim in the source at the cited URL", "T30 quote next to a URL not verbatim"),
                         ("not in the archive", "T32 Sources lists an unarchived URL")):
        check(name, any(needle in i for i in issues))
    check("T8d sentence without a claim has no brief audit",
          any("no current brief audit" in i and "main brand risk" in i for i in issues))

    # contract 0.5: substantive ACH audit, then the semantic brief audit (ACH status is part of the line hash)
    sound = {"ach_id": "ACH-0002", "verdict": "SOUND", "issues": "", "reasoning": "fixture", "auditor": "fixture-auditor",
             "evidence_checks": [{"evidence_id": E["a1"], "h_id": "H1", "role": "supports",
                                  "located_span": "my shoulder aches by lunch", "holds": True, "note": ""}]}
    run([str(SCRIPTS / "audit_packet.py"), "--project-dir", pdir, "--ach", "ACH-0002"], True)
    pk = Path(pdir, "ach_packet.json")
    pk.write_text(run([str(SCRIPTS / "audit_packet.py"), "--project-dir", pdir, "--ach", "ACH-0002"]).stdout)
    p = run([str(SCRIPTS / "ledger.py"), "--project-dir", pdir, "add", "ach_audits", json.dumps(sound), "--packet", str(pk)], True)
    _, _, ach = brief_issues()
    check("T29b ACH with approved pattern and SOUND audit is ACH_AUDITED", ach["ACH-0002"]["status"] == "ACH_AUDITED")

    run([str(SCRIPTS / "brief_packet.py"), "--project-dir", pdir] + brief_args + ["--out-dir", f"{pdir}/bp"], True)
    lines = json.loads(Path(pdir, "bp/brief_packet_01.json").read_text())["lines"]
    answers = [{"line_hash": x["line_hash"], "auditor": "fixture-auditor", "issue": "" if "risk" not in x["line"]
                and "риск" not in x["line"] else "asserts the main brand risk without a record",
                "verdict": "NOT_SUPPORTED" if ("risk" in x["line"] or "риск" in x["line"]) else "ENTAILED"} for x in lines]
    run([str(SCRIPTS / "ledger.py"), "--project-dir", pdir, "add", "brief_audits", json.dumps(answers),
         "--packet", f"{pdir}/bp/brief_packet_01.json"], True)
    issues, _, _ = brief_issues()
    check("T26 audited line judged NOT_SUPPORTED fails the export", any("says NOT_SUPPORTED" in i for i in issues))
    check("T27 every other line now has a current brief audit", not any("no current brief audit" in i for i in issues))
    check("T29b' ACH_AUDITED needs no preliminary label", not any("ACH-0002 is" in i for i in issues))

    # contract 0.6: headings are audited lines; hidden HTML comments are rejected
    ru_txt = Path(pdir, "ru.md").read_text(encoding="utf-8")
    Path(pdir, "ru.md").write_text(ru_txt.replace("## Главное", "## Клинически доказано: боль исчезает", 1)
                                   + "<!-- hidden promise: cures pain -->\n", encoding="utf-8")
    issues, _, _ = brief_issues()
    check("T33 a heading changed into a promise needs a brief audit",
          any("no current brief audit" in i and "Клинически" in i for i in issues))
    check("T35 HTML comment other than STATS markers is rejected", any("HTML comment" in i for i in issues))
    Path(pdir, "ru.md").write_text(ru_txt, encoding="utf-8")

    # contract 0.6: source provenance is part of the content hash
    t21 = C["T21 corpus statistic correct"]
    rewrite(pdir, "archive/sources.jsonl", "source_id", "RD-a2", commercial_disclosure="PAID_BRAND_PARTNERSHIP")
    _, st, _ = brief_issues()
    check("T34 provenance change of a cited source (paid partnership, text unchanged) makes the audit stale",
          st[t21]["status"] != "FACT_APPROVED" and any("stale" in r for r in st[t21]["reasons"]))

    # X04 class: the ACH argument changes after its audit
    rewrite(pdir, "hypotheses.jsonl", "ach_id", "ACH-0002",
            preference_reason="All buyers are wrong; the bag never breaks and this is scientifically proven.")
    issues, _, ach = brief_issues()
    check("T29c ACH edited after audit falls back to PATTERN_VALID", ach["ACH-0002"]["status"] == "PATTERN_VALID")
    check("T29c' its brief line needs a new audit", any("no current brief audit" in i and "ACH-0002" in i for i in issues))
    unsound = dict(sound, verdict="UNSOUND", issues="preference_reason asserts proof the evidence does not show")
    pk.write_text(run([str(SCRIPTS / "audit_packet.py"), "--project-dir", pdir, "--ach", "ACH-0002"]).stdout)
    run([str(SCRIPTS / "ledger.py"), "--project-dir", pdir, "add", "ach_audits", json.dumps(unsound), "--packet", str(pk)], True)
    issues, _, ach = brief_issues()
    check("T29d UNSOUND ACH is ACH_REJECTED and cannot be cited",
          ach["ACH-0002"]["status"] == "ACH_REJECTED" and any("ACH-0002 is ACH_REJECTED" in i for i in issues))

    rewrite(pdir, "hypotheses.jsonl", "ach_id", "ACH-0002", preference_reason="fixture: reworded without a new audit")
    _, _, ach = brief_issues()
    check("T29e editing a rejected ACH does not clear the rejection", ach["ACH-0002"]["status"] == "ACH_REJECTED")

    # X01 / X05 class: claim text changes after its audit
    old_hash = ContentHasher(tables(pdir)).claim(t9)
    rewrite(pdir, "claims.jsonl", "claim_id", t9, text="Clinical tests prove the tote prevents shoulder pain")
    issues, st, _ = brief_issues()
    check("T23 fact edited after audit loses FACT_APPROVED (stale audit)",
          st[t9]["status"] != "FACT_APPROVED" and any("stale" in r for r in st[t9]["reasons"]))
    t20 = C["T20 clean hypothesis on approved premise"]
    check("T23' hypothesis on the edited premise is no longer HYPOTHESIS_UNTESTED (recursive)",
          st[t20]["status"] != "HYPOTHESIS_UNTESTED")
    check("T28 brief line citing the edited claim fails", any(t9 in i for i in issues))
    p = add(pdir, "audits", dict(audit(t9, good), claim_hash=old_hash), expect_ok=False)
    check("T24 audit made for the old content is rejected at insert", "not the current content" in p.stdout)
    print(f"\n{'ALL TRAPS CAUGHT' if not failures else f'{failures} FAILURES'}  (project: {pdir})")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
