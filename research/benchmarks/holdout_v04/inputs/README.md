# Creative Research Gate Contract 0.4 — independent holdout v04

This is a synthetic, deliberately unseen test set. No expected answers are included.

- `inputs_claims.jsonl`: 20 individual claim cases, using the same `test_id/sources/claim` shape as the existing `run_blind.py` benchmark. These cases test semantic claims, hidden premises, causal leaps and correctly limited hypotheses.
- `integration_cases.jsonl`: 6 separate black-box mutation probes against a TEMP COPY of the supplied LEVANT-001 project. Do NOT modify the working/original project. These probes test the actual production `validate.py` and brief/ACH integration.

## Protocol
1. Lock the engine and audit prompt version before running.
2. For `inputs_claims.jsonl`, give auditors the cases without any answer key, run exactly the current prompt, then return `predictions_holdout04.json` with literal, structural, evidence sufficiency, substantive, engine status, final, and rationale. Track which tests your current `run_blind.py` can and cannot represent; do not silently skip unsupported contract fields.
3. For `integration_cases.jsonl`, apply each mutation independently to a clean temporary copy of LEVANT-001, run the full real project validator, and return `integration_results04.json` with status, exit code, error messages and observed behavior. Never change the gold project in place.
4. Return the two prediction files and a reproducibility log *before* seeing the expected decisions. Preserve the originally submitted predictions.

The integration cases intentionally demand a real project validator, NOT the current lightweight blind adapter, which does not transmit `premise_claim_ids` or `claim_class` into the full claim ledger.
These synthetic comments, products and results are fabricated test fixtures, NOT consumer research evidence.
