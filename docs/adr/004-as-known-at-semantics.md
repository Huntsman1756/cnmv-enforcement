# ADR-004 — AS_KNOWN_AT semantics (ownership-radar doctrine)

Two axes never interchangeable: effective date (when the regulatory
thing happened) vs observed_at (when THIS PROJECT observed it).

`?known_at=T` / `--known-at T` answers "what had this project
observed by T" — it gates evidence, events, and status observations
on observed_at/first_observed_at <= T, never on effective dates.

- case row derived/epistemic fields (appeal status, counts) are
  recomputed or nulled for the T-view — later observations cannot
  leak as current attributes
- respondents are observed with the case document (no separate
  observation event)
- date-only T means end-of-day; malformed input is a 400
- `NO_OBSERVATION_HISTORY` marks a T-view with zero evidence

It deliberately answers "what had the project observed", NOT "what
was publicly available" — publication-date views are a different,
explicit semantics.
