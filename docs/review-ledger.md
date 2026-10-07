# Review ledger — version-bound judgements

`review_item` = a probatory decision bound to
(source bytes `raw_sha256` × `review_compat_version`). Authoritative
*project metadata*, never official regulatory fact.

Statuses: PENDING → ACCEPTED | CORRECTED | ABSTAINED;
any of those → STALE when `raw_sha256` changes or
`review_compat_version` shifts (semantic band — patch releases never
invalidate). `data/review/review_ledger.jsonl` is append-only;
ids are never rewritten.

Seeded from `data/review/defect_registry.yaml`: the 18 adversarial
defects (12 classes) live as CORRECTED items — a future parser change
that flips `review_compat_version` makes them STALE, forcing re-review
instead of silently re-accepting corrupted semantics.
