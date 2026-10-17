#!/usr/bin/env python3
"""Black-box mutation probes against a real project, run through the production validate.py.

  python3 run_integration.py --cases integration_cases.jsonl --project research/LEVANT-001 --out results.json

Each case is applied to its own fresh temporary copy of the project; the original is never touched.
The full validator runs exactly as an operator would run it before export:
  validate.py --project-dir COPY --brief-ru brief_RU.md --brief-en brief_EN.md
Reported per case: exit code, claim / ACH statuses asked for, brief issues and the validator's last lines.
Supported operations: replace_claim_text, replace_hypothesis_text, replace_ach_preference_reason,
insert_line_under_summary_both_languages, insert_line_under_unchecked_heading_both_languages,
replace_headings_both_languages, set_source_field.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VALIDATE = ROOT / "scripts" / "validate.py"
SUMMARY_HEADING = {"RU": "## Главное за 30 секунд", "EN": "## The main points in 30 seconds"}
# brief headings are written per language; an English heading given for RU is mapped to its RU twin
HEADING_TWINS = {"## The product: what is known and what is not": "## Продукт: что известно и что нет"}


def rewrite_jsonl(path, key, rid, field, value):
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    hit = [r for r in rows if r.get(key) == rid]
    if not hit:
        raise ValueError(f"{rid} not found in {path.name}")
    for r in hit:
        r[field] = value
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def insert_after_heading(path, heading, line):
    lines = path.read_text(encoding="utf-8").split("\n")
    idx = next((i for i, l in enumerate(lines) if l.strip() == heading.strip()), None)
    if idx is None:
        raise ValueError(f"heading {heading!r} not in {path.name}")
    lines[idx + 1:idx + 1] = ["", line]
    path.write_text("\n".join(lines), encoding="utf-8")


def apply(mut, pdir, notes):
    op = mut["operation"]
    if op == "none":
        return
    if op in ("replace_claim_text", "replace_hypothesis_text"):
        rewrite_jsonl(pdir / "claims.jsonl", "claim_id", mut["claim_id"], "text", mut["new_text"])
    elif op == "replace_ach_preference_reason":
        rewrite_jsonl(pdir / "hypotheses.jsonl", "ach_id", mut["ach_id"], "preference_reason", mut["new_text"])
    elif op == "insert_line_under_summary_both_languages":
        for lang in ("RU", "EN"):
            insert_after_heading(pdir / f"brief_{lang}.md", SUMMARY_HEADING[lang], mut[lang.lower()])
    elif op == "insert_line_under_unchecked_heading_both_languages":
        for lang in ("RU", "EN"):
            h = mut[f"{lang.lower()}_heading"]
            if lang == "RU" and h in HEADING_TWINS:
                notes.append(f"RU heading {h!r} mapped to {HEADING_TWINS[h]!r} (the RU brief has Russian headings)")
                h = HEADING_TWINS[h]
            insert_after_heading(pdir / f"brief_{lang}.md", h, mut[lang.lower()])
    elif op == "replace_headings_both_languages":
        for lang in ("RU", "EN"):
            path = pdir / f"brief_{lang}.md"
            lines = path.read_text(encoding="utf-8").split("\n")
            n = 0
            for i, l in enumerate(lines):
                if l.startswith(mut.get("level", "## ")):
                    lines[i] = mut.get("level", "## ") + mut[lang.lower()]
                    n += 1
            if not n:
                raise ValueError(f"no headings in {path.name}")
            notes.append(f"{lang}: {n} headings replaced")
            path.write_text("\n".join(lines), encoding="utf-8")
    elif op == "set_source_field":
        rewrite_jsonl(pdir / "archive" / "sources.jsonl", "source_id", mut["source_id"], mut["field"], mut["value"])
    else:
        raise ValueError(f"unsupported operation {op}")


def run_case(case, project):
    notes = []
    with tempfile.TemporaryDirectory() as tmp:
        pdir = Path(tmp) / project.name
        shutil.copytree(project, pdir, ignore=shutil.ignore_patterns("raw"))
        try:
            apply(case["mutation"], pdir, notes)
        except ValueError as e:
            return {"test_id": case["test_id"], "applied": False, "error": str(e)}
        p = subprocess.run([sys.executable, str(VALIDATE), "--project-dir", str(pdir),
                            "--brief-ru", str(pdir / "brief_RU.md"), "--brief-en", str(pdir / "brief_EN.md")],
                           capture_output=True, text=True)
        report = json.loads((pdir / "gate_report.json").read_text())
        status = {c["claim_id"]: c["status"] for c in report["claims"]}
        out = {"test_id": case["test_id"], "applied": True, "validator_exit": p.returncode,
               "brief_issues": report.get("brief_issues", []),
               "summary_line": (p.stdout.strip().splitlines() or [""])[-1], "notes": notes}
        for req in case.get("requested_outputs", []):
            kind, _, rid = req.partition(":")
            if kind == "claim_status":
                out[req] = status.get(rid)
            elif kind == "ach_status":
                out[req] = (report.get("ach") or {}).get(rid, {}).get("status")
        if p.returncode and p.stderr:
            out["stderr_tail"] = p.stderr.strip().splitlines()[-5:]
        return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    project = Path(args.project).resolve()
    cases = [json.loads(l) for l in Path(args.cases).read_text(encoding="utf-8").splitlines() if l.strip()]
    baseline = {"test_id": "BASELINE", "mutation": {"operation": "none"},
                "requested_outputs": sorted({r for c in cases for r in c.get("requested_outputs", []) if ":" in r})}
    results = [run_case(c, project) for c in [baseline] + cases]
    Path(args.out).write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    for r in results:
        print(r["test_id"], {k: v for k, v in r.items() if k not in ("test_id", "notes", "brief_issues")})


if __name__ == "__main__":
    main()
