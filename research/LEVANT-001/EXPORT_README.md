# LEVANT-001: package for independent review

Research-engine v3 pilot (contract 0.3), Siena Lévant Tote Bag, Reddit only. Snapshot of 2026-10-17.

## Files
| File | Contents |
|---|---|
| `project.json` | brief, verified and unverified product facts, open questions |
| `capabilities.json` | which routes worked from the cloud environment |
| `queries.jsonl` | search log: 29 queries with branch, reason, journey stage, scope, market, polarity, results |
| `archive/candidates.jsonl` | every thread each query returned |
| `archive/threads.jsonl` | completeness record per thread read (RSS count, archive count, edited since archive, parents missing) |
| `archive/sources.jsonl` | full text of all retrieved objects (39 Reddit threads plus user-provided screenshots and messages), with retrieval method and access status |
| `archive/user/pdp_screenshot_2026-10-17.png` | the user's product-page screenshot |
| `evidence.jsonl` | 446 evidence rows; `quote_span` is verbatim in the source text |
| `claims.jsonl` | 52 claims, including superseded revisions |
| `hypotheses.jsonl` | 2 ACH analyses |
| `audits.jsonl` | every independent audit, with located spans |
| `gate_report.json` / `gate_report.md` | statuses computed by validate.py |
| `brief_RU.md` / `brief_EN.md` | the briefs; they use only APPROVED and HYPOTHESIS_UNTESTED claims |
| `work/` | extractor brief and notes, claim batches, audit packets and raw audit outputs |

## Approved claims used in the briefs
C-0010, C-0012, C-0015, C-0020, C-0023, C-0024, C-0035, C-0036, C-0038, C-0039, C-0040, C-0045, C-0046, C-0050, C-0051, C-0052.

Hypotheses used (HYPOTHESIS_UNTESTED): C-0016, C-0017, C-0044, C-0047.

## Reproduce
Status computation: `python3 scripts/validate.py --project-dir <this folder> --brief-ru brief_RU.md --brief-en brief_EN.md`, run with the research-engine skill included in this zip.

A quote check needs nothing but `evidence.jsonl` and `archive/sources.jsonl`: `quote_span` must appear in `text` after whitespace and quote normalisation.
