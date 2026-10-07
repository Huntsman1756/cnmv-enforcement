# Temporal semantics — ownership-radar doctrine

Two axes, never interchangeable:

```text
effective date     when the regulatory thing happened (resolution,
                   publication, conduct window)
observed_at        when THIS PROJECT observed the evidence
```

```text
CURRENT_KNOWLEDGE_RECONSTRUCTED   (default — everything known now)
AS_KNOWN_AT(T)                    only observations with
                                  observed_at <= T
```

- `GET /api/v1/cases/{id}?known_at=2025-01-01` — filters evidence,
  events, status notes; entities visible only when observed by T;
  `observation_note=NO_OBSERVATION_HISTORY` when nothing existed.
- `cnmv-enforcement case <id> --known-at 2026-01-01`.
- `history_mode` in the response states which mode ran.
- `known_at` NEVER filters effective dates and never lets future
  evidence (e.g. a later appeal note) leak backwards.
