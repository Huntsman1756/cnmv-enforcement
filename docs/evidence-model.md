# Evidence model — DOCUMENT ≠ LOCATION ≠ VALUE_BINDING

Every `FactEvidence` binds one field of one entity to an immutable
artifact (`artifact_sha256`). Proof levels (never conflated):

```text
VALUE_BINDING_PROVEN   locator resolves + raw value verbatim in excerpt
LOCATION_PROVEN        locator resolves + excerpt verbatim in paragraph
DOCUMENT_PROVEN        document supports the fact, binding not proven
NORMALIZED_VALUE_DERIVED  value derived from an evidenced source value
```

- `locator_type=PARAGRAPH` (`texto/p[N]`) against the frozen XML bytes —
  a locator belongs to `artifact_sha256`, never to a URL.
- Abstention rule: when the binding cannot be demonstrated, the record
  stays at DOCUMENT_PROVEN. No fabricated xpath/span/bbox.
- Current build: ~1,175 VB / ~743 LOC / ~295 DOC records.
- Gates: G18 referential integrity, G19 VB requires locator+sha.
