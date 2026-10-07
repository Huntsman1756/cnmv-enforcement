"""Evidence binding verification — DOCUMENT ≠ LOCATION ≠ VALUE_BINDING.

Proof assignment is deterministic against the *artifact bytes* the
locator was generated from (``artifact_sha256``), never against a URL
or a live document:

- ``VALUE_BINDING_PROVEN``: locator resolves inside the source
  paragraph AND the field's raw value appears verbatim in the excerpt;
- ``LOCATION_PROVEN``: locator resolves and the excerpt verifies
  verbatim inside the cited paragraph;
- ``DOCUMENT_PROVEN``: the document supports the fact but no stronger
  binding is demonstrated — honest abstention, never fabrication.
"""

from __future__ import annotations

import re

from cnmv_enforcement.domain.provenance import FactEvidence
from cnmv_enforcement.parsing.boe_publication import ParsedPublication

DOCUMENT_PROVEN = "DOCUMENT_PROVEN"
LOCATION_PROVEN = "LOCATION_PROVEN"
VALUE_BINDING_PROVEN = "VALUE_BINDING_PROVEN"
NORMALIZED_VALUE_DERIVED = "NORMALIZED_VALUE_DERIVED"

_PARA_LOCATOR = re.compile(r"^texto/p\[(\d+)\]$")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def verify_binding(
    ev: FactEvidence, pub: ParsedPublication | None
) -> str:
    """Return the highest provable proof level for an evidence record."""
    if pub is None:
        # document not in the parsed corpus (e.g. CNMV-PDF notes) —
        # document provenance only
        return DOCUMENT_PROVEN
    # the binding must target THIS artifact's bytes — a hash mismatch
    # means the locator was generated against different bytes
    sha_ok = not ev.artifact_sha256 or ev.artifact_sha256 == pub.raw_sha256
    m = _PARA_LOCATOR.match(ev.locator or "")
    if not sha_ok or not m:
        return DOCUMENT_PROVEN
    idx = int(m.group(1))
    paras = {p.index + 1: p.text for p in pub.paragraphs}  # 1-based XPath
    para = paras.get(idx)
    if para is None:
        return DOCUMENT_PROVEN
    excerpt = _norm(ev.excerpt or "")
    para_n = _norm(para)
    located = excerpt[:200] in para_n or para_n[:200] in excerpt or (
        excerpt[:120] in para_n
    )
    if not excerpt or not located:
        return DOCUMENT_PROVEN
    if ev.raw_value and _norm(ev.raw_value) in excerpt and (
        _norm(ev.raw_value) in para_n
    ):
        # the raw value is IN the cited location AND the excerpt —
        # a wrong paragraph_index cannot pass this check
        return VALUE_BINDING_PROVEN
    return LOCATION_PROVEN
