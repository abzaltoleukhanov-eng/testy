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
