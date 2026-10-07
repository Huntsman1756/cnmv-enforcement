# H0 — register ↔ historical BOE handoff reconciliation

## Boundary

| corpus | publication range | docs | overlap |
|---|---|---|---|
| historical_backfill | 2018-01-04 → 2021-10-01 | 70 (69 case + 1 SUBSEQUENT_EVENT) | 0 |
| register_snapshot | 2021-11-18 → 2026-08-03 | 91 | 0 |

Zero duplicate `boe_id`s, zero duplicate `case_id`s — the two corpora
are fully disjoint.

## The 6-week window (2021-10-02 → 2021-11-17)

Enumerated via the resumable sumario manifest
(`data/runtime/boe_history_gap.jsonl`, 40 days, 7 Sundays without
sumario = expected errors). CNMV items found: **6, none sanctions**:

| date | boe_id | kind |
|---|---|---|
| 2021-10-08 | BOE-A-2021-16348 | Circular 2/2021 (stats) |
| 2021-10-09 | BOE-A-2021-16391 | Circular 3/2021 (remuneration) |
| 2021-10-15 | BOE-A-2021-16800 | register removal (agencia) |
| 2021-10-29 | BOE-A-2021-17656 | register removal (fund) |
| 2021-11-15 | BOE-A-2021-18701 | competence delegation |
| 2021-11-16 | BOE-A-2021-18802 | register removal (agencia) |

**Verdict: clean handoff** — no CNMV sanction publication exists in
the boundary window. The corpora connect without a gap or overlap.

## register → BOE linkage

All 91 register entries carry a `boe_id` (each resolved via the
sumario manifest at acquire time) — 100% BOE-linked.

## BOE → register

The 69 historical case documents are absent from the register snapshot
by design — the register only exposes currently-observable entries;
older publications drop off. No deduplication needed since disjoint.

## The one non-case document

BOE-A-* in `historical_backfill` classified SUBSEQUENT_EVENT (a
revocation notice) — it produces no `documents` row (documents = case
publications only; known behavior per F-20 review note).
