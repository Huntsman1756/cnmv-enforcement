"""Spanish date parsing. Legal dates are ``date`` — never timestamps."""

from __future__ import annotations

import re
from datetime import date

MONTHS_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_LONG_RE = re.compile(
    r"(\d{1,2})\s+de\s+(" + "|".join(MONTHS_ES) + r")\s+de\s+(\d{4})",
    re.IGNORECASE,
)
_SLASH_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_COMPACT_RE = re.compile(r"\b(\d{4})(\d{2})(\d{2})\b")


def parse_long_es(text: str) -> date | None:
    """Parse '17 de julio de 2026' (first match)."""
    m = _LONG_RE.search(text)
    if not m:
        return None
    d, month, y = int(m.group(1)), MONTHS_ES[m.group(2).lower()], int(m.group(3))
    try:
        return date(y, month, d)
    except ValueError:
        return None


def parse_slash_es(text: str) -> date | None:
    """Parse '17/07/2026' (dd/mm/yyyy)."""
    m = _SLASH_RE.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def parse_boe_compact(text: str) -> date | None:
    """Parse BOE metadata '20260803'."""
    m = _COMPACT_RE.match(text.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_any_es(text: str) -> date | None:
    return parse_long_es(text) or parse_slash_es(text) or parse_boe_compact(text)
