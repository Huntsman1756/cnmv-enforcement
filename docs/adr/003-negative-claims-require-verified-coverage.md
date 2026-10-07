# ADR-003 — Negative claims require a verified coverage basis

0 results ≠ proof of absence. A strong negative
(NOT_OBSERVED_WITHIN_VERIFIED_COVERAGE) is emitted only when the
source surface was actually enumerated: the pdf-status entry must
carry `retrieval=OK` (successful fetch + non-empty text extraction)
and the claim carries a `coverage_basis_id` identifying the manifest.

A failed fetch, empty extraction, or unscanned case is INCONCLUSIVE —
never a negative. Pre-v0.5 snapshots lacking `retrieval` are
INCONCLUSIVE until re-verified.
