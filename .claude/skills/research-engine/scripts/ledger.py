#!/usr/bin/env python3
"""Add records to the research ledger with immediate checks.

  python3 ledger.py --project-dir D add evidence '{"source_id": "RD-abc", "quote_span": "...", ...}'
  python3 ledger.py --project-dir D add claims @claims_batch.json      (a JSON object or a list)

IDs are assigned automatically (E-0001, C-0001, ACH-0001, A-0001) unless given.
Insert-time checks: required fields, enum values, referenced ids exist, quote_span is verbatim in the source text.
A record that fails is not written. Statuses are never written here: validate.py computes them.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from re_lib import append_jsonl, load_contract, next_id, now_iso, read_jsonl, span_in, table_path  # noqa: E402

PREFIX = {"evidence": "E-", "claims": "C-", "hypotheses": "ACH-", "audits": "A-"}
FORBIDDEN = {"status", "claim_status", "gate_status", "approved"}
ALLOW_EMPTY = {"scope_issue"}  # an empty scope_issue means the auditor found none


def check_record(table, rec, contract, project_dir):
    spec = contract["tables"][table]
    enums = contract["enums"]
    errs = []
    if FORBIDDEN & set(rec):
        errs.append(f"status fields are computed by validate.py, remove: {sorted(FORBIDDEN & set(rec))}")
    allowed = set(spec["required"]) | set(spec.get("optional", []))
    extra = set(rec) - allowed
    if extra:
        errs.append(f"unknown fields: {sorted(extra)}")
    for f in spec["required"]:
        if f not in rec or rec[f] is None or (rec[f] == "" and f not in ALLOW_EMPTY):
            errs.append(f"missing required field: {f}")
    for field, enum_name in spec.get("enum_fields", {}).items():
        v = rec.get(field)
        if v is not None and v not in enums[enum_name] and v not in spec.get("enum_allow_any", []):
            errs.append(f"{field}={v!r} not in {enum_name}")

    sources = {r["source_id"]: r for r in read_jsonl(table_path(project_dir, "sources", contract))}
    evidence = {r["evidence_id"]: r for r in read_jsonl(table_path(project_dir, "evidence", contract))}
    claims = {r["claim_id"]: r for r in read_jsonl(table_path(project_dir, "claims", contract))}
    queries = {r["query_id"] for r in read_jsonl(table_path(project_dir, "queries", contract))}

    if table == "evidence":
        src = sources.get(rec.get("source_id"))
        if not src:
            errs.append(f"source_id {rec.get('source_id')} not in archive")
        elif not span_in(rec.get("quote_span", ""), src["text"]):
            errs.append("quote_span is not verbatim in the stored source text")
        if rec.get("evidence_kind") == "DECISION":
            d = rec.get("decision") or {}
            missing = [f for f in spec["decision_fields"] if f not in d]
            if missing:
                errs.append(f"DECISION evidence needs decision.{missing}")
            if d.get("reason_basis") not in (None, *enums["reason_basis"]):
                errs.append("decision.reason_basis must be EXPLICIT or INFERRED")
    if table == "claims":
        for k in ("supporting_evidence_ids", "contradicting_evidence_ids"):
            for eid in rec.get(k, []):
                if eid not in evidence:
                    errs.append(f"{k}: {eid} not in evidence")
        for qid in rec.get("counter_search_query_ids", []):
            if qid not in queries:
                errs.append(f"counter_search_query_ids: {qid} not in queries")
        if rec.get("claim_type") == "HYPOTHESIS" and not rec.get("hypothesis_label"):
            errs.append("HYPOTHESIS claims need hypothesis_label")
        if not isinstance(rec.get("critical"), bool):
            errs.append("critical must be true or false")
    if table == "hypotheses":
        if rec.get("pattern_claim_id") not in claims:
            errs.append(f"pattern_claim_id {rec.get('pattern_claim_id')} not in claims")
        hs = rec.get("hypotheses") or []
        if len(hs) < 2:
            errs.append("ACH needs at least two competing hypotheses")
        for h in hs:
            missing = [f for f in spec["hypothesis_fields"] if f not in h]
            if missing:
                errs.append(f"hypothesis {h.get('h_id')} missing {missing}")
            if h.get("diagnosticity") not in enums["diagnosticity"]:
                errs.append(f"hypothesis {h.get('h_id')} diagnosticity must be HIGH/MEDIUM/LOW")
            for eid in h.get("supporting_ids", []) + h.get("refuting_ids", []):
                if eid not in evidence:
                    errs.append(f"hypothesis {h.get('h_id')}: {eid} not in evidence")
        if rec.get("causal_status") != "NOT_ESTABLISHED":
            errs.append("causal_status must be NOT_ESTABLISHED: ACH ranks explanations, it does not prove purchase causality")
    if table == "audits":
        if rec.get("claim_id") not in claims:
            errs.append(f"claim_id {rec.get('claim_id')} not in claims")
        for ch in rec.get("evidence_checks") or []:
            missing = [f for f in spec["evidence_check_fields"] if f not in ch]
            if missing:
                errs.append(f"evidence_check missing {missing}")
            if ch.get("evidence_id") not in evidence:
                errs.append(f"evidence_check: {ch.get('evidence_id')} not in evidence")
    return errs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-dir", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("table", choices=list(PREFIX))
    p.add_argument("payload", help="JSON object/list, or @file.json")
    args = ap.parse_args()

    contract = load_contract()
    raw = Path(args.payload[1:]).read_text(encoding="utf-8") if args.payload.startswith("@") else args.payload
    data = json.loads(raw)
    records = data if isinstance(data, list) else [data]
    path = table_path(args.project_dir, args.table, contract)
    key = contract["tables"][args.table]["key"]
    project_id = json.loads((Path(args.project_dir) / "project.json").read_text())["project_id"]

    written, failed = 0, 0
    for rec in records:
        rows = read_jsonl(path)
        rec.setdefault(key, next_id(rows, key, PREFIX[args.table]))
        if args.table != "audits":
            rec.setdefault("project_id", project_id)
        if args.table == "audits":
            rec.setdefault("audited_at", now_iso())
        if any(r[key] == rec[key] for r in rows):
            print(f"FAIL {rec[key]}: duplicate id")
            failed += 1
            continue
        errs = check_record(args.table, rec, contract, args.project_dir)
        if errs:
            failed += 1
            print(f"FAIL {rec[key]}:")
            for e in errs:
                print(f"   - {e}")
            continue
        append_jsonl(path, [rec])
        written += 1
        print(f"OK   {rec[key]}")
    print(f"{written} written, {failed} rejected")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
