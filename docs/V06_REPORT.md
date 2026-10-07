# cnmv-enforcement v0.6.0 — historical coverage report

## KPI summary (coverage-first, not row-count)

| metric | value |
|---|---|
| historical years assessed | 2000–2026 |
| years reproducibly enumerated | **2000–2026** (sumario API + dept-1040, fixed) |
| years verified (VERIFIED cohort) | **2010–2021** (H1+H2 backfill) + register 2021–2026 |
| years partial | 2000–2009 (see regime note) |
| documents accounted for | **97/97** H2 + **77/77** H1 + 204 hist + gap 6/6 |
| new defect classes discovered | +6 (D33–D43) |
| total defects registered | **43 / 43 regression-covered** (G16) |
| holdout failures | H2: **2 revealed** (D41 compound surname, D42 `de su Consejo`/`al miembro`) — fixed generically, 12/12 PASS |
| unexplained parse failures | **0** (3 `SUBSEQUENT_EVENT_DOC` corrections are classified, not failures) |
| unsupported coverage claims | 0 — pre-2010 marked `PARTIAL`/`ENUMERATED`, not `VERIFIED` |

## Coverage by cohort

| period | status | docs | how obtained |
|---|---|---|---|
| 2021-11→2026 | REGISTER | 91 | live CNMV register snapshot |
| 2021-10→11 gap | RECONCILED (no sanctions) | 6 enumerated | H0 gap enumeration |
| 2018-01→2021-10 | VERIFIED | 69+1 | H0 historical backfill |
| 2015–2017 | VERIFIED (dev) | 61 + 16 holdout | H1: 77 sanction pubs, holdout 16/16 |
| 2010–2014 | VERIFIED (dev) | 83 + 12 holdout | H2: 97 sanction pubs, holdout 12/12 |
| 2004–2009 | **GO** (feasibility proven, not yet backfilled) | 13 sample | H3 probe: same methodology works |
| 2000–2003 | **PARTIAL** (notification era) | 3 sample | BOE-B notifications carry no sanction content |

## Build (dev corpora only — holdouts excluded by design)

- cases: **304** (221 baseline + 83 h2-dev)
- respondents: **538** · case-respondents: **612**
- infringements: **549** · sanctions: **751**
- evidence: 4 482 rows — VALUE_BINDING_PROVEN 2 886 (64 %) / LOCATION_PROVEN 983 / DOCUMENT_PROVEN 613
- `rule_version_id` unresolved: 341 — honest `UNRESOLVED_RULE_VERSION` kept, not papered over
- parse_issues: **3** = legitimate `SUBSEQUENT_EVENT_DOC` corrections
- gates: **28/28** · tests: **158** · defects: **43/43** covered

## First-parse → post-fix evolution (H2 evidence)

| stage | clean | zero-block | zero-sanction | issues |
|---|---|---|---|---|
| first parse (H1 parser) | 79/85 | 4 | 1 | 1 |
| after generic fixes | **85/85** | 0 | 0 | 0 (3 = legit corrections) |

## H3 verdict — `GO_WITH_PARTIAL_COVERAGE`

- **GO: 2004–2009** — sumario enumeration, `xml.php` docs, dept-1040 and the sanction-publication titles all work identically; 13/13 sampled docs parse clean after D43
- **PARTIAL: 2000–2003** — sanction *content* largely absent; BOE-B notifications carry only existence-of-procedure (`DOCUMENT_PROVEN` ceiling)
- No production OCR was introduced

## Methodology notes

- **Holdout discipline held**: H2's 12-doc holdout caught two real defects (compound surname `y`-split; `de su Consejo`/`al miembro` variants) — both fixed generically, then permanently regression-covered
- **Sumario-shape coverage bug**: pre-2005 `item` sits directly under `departamento` (no `epigrafe`) — the enumerator silently returned 0 items for 2000–2004; fixed by covering both shapes
- All splits deterministic (`sha256(boe_id) % 5 == 0` → holdout); all manifests committed under `coverage/history/`
- Exact `Decimal` amounts preserved; every fact carries `artifact_sha256` + locator evidence
