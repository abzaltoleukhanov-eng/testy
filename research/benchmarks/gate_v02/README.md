# Gate benchmark v02 (ChatGPT blind set, 66 cases): engine predictions

Run on 2026-10-16 against research-engine contract 0.2, rules unchanged. The answer key was never available to the engine, the auditors or the operator.

## How each case was processed
1. **Python literal check** (`ledger.py` rule): every quote anchor must be verbatim in the stored source text.
2. **LLM auditor**: 11 fresh agents, 6 cases each. Each agent read only its own packet; prompt in `auditor_prompt.txt` plus the output fields the protocol asks for. Raw outputs are in `auditor_outputs/`.
3. **Python gate** (`validate.gate_check`, unchanged), run on usable, anchored evidence and then again on auditor-confirmed evidence.
4. **Status mapping**, fixed before scoring:
   - APPROVED or HYPOTHESIS_LABELED → APPROVE_SCOPED
   - literal mismatch, CONTRADICTED, BLOCKED type or auditor DOES_NOT_SUPPORT → BLOCK
   - everything else → NEEDS_REVIEW

`decided_by` in `predictions.json` names every component that rejected or downgraded the claim.

## Known limits of this run
- **No separate author.** The auditor's evidence labels (product match, action, evidence kind) stood in for the author's labels.
- **No counter-search in the benchmark inputs.** Every PATTERN, PURCHASE_DRIVER and PRODUCT_PERFORMANCE claim therefore fails the counter-search part of the structural gate. This is how the engine behaves, but part of it comes from the benchmark format.
- **Defect visible before scoring: 5 cases.** In G14, G20, G22, G26 and G40 the final verdict is APPROVE_SCOPED although the auditor said DOES_NOT_SUPPORT. The engine passes HYPOTHESIS and SITUATION_REACH claims on their label alone, so a hypothesis label can launder a factual assertion. Under the protocol this is not fixed before scoring.

Totals: final BLOCK 49, NEEDS_REVIEW 5, APPROVE_SCOPED 12.
