# Holdout v03 (ChatGPT, 18 new cases): predictions from contract 0.3, rules unchanged

Run on 2026-10-17. No answer key was present in the archive. The pipeline is the same as for gate_v02:
- 3 fresh auditors, 6 cases each, with the unchanged `references/audit.md` prompt plus the output fields the protocol asks for;
- the validate.py gates;
- the status mapping from run_blind.py, contract 0.3.

Totals:
- final: BLOCK 10, APPROVE_SCOPED 5, APPROVE_HYPOTHESIS_UNTESTED 2, NEEDS_REVIEW 1;
- structural: PASS 17, REVIEW 1;
- evidence_sufficiency: PASS 8, FAIL 6, NOT_APPLICABLE 4;
- substantive: PASS 8, FAIL 10.

## Suspected defects, noted before scoring and not fixed
- **H18: likely a false approval.** The hypothesis "the absence of online reviews means the tote is a poor-quality product" passed as FORWARD_LOOKING_OK. The framing check looks at whether the conclusion is forward-looking, but not at the premise. The premise is a world claim ("absence of online reviews"), while the source only reports that support has not published reviews on one page. The hypothesis also makes a causal leap. Fix proposal: the auditor classifies each premise as SOURCE_REPORT, OBSERVED_STATE, WORLD_CLAIM or FUTURE_HYPOTHESIS, and a WORLD_CLAIM premise without support blocks the hypothesis.
- **H10: likely over-strict.** "In this complaint-oriented corpus, 24 of 80 comments mentioned shoulder pain; this is not a population estimate" got NEEDS_REVIEW, because the PATTERN gate requires 3 independent groups. A correctly scoped description of the corpus is a SOURCE_REPORT about our own dataset, and the contract has no claim type for it.

## Regression under contract 0.4 (same 18 cases, known after feedback; not a blind test)
Hypothesis cases were re-audited with the 0.4 prompt (`hypothesis_check`, `uncovered_premises`, `link_check`); fact cases kept their 0.3 audits. Mapping from `run_blind.py`, contract 0.4.
- **Run 2** (`predictions_holdout_contract04_draft_before_condition_fix.json`): H18 became RESEARCH_QUESTION, as intended. But H06 was over-blocked: the auditor listed the hypothesis's own explicit condition ("if … is verified") as an uncovered premise.
- **Prompt fix**: an explicit condition the text presents as still to be checked is not an uncovered premise (`references/audit.md`).
- **Run 3** (`predictions_holdout_v2_contract04.json`, auditor output `auditor_outputs/audit_hyp_contract04.json`): H06 APPROVE_HYPOTHESIS_UNTESTED, H18 RESEARCH_QUESTION, H07–H09 BLOCK; the other 13 cases are unchanged from 0.3.
- **H10** is still NEEDS_REVIEW. The case arrives as a PATTERN claim without the `corpus_stat` fields (unit, denominator queries, numerator evidence), so the new CORPUS_STATISTIC class cannot apply. With those fields the gate would compute it; see traps T21/T22 in `tests/test_gates.py`.

All of these cases were seen before the fixes, so this only shows that the fixes work on known cases. A new hidden holdout is needed to measure the false-approval rate.
