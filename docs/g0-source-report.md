# G0-R — Source reconnaissance report

**Audit date:** 2026-10-07. All evidence gathered with plain HTTP `GET`
(`curl`/`python urllib`), a descriptive `User-Agent`, no cookies, no browser
automation. Prior-art review: `enforcement-es` (sibling repo, G0 audited
2026-10-06), `short-es`, `boletines-md-corpus`.

## Verdict

**GO_WITH_DEGRADED_CNMV_ENUMERATION** → in practice **GO**:

- BOE gives **reproducible enumeration** via the official OpenData sumario API
  (verified back to 1961; CNMV exists since 1988).
- The CNMV register is **a reliable snapshot** (server-rendered table, stable
  pagination), but there is no public list API and no declared total, so its
  enumeration status is `COMPLETE_OBSERVED_SNAPSHOT`, not
  `VERIFIED_REPRODUCIBLE_ENUMERATION`.
- Canonical document identity is anchored on `BOE-A-*` identifiers, which both
  surfaces agree on (the register links PDFs whose content **is** the BOE
  typeset and whose register row names the BOE issue date).

---

## 1. CNMV public sanctions register

### 1.1 Retrieval — direct HTTP works

```text
GET https://www.cnmv.es/Portal/Consultas/RegistroSanciones/verRegSanciones?lang=es
  → 301 → .../verregsanciones?lang=es → 200, text/html; charset=utf-8, ~160 KB
GET .../verregsanciones.aspx?lang=es&page=18   → 301 (drops .aspx) → 200
```

No JavaScript required, no cookies required, no session. ~30 requests during
the audit, no 403/429 observed (the only 403 was a nonexistent URL
`/Portal/Aviso-Legal/...`). Still: polite pacing is mandated in the fetcher.

`robots.txt`: only `Disallow: *.shtml`. Nothing blocks the register.

### 1.2 Listing structure

Server-side rendered `<table>` `#ctl00_ContentPrincipal_grdRegSanciones`,
5 rows per page, pager `Página X de Y`.

| Page URL | `?page=` index |
|---|---|
| `verregsanciones?lang=es&page=0` | "Página 1 de 19" |
| `verregsanciones?lang=es&page=18` | "Página 19 de 19", 1 row |

Derived total on 2026-10-07: **91 resolutions**
(18 full pages × 5 + 1), matching the independent 2026-10-06 audit.
Count derivation is structural: `last_page_index × rows_per_page +
rows_on_last_page`, cross-checked against `Página X de N`. **There is no
declared total** — treat the snapshot as observed-complete, never verified.

### 1.3 Row structure (one row = one resolution, not one sanction)

```html
<tr>
  <td data-th="Fecha de incorporación al registro">
    <a href="https://www.cnmv.es/webservices/verdocumento/ver?e=<opaque>" ...>17/07/2026</a>
  </td>
  <td class="Izquierda" data-th="Resolución">
    Resolución de 17 de julio de 2026, de la Comisión Nacional del Mercado de
    Valores, por la que se publican las sanciones por infracciones muy grave y
    graves a Gesconsult, SA, SGIIC y a don Juan Lladó García-Lomas (BOE de 3 de
    agosto de 2026).
  </td>
  <td class="Izquierda" data-th=""></td>
</tr>
```

- First column: register entry date (`dd/mm/yyyy`) — **not** the resolution
  date, **not** the offence date.
- Second column: full resolution title, ending in `(BOE de D de <month> de
  YYYY)` — observed variants `(BOE de …)`, `(BOE del …)`, `(BOE D de …)`.
- Third column: observed empty on all 91 rows on 2026-10-07.
- Exactly one link per row (the PDF), always in column 1.

### 1.4 Document links

`https://www.cnmv.es/webservices/verdocumento/ver?e=<opaque token>` → `200`,
`application/pdf`. Example (Gesconsult): 580 639 bytes, `PDF-1.7`; text layer
is the BOE typeset including the `cve: BOE-A-2026-16921` marker and footer
`Verificable en https://www.boe.es`.

Known hazards (from `enforcement-es` audit):

- CNMV **regenerates** PDFs prepending a firmness note (`En relación con la
  Resolución de … se hace constar que: … es firme a todos los efectos…`). Same
  URL, different bytes ⇒ change detection must key on canonical locator +
  sha256, never assume URL→bytes stability.
- Older PDFs have a font without ToUnicode map ⇒ **PDF text is lossy**;
  authoritative text must come from the BOE document (`xml.php`/`txt.php`).

### 1.5 Declared scope (verbatim, `IniRegSanciones.aspx`, 2026-10-07)

> "De acuerdo con lo establecido en el artículo 334 de la Ley 6/2023, de 17 de
> marzo, de los Mercados de Valores y de los Servicios de Inversión, así como
> en el artículo 94 bis de la Ley 35/2003, de 4 de noviembre, de Instituciones
> de Inversión Colectiva, la CNMV publica en su página web las medidas
> acordadas y las sanciones impuestas por la comisión de infracciones pudiendo,
> en su caso, mantener el anonimato de la persona sancionada. En el caso de las
> infracciones muy graves y graves, la citada información se publica a través
> del registro público de sanciones previsto en el artículo 244.1 de la Ley de
> los Mercados de Valores y los Servicios de Inversión, en relación con el
> artículo 2 j) del Real Decreto 815/2023, de 8 de noviembre, por el que se
> desarrolla la Ley 6/2023, en relación con los registros oficiales de la
> Comisión Nacional del Mercado de Valores. La información que se publica
> incluye también la interposición, en su caso, de recursos
> contencioso-administrativos contra la resolución correspondiente y la
> posterior relativa a su resultado. **La información se mantiene en el
> registro durante cinco años.**"

Consequences baked into the coverage model:

- register scope = `VERY_SERIOUS` + `SERIOUS` only;
- `minor_infringements_coverage = NOT_GUARANTEED`;
- rolling 5-year window ⇒ **register absence ≠ no sanction**;
- anonymized persons possible ⇒ never re-identify;
- appeal docs may appear "en su caso" (none titled so on 2026-10-07);
- items disappear by design ⇒ status `REMOVED_FROM_OBSERVED_REGISTER`, never
  `REMOVED`.

### 1.6 Appeal / judicial-result documents

Register intro promises their publication "en su caso". On 2026-10-07 all 91
rows are publication resolutions; no appeal-titled row, no second document
link. The observed mutation vector for legal status is **inside the CNMV
PDF** (regenerated bytes with a firmness note). Handling: store every PDF
snapshot, diff sha256, extract the note, emit `ADMINISTRATIVE_FINALITY`
events. Do not trust PDF text for amounts (garbled fonts) — firmness notes
are clean text and can be extracted.

### 1.7 Reuse terms

`NotaLegal.aspx`: reproduction/distribution permitted if faithful and
unaltered; non-free redistribution must disclose free availability at source.
The dataset publishes **derived structured facts** (not page clones), cites
the source per fact, and links back to official URLs — compatible.

---

## 2. BOE

### 2.1 OpenData API — official, documented

`https://www.boe.es/datosabiertos/` documents:

```text
GET /datosabiertos/api/boe/sumario/{yyyymmdd}
    Accept: application/json required (default XML)  → 200, ~100–300 KB/day
```

Verified responses: `1980-01-04`, `1961-01-04`, `1989`, `1990`, `2004`,
`2014`, `2026` → all 200 with `fecha_publicacion` echoing the date.
**Practical range: ≥ 1961** — far beyond CNMV's existence (1988). This makes
historical enumeration `REPRODUCIBLY_ENUMERATED`.

Response shape:

```text
data.sumario.diario[]
  .seccion[]            {codigo, nombre, departamento[]}
    .departamento[]     {codigo:"1040", nombre:"Comisión Nacional del Mercado
                         de Valores", epigrafe[]|str}
      .epigrafe[]       {nombre, item[]|item}
        .item           {identificador:"BOE-A-2026-16921", control, titulo,
                         url_pdf{szBytes,szKBytes,pagina_inicial,
                                 pagina_final,texto},
                         url_html, url_xml}
```

Hazards: `epigrafe` may be a bare string; `item` may be a dict or list —
normalize all of these defensively.

### 2.2 CNMV department is not enforcement-only

`departamento.codigo == "1040"` on 2026-08-03 returned 4 items: one
*convenio* (`BOE-A-2026-16920`) plus three sanction publications. On
2026-09-09 / 2026-09-28 the only CNMV items were convenios. ⇒ **Title
classification is mandatory.** Enforcement publications observed:

```text
Resolución de <d> de <month> de <y>, de la Comisión Nacional del Mercado de
Valores, por la que se publica(n) la(s) sanción(es) por infracción
(grave|muy grave|graves|muy graves) (impuesta|…) a … (BOE …).
```

The classifier must remain conservative: ambiguous titles land in
`OTHER_OFFICIAL_DOCUMENT`, never silently dropped.

### 2.3 Document endpoints (all verified on BOE-A-2026-16921)

| Format | URL | Status |
|---|---|---|
| XML (structured) | `https://www.boe.es/diario_boe/xml.php?id=BOE-A-2026-16921` | 200 `application/xml` 7 KB |
| HTML | `https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-16921` | 200 `text/html` 19 KB, body at `#textoxslt` |
| PDF | `https://www.boe.es/boe/dias/2026/08/03/pdfs/BOE-A-2026-16921.pdf` | via `url_pdf.texto` in sumario/XML (193 KB) |

XML layout:

```xml
<documento fecha_actualizacion="20260803071552">
  <metadatos> identificador, departamento@codigo, rango, fecha_disposicion,
    titulo, fecha_publicacion, diario_numero, seccion, pagina_inicial/final,
    url_pdf, <analisis> materias, referencias.anteriores/posteriores </metadatos>
  <texto><p class="parrafo|parrafo_2">…</p></texto>
</documento>
```

The `xml.php` body is clean, tagged paragraphs — **primary parse target**.
PDF is stored as official artifact and for visual verification only.
`robots.txt` discourages bulk `xml.php` for crawlers; honor that by using the
documented OpenData API for enumeration and fetching document XML at a polite
rate (the same endpoint the OpenData API itself advertises).

### 2.4 Corrections

Corrections are **separate BOE-A/BOE-B documents**, e.g. on 2026-08-03:
`BOE-A-2026-16857` "…por la que se corrigen errores en la de 3 de julio de
2026…". They never delete the original. Mechanism verified; CNMV-specific
corrections will be discovered during enumeration (title `corri`/`error`
inside dept 1040, then `referencias` in XML or in-body citation to the
corrected document). Modeled as `document_relationship(CORRECTS)` + event —
never an overwrite.

### 2.5 Reuse terms

Aviso legal (`/informacion/aviso_legal/index.php`): "Condiciones de
reutilización" per Resolución de la Agencia de 27 de junio de 2024 —
commercial and non-commercial reuse permitted subject to diligent use and the
stated conditions; excludes site design, trademarks, third-party content.
Dataset = derived facts + source citation + official links ⇒ compatible.
Raw BOE PDFs kept for private verification; redistribution of verbatim
documents should link to `boe.es` rather than republish.

---

## 3. Golden case verified — BOE-A-2026-16921 (Gesconsult)

From `xml.php` (authoritative), 12 `<p>` paragraphs:

| # | Content |
|---|---|
| 0 | Preamble: renunciation of administrative appeal → firm in that venue; cites infringement articles 93.a, 94.ñ, 94.o of Ley 22/2014; **sanctioning resolution: Consejo CNMV 30-04-2026** |
| 1,4,7 | `1./2./3. Imponer por la comisión de una infracción (muy grave|grave) tipificada en el artículo … en relación con los artículos … de la Ley 22/2014 … <conduct clause>` |
| 2,5,8 | `– A Gesconsult, SA, SGIIC: Multa por importe de 50.000 / 30.000 / 35.000 euros` |
| 3,6,9 | `– A don Juan Lladó García-Lomas: Multa por importe de 40.000 / 20.000 / 25.000 euros` |
| 10 | Judicial-review wording: "…únicamente ha devenido firme en dicha vía, siendo susceptible de revisión jurisdiccional por la Sala de lo Contencioso-Administrativo de la Audiencia Nacional." |
| 11 | Signature: Madrid, 17 de julio de 2026, El Presidente… |

**Observed cardinalities:** 1 publication resolution, 2 respondents
(1 legal person + 1 natural person), 3 infringements (1 muy grave 93.a +
2 graves 94.ñ, 94.o), **6 monetary fines** (EUR), 3 distinct dates
(sanctioning 2026-04-30, publication resolution 2026-07-17, BOE
2026-08-03), administrative finality + possibility of judicial review.

> **Correction to the brief:** the brief assumed *5* monetary sanctions; the
> document contains **6** (2 respondents × 3 infringements). The golden test
> pins the observed truth (6), not the assumed number.

No Gesconsult-specific code paths — the general `N. Imponer … – A <subject>:
<sanction>` pattern produces this.

---

## 4. Source-status ledger for coverage.json

| Surface | Status | Basis |
|---|---|---|
| CNMV register listing | `COMPLETE_OBSERVED_SNAPSHOT` | HTML table, derivable count, no public list API; re-enumerable today, not historically |
| CNMV resolution PDFs | `REPRODUCIBLY_ENUMERATED`* | reachable only via register rows; *bounded by the register snapshot |
| BOE sumarios | `REPRODUCIBLY_ENUMERATED` | official API, deterministic date iteration |
| BOE CNMV-dept documents | `REPRODUCIBLY_ENUMERATED` | dept 1040 + title classifier + identifier manifest + sha256 |
| BOE corrections | `PARTIAL` until enumerated | mechanism verified; CNMV instances not yet inventoried |
| Judicial outcomes (CENDOJ/Audiencia Nacional) | `UNVERIFIED` | explicitly out of v0.1 scope |

## 5. Decisions carried into design

1. `BOE-A-*` id is the canonical locator; `verdocumento?e=` tokens are
   retrieval locators (opaque, possibly unstable — never canonical).
2. Register row → `case` via BOE id matching (title+date, Jaccard fallback)
   — mirroring `enforcement-es`, which achieved 91/91 matches.
3. Parse BOE `xml.php`; keep HTML + PDF + CNMV PDF as artifacts/evidence.
4. Store every fetched artifact immutably with
   `{source_id, authority, canonical_locator, retrieval_url, retrieved_at,
   sha256, content_type, http_status, document_type}`.
5. Detect CNMV PDF byte-mutations (firmness notes) as events, not errors.
6. Polite fetch policy: descriptive UA, ≤ ~2 req/s, backoff, bounded
   concurrency = 1 initially.
7. `epigrafe`/`item` cardinality is irregular — defensive normalization.
