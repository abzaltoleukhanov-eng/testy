# Blind brief-level semantic audit — contract 0.5

Contains 24 **synthetic new brief lines** written against the real, audited LEVANT-001 claim/ACH records. No answer key is included.

## Protocol

1. Freeze contract 0.5 auditor prompt before running. **Do not modify rules based on case content before reporting baseline.**
2. Send `brief_packet_blind_01.json` through `brief_packet_blind_04.json` to the existing semantic brief auditor in four isolated batches. Use `lines[]`, `records{}` like normal `brief_packet.py` output. Do not give the auditor the project reasoning or a gold key.
3. For every `test_id`, return `line_hash`, `verdict` (ENTAILED / LIMITATION_OK / OVERSTATES / NOT_SUPPORTED), `issue`, the IDs actually relied on and a brief explanation of the entailment or overreach.
4. Save a **single `brief_holdout_predictions.json`** keyed by test ID and send it back unchanged for scoring. Judge only content with available records, not assumptions about real customers.
5. Do not insert any of these synthetic lines into the real LEVANT brief.

This test measures substantive inference, not the production validator's handling of missing audits. Once results are scored, we can run separate integration mutations of title/heading and changed source metadata on disposable copies of the project. The benchmark author keeps the answer key private.
