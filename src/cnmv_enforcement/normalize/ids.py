"""Deterministic entity identifiers.

Ids are stable across reparses of the same document and across CNMV PDF
byte-regeneration (which changes sha256 but not the case). They are *not*
sequential database ids — they are content-derived.
"""

from __future__ import annotations

import hashlib
import re

from cnmv_enforcement.parsing.text import normalize_key


def content_hash(*parts: str | None) -> str:
    joined = "|".join(p or "" for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def case_id_for(boe_id: str | None, fallback_key: str) -> str:
    if boe_id:
        return f"CNMV-{boe_id}"
    return f"CNMV-REG-{content_hash(fallback_key)[:16]}"


def respondent_id_for(normalized_name: str, respondent_type: str) -> str:
    return f"RESP-{content_hash(normalized_name, respondent_type)[:16]}"


def sanction_id_for(case_id: str, ordinal: int) -> str:
    return f"{case_id}/S{ordinal}"


def infringement_id_for(case_id: str, ordinal: int) -> str:
    return f"{case_id}/I{ordinal}"


def event_id_for(
    case_id: str, event_type: str, ordinal: int, source_document_id: str
) -> str:
    h = content_hash(case_id, event_type, str(ordinal), source_document_id)[:12]
    return f"{case_id}/EV-{event_type}-{h}"


_BOE_ID_RE = re.compile(r"BOE-[A-Z]-\d{4}-\d+")


def extract_boe_id(text: str) -> str | None:
    m = _BOE_ID_RE.search(text)
    return m.group(0) if m else None
