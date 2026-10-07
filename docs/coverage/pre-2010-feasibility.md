# H3 — pre-2010 feasibility assessment

**Verdict: `GO_WITH_PARTIAL_COVERAGE`**

## Sampled probes

| year | window | dept-1040 items | sanction-content pubs | parse result |
|---|---|---|---|---|
| 2009 | full year | 34 | 2 | **2/2 clean** (`Imponer a…por la comisión`, exact amounts) |
| 2005 | Apr–Dec | 26 | 5 | **5/5 clean** (`por la que se da publicidad a las sanciones`) |
| 2004 | full year | 83 | 6 | **6/6 clean** (incl. compound `las sanciones de amonestación…y de multa`) |
| 2000 | Q1 + probes | 16 (Q1) | 0 sanction-CONTENT docs | notification-only |

## Source availability

| question | answer |
|---|---|
| enumeration reproducible? | **YES** — `datosabiertos` sumario API works for 2000 (and likely earlier); dept 1040 exists throughout |
| HTML usable? | YES — `diario_boe/txt.php` live for 2000 docs |
| XML available? | **YES** — `diario_boe/xml.php?id=` works for `BOE-B-2000-*` items too |
| PDF text? | available (`url_pdf` present in 2000 sumario) |
| scanned PDF? | not needed — XML/HTML are native digital |
| department metadata reliable? | YES — `departamento.codigo == 1040` = CNMV throughout (probes 2000–2026) |
| sanction publications distinguishable? | **PARTIAL** — 2004–2009: `por la que se da publicidad a las sanciones` / `publican las sanciones` titles; 2000–2003: sanction CONTENT largely absent from BOE |
| exact evidence binding achievable? | YES for publication docs (same XML as modern era); for the notification era only DOCUMENT_PROVEN |

## Regime transition discovered

| era | regime |
|---|---|
| 2000–2003 | **Notification era**: CNMV sanctions mostly reach BOE as `BOE-B-*` notifications (`Intentada y no habiendo podido practicarse la notificación personal…`) — the BOE text does NOT carry the sanction's amount/article/severity. A handful of `por la que se publican`-style docs appear (2001: 2, 2003: 1). |
| 2004–2009 | **Publication era emerging**: `por la que se da publicidad a las sanciones` docs with full content (2004: 6, 2005: 5, 2009: 2 — quarterly rhythm). Same XML structure as the modern corpus — the parser handles them (D43 fixed). |
| 2010–2026 | Established `publican las sanciones` regime (H1/H2). |

## Sumario-shape defect found and fixed

Pre-2005 sumarios place `item` directly under `departamento` (no
`epigrafe` layer) — the enumerator silently returned 0 items for
2000–2004 until fixed (`_iter_items` over both shapes). This was a
coverage bug masquerading as source absence.

## Honest coverage statement

Pre-2010 coverage can be **reproducibly enumerated and fetched at
XML level for all of 2000–2009**, but for ~2000–2003 the BOE does
not carry sanction *content* — only service-of-process
notifications naming respondent + expediente date. Facts for that
era would be `DOCUMENT_PROVEN` at best (existence of a sanction
procedure, not its parameters).

**Decision for v0.6**: `GO_WITH_PARTIAL_COVERAGE` — extend the
manifest enumeration to 2004–2009 as `PARSED`-capable; mark
2000–2003 `ENUMERATED`/`PARTIAL` with the notification-regime
limitation documented; do NOT claim content coverage for it.
