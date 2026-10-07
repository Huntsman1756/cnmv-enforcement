# FINAL REVIEW — cnmv-enforcement v0.5.0

Baseline preserved: `v0.4.0` at `888f024` byte-intact (artifacts,
manifest, SHA256SUMS untouched; the tag was never moved).

## Scope delivered

Evidence & review hardening only — no new sources, no new domain.

1. **Review ledger** — `review_item` table + append-only JSONL;
   version-bound judgements (`raw_sha256` × `review_compat_version`);
   deterministic STALE on byte/semantic change; 25 seeded items from
   the defect registry; ledger ⊆ registry reconciliation in G16.
2. **Evidence binding** — `FactEvidence` gains `representation`,
   `locator_type` (PARAGRAPH, XPath-true `texto/p[N]`),
   `artifact_sha256`, `proof_level`, `raw_value`; proof computed by
   `verify_binding` — VB requires the raw value verbatim in BOTH the
   cited paragraph and the excerpt, and sha equality against the
   artifact bytes. Distribution: 1,430 VB / 489 LOCATION / 294 DOCUMENT.
3. **Epistemic coverage** — `OBSERVED /
   NOT_OBSERVED_WITHIN_VERIFIED_COVERAGE / UNAVAILABLE / INCONCLUSIVE`
   + `coverage_basis_id`; a strong negative requires
   `retrieval=OK` — a failed fetch/extract is INCONCLUSIVE.
   Appeals: 28 OBSERVED / 59 verified-negative / 73 INCONCLUSIVE.
4. **AS_KNOWN_AT** — `?known_at=` (API) + `--known-at` (CLI), gated on
   the observation axis; derived/epistemic fields scrubbed or re-joined
   by `observed_at ≤ T`; `NO_OBSERVATION_HISTORY`; date-only T =
   end-of-day; malformed → 400; tz-aware input normalized to UTC.
5. **Gates G16–G22** — regression coverage, staleness oracle,
   referential integrity, binding honesty, negative-claim basis,
   future-leakage, fixture integrity — now covering BOTH corpora.

## Adversarial review (2 independent rounds + scoped re-judgment)

- Round A (data/evidence): 6 SEVERE + 9 WARNING + 8 INFO.
  **Live defect found:** `99, letra z) bis` → `99.z` (restored `99.z.bis`);
  gates G17/G19/G20 found vacuous (rewritten as independent oracles);
  gates widened to `corpus_historical`.
- Round B (temporal/epistemic): 3 SEVERE + 7 WARNING + 8 INFO.
  **Found:** failed PDF fetch/extract emitted verified-negative appeals;
  `known_at` leaked appeal state via unfiltered case row; respondents
  unreachable at T; positional PDF event ids; lexicographic T.
- Re-judgment found 2 more live defects (`X y su consejero, don Y`
  fusion; `81.2. a)` related-letter loss) + `(650.000) euros` amount +
  chain-head statute + `83 ter 12` — all fixed, registered D19–D22.
- Clean-checkout bug caught: exports_dir ordering.

## Registry growth

18 original defects → **22** (12→14 classes). Regression coverage
22/22 (`artifacts/review-coverage.json`, G16).

## Regulatory-fact deltas vs v0.4 (all confirmed corrections)

| table | delta | cause |
|---|---|---|
| respondents | 272→271 | `su Presidente,` phantom merged into the real person |
| case_respondents | 295→294 | same merge |
| infringements | DIFF | `99.z.bis`, `83.ter.12`, chain statute `Ley 24/1988` |
| related_provisions | DIFF | `81.2.a/b`, `227.1.a/b` restored |
| sanctions | DIFF | `650000` recovered (written+paren amount) |
| cases | +2 cols | epistemic appeal state + basis id |
| case_status | +1 col | `first_observed_at` |
| evidence | +5 cols | proof/locator/sha/representation/raw_value |
| events | DIFF | content-hashed PDF event ids + observation axis |
| review_items | NEW (25) | project metadata — not regulatory fact |

documents / status_notes / parse_issues logically identical.

## Numbers

```text
tests:        136 passed (4 duckdb-dependent skip in CI-only runs)
gates:        21/21 — 14 named invariants + G16–G22
              (v0.4 reported "15/15" = 14 gate entries + the report's
              own top-level "ok" — same 14 gate names, byte-identical
              block; no gate was dropped)
defects:      22 registered / 22 regression-covered
review items: 25 (all sha-bound)
evidence:     2213 — VB 1430 / LOC 489 / DOC 294
appeals:      28 OBSERVED / 59 NOT_OBSERVED_VERIFIED / 73 INCONCLUSIVE
              (NB unit: OBSERVED = cases with ANY appeal-family note —
              JUDICIAL_APPEAL_OBSERVED ∪ JUDGMENT_OBSERVED ∪
              RENUNCIATION_TO_APPEAL. v0.4's "14 observed appeals" was
              firmness_status=APPEAL_OBSERVED — a mutually-exclusive
              firmness class. Note-level counts: 23 appeal-filed notes,
              28 renunciation notes, judgments included.)
corpus:       8e8446796b0f (v0.4: f50c4d336e09 — diff explained above)
clean-checkout: 136 tests + 21/21 gates from frozen inputs
```

## Known limitations (declared, not hidden)

- `NORMALIZED_VALUE_DERIVED` is defined but unused — all evidence is
  verbatim-bound or abstains.
- `known_at` gates the observation axis only: it answers "what had the
  PROJECT observed", never "what was publicly available at T".
- Legacy pdf snapshots without `retrieval` demote to INCONCLUSIVE —
  the current snapshot was re-verified with retrieval flags.
- Respondent evidence joins a case via `case_respondents` ids (RESP-*
  ids aren't case-prefixed) — consistent across all endpoints now.
- G21 tolerates ±1h clock skew vs the build instant.
- pdf-status re-runs overwrite `observed_at` (last seen);
  `first_observed_at` preserves the first observation.

## Verdict

**PASS** — v0.4.0 preserved byte-exact; 22/22 defect classes covered;
review ledger operational with deterministic staleness; evidence
bindings audit-verified; no unbased negative claims; no
future-evidence leakage on either known_at surface.
