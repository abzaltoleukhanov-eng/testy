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
from re_lib import append_jsonl, text_hash  # noqa: E402

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
                     "text": text, "source_version": text_hash(text)})
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
    ]
    C = {}
    for name, rec in claims:
        add(pdir, "claims", rec)
        C[name] = f"C-{len(C) + 1:04d}"

    def audit(cid, checks, verdict="SUPPORTS", scope_issue="", open_c=False):
        return {"claim_id": cid, "auditor": "fixture-auditor", "verdict": verdict, "scope_issue": scope_issue,
                "open_contradiction": open_c, "reasoning": "fixture",
                "evidence_checks": [{"evidence_id": E[k], "located_span": s, "supports": True, "note": ""} for k, s in checks]}

    good = [("a1", "my shoulder aches by lunch"), ("b1", "with my laptop it was too heavy"), ("c1", "the tote with my laptop gets heavy")]
    add(pdir, "audits", audit(C["T3 fake auditor span"], [("a1", "my shoulder aches by lunch"), ("b1", "too heavy, I hated it"),
                                                         ("c1", "the tote with my laptop gets heavy")]))
    add(pdir, "audits", audit(C["T9 clean pattern"], good))
    add(pdir, "audits", audit(C["T13 no counter-search"], good))
    add(pdir, "audits", audit(C["T10 40-50 professional"], [("c2", "it looks professional"), ("d1", "looks more put together"),
                                                           ("e1", "looks polished in meetings")],
                              scope_issue="age 40-50 not established; no purchase stated"))

    run([str(SCRIPTS / "validate.py"), "--project-dir", pdir])
    report = json.loads(Path(pdir, "gate_report.json").read_text())
    st = {c["claim_id"]: c for c in report["claims"]}
    expect = {
        "T1 one thread": "NEEDS_REVIEW", "T2 no audit": "NEEDS_REVIEW", "T3 fake auditor span": "NEEDS_REVIEW",
        "T4 complaints as purchase driver": "NEEDS_REVIEW", "T5 product fact from category": "NEEDS_REVIEW",
        "T6 snippet only": "NEEDS_REVIEW", "T9 clean pattern": "APPROVED", "T10 40-50 professional": "NEEDS_REVIEW",
        "T12 hypothesis": "HYPOTHESIS_LABELED", "T13 no counter-search": "NEEDS_REVIEW",
    }
    failures = 0
    for name, want in expect.items():
        got = st[C[name]]["status"]
        mark = "ok  " if got == want else "FAIL"
        failures += got != want
        print(f"{mark} {name:36s} -> {got:18s} {'; '.join(st[C[name]]['reasons'])[:110]}")

    # Brief traps
    Path(pdir, "ru.md").write_text(f"Инсайт [{C['T9 clean pattern']}] https://example.test/x\n"
                                   f"Ещё [{C['T1 one thread']}]\nГипотеза: [{C['T12 hypothesis']}]\n", encoding="utf-8")
    Path(pdir, "en.md").write_text(f"Insight [{C['T9 clean pattern']}] https://example.test/x\n"
                                   f"Also [{C['T1 one thread']}]\n[{C['T12 hypothesis']}] structure signals competence. Привет\n",
                                   encoding="utf-8")
    run([str(SCRIPTS / "validate.py"), "--project-dir", pdir, "--brief-ru", f"{pdir}/ru.md", "--brief-en", f"{pdir}/en.md"])
    issues = json.loads(Path(pdir, "gate_report.json").read_text())["brief_issues"]
    for needle, name in (("Cyrillic", "T8a EN Cyrillic"), ("cannot appear", "T8b unapproved claim in brief"),
                         ("no 'hypothes' label", "T8c unlabeled hypothesis")):
        hit = any(needle in i for i in issues)
        failures += not hit
        print(f"{'ok  ' if hit else 'FAIL'} {name}")
    print(f"\n{'ALL TRAPS CAUGHT' if not failures else f'{failures} FAILURES'}  (project: {pdir})")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
