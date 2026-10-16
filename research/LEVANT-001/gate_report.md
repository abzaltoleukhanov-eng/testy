# Gate report: LEVANT-001

Computed 2026-10-16T19:36:51+00:00 by validate.py (contract 0.2). Statuses here are computed, not self-declared.

**Schema errors:** 0

## Claims

| Claim | Type | Status | Why |
|---|---|---|---|
| C-0001 | PATTERN | **NEEDS_REVIEW** | no independent audit yet |
| C-0002 | PURCHASE_DRIVER | **NEEDS_REVIEW** | no independent audit yet |
| C-0003 | PATTERN | **NEEDS_REVIEW** | no independent audit yet |
| C-0004 | PATTERN | **NEEDS_REVIEW** | no independent audit yet |
| C-0005 | PATTERN | **NEEDS_REVIEW** | no independent audit yet |
| C-0006 | PATTERN | **NEEDS_REVIEW** | no independent audit yet |
| C-0007 | PATTERN | **NEEDS_REVIEW** | no independent audit yet |
| C-0008 | PURCHASE_DRIVER | **NEEDS_REVIEW** | no independent audit yet |
| C-0009 | PATTERN | **NEEDS_REVIEW** | no independent audit yet |
| C-0010 | PATTERN | **NEEDS_REVIEW** | no independent audit yet |
| C-0011 | PURCHASE_DRIVER | **NEEDS_REVIEW** | no independent audit yet |
| C-0012 | PERSONAL_EXPERIENCE | **NEEDS_REVIEW** | no independent audit yet |
| C-0013 | PATTERN | **NEEDS_REVIEW** | platforms 1 and situations 1 both < 2; no independent audit yet |
| C-0014 | PATTERN | **NEEDS_REVIEW** | platforms 1 and situations 1 both < 2; no independent audit yet |
| C-0015 | PATTERN | **NEEDS_REVIEW** | no independent audit yet |
| C-0016 | HYPOTHESIS | **HYPOTHESIS_LABELED** | all checks passed |
| C-0017 | HYPOTHESIS | **HYPOTHESIS_LABELED** | all checks passed |
| C-0018 | HYPOTHESIS | **HYPOTHESIS_LABELED** | all checks passed |
| C-0019 | HYPOTHESIS | **HYPOTHESIS_LABELED** | all checks passed |

## Coverage: COVERAGE_LIMITED
- planned source not retrievable by any tested route: official
- branches without NEUTRAL/POSITIVE queries: ['B03', 'B04', 'B05']

| Branch | Queries | Polarities | Threads read | Balanced |
|---|---|---|---|---|
| B01 | 3 | NEUTRAL | 7 | True |
| B02 | 3 | NEUTRAL | 9 | True |
| B03 | 2 | PROBLEM | 4 | False |
| B04 | 2 | SWITCH | 2 | False |
| B05 | 2 | PROBLEM, SWITCH | 2 | False |
| B06 | 2 | POSITIVE | 1 | True |
| B07 | 2 | NEUTRAL, PROBLEM | 3 | True |
| B08 | 2 | NEUTRAL | 3 | True |
| B09 | 2 | NEUTRAL, POSITIVE | 2 | True |
| B10 | 3 | NEUTRAL | 3 | True |
| B11 | 2 | NEUTRAL | 2 | True |
| B12 | 1 | NEUTRAL | 0 | True |
| B13 | 2 | NEUTRAL | 1 | True |
| B14 | 1 | NEUTRAL | 0 | True |

| Branch | Evidence | Situation clusters | Behaviour patterns | Saturation signal |
|---|---|---|---|---|
| B01 | 103 | 6 | 85 | False |
| B02 | 201 | 8 | 172 | False |
| B06 | 9 | 2 | 9 | False |
| B04 | 29 | 5 | 25 | False |
| B03 | 61 | 3 | 52 | False |
| B05 | 3 | 2 | 3 | False |
| B07 | 25 | 3 | 16 | False |
| ALL | 431 | 10 | 355 | False |

## Corpus

- sources: 2184
- threads: 39
- authors (within platform): 1516
- retrieval methods: {'RSS': 2184}
- edited since archive (SOURCE_CHANGED): 150
- evidence rows: 431
- decision evidence: 107
- queries: 29
- claim statuses: {'NEEDS_REVIEW': 15, 'HYPOTHESIS_LABELED': 4}
