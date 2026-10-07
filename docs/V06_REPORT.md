# cnmv-enforcement v0.6.0 — historical coverage report

## KPI summary (coverage-first, not row-count)

| metric | value |
|---|---|
| historical years assessed | 2000–2026 |
| years reproducibly enumerated | **2000–2026** (sumario API + dept-1040, shape fix) |
| years VERIFIED (dev cohorts) | **2004–2021** (H1/H2/H4) + register 2021–2026 |
| years PARTIAL | 2000–2003 (notification era, no sanction content) |
| documents accounted for | 58/58 H4 + 97/97 H2 + 77/77 H1 + 204 hist + gap 6/6 |
| new defect classes discovered | +8 (D33–D45, incl. sumario-shape, lettered items) |
| total defects registered | **45 / 45 regression-covered** |
| holdout failures | H2: 2 revealed (D41/D42, fixed). H4: 0 (14/14 PASS) |
| unexplained parse failures | **0** (3 SUBSEQUENT_EVENT_DOC = classified corrections) |
| unsupported coverage claims | 0 — pre-2004 kept PARTIAL/ENUMERATED |

## Reconciliation v0.5 → v0.6 (per source surface)

| cohort | docs | cases | sanctions | infringements |
|---|---:|---:|---:|---:|
| register snapshot 2021–2026 (v0.5) | 91 | 91 | 238 | 156 |
| historical backfill 2018–2021 (v0.5) | 69 | 69 | 147 | 105 |
| + h1 dev 2015–2017 | 61 | +61 | +132 | +113 |
| + h2 dev 2010–2014 | 83 | +83 | +234 | +175 |
| + h4 dev 2004–2009 | 44 | +44 | +76 | +71 |
| **v0.6 total (dev corpora)** | **348** | **348** | **827** | **620** |

**v0.5 base**: 221 cases / 517 sanctions / 376 infringements / 367 respondents.
**v0.6 delta**: +127 cases / +310 sanctions / +244 infringements / +232 respondents — ALL new historical coverage; corrections to previously published facts are documented per-defect (BOE-A-2022-10033 Arturo Sotillo third infringement recovered; BOE-A-2021-18970 article now `92.d` — letter extracted).

## Coverage by period (per-surface)

| period | status | methodology |
|---|---|---|
| 2021-11→2026 | REGISTER | rolling CNMV sanctions register |
| 2021-10→11 gap | RECONCILED (0 sanctions) | H0 gap enumeration |
| 2018-01→2021-10 | VERIFIED | historical backfill (v0.5) |
| 2015–2017 | VERIFIED-dev + holdout 16/16 | H1: 77 pubs, D23–D32 |
| 2010–2014 | VERIFIED-dev + holdout 12/12 | H2: 97 pubs, D33–D42 |
| 2004–2009 | VERIFIED-dev + holdout 14/14 | H4: 58 pubs, D44–D45 |
| 2004–2009 remainder | same methodology, assessed | H3 probe |
| 2000–2003 | PARTIAL — notification era | BOE-B service-of-process only; DOCUMENT_PROVEN ceiling |

## Build (dev corpora — holdouts excluded)

- cases: **348** · respondents: **599** · case-respondents: 677
- infringements: **620** · sanctions: **827** · evidence: 4 978
- VALUE_BINDING_PROVEN 3 187 (64 %) / LOCATION_PROVEN 1 107 / DOCUMENT_PROVEN 684 — honest decline with era, not forced
- `rule_version_id` unresolved: 412 — UNRESOLVED_RULE_VERSION kept honest
- gates: **29/29** · tests: **160** · defects: **45/45** covered

## First-parse → post-fix evolution

| cohort | clean first-pass | after generic fixes | holdout |
|---|---|---|---|
| H1 2015–17 | 32/61 | 61/61 | 16/16 (D31 found) |
| H2 2010–14 | 79/85 | 85/85 | 12/12 (D41/D42 found) |
| H4 2004–09 | 40/44 | 44/44 | 14/14 (0 found) |

## Test-suite split (release verification)

| suite | scope | clean-checkout |
|---|---|---|
| offline deterministic | 160 tests — goldens, defect registry, known_at unit, gates | all pass |
| `test_known_at_api.py` (8 tests) | API-level AS_KNown_AT on the register corpus (gitignored, released as asset) | conditional-skip when `data/corpus/` absent — semantics duplicated by `test_known_at.py` unit tests which DO run offline |

## H3 verdict — `GO_WITH_PARTIAL_COVERAGE` → H4 executed

- **GO executed: 2004–2009** — verified via H4 (this report)
- **PARTIAL: 2000–2003** — BOE-B notification era; content coverage impossible at this standard; no OCR
- sumario-shape coverage bug (pre-2005 `departamento→item`) fixed + G30-gated

## v0.6.0 close criteria

```text
[x] 2004–2009 fully enumerated (2,192 days, 0 missing)
[x] identifier manifests frozen + committed
[x] all discovered documents accounted for
[x] zero unexplained retrieval/parse/reconciliation failures
[x] new defect classes regression-covered (44/44→45/45)
[x] fresh year-stratified holdout PASS 14/14
[x] monetary exactness PASS (G6 + G26)
[x] legal-reference integrity PASS (G5 + article/statute gates)
[x] evidence integrity PASS (G29)
[x] coverage claims PASS (G28)
[x] clean-checkout deterministic suite PASS (160)
[x] coverage_matrix.json updated
[x] docs/coverage/2004-2009.md generated
[x] docs/V06_REPORT.md updated
```
