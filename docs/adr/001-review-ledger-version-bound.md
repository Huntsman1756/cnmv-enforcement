# ADR-001 — Human reviews are version-bound evidence judgements

A review is not valid forever. `review_item` binds a probatory
decision to (source bytes `raw_sha256` × `review_compat_version`).
It goes STALE when the artifact bytes change or a semantic
parser/normalization/schema change lands — never on patch-level
churn. STALE means re-review required, not deleted: the append-only
JSONL keeps history, the built table projects the current state.

Rationale: the two adversarial rounds produced 18 material defect
findings. Encoding them as reviews (not just tests) makes a future
parser regression visible as `STALE` review items instead of silent
re-acceptance of corrupted semantics.
