# Brief-line holdout v05 (ChatGPT, 24 synthetic lines): predictions on the frozen contract 0.5 brief auditor

Run on 2026-10-17, before any answer key was seen and before any change to code or prompt.
- `engine_lock.json`: git commit, sha256 of the brief-audit prompt block in `references/audit.md` and of the
  engine files, sha256 of the four input packets.
- `auditor_prompt_used.txt`: the brief-audit prompt from `references/audit.md`, unchanged, plus the
  benchmark's output fields (`test_id`, `relied_on_ids`, `explanation`).
- 4 fresh auditors, one packet each (6 lines). Each read only its own packet and the prompt. Raw outputs are in
  `auditor_outputs/`.
- `brief_holdout_predictions.json`: one entry per test_id, assembled from the raw outputs without editing.

Totals: ENTAILED 9, NOT_SUPPORTED 8, OVERSTATES 6, LIMITATION_OK 1.
None of these lines was inserted into the LEVANT-001 brief.

## After the predictions: ChatGPT defects A and B, contract 0.6 (not blind)
Added after the predictions above were committed (commit 655bd73); they stay as submitted.
- `integration_cases_v05.jsonl`: Claude's reproductions of both defects. X07 replaces the document title (`#`) with
  an unsupported promise. Replacing every `##` heading would also delete the Sources heading and trip unrelated
  checks, so it would not isolate the defect. X08 marks RD-1wwpn82 (cited by approved C-0020) as
  `commercial_disclosure: PAID_BRAND_PARTNERSHIP` without changing its text.
- `integration_results_v05_before_fix.json`: on 0.5 both exit 0 with 0 brief issues, so both defects reproduce.
- Fix (contract 0.6):
  - headings and table header rows are audited lines; HTML comments other than the STATS markers are rejected;
  - every source field except `source_hash_volatile_fields` (`retrieved_at`, `query_id`, `score`, plus text and
    ids, which are hashed separately) is part of the content hash. This is an exclusion list, so a new
    provenance field is covered the moment it appears.
- Migration (`scripts/migrate_06.py`): an audit was re-bound only if its 0.5 hash matched the current content and no
  source it depends on changed provenance in any committed version of `archive/sources.jsonl`. One source did
  change (RD-1wm0tkm, READ_FULL to READ_PARTIAL, the earlier title-only fix); nothing cites it. Results: 62/62 claim
  audits, 5/5 ACH audits and 224 brief audits re-bound; 32 old brief audits belong to lines rewritten since.
  The 22 heading and table-header lines got their first audit: all LIMITATION_OK.
- `integration_results_v06_regression.json`: X01–X08 plus X04b. Every probe fails the export except X04, where the
  edited ACH-0003 stays ACH_REJECTED and the brief does not cite it. Traps T33 (heading), T34 (provenance) and T35
  (HTML comment) were added; 44 checks pass.
