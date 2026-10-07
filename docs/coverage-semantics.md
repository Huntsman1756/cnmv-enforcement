# Coverage semantics — absence is a claim

```text
OBSERVED
NOT_OBSERVED_WITHIN_VERIFIED_COVERAGE   (requires coverage_basis_id)
UNAVAILABLE
INCONCLUSIVE
```

0 results ≠ proof of absence. A strong negative is only admissible over
a `CoverageBasis` (source + enumeration + date range + manifest hash +
retrieval status). HTTP errors, partial enumerations and ambiguous
terminations are INCONCLUSIVE — never NOT_OBSERVED.

Applied now to the appeal axis (`cases.appeal_observation_status`):
the CNMV-PDF status run (88 scanned PDFs) is the coverage basis;
unscanned historical cases are INCONCLUSIVE, not negative.
