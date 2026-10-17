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
