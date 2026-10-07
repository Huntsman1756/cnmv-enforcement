"""CNMV-hosted PDF text extraction + status-note detection.

CNMV 'verdocumento' PDFs are BOE-derived but may carry later marginal
or trailing notes about firmness, appeals or judicial review. They are
*temporal evidence*: the same URL can be regenerated and yield new
observations. Every extracted note keeps its verbatim text + page
locator — a note never upgrades into a legal claim by itself.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from pypdf import PdfReader

_STATUS_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "RENUNCIATION_TO_APPEAL",
        re.compile(
            r"Habi[eé]ndose\s+renunciado[^.;]*(?:interposici[oó]n\s+de\s+"
            r"recursos|recurso[^.;]*)?[^.;]*v[ií]a\s+administrativa[^.;]*",
            re.IGNORECASE,
        ),
    ),
    (
        "ADMINISTRATIVE_FINALITY",
        re.compile(
            r"(?:ha[n]?\s+devenido|deviniendo|devenga[n]?|advenido|"
            r"es\s+firme|firmes?)\s+(?:en\s+dicha\s+v[ií]a|"
            r"en\s+v[ií]a\s+administrativa|en\s+dicha\s+v[ií]a)"
            r"[^.;]*",
            re.IGNORECASE,
        ),
    ),
    (
        "JUDICIAL_REVIEW_POSSIBLE",
        re.compile(
            r"(?:susceptible|posibilidad)\s+de\s+revisi[oó]n\s+jurisdiccional"
            r"[^.;]*|Sala\s+de\s+lo\s+Contencioso[^.;]*",
            re.IGNORECASE,
        ),
    ),
    (
        "JUDICIAL_APPEAL_OBSERVED",
        re.compile(
            r"(?:interpuest[oa]|interposici[oó]n)\s+(?:de\s+)?recurso\s+"
            r"(?:contencioso|ante)[^.;]*|"
            r"recurrid[oa]\s+(?:ante|en)\s+(?:la\s+)?(?:Sala|Audiencia)[^.;]*",
            re.IGNORECASE,
        ),
    ),
    (
        "JUDGMENT_OBSERVED",
        re.compile(
            r"(?:Sentencia|Auto)\s+(?:de\s+la\s+)?(?:Sala|Tribunal)[^.;]*|"
            r"ha\s+estimado\s+el\s+recurso[^.;]*|"
            r"ha\s+desestimado\s+el\s+recurso[^.;]*|"
            r"anulad[oa]\s+(?:la\s+)?(?:sanci[oó]n|resoluci[oó]n)[^.;]*",
            re.IGNORECASE,
        ),
    ),
]


@dataclass
class PdfStatusNote:
    kind: str
    verbatim: str
    page: int


@dataclass
class PdfText:
    text: str
    n_pages: int
    status_notes: list[PdfStatusNote] = field(default_factory=list)


def extract_pdf_text(pdf_bytes: bytes) -> PdfText:
    """Extract full text + status notes from a CNMV PDF."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages_text: list[str] = []
    notes: list[PdfStatusNote] = []
    for i, page in enumerate(reader.pages):
        t = page.extract_text() or ""
        t = re.sub(r"\s+", " ", t).strip()
        pages_text.append(t)
        for kind, rx in _STATUS_PATTERNS:
            for m in rx.finditer(t):
                notes.append(
                    PdfStatusNote(
                        kind=kind, verbatim=m.group(0).strip(), page=i + 1
                    )
                )
    return PdfText(
        text="\n\n".join(pages_text),
        n_pages=len(reader.pages),
        status_notes=notes,
    )
