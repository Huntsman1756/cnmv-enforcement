# ADR-002 — Evidence proof levels (regdelta doctrine)

DOCUMENT_PROVEN ≠ LOCATION_PROVEN ≠ VALUE_BINDING_PROVEN.

Every evidence row declares what is actually provable:
- DOCUMENT: the artifact is the correct source (sha256-pinned)
- LOCATION: the cited locator resolves inside that artifact and
  the excerpt appears there
- VALUE_BINDING: additionally the raw source value appears verbatim
  in BOTH the cited paragraph and the excerpt

Abstention is mandatory: a fact that cannot be located drops to
DOCUMENT_PROVEN; locators are never fabricated. VB requires the raw
value inside the paragraph — a wrong paragraph_index cannot pass.

Locators use XPath-true `texto/p[N]` (1-based) against the frozen
XML bytes identified by `artifact_sha256`.
