#!/usr/bin/env python3
"""Add records to the research ledger with immediate checks.

  python3 ledger.py --project-dir D add evidence '{"source_id": "RD-abc", "quote_span": "...", ...}'
  python3 ledger.py --project-dir D add claims @claims_batch.json      (a JSON object or a list)

  python3 ledger.py --project-dir D add audits @audits.json --packet packet.json
  python3 ledger.py --project-dir D add brief_audits @brief_audits.json --packet brief_packet.json

IDs are assigned automatically (E-0001, C-0001, ACH-0001, A-0001, AA-0001, BA-0001) unless given.
Insert-time checks: required fields, enum values, referenced ids exist, quote_span is verbatim in the source text.
Audits are bound to content (contract 0.5): --packet copies claim_hash / ach_hash / line_hash from the packet the
auditor read, and an audit whose hash is not the current content hash is rejected (the claim changed after the
packet was built: rebuild the packet and audit again).
A record that fails is not written. Statuses are never written here: validate.py computes them.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from re_lib import ContentHasher, append_jsonl, load_contract, next_id, now_iso, read_jsonl, span_in, table_path  # noqa: E402

PREFIX = {"evidence": "E-", "claims": "C-", "hypotheses": "ACH-", "audits": "A-", "ach_audits": "AA-",
          "brief_audits": "BA-"}
AUDIT_TABLES = ("audits", "ach_audits", "brief_audits")
FORBIDDEN = {"status", "claim_status", "gate_status", "approved"}
ALLOW_EMPTY = {"scope_issue", "issue", "issues"}  # empty means the auditor found none


_INDEX = {}


def _index(project_dir, table, contract):
    """{key: row} for a table, cached until the file changes (validate.py re-checks every row)."""
    path = table_path(project_dir, table, contract)
    st = path.stat() if path.exists() else None
    k = (str(path), st and st.st_mtime_ns, st and st.st_size)
    if k not in _INDEX:
        key = contract["tables"][table]["key"]
        _INDEX[k] = {r[key]: r for r in read_jsonl(path)}
    return _INDEX[k]


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

    sources = _index(project_dir, "sources", contract)
    evidence = _index(project_dir, "evidence", contract)
    claims = _index(project_dir, "claims", contract)
    queries = set(_index(project_dir, "queries", contract))

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
        hyp_classes = contract.get("class_rules", {}).get("hypothesis_classes", [])
        if (rec.get("claim_type") == "HYPOTHESIS" or rec.get("claim_class") in hyp_classes) and not rec.get("hypothesis_label"):
            errs.append("hypothesis claims (type HYPOTHESIS or a hypothesis class) need hypothesis_label")
        for pid in rec.get("premise_claim_ids") or []:
            if pid not in claims:
                errs.append(f"premise_claim_ids: {pid} not in claims (add the premise as its own claim first)")
        if rec.get("claim_class") == "CORPUS_STATISTIC":
            spec = rec.get("corpus_stat") or {}
            for f in ("unit", "denominator_query_ids", "numerator_evidence_ids"):
                if not spec.get(f):
                    errs.append(f"CORPUS_STATISTIC needs corpus_stat.{f}")
            for qid in spec.get("denominator_query_ids") or []:
                if qid not in queries:
                    errs.append(f"corpus_stat.denominator_query_ids: {qid} not in queries")
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
    if table == "ach_audits":
        hyps = _index(project_dir, "hypotheses", contract)
        if rec.get("ach_id") not in hyps:
            errs.append(f"ach_id {rec.get('ach_id')} not in hypotheses")
        for ch in rec.get("evidence_checks") or []:
            missing = [f for f in spec["evidence_check_fields"] if f not in ch]
            if missing:
                errs.append(f"evidence_check missing {missing}")
            ev = evidence.get(ch.get("evidence_id"))
            if not ev:
                errs.append(f"evidence_check: {ch.get('evidence_id')} not in evidence")
            elif ch.get("holds") and not span_in(ch.get("located_span", ""), sources.get(ev["source_id"], {}).get("text", "")):
                errs.append(f"evidence_check {ch.get('evidence_id')}: located_span is not verbatim in the source")
    if table == "brief_audits":
        if rec.get("lang") not in ("RU", "EN"):
            errs.append("lang must be RU or EN")
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


def bind_audit(table, rec, packet, hasher, have_packet):
    """Copy the packet's content hash into an audit record and refuse an audit made for older content."""
    errs = []
    if table == "audits":
        it = packet.get(("claim_id", rec.get("claim_id")))
        if it and "claim_hash" not in rec:
            rec["claim_hash"] = it.get("claim_hash")
        cur = hasher.claim(rec.get("claim_id"))
        if rec.get("claim_hash") and rec["claim_hash"] != cur:
            errs.append(f"claim_hash {rec['claim_hash']} is not the current content of {rec.get('claim_id')} ({cur}): "
                        "the claim, its evidence or a premise changed after the packet was built; audit again")
    elif table == "ach_audits":
        it = packet.get(("ach_id", rec.get("ach_id")))
        if it and "ach_hash" not in rec:
            rec["ach_hash"] = it.get("ach_hash")
        cur = hasher.ach(rec.get("ach_id"))
        if rec.get("ach_hash") and rec["ach_hash"] != cur:
            errs.append(f"ach_hash {rec['ach_hash']} is not the current content of {rec.get('ach_id')} ({cur}); audit again")
    elif table == "brief_audits":
        it = packet.get(("line_hash", rec.get("line_hash")))
        if have_packet and not it:
            errs.append(f"line_hash {rec.get('line_hash')} is not in the packet")
        elif it:
            for k in ("lang", "line", "section"):
                rec.setdefault(k, it.get(k))
    return errs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-dir", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("table", choices=list(PREFIX))
    p.add_argument("payload", help="JSON object/list, or @file.json")
    p.add_argument("--dry-run", action="store_true", help="check records, write nothing (for parallel authors)")
    p.add_argument("--packet", help="audit tables: the packet the auditor read; its content hashes are copied")
    args = ap.parse_args()

    contract = load_contract()
    raw = Path(args.payload[1:]).read_text(encoding="utf-8") if args.payload.startswith("@") else args.payload
    data = json.loads(raw)
    records = data if isinstance(data, list) else [data]
    path = table_path(args.project_dir, args.table, contract)
    key = contract["tables"][args.table]["key"]
    project_id = json.loads((Path(args.project_dir) / "project.json").read_text())["project_id"]

    packet = {}
    if args.packet:
        pk = json.loads(Path(args.packet).read_text(encoding="utf-8"))
        items = pk.get("lines", []) if isinstance(pk, dict) else pk
        for it in items:
            for k in ("claim_id", "ach_id", "line_hash"):
                if it.get(k):
                    packet[(k, it[k])] = it
    hasher = ContentHasher({n: read_jsonl(table_path(args.project_dir, n, contract))
                            for n in ("claims", "evidence", "sources", "hypotheses")}) if args.table in AUDIT_TABLES else None

    written, failed = 0, 0
    for rec in records:
        rows = read_jsonl(path)
        bind_errs = bind_audit(args.table, rec, packet, hasher, bool(args.packet))
        if args.dry_run:
            rec = dict(rec)
            rec.setdefault(key, "DRY-" + str(written + failed + 1))
        rec.setdefault(key, next_id(rows, key, PREFIX[args.table]))
        if args.table not in AUDIT_TABLES:
            rec.setdefault("project_id", project_id)
        else:
            rec.setdefault("audited_at", now_iso())
        if any(r[key] == rec[key] for r in rows):
            print(f"FAIL {rec[key]}: duplicate id")
            failed += 1
            continue
        errs = bind_errs + check_record(args.table, rec, contract, args.project_dir)
        if errs:
            failed += 1
            print(f"FAIL {rec[key]}:")
            for e in errs:
                print(f"   - {e}")
            continue
        if not args.dry_run:
            append_jsonl(path, [rec])
        written += 1
        print(f"OK   {rec[key]}")
    print(f"{written} {'would be written (dry run)' if args.dry_run else 'written'}, {failed} rejected")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
