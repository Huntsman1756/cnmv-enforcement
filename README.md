# cnmv-enforcement

The CNMV publishes enforcement information across a rolling public sanctions
register, BOE publication resolutions and subsequent official documents.
`cnmv-enforcement` reconstructs those **publicly observable** sources into an
auditable case-level ledger of respondents, infringements, sanctions, legal
bases and later events, with explicit provenance and coverage limitations.

> An evidence-backed historical ledger of publicly observable CNMV
> enforcement, reconstructed from the CNMV public sanctions register, BOE
> publications and subsequent official documents.

## What it is not

- **Not a complete database of all CNMV sanctions.** Coverage is the
  publicly observable surface only. Absence from this dataset does not
  establish that no sanction was imposed.
- Not an official register. Official records remain the authoritative source.
- Not legal advice.

## Current coverage

| Layer | Counts |
|---|---|
| Register-linked cases (live snapshot) | 91 |
| Infringements | 155 |
| Sanctions | 237 |
| Respondents | 177 |
| CNMV-PDF status observations | 88 PDFs — 14 judicial appeals observed, 22 firm-stated |

The register retains entries for five years; the live snapshot is a
point-in-time observation, not a historical archive. Historical backfill is
a separate, explicitly-versioned corpus (`data/corpus_historical`), built by
`enumerate-history` + `backfill-fetch` over BOE Sección III dept 1040.

## Pipeline

```
register (CNMV) ──► resolve ──► sumario (BOE) ──► XML corpus ──► parse ──► assemble
     │                                                                 │
     └──► verdocumento PDFs ──► status notes ──► firmness projections   ▼
                                                       case_status + status_notes + events ──► parquet ──► duckdb ──► API ──► web
```

- **Sources**: `sources/cnmv/register.py`, `sources/boe/sumario.py`,
  `sources/boe/resolve.py`, `sources/boe/historical.py` — all fetches go
  through a paced HTTP client and land in the immutable raw store
  (`acquisition/rawstore.py`, sha256 + manifest).
- **Parser**: `parsing/boe_publication.py` — deterministic, grammar-variant
  BOE publication parser (Unicode bullets, multi-subject/multi-sanction
  clauses, lettered/numbered forms, `cada uno` expansions, typos in source).
  An unhandled bullet line never drops silently: it surfaces as a
  `parse_issues` row and fails release gates.
- **Legal**: `normalize/legal.py`, `legal/rules.py` — statute/article
  normalization + temporal rule-version resolution
  (`VALID_FOR_CONDUCT` / `UNRESOLVED_RULE_VERSION` / `NO_RULE_DEFINED`).
- **Assembly**: `parsing/assemble.py` — parsed blocks → domain model with
  per-field evidence records.
- **Status**: `parsing/cnmv_pdf.py`, `projections/state.py` — CNMV-PDF
  marginal-note extraction (renunciation, finality, appeal, judgment) and
  per-case observed-state projection.
- **Outputs**: 12-table Parquet export + DuckDB + `coverage.json`.

## CLI

```bash
cnmv-enforcement probe          # live source structure check
cnmv-enforcement enumerate      # register → BOE-id resolution report
cnmv-enforcement fetch          # fetch corpus XMLs → data/corpus
cnmv-enforcement pdf-status     # CNMV PDF status-note observations
cnmv-enforcement enumerate-history 2018-01-01 2021-12-31
cnmv-enforcement backfill-fetch # XMLs for sanction-like history items
cnmv-enforcement parse          # parse corpus, per-document summary
cnmv-enforcement build          # corpus → parquet + duckdb + coverage.json
cnmv-enforcement validate       # release gates (fail loudly)
cnmv-enforcement coverage       # latest coverage ledger
cnmv-enforcement stats          # corpus stats from duckdb
cnmv-enforcement case <id>      # case detail
cnmv-enforcement respondent <q> # respondent lookup
cnmv-enforcement article <statute> <art>
cnmv-enforcement export --table sanctions --fmt csv
```

## API & frontend

```bash
uvicorn cnmv_enforcement.api.app:app --port 8765
cd web && npm ci && npm run dev   # http://localhost:5174
```

Endpoints: `/coverage`, `/stats`, `/cases`, `/cases/{id}`, `/respondents`,
`/respondents/{id}`, `/laws`, `/laws/{statute}/articles/{article}`, `/status`.

## Domain invariants

These distinctions are enforced in code, tests and outputs:

```
FACT ≠ INFERENCE          OBSERVED ≠ TRUE FOR ALL TIME
PUBLICLY OBSERVABLE ≠ ALL CNMV ENFORCEMENT
REGISTER ABSENCE ≠ NO SANCTION
REMOVED FROM REGISTER ≠ LEGALLY ERASED
BOE PUBLICATION RESOLUTION ≠ FULL SANCTIONING DECISION
PUBLICATION DATE ≠ OFFENCE DATE
RESOLUTION DATE ≠ OFFENCE DATE
CURRENT LAW ≠ LAW APPLICABLE TO HISTORICAL CONDUCT
NO APPEAL OBSERVED ≠ NO APPEAL
```

Respondents are reproduced only as the official source names them
(`publication_policy`: `SOURCE_NAMED` / `SOURCE_ANONYMIZED`) — no
enrichment, no reidentification. Later identity links to regulatory
registries are only accepted via strong-identifier evidence.

## Testing

```bash
uv run pytest        # 100 tests incl. 91-document golden corpus
uv run ruff check .
uv run mypy src
cnmv-enforcement validate   # release gates over data/corpus
```

The golden corpus (`tests/fixtures/corpus`, `tests/golden/`) freezes all
91 register-linked publications with per-document expectations —
stratified across every observed grammar variant. A parser change that
alters any document's parse is a regression test failure by design.

## Repo layout

```
src/cnmv_enforcement/
  acquisition/   immutable raw store (sha256 + manifest)
  api/           read-only FastAPI
  cli/           typer CLI
  coverage/      honest-scope ledger
  domain/        pydantic model (case/respondent/infringement/sanction/…)
  legal/         rule-version catalog + resolution
  normalize/     ids, article/statute normalization
  parsing/       BOE publication parser, dates, money, spanish numbers,
                 cnmv_pdf notes, assemble
  pipeline/      deterministic corpus build
  projections/   observed-state projections
  sources/       http client, cnmv register, boe sumario/resolve/historical
  storage/       flat tables, parquet, duckdb
  validation/    release gates
config/legal_rules.yaml
tests/fixtures/corpus/   91 frozen BOE XMLs
docs/g0-source-report.md docs/provenance-contract.md docs/deploy.md
web/                     React/Vite frontend
```

See `docs/g0-source-report.md` for source reconnaissance,
`docs/provenance-contract.md` for the evidence model and
`docs/deploy.md` for operations.
