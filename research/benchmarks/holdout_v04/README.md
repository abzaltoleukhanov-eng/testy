# Holdout v04 (ChatGPT, 20 claim cases + 6 integration probes): results on contract 0.4, rules unchanged

Run on 2026-10-17, before any expected answers were seen. The engine and the auditor prompt were locked first:
`engine_lock.json` holds the git commit and the sha256 of the contract, `audit.md`, `validate.py`, `re_lib.py`,
`render_stats.py`, `run_blind.py` and the three input files. Nothing in the engine changed between the lock and
these results.

## Claim cases (`inputs/inputs_claims.jsonl`) → `predictions_holdout04.json`
- `run_blind.py prepare --batch 5`: 20 cases, 0 literal mismatches, 4 packets (`packets/`).
- 4 fresh auditors, 5 cases each. Each read only its own packet and `auditor_prompt_used.txt`, which is the
  locked `references/audit.md` prompt plus the benchmark's output fields (same additions as holdout v03).
  Raw outputs are in `auditor_outputs/`.
- `run_blind.py finalize`, contract 0.4 mapping.
- Totals: final BLOCK 14, APPROVE_SCOPED 3 (V02, V09, V15), APPROVE_HYPOTHESIS_UNTESTED 3 (V07, V17, V19).

What the adapter cannot represent (stated, not skipped silently):
- The cases carry no `claim_class` or `premise_claim_ids`, and `run_blind.py` does not build a claim ledger.
  So the Premise Gate is tested only through the auditor's `uncovered_premises` and `link_check`, judged
  against the case sources. `hypothesis_status(a)` gets no premise statuses.
- Fact cases are gated by `gate_check` with an empty query log, so counter-search rules are not exercised.
- V17 got auditor verdict PARTIAL (its source proposes a different scene), but the hypothesis passes,
  because hypothesis framing, not source support, decides hypothesis cases. That is current contract
  behaviour, recorded as is.

## Integration probes (`inputs/integration_cases.jsonl`) → `integration_results04.json`
Runner: `skills/research-engine/tests/run_integration.py`. Each probe gets its own fresh temporary copy of
LEVANT-001; the original project is never changed. The full production validator runs on the copy:
`validate.py --project-dir COPY --brief-ru … --brief-en …`. A BASELINE run with no mutation comes first.

| Probe | Result on 0.4 |
|---|---|
| BASELINE | exit 0, C-0051 FACT_APPROVED, C-0062 HYPOTHESIS_UNTESTED, ACH-0003 VALID, 0 brief issues |
| X01 claim text replaced, old audit kept | exit 0; C-0051 still FACT_APPROVED, C-0062 still HYPOTHESIS_UNTESTED |
| X02 non-entailed line with a valid [C-0051] marker | exit 0, 0 brief issues |
| X03 unsupported line with a product URL as citation | exit 0, 0 brief issues |
| X04 ACH-0003 preference_reason replaced | exit 0, ACH-0003 still VALID |
| X05 hypothesis text replaced, old audit kept | exit 0, C-0062 still HYPOTHESIS_UNTESTED |
| X06 conclusion under an unchecked heading | exit 0, 0 brief issues |

Note on X06: the case gives the English heading for both languages; the RU brief has Russian headings, so the
runner mapped it to `## Продукт: что известно и что нет` and recorded that in `notes`.

All six probes pass the validator undetected. The three defects ChatGPT reported reproduce on the real
project: audits are not bound to claim content (X01, X05); the brief check verifies that a reference exists,
not what it supports (X02, X03, X06); ACH VALID depends only on the pattern claim (X04).

## Reproduce
```
python3 skills/research-engine/tests/run_blind.py prepare  --inputs research/benchmarks/holdout_v04/inputs/inputs_claims.jsonl --out OUT --batch 5
# auditors: one fresh agent per packet, prompt auditor_prompt_used.txt, output OUT/audit_NN.json
python3 skills/research-engine/tests/run_blind.py finalize --inputs research/benchmarks/holdout_v04/inputs/inputs_claims.jsonl --out OUT
python3 skills/research-engine/tests/run_integration.py --cases research/benchmarks/holdout_v04/inputs/integration_cases.jsonl --project research/LEVANT-001 --out integration_results04.json
```
Run the commands at the commit in `engine_lock.json`; later commits change the engine.
