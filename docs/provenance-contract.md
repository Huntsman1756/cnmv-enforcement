# Provenance contract

This document is the semantic contract for every artifact and every fact in
`cnmv-enforcement`. It is deliberately a *contract*, not a shared library:
fields below MUST appear with these exact meanings in manifests, Parquet
schemas, API payloads and evidence records.

## Artifact-level fields

| Field | Meaning |
|---|---|
| `source_id` | Stable internal identifier of this artifact. Format `{authority}:{kind}:{digest16}` where `digest16 = sha256(content)[:16]`. Two retrievals of identical bytes share one `source_id`. |
| `authority` | Publishing authority. `CNMV` | `AEBOE`. |
| `canonical_locator` | Authority-native identifier of the document, e.g. `BOE-A-2026-16921`. **Never** a retrieval URL. Opaque or ephemeral locators (CNMV `verdocumento?e=` tokens) are NOT canonical. |
| `retrieval_url` | The exact URL used for *this* retrieval. May change between retrievals while `canonical_locator` stays fixed. |
| `retrieved_at` | UTC instant at which these bytes were obtained (RFC 3339). |
| `sha256` | SHA-256 hex digest of exactly the stored bytes. |
| `content_type` | HTTP `Content-Type` of the response. |
| `http_status` | Final HTTP status of the retrieval. |
| `document_type` | Semantic classification: `CNMV_REGISTER_PAGE`, `CNMV_RESOLUTION_PDF`, `BOE_XML`, `BOE_HTML`, `BOE_PDF`, `BOE_SUMARIO`, `OTHER_OFFICIAL_DOCUMENT`. |
| `raw_path` | Path of the byte-exact copy under `data/raw/`. |

## Fact-level fields

| Field | Meaning |
|---|---|
| `observed_at` | Instant UTC at which the pipeline observed the public evidence. Every fact carries the `observed_at` of its supporting document's retrieval. |
| `effective_at` | Legal/operative date the fact *refers to*, stored only when the source explicitly supports it (e.g. conduct period, resolution date). `NULL` when unsupported. **Never** confused with `observed_at`. |
| `document_id` | The `source_id` of the document the fact was extracted from. |
| `locator` | Where inside the document: XPath, paragraph index, text span, page. |
| `extraction_method` | `DIRECT` (verbatim field), `NORMALIZED` (deterministic transform), `DERIVED` (computed from other evidenced facts), `MANUALLY_REVIEWED` (versioned manual override). |
| `confidence_type` | One of `DIRECT`, `NORMALIZED`, `DERIVED`, `MANUALLY_REVIEWED`. It is *not* a probabilistic score. |

## Invariants

- Same `canonical_locator` + different `sha256` = **a recorded change**, never
  a silent overwrite.
- `observed_at` is pipeline time; `effective_at` is legal time.
- `UNKNOWN` ≠ negative. Absence of evidence ⇒ `NULL`/no claim.
